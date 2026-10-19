import argparse
import json
from pathlib import Path


MAPS = {"1": "95area", "2": "9area", "3": "3area", "4": "custom_2"}
ROOT = Path(__file__).resolve().parents[2]


# Read a numbered choice
def ask_choice():
    print("Choose a map:")
    for key, value in MAPS.items():
        print(f"  {key}. {value}")
    while True:
        selection = input("Map (1-4): ").strip()
        if selection in MAPS:
            return MAPS[selection]
        print("Enter 1, 2, 3, or 4.")


# Read bounded agent counts
def ask_count(name):
    while True:
        value = input(f"Number of {name} (2-5): ").strip()
        if value.isdecimal() and 2 <= int(value) <= 5:
            return int(value)
        print("Enter an integer between 2 and 5.")


# Read valid map positions
def ask_positions(name, count, areas):
    result = []
    for index in range(count):
        while True:
            value = input(f"{name} {index + 1} position (1-{len(areas)}): ").strip()
            if value.isdecimal() and 1 <= int(value) <= len(areas):
                result.append(areas[int(value) - 1])
                break
            print(f"Enter a number from 1 to {len(areas)}.")
    return result


# Validate supplied positions
def validate_positions(values, count, areas, title):
    if values is None:
        return ask_positions(title, count, areas)
    if len(values) != count or any(i < 1 or i > len(areas) for i in values):
        raise ValueError(f"{title} requires {count} positions from 1 to {len(areas)}")
    return [areas[i - 1] for i in values]


# Format ISPL action sets
def action_set(actions):
    return "{" + ", ".join(actions) + "}"


