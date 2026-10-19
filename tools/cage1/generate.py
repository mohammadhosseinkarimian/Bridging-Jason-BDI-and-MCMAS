import argparse
import json
from pathlib import Path


# Read positive host counts
def read_count(name, supplied):
    if supplied is not None:
        if supplied < 1:
            raise ValueError(f"{name} must be at least 1")
        return supplied
    while True:
        value = input(f"How many {name}? ").strip()
        if value.isdecimal() and int(value) > 0:
            return int(value)
        print("Enter a positive integer.")


# Build subnet host lists
def build_hosts(mapping, counts):
    groups = {}
    for name, spec in mapping["subnets"].items():
        groups[name] = [f"{spec['prefix']}{i}" for i in range(counts[name])]
        groups[name] += spec["fixed"]
    hosts = [host for group in groups.values() for host in group]
    return groups, hosts, groups["enterprise"][counts["enterprise"] - 1], mapping["roles"]["critical"]


# Expand mapped rule text
def expand(rule, context):
    for name, value in context.items():
        rule = rule.replace("{" + name + "}", str(value))
    return rule


# Append indented rule lines
def add_rules(lines, rules, context, indent=8):
    if isinstance(rules, str):
        rules = [rules]
    lines.extend(" " * indent + expand(rule, context) for rule in rules)


# Format variable declarations
def field(name, values):
    kind = values if isinstance(values, str) else "{" + ", ".join(values) + "}"
    return f"        {name} : {kind};"


# Format action declarations
def action_set(actions, indent=8, per_line=5):
    rows = ["{"]
    for i in range(0, len(actions), per_line):
        part = ", ".join(actions[i:i + per_line])
        rows.append(" " * indent + part + ("," if i + per_line < len(actions) else ""))
    rows.append(" " * (indent - 4) + "}")
    return "\n".join(rows)


# Render configured ISPL baseline
def render(mapping, counts):
    groups, hosts, gateway, server = build_hosts(mapping, counts)
    foothold = mapping["roles"]["foothold"]
    context = {"gateway": gateway, "server": server}
    state, initial, actions, protocols, evolution = (
        mapping[k] for k in ("state", "initial", "actions", "protocols", "evolution")
    )
    lines = ["Semantics=SingleAssignment;", "", "Agent Environment", "    Obsvars:"]
    lines += [field(name, values) for name, values in state["public"].items()]
    lines += ["    end Obsvars", "    Vars:"]
    for subnet, members in groups.items():
        lines.append(field(mapping["subnets"][subnet]["decoy"], ["none"] + [f"d_{host}" for host in members]))
    lines += [field(name, values) for name, values in state["private"].items()]
    for host in hosts:
        for name, values in state["host"].items():
            lines.append(field(f"{name}_{host}", values))
    for host in hosts:
        for name, values in state["observations"].items():
            lines.append(field(f"{name}_{host}", values))
    lines += ["    end Vars", "", "    Actions = {" + ", ".join(actions["environment"]) + "};", "", "    Protocol:"]
    add_rules(lines, protocols["environment"], context)
    lines += ["    end Protocol", "", "    Evolution:"]
    add_rules(lines, evolution["turn"], context)

    for subnet, members in groups.items():
        spec = mapping["subnets"][subnet]
        for host in members:
            values = context | {"host": host, "decoy": spec["decoy"], "discovery": spec["discovery"],
                                "guard": expand(spec["guard"], context)}
            add_rules(lines, evolution["decoy_place"], values)
            add_rules(lines, evolution["decoy_clear"], values)
            if host != foothold:
                add_rules(lines, evolution["blue_host"], values)
            add_rules(lines, evolution["red_discover"], values)
            add_rules(lines, evolution["red_host"], values)
            lines.append("")
    add_rules(lines, evolution["impact"], context)
    lines.append("")
    for subnet, members in groups.items():
        spec = mapping["subnets"][subnet]
        for host in members:
            values = context | {"host": host, "decoy": spec["decoy"]}
            add_rules(lines, evolution["observe_foothold"] if host == foothold else evolution["observe_blue"], values)
            add_rules(lines, evolution["observe_red"], values)
    lines += ["    end Evolution", "end Agent", "", "Agent Blue"]
    blue_visible = [spec["decoy"] for spec in mapping["subnets"].values()]
    for name in state["observations"]:
        blue_visible.extend(f"{name}_{host}" for host in hosts)
    lines += ["    Lobsvars = {" + ", ".join(blue_visible) + "};",
              "    Vars:", field("dummy", "boolean"), "    end Vars", ""]

    blue = actions["blue"]
    blue_active = blue["common"] + [f"{action}_{host}" for host in hosts for action in blue["host"]]
    lines += ["    Actions = " + action_set(blue_active + [blue["wait"]]) + ";",
              "    Protocol:", "        Environment.turn = blue_turn : " + action_set(blue_active, 12) + ";",
              f"        Environment.turn = red_turn : {{{blue['wait']}}};",
              "    end Protocol", "    Evolution:",
              "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
              "    end Evolution", "end Agent", "", "Agent Red",
              "    Lobsvars = {" + ", ".join(f"red_{host}" for host in hosts) + "};",
              "    Vars:", field("dummy", "boolean"), "    end Vars", ""]

    red = actions["red"]
    red_actions = red["common"] + [f"{red['discover']}_{spec['discovery']}" for spec in mapping["subnets"].values()]
    red_actions += [f"{action}_{host}" for host in hosts for action in red["host"]]
    red_actions += [f"{red['impact']}_{server}", red["wait"]]
    lines += ["    Actions = " + action_set(red_actions) + ";", "    Protocol:",
              f"        Environment.turn = blue_turn : {{{red['wait']}}};"]
    add_rules(lines, protocols["red_common"], context)
    add_rules(lines, protocols["red_operational"], context)
    for host in hosts:
        add_rules(lines, protocols["red_host"], context | {"host": host})
    add_rules(lines, protocols["red_impact"], context)
    lines += ["    end Protocol", "    Evolution:",
              "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
              "    end Evolution", "end Agent", "", "Evaluation"]
    for name, condition in mapping["evaluation"].items():
        lines.append(f"    {expand(name, context)} if {expand(condition, context)};")
    lines += ["end Evaluation", "", "InitStates"]

    assignments = []
    assignments += [f"Environment.{name} = {value}" for name, value in initial["public"].items()]
    assignments += [f"Environment.{spec['decoy']} = {initial['decoy']}" for spec in mapping["subnets"].values()]
    assignments += [f"Environment.{name} = {value}" for name, value in initial["private"].items()]
    for host in hosts:
        settings = initial["foothold_observations"] if host == foothold else initial["observations"]
        assignments += [f"Environment.{name}_{host} = {value}" for name, value in settings.items()]
    for host in hosts:
        settings = initial["foothold"] if host == foothold else initial["host"]
        assignments += [f"Environment.{name}_{host} = {value}" for name, value in settings.items()]
    assignments += [f"{agent}.{name} = {value}" for agent in ("Blue", "Red") for name, value in initial["agent"].items()]
    lines += ["    " + condition + (";" if i == len(assignments) - 1 else " and")
              for i, condition in enumerate(assignments)]
    lines += ["end InitStates", "", "Groups", "    blue_team = {Blue};", "    red_team = {Red};",
              "end Groups", "", "Formulae"]
    add_rules(lines, mapping["formulae"], context, indent=4)
    lines += ["end Formulae", ""]
    return "\n".join(lines)