# Build rescue domain model
def baseline_model(layout, fire_positions, ambulance_positions, civilian_positions):
    areas = layout["areas"]
    adjacent = layout["adjacency"]
    fires = [f"FireBrigade{i}" for i in range(len(fire_positions))]
    ambulances = [f"AmbulanceTeam{i}" for i in range(len(ambulance_positions))]
    civilians = [f"Civ{i}" for i in range(len(civilian_positions))]
    refuge = layout["refuge"]
    domain = action_set(areas)
    carriers = action_set(["none"] + ambulances)
    lines = ["Semantics=SingleAssignment;", "", "Agent Environment", "    Obsvars:"]
    for i in range(len(fires)):
        lines.append(f"        fb_area_{i}: {domain};")
    for i in range(len(ambulances)):
        lines.append(f"        at_area_{i}: {domain};")
    lines.append(f"        refuge_area: {domain};")
    for area in areas:
        lines.append(f"        status_{area}: {{road, healthy, damaged, collapsed}};")
    for civ in civilians:
        lines += [
            f"        civ_area_{civ}: {domain};",
            f"        alive_{civ}: boolean;",
            f"        dead_{civ}: boolean;",
            f"        health_{civ}: {{high, moderate, at_risk, dead}};",
            f"        buriedness_value_{civ}: 0 .. 1;",
            f"        loaded_{civ}: boolean;",
            f"        carrier_{civ}: {carriers};",
            f"        delivered_{civ}: boolean;",
        ]
    lines += ["    end Obsvars", "    Actions = {env_idle};", "    Protocol:", "        Other: {env_idle};", "    end Protocol", "    Evolution:"]
    for i, agent in enumerate(fires):
        for dest in areas:
            lines.append(f"        fb_area_{i} = {dest} if {agent}.Action = fb{i}_move_to_{dest};")
    for i, agent in enumerate(ambulances):
        for dest in areas:
            lines.append(f"        at_area_{i} = {dest} if {agent}.Action = at{i}_move_to_{dest};")
    for civ in civilians:
        lines += [
            f"        health_{civ} = moderate if alive_{civ} = true and buriedness_value_{civ} = 1 and health_{civ} = high;",
            f"        health_{civ} = at_risk if alive_{civ} = true and buriedness_value_{civ} = 1 and health_{civ} = moderate;",
            f"        health_{civ} = dead if alive_{civ} = true and buriedness_value_{civ} = 1 and health_{civ} = at_risk;",
            f"        alive_{civ} = false if alive_{civ} = true and buriedness_value_{civ} = 1 and health_{civ} = at_risk;",
            f"        dead_{civ} = true if alive_{civ} = true and buriedness_value_{civ} = 1 and health_{civ} = at_risk;",
        ]
        for i, agent in enumerate(fires):
            lines.append(f"        buriedness_value_{civ} = 0 if alive_{civ} = true and buriedness_value_{civ} = 1 and fb_area_{i} = civ_area_{civ} and {agent}.Action = fb{i}_rescue_{civ};")
        for i, agent in enumerate(ambulances):
            load_guard = (f"alive_{civ} = true and buriedness_value_{civ} = 0 and loaded_{civ} = false "
                          f"and delivered_{civ} = false and at_area_{i} = civ_area_{civ} and {agent}.Action = at{i}_load_{civ}")
            earlier = []
            for j in range(i):
                prior = (f"alive_{civ} = true and buriedness_value_{civ} = 0 and loaded_{civ} = false "
                         f"and delivered_{civ} = false and at_area_{j} = civ_area_{civ} and AmbulanceTeam{j}.Action = at{j}_load_{civ}")
                earlier.append(f"!({prior})")
            winner = load_guard + (" and " + " and ".join(earlier) if earlier else "")
            lines.append(f"        carrier_{civ} = {agent} if {winner};")
            lines.append(f"        loaded_{civ} = true if {winner};")
            for dest in areas:
                lines.append(f"        civ_area_{civ} = {dest} if loaded_{civ} = true and carrier_{civ} = {agent} and {agent}.Action = at{i}_move_to_{dest};")
            unload = (f"loaded_{civ} = true and carrier_{civ} = {agent} and "
                      f"at_area_{i} = refuge_area and {agent}.Action = at{i}_unload_{civ}")
            lines.append(f"        carrier_{civ} = none if {unload};")
            lines.append(f"        loaded_{civ} = false if {unload};")
            lines.append(f"        delivered_{civ} = true if {unload};")
    lines += ["    end Evolution", "end Agent", ""]
    for i, agent in enumerate(fires):
        rest = f"fb{i}_rest"
        actions = [f"fb{i}_move_to_{area}" for area in areas] + [f"fb{i}_rescue_{civ}" for civ in civilians] + [rest]
        lines += [f"Agent {agent}", "    Vars:", "        dummy: boolean;", "    end Vars", f"    Actions = {action_set(actions)};", "    Protocol:"]
        for area in areas:
            moves = [f"fb{i}_move_to_{p}" for p in adjacent[area]]
            lines.append(f"        Environment.fb_area_{i} = {area}: {action_set(moves + [rest])};")
        for civ in civilians:
            lines.append(f"        Environment.alive_{civ} = true and Environment.buriedness_value_{civ} = 1 and Environment.fb_area_{i} = Environment.civ_area_{civ}: {{{f'fb{i}_rescue_{civ}'}}};")
        lines += [f"        Other: {{{rest}}};", "    end Protocol", "    Evolution:", "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;", "    end Evolution", "end Agent", ""]
    for i, agent in enumerate(ambulances):
        rest = f"at{i}_rest"
        actions = [f"at{i}_move_to_{area}" for area in areas] + [f"at{i}_load_{civ}" for civ in civilians] + [f"at{i}_unload_{civ}" for civ in civilians] + [rest]
        lines += [f"Agent {agent}", "    Vars:", "        dummy: boolean;", "    end Vars", f"    Actions = {action_set(actions)};", "    Protocol:"]
        for area in areas:
            moves = [f"at{i}_move_to_{p}" for p in adjacent[area]]
            lines.append(f"        Environment.at_area_{i} = {area}: {action_set(moves + [rest])};")
        for civ in civilians:
            lines.append(f"        Environment.alive_{civ} = true and Environment.buriedness_value_{civ} = 0 and Environment.loaded_{civ} = false and Environment.delivered_{civ} = false and Environment.at_area_{i} = Environment.civ_area_{civ}: {{at{i}_load_{civ}}};")
            lines.append(f"        Environment.loaded_{civ} = true and Environment.carrier_{civ} = {agent} and Environment.at_area_{i} = Environment.refuge_area: {{at{i}_unload_{civ}}};")
        lines += [f"        Other: {{{rest}}};", "    end Protocol", "    Evolution:", "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;", "    end Evolution", "end Agent", ""]
    lines += ["Evaluation"]
    for civ in civilians:
        lines.append(f"    surface_alive_{civ}_eval if Environment.alive_{civ} = true and Environment.buriedness_value_{civ} = 0;")
        lines.append(f"    delivered_alive_{civ}_eval if Environment.delivered_{civ} = true and Environment.alive_{civ} = true and Environment.loaded_{civ} = false;")
    lines += ["end Evaluation", "", "InitStates"]
    init = [f"Environment.fb_area_{i} = {pos}" for i, pos in enumerate(fire_positions)]
    init += [f"Environment.at_area_{i} = {pos}" for i, pos in enumerate(ambulance_positions)]
    init.append(f"Environment.refuge_area = {refuge}")
    init += [f"Environment.status_{place} = {layout['status'][place]}" for place in areas]
    for civ, place in zip(civilians, civilian_positions):
        init += [f"Environment.civ_area_{civ} = {place}", f"Environment.alive_{civ} = true", f"Environment.dead_{civ} = false",
                 f"Environment.health_{civ} = high", f"Environment.buriedness_value_{civ} = 1", f"Environment.loaded_{civ} = false",
                 f"Environment.carrier_{civ} = none", f"Environment.delivered_{civ} = false"]
    init += [f"{agent}.dummy = false" for agent in fires + ambulances]
    for idx, assignment in enumerate(init):
        lines.append(f"    {assignment}{';' if idx == len(init)-1 else ' and'}")
    lines += ["end InitStates", "", "Groups", f"    fire_only = {action_set(fires)};", f"    ambulance_only = {action_set(ambulances)};", f"    rescue_team = {action_set(fires + ambulances)};", "end Groups", "", "Formulae"]
    for civ in civilians:
        lines.append(f"    <fire_only> F surface_alive_{civ}_eval;")
        lines.append(f"    <rescue_team> F delivered_alive_{civ}_eval;")
    lines += ["end Formulae", ""]
    return "\n".join(lines)


# Build Jason role mappings
def jason_mapping(name, fire_positions, ambulance_positions, civilian_positions, output_directory):
    count_f, count_a, count_c = len(fire_positions), len(ambulance_positions), len(civilian_positions)
    civilians = [f"Civ{i}" for i in range(count_c)]
    roles = {}
    for kind, count in (("fire", count_f), ("ambulance", count_a)):
        for i in range(count):
            prefix = ("fb" if kind == "fire" else "at") + str(i)
            agent = ("FireBrigade" if kind == "fire" else "AmbulanceTeam") + str(i)
            role = {
                "program": "../../../agents/" + ("fire_brigade.asl" if kind == "fire" else "ambulance_team.asl"),
                "ispl_agent": agent,
                "entry_goal": "step",
                "goal_var": prefix + "_goal_level",
                "plan": {
                    "ground": {
                        "variable": "Civ", "members": civilians,
                        "signatures": {key: [0] for key in (
                            "rescued_buried_civilian", "buried_civilian", "buried_victim", "found_civilian",
                            "surface_civilian", "ready_for_ambulance", "ready_for_pickup", "loaded", "delivered",
                            "rescue", "load", "told_ambulance", "told_fire", "rescued", "pickup_needed",
                            "reported_transportable", "fire_ready", "fire_done", "reported_to_peer"
                        )}
                    },
                    "actions": {},
                    "predicates": {
                        "at_area": True, "at": True, "area": True, "refuge": True,
                        "found_refuge": True, "found_civilian": True, "reported_pickup_place": False,
                        "reported_pickup_at": False, "ready_for_pickup": False,
                        "pickup_needed": False, "command_ambulance": False,
                        "at_civilian": True, "visited": False, "known_road": True,
                        "collapsed": True, "damaged": True, "building": True, "road": True,
                        "told_refuge": True, "told_fire": True, "told_ambulance": True,
                        "ready_for_ambulance": False, "fire_ready": False,
                        "fire_done": False, "reported_transportable": False,
                        "rescued": True, "buried_civilian": True,
                        "delivered": True, "loaded": True, "surface_civilian": True,
                    },
                    "pass_through_patterns": ([r"(?:" + prefix + r"_move_to_.*)"] if kind == "fire" else [r"(?:" + prefix + r"_move_to_.*|" + prefix + r"_unload_Civ\d+)"]),
                    "transitions": [],
                    "fallback": prefix + "_rest",
                },
            }
            for civ in civilians:
                role["plan"]["predicates"].update({
                    f"buried_civilian_{civ}": {"all": [{"eq": [{"env": f"alive_{civ}"}, True]}, {"eq": [{"env": f"buriedness_value_{civ}"}, 1]}]},
                    f"buried_victim_{civ}": {"eq": [{"env": f"buriedness_value_{civ}"}, 1]},
                    f"surface_civilian_{civ}": {"all": [{"eq": [{"env": f"alive_{civ}"}, True]}, {"eq": [{"env": f"buriedness_value_{civ}"}, 0]}]},
                    f"found_civilian_{civ}": True,
                    f"loaded_{civ}": {"eq": [{"env": f"loaded_{civ}"}, True]},
                    f"delivered_{civ}": {"eq": [{"env": f"delivered_{civ}"}, True]},
                    f"rescued_{civ}": {"eq": [{"env": f"buriedness_value_{civ}"}, 0]},
                    f"told_ambulance_{civ}": True,
                    f"told_fire_{civ}": True,
                    f"ready_for_ambulance_{civ}": False,
                    f"ready_for_pickup_{civ}": False,
                    f"pickup_needed_{civ}": False,
                    f"reported_transportable_{civ}": False,
                    f"fire_ready_{civ}": False,
                    f"fire_done_{civ}": False,
                })
                if kind == "fire":
                    role["plan"]["actions"][f"rescue_{civ}"] = f"{prefix}_rescue_{civ}"
                    role["plan"]["transitions"].append({"from": f"rescued_buried_civilian_{civ}", "to": "saved_civilians", "action": f"rescue_{civ}"})
                    role["plan"]["transitions"].append({"from": f"rescued_buried_civilian_{civ}", "to": "saved_civilians", "when": {"any": [{"eq": [{"env": f"buriedness_value_{civ}"}, 0]}, {"eq": [{"env": f"dead_{civ}"}, True]}]}})
                else:
                    role["plan"]["actions"][f"load_{civ}"] = f"{prefix}_load_{civ}"
                    role["plan"]["transitions"].append({"from": f"loaded_{civ}", "to": "saved_civilians", "action": f"load_{civ}"})
                    role["plan"]["transitions"].append({"from": f"loaded_{civ}", "to": "saved_civilians", "when": {"any": [{"eq": [{"env": f"loaded_{civ}"}, True]}, {"eq": [{"env": f"dead_{civ}"}, True]}, {"eq": [{"env": f"delivered_{civ}"}, True]}]}})
                    role["plan"]["actions"]["unload"] = f"{prefix}_unload_{civ}" if count_c == 1 else None
            role["plan"]["actions"] = {k: v for k, v in role["plan"]["actions"].items() if v is not None}
            role["plan"]["ignore_actions"] = ["log", "radio_busy", "radio_done", "radio_found", "radio_loaded", "notify_fire_needed", "notify_ambulance_ready"]
            roles[f"{kind}_{i}"] = role
    return {
        "files": {"raw": name + ".ispl", "output": "../generated/" + name + "_jason_guided.ispl"},
        "model": {"environment_agent": "Environment"},
        "jason": {"vocabulary": {"actions": {}, "predicates": {}}, "roles": roles},
    }