# Build Jason translator mapping
def render_jason(mapping, counts, baseline_name, program):
    groups, hosts, _, server = build_hosts(mapping, counts)
    foothold = mapping["roles"]["foothold"]
    source = mapping["jason"]
    plan = source["plan"]
    actions = {"monitor": "monitor"}
    predicates = {}
    transitions = []
    for host in hosts:
        for action in ("restore", "remove"):
            actions[f"{action}_{host}"] = f"{action}_{host}"
            transitions.append({"from": f"secure_{host}", "to": "secure_network", "action": f"{action}_{host}"})
        predicates[f"secure_{host}"] = (True if host in (foothold, "Defender") else
                                           {"eq": [{"env": f"compromised_{host}"}, "no"]})
        predicates[f"initial_foothold_{host}"] = host == foothold
        predicates[f"host_state_{host}_any"] = True
        for level in ("user", "privileged"):
            predicates[f"host_state_{host}_{level}"] = {"eq": [{"env": f"compromised_{host}"}, level]}
    role = {"program": program, "ispl_agent": "Blue", "entry_goal": source["entry_goal"],
            "goal_var": source["goal_var"],
            "plan": {"ground": plan["ground"] | {"members": hosts}, "actions": actions,
                     "predicates": predicates, "pass_through": plan["pass_through"],
                     "transitions": transitions, "fallback": plan["fallback"]}}
    role["plan"]["pass_through"] = [x.replace("{server}", server) for x in plan["pass_through"]]
    return {"files": {"raw": baseline_name, "output": "../generated/cage1_jason_guided.ispl"},
            "model": {"environment_agent": "Environment"},
            "jason": {"vocabulary": source["vocabulary"], "roles": {"blue": role}}}


# Generate both configuration files
def main():
    parser = argparse.ArgumentParser(description="Generate the CAGE 1 baseline and Jason mapping")
    parser.add_argument("--users", type=int)
    parser.add_argument("--enterprises", type=int)
    parser.add_argument("--hosts", type=int)
    parser.add_argument("--mapping", type=Path, default=Path(__file__).with_name("mapping.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--baseline-name", default="cage1_baseline.ispl")
    parser.add_argument("--program", default="../../../agents/blue_agent.asl")
    args = parser.parse_args()
    try:
        counts = {"user": read_count("users", args.users), "enterprise": read_count("enterprises", args.enterprises),
                  "operational": read_count("hosts", args.hosts)}
    except ValueError as error:
        parser.error(str(error))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = args.output_dir / args.baseline_name
    jason = args.output_dir / "jason_mapping.json"
    baseline.write_text(render(mapping, counts), encoding="utf-8")
    jason.write_text(json.dumps(render_jason(mapping, counts, baseline.name, args.program), indent=2) + "\n", encoding="utf-8")
    print(f"Created {baseline}")
    print(f"Created {jason}")


if __name__ == "__main__":
    main()