# Generate the selected scenario
def main():
    parser = argparse.ArgumentParser(description="Generate an RCRS baseline and Jason mapping")
    parser.add_argument("--map", choices=["1", "2", "3", "4", *MAPS.values()])
    parser.add_argument("--fire-brigades", type=int)
    parser.add_argument("--ambulances", type=int)
    parser.add_argument("--civilians", type=int)
    parser.add_argument("--fire-positions", nargs="+", type=int)
    parser.add_argument("--ambulance-positions", nargs="+", type=int)
    parser.add_argument("--civilian-positions", nargs="+", type=int)
    parser.add_argument("--examples-dir", type=Path, default=ROOT / "examples")
    args = parser.parse_args()
    name = MAPS[args.map] if args.map in MAPS else (args.map or ask_choice())
    layout = json.loads((Path(__file__).parent / "maps" / (name + ".json")).read_text(encoding="utf-8"))
    counts = []
    for number, title in ((args.fire_brigades, "fire brigades"), (args.ambulances, "ambulances"), (args.civilians, "civilians")):
        if number is None:
            number = ask_count(title)
        if not 2 <= number <= 5:
            parser.error(f"{title} must be between 2 and 5")
        counts.append(number)
    nf, na, nc = counts
    print(f"\n{len(layout['areas'])} available areas (number = actual map identifier):")
    for index, area in enumerate(layout["areas"], 1):
        print(f"  {index}: {area}")
    try:
        fire = validate_positions(args.fire_positions, nf, layout["areas"], "Fire brigade")
        ambulance = validate_positions(args.ambulance_positions, na, layout["areas"], "Ambulance")
        civilian = validate_positions(args.civilian_positions, nc, layout["areas"], "Civilian")
    except ValueError as exc:
        parser.error(str(exc))
    directory = f"{name}_f{nf}_a{na}_c{nc}"
    input_dir = args.examples_dir / directory / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    output = input_dir / (directory + ".ispl")
    output.write_text(baseline_model(layout, fire, ambulance, civilian), encoding="utf-8")
    config = jason_mapping(directory, fire, ambulance, civilian, input_dir)
    (input_dir / "jason_mapping.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nCreated {output}")
    print(f"Created {input_dir / 'jason_mapping.json'}")
    print(f"Translate: python3 src/jason_guided.py --config examples/{directory}/input/jason_mapping.json")


if __name__ == "__main__":
    main()
