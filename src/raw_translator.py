from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
import xml.etree.ElementTree as ET

VALID_HEALTH = {"complete", "high", "moderate", "at_risk", "dead"}
VALID_DAMAGE = {"none", "moderate"}
VALID_BROKENNESS = {"healthy", "damaged", "collapsed"}


def area_name(area_id: int) -> str:
    return f"area_{int(area_id)}"


def fb_move(area_id: int) -> str:
    return f"fb_move_to_{int(area_id)}"


def at_move(area_id: int) -> str:
    return f"at_move_to_{int(area_id)}"


def indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def wrap_enum(values: Sequence[str], width: int = 8) -> str:
    values = list(values)
    chunks = [", ".join(values[i:i + width]) for i in range(0, len(values), width)]
    if len(chunks) == 1:
        return "{" + chunks[0] + "}"
    return "{\n" + ",\n".join("            " + chunk for chunk in chunks) + "\n        }"


def action_set(actions: Sequence[str], indent_spaces: int = 16, per_line: int = 4) -> str:
    actions = list(actions)
    chunks = [", ".join(actions[i:i + per_line]) for i in range(0, len(actions), per_line)]
    if len(chunks) == 1:
        return "{" + chunks[0] + "}"
    pad = " " * indent_spaces
    return "{\n" + ",\n".join(pad + chunk for chunk in chunks) + "\n" + " " * (indent_spaces - 4) + "}"


@dataclass
class MapData:
    roads: List[int]
    buildings: List[int]
    areas: List[int]
    neighbours: Dict[int, List[int]]
    forced_collapsed_buildings: List[int]


@dataclass
class InitialSetup:
    name: str
    initial: Dict[str, object]
    building_brokenness_default: str
    building_brokenness: Dict[str, str]


def read_zip_text(zf: zipfile.ZipFile, suffix: str) -> Optional[str]:
    matches = [name for name in zf.namelist() if name.endswith(suffix)]
    if not matches:
        return None
    return zf.read(sorted(matches, key=len)[0]).decode("utf-8", errors="replace")


def read_namespaces(xml_text: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for _, item in ET.iterparse(io.StringIO(xml_text), events=("start-ns",)):
        prefix, uri = item
        found[prefix] = uri
    if "rcr" not in found or "gml" not in found:
        raise ValueError("map.gml must define rcr and gml XML namespaces")
    return {"rcr": found["rcr"], "gml": found["gml"]}


def parse_map_gml(gml_text: str) -> Tuple[List[int], List[int], Dict[int, List[int]]]:
    ns = read_namespaces(gml_text)
    root = ET.fromstring(gml_text)
    roads: Set[int] = set()
    buildings: Set[int] = set()
    neighbours: Dict[int, Set[int]] = {}
    gml_id = f"{{{ns['gml']}}}id"
    rcr_neighbour = f"{{{ns['rcr']}}}neighbour"

    def get_id(elem: ET.Element) -> int:
        return int(elem.attrib[gml_id])

    for tag, bucket in [("road", roads), ("building", buildings)]:
        for elem in root.findall(f".//rcr:{tag}", ns):
            area_id = get_id(elem)
            bucket.add(area_id)
            neighbours.setdefault(area_id, set())
            for edge in elem.findall(".//gml:directedEdge", ns):
                neighbour = edge.attrib.get(rcr_neighbour)
                if neighbour is not None:
                    neighbours[area_id].add(int(neighbour))

    areas = roads | buildings
    clean: Dict[int, Set[int]] = {area_id: set() for area_id in areas}
    for src, nbs in neighbours.items():
        if src not in areas:
            continue
        for dst in nbs:
            if dst in areas and dst != src:
                clean[src].add(dst)
                clean[dst].add(src)

    return sorted(roads), sorted(buildings), {k: sorted(v) for k, v in sorted(clean.items())}


def parse_collapse_cfg(cfg_text: Optional[str]) -> List[int]:
    if not cfg_text:
        return []
    ids: List[int] = []
    for line in cfg_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line.startswith("collapse.ids"):
            parts = re.split(r"[:=]", line, maxsplit=1)
            if len(parts) == 2:
                ids.extend(int(x) for x in re.findall(r"\d+", parts[1]))
    return sorted(set(ids))


def read_map(input_zip: Path) -> MapData:
    with zipfile.ZipFile(input_zip) as zf:
        gml_text = read_zip_text(zf, "map.gml")
        if gml_text is None:
            raise FileNotFoundError("No map.gml found inside the zip file.")
        collapse_text = read_zip_text(zf, "collapse.cfg")

    roads, buildings, neighbours = parse_map_gml(gml_text)
    areas = sorted(set(roads) | set(buildings))
    return MapData(
        roads=roads,
        buildings=buildings,
        areas=areas,
        neighbours=neighbours,
        forced_collapsed_buildings=parse_collapse_cfg(collapse_text),
    )


def load_initial(path: Path) -> InitialSetup:
    data = json.loads(path.read_text())
    return InitialSetup(
        name=str(data.get("name", "custom")),
        initial=dict(data.get("initial", {})),
        building_brokenness_default=str(data.get("building_brokenness_default", "healthy")),
        building_brokenness={str(k): str(v) for k, v in dict(data.get("building_brokenness", {})).items()},
    )


def validate_initial(data: MapData, setup: InitialSetup) -> None:
    init = setup.initial
    required = [
        "fb_area", "at_area", "civ_area", "refuge_area", "health_Civ", "damage_Civ",
        "buriedness_value_Civ", "health_clock", "alive_Civ", "dead_Civ",
        "loaded_Civ", "delivered_Civ", "all_roads_initially_clear",
    ]
    missing = [key for key in required if key not in init]
    if missing:
        raise ValueError(f"initial JSON is missing required fields: {missing}")

    areas = set(data.areas)
    buildings = set(data.buildings)
    for key in ["fb_area", "at_area", "civ_area", "refuge_area"]:
        if int(init[key]) not in areas:
            raise ValueError(f"initial.{key}={init[key]} is not a map area id")

    if setup.building_brokenness_default not in VALID_BROKENNESS:
        raise ValueError("building_brokenness_default must be healthy, damaged, or collapsed")

    for raw_id, value in setup.building_brokenness.items():
        bid = int(raw_id)
        if bid not in buildings:
            raise ValueError(f"building_brokenness contains {bid}, but it is not a building id")
        if value not in VALID_BROKENNESS:
            raise ValueError(f"brokenness for building {bid} must be healthy, damaged, or collapsed")

    for bid in data.forced_collapsed_buildings:
        if bid in buildings and setup.building_brokenness.get(str(bid), "collapsed") != "collapsed":
            raise ValueError(f"collapse.cfg forces building {bid} to be collapsed, but JSON contradicts it")

    if str(init["health_Civ"]) not in VALID_HEALTH:
        raise ValueError("health_Civ must be complete, high, moderate, at_risk, or dead")
    if str(init["damage_Civ"]) not in VALID_DAMAGE:
        raise ValueError("damage_Civ must be none or moderate")
    if not (0 <= int(init["buriedness_value_Civ"]) <= 6):
        raise ValueError("buriedness_value_Civ must be between 0 and 6")
    if not (0 <= int(init["health_clock"]) <= 19):
        raise ValueError("health_clock must be between 0 and 19")
    for key in ["alive_Civ", "dead_Civ", "loaded_Civ", "delivered_Civ", "all_roads_initially_clear"]:
        if not isinstance(init[key], bool):
            raise ValueError(f"initial.{key} must be true or false")


def health_guard(prefix: str = "Environment.") -> str:
    return (
        f"({prefix}health_Civ = complete or {prefix}health_Civ = high or "
        f"{prefix}health_Civ = moderate or ({prefix}health_Civ = at_risk and ("
        + " or ".join(f"{prefix}health_clock = {i}" for i in range(19))
        + ")))"
    )


def positive_buried(prefix: str = "Environment.") -> str:
    return "(" + " or ".join(f"{prefix}buriedness_value_Civ = {i}" for i in range(1, 7)) + ")"


def collapsed_civ_guard(data: MapData, prefix: str = "") -> str:
    """Condition that Civ is physically located in a collapsed building."""
    terms = [
        f"({prefix}civ_area = {area_name(bid)} and {prefix}brokenness_{bid} = collapsed)"
        for bid in data.buildings
    ]
    return "(" + " or ".join(terms) + ")" if terms else "false"


def all_area_values(data: MapData) -> List[str]:
    return [area_name(x) for x in data.areas]


def generate_environment(data: MapData) -> str:
    area_enum = wrap_enum(all_area_values(data), width=8)
    civ_enum = wrap_enum(all_area_values(data) + ["in_ambulance"], width=8)

    obs: List[str] = [
        f"fb_area: {area_enum};",
        f"at_area: {area_enum};",
        f"civ_area: {civ_enum};",
        f"refuge_area: {area_enum};",
        "civilian_Civ: boolean;",
    ]
    for rid in data.roads:
        obs.append(f"road_{rid}: boolean;")
    for bid in data.buildings:
        obs.append(f"building_{bid}: boolean;")
        obs.append(f"brokenness_{bid}: {{healthy, damaged, collapsed}};")
    obs += [
        "all_roads_initially_clear: boolean;",
        "health_Civ: {complete, high, moderate, at_risk, dead};",
        "damage_Civ: {none, moderate};",
        "buriedness_value_Civ: 0 .. 6;",
        "health_clock: 0 .. 19;",
        "alive_Civ: boolean;",
        "dead_Civ: boolean;",
        "loaded_Civ: boolean;",
        "delivered_Civ: boolean;",
    ]

    evo: List[str] = ["-- Movement"]
    for dst in data.areas:
        evo.append(f"fb_area = {area_name(dst)} if FireBrigade.Action = {fb_move(dst)};")
    evo.append("fb_area = fb_area if FireBrigade.Action = fb_rest;")
    evo.append("fb_area = fb_area if FireBrigade.Action = fb_rescue_Civ;")
    for dst in data.areas:
        evo.append(f"at_area = {area_name(dst)} if AmbulanceTeam.Action = {at_move(dst)};")
    evo.append("at_area = at_area if AmbulanceTeam.Action = at_rest;")
    evo.append("at_area = at_area if AmbulanceTeam.Action = at_load_Civ;")
    evo.append("at_area = at_area if AmbulanceTeam.Action = at_unload_Civ;")

    evo.append("-- Rescue")
    for bid in data.buildings:
        for cur in range(6, 0, -1):
            evo.append(
                f"buriedness_value_Civ = {cur - 1} if alive_Civ = true and buriedness_value_Civ = {cur} "
                f"and civ_area = {area_name(bid)} and fb_area = {area_name(bid)} and FireBrigade.Action = fb_rescue_Civ;"
            )

    evo.append("-- Load")
    for area in data.areas:
        evo.append(
            f"loaded_Civ = true if alive_Civ = true and delivered_Civ = false and buriedness_value_Civ = 0 "
            f"and civ_area = {area_name(area)} and at_area = {area_name(area)} and AmbulanceTeam.Action = at_load_Civ;"
        )
        evo.append(
            f"civ_area = in_ambulance if alive_Civ = true and delivered_Civ = false and buriedness_value_Civ = 0 "
            f"and civ_area = {area_name(area)} and at_area = {area_name(area)} and AmbulanceTeam.Action = at_load_Civ;"
        )

    evo.append("-- Unload")
    hg = health_guard(prefix="")
    for area in data.areas:
        evo.append(
            f"loaded_Civ = false if loaded_Civ = true and alive_Civ = true and delivered_Civ = false "
            f"and at_area = {area_name(area)} and refuge_area = {area_name(area)} and {hg} and AmbulanceTeam.Action = at_unload_Civ;"
        )
        evo.append(
            f"delivered_Civ = true if loaded_Civ = true and alive_Civ = true and delivered_Civ = false "
            f"and at_area = {area_name(area)} and refuge_area = {area_name(area)} and {hg} and AmbulanceTeam.Action = at_unload_Civ;"
        )
        evo.append(
            f"civ_area = {area_name(area)} if loaded_Civ = true and alive_Civ = true and delivered_Civ = false "
            f"and at_area = {area_name(area)} and refuge_area = {area_name(area)} and {hg} and AmbulanceTeam.Action = at_unload_Civ;"
        )

    evo.append("-- Health: progresses only while Civ is in a collapsed building")
    collapsed = collapsed_civ_guard(data)
    evo.append("health_clock = health_clock if delivered_Civ = true and dead_Civ = false;")
    evo.append("health_clock = health_clock if dead_Civ = true;")
    for cur in range(19):
        evo.append(
            f"health_clock = {cur + 1} if alive_Civ = true and delivered_Civ = false "
            f"and {collapsed} and health_clock = {cur};"
        )
    evo.append(
        f"health_clock = 0 if alive_Civ = true and delivered_Civ = false "
        f"and {collapsed} and health_clock = 19;"
    )
    evo.append(
        f"health_Civ = high if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = complete and health_clock = 19;"
    )
    evo.append(
        f"health_Civ = moderate if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = high and health_clock = 19;"
    )
    evo.append(
        f"health_Civ = at_risk if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = moderate and health_clock = 19;"
    )
    evo.append(
        f"health_Civ = dead if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = at_risk and health_clock = 19;"
    )
    evo.append(
        f"damage_Civ = moderate if alive_Civ = true and {collapsed} "
        "and health_Civ = complete and health_clock = 19;"
    )
    evo.append(
        f"alive_Civ = false if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = at_risk and health_clock = 19;"
    )
    evo.append(
        f"dead_Civ = true if alive_Civ = true and delivered_Civ = false and {collapsed} "
        "and health_Civ = at_risk and health_clock = 19;"
    )

    return (
        "Agent Environment\n"
        "    Obsvars:\n"
        + indent("\n".join(obs), "        ") + "\n"
        "    end Obsvars\n"
        "    Actions = {env_idle};\n"
        "    Protocol:\n"
        "        Other: {env_idle};\n"
        "    end Protocol\n"
        "    Evolution:\n"
        + indent("\n".join(evo), "        ") + "\n"
        "    end Evolution\n"
        "end Agent\n"
    )


def generate_fb(data: MapData) -> str:
    actions = [fb_move(x) for x in data.areas] + ["fb_rescue_Civ", "fb_rest"]
    lines = [
        "Agent FireBrigade",
        "    Vars:",
        "        dummy: boolean;",
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=4)};",
        "    Protocol:",
        "        Environment.dead_Civ = true: {fb_rest};",
        "        Environment.delivered_Civ = true: {fb_rest};",
    ]
    buried = positive_buried()
    for area in data.areas:
        moves = [fb_move(x) for x in data.neighbours.get(area, [])]
        if area in data.buildings:
            lines += [
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.fb_area = {area_name(area)} and "
                f"Environment.alive_Civ = true and Environment.civ_area = {area_name(area)} and {buried}:",
                f"            {action_set(moves + ['fb_rescue_Civ', 'fb_rest'])};",
            ]
        lines += [
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.fb_area = {area_name(area)}:",
            f"            {action_set(moves + ['fb_rest'])};",
        ]
    lines += [
        "        Other: {fb_rest};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "    end Evolution",
        "end Agent",
    ]
    return "\n".join(lines) + "\n"


def generate_at(data: MapData) -> str:
    actions = [at_move(x) for x in data.areas] + ["at_load_Civ", "at_unload_Civ", "at_rest"]
    lines = [
        "Agent AmbulanceTeam",
        "    Vars:",
        "        dummy: boolean;",
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=4)};",
        "    Protocol:",
        "        Environment.dead_Civ = true: {at_rest};",
        "        Environment.delivered_Civ = true: {at_rest};",
    ]
    hg = health_guard(prefix="Environment.")
    for area in data.areas:
        moves = [at_move(x) for x in data.neighbours.get(area, [])]
        lines += [
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_area = {area_name(area)} and "
            f"Environment.alive_Civ = true and Environment.civ_area = {area_name(area)} and Environment.buriedness_value_Civ = 0 and "
            f"Environment.loaded_Civ = false:",
            f"            {action_set(moves + ['at_load_Civ', 'at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_area = {area_name(area)} and "
            f"Environment.loaded_Civ = true and Environment.alive_Civ = true and Environment.refuge_area = {area_name(area)} and {hg}:",
            f"            {action_set(moves + ['at_unload_Civ', 'at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_area = {area_name(area)} and Environment.loaded_Civ = true:",
            f"            {action_set(moves + ['at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_area = {area_name(area)}:",
            f"            {action_set(moves + ['at_rest'])};",
        ]
    lines += [
        "        Other: {at_rest};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "    end Evolution",
        "end Agent",
    ]
    return "\n".join(lines) + "\n"


def generate_evaluation(data: MapData) -> str:
    delivered_terms = []
    for area in data.areas:
        delivered_terms.append(
            f"(Environment.delivered_Civ = true and Environment.alive_Civ = true and Environment.dead_Civ = false and "
            f"Environment.loaded_Civ = false and Environment.civ_area = {area_name(area)} and Environment.at_area = {area_name(area)} and "
            f"Environment.refuge_area = {area_name(area)})"
        )
    delivered = " or ".join(delivered_terms)
    return f"""Evaluation
    Civ_complete if Environment.health_Civ = complete;
    Civ_high if Environment.health_Civ = high;
    Civ_moderate if Environment.health_Civ = moderate;
    Civ_at_risk if Environment.health_Civ = at_risk;
    Civ_dead if Environment.dead_Civ = true;
    Civ_deep if Environment.buriedness_value_Civ = 4 or Environment.buriedness_value_Civ = 5 or Environment.buriedness_value_Civ = 6;
    Civ_shallow if Environment.buriedness_value_Civ = 1 or Environment.buriedness_value_Civ = 2 or Environment.buriedness_value_Civ = 3;
    surface_Civ_eval if Environment.alive_Civ = true and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;
    loaded_Civ_eval if Environment.loaded_Civ = true;
    rescued_Civ_eval if Environment.alive_Civ = true and Environment.buriedness_value_Civ = 0;
    delivered_alive_Civ_eval if {delivered};
    terminal_dead_Civ_eval if Environment.dead_Civ = true;
    terminal_Civ_eval if Environment.dead_Civ = true or {delivered};
end Evaluation
"""


def generate_init(data: MapData, setup: InitialSetup) -> str:
    init = setup.initial
    lines = ["InitStates", "    -- Init"]
    assignments: List[str] = [
        f"Environment.fb_area = {area_name(int(init['fb_area']))}",
        f"Environment.at_area = {area_name(int(init['at_area']))}",
        f"Environment.civ_area = {area_name(int(init['civ_area']))}",
        f"Environment.refuge_area = {area_name(int(init['refuge_area']))}",
        "Environment.civilian_Civ = true",
    ]
    for rid in data.roads:
        assignments.append(f"Environment.road_{rid} = true")
    for bid in data.buildings:
        assignments.append(f"Environment.building_{bid} = true")
        brokenness = setup.building_brokenness.get(str(bid))
        if brokenness is None and bid in data.forced_collapsed_buildings:
            brokenness = "collapsed"
        if brokenness is None:
            brokenness = setup.building_brokenness_default
        assignments.append(f"Environment.brokenness_{bid} = {brokenness}")
    assignments += [
        f"Environment.all_roads_initially_clear = {'true' if init['all_roads_initially_clear'] else 'false'}",
        f"Environment.health_Civ = {init['health_Civ']}",
        f"Environment.damage_Civ = {init['damage_Civ']}",
        f"Environment.buriedness_value_Civ = {int(init['buriedness_value_Civ'])}",
        f"Environment.health_clock = {int(init['health_clock'])}",
        f"Environment.alive_Civ = {'true' if init['alive_Civ'] else 'false'}",
        f"Environment.dead_Civ = {'true' if init['dead_Civ'] else 'false'}",
        f"Environment.loaded_Civ = {'true' if init['loaded_Civ'] else 'false'}",
        f"Environment.delivered_Civ = {'true' if init['delivered_Civ'] else 'false'}",
        "FireBrigade.dummy = false",
        "AmbulanceTeam.dummy = false",
    ]
    for i, item in enumerate(assignments):
        suffix = ";" if i == len(assignments) - 1 else " and"
        lines.append(f"    {item}{suffix}")
    lines.append("end InitStates")
    return "\n".join(lines) + "\n"


def generate_groups_formulae() -> str:
    return """Groups
    fire_only = {FireBrigade};
    ambulance_only = {AmbulanceTeam};
    rescue_team = {FireBrigade, AmbulanceTeam};
end Groups

Formulae
    <fire_only> F surface_Civ_eval;
    <ambulance_only> F loaded_Civ_eval;
    <rescue_team> F delivered_alive_Civ_eval;
end Formulae
"""


def generate_complete(data: MapData, setup: InitialSetup) -> str:
    validate_initial(data, setup)
    return "\n".join([
        "Semantics=SingleAssignment;\n",
        generate_environment(data),
        generate_fb(data),
        generate_at(data),
        generate_evaluation(data),
        generate_init(data, setup),
        generate_groups_formulae(),
    ])



# ---------- Fire-only exact compatibility ----------

def read_full_initial_config(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Initial JSON must contain an object")
    return data


def requested_agents(config: dict) -> Optional[Set[str]]:
    value = config.get("agents")
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("agents must be a non-empty list when provided")
    return {str(item) for item in value}


def is_fire_only_config(config: dict) -> bool:
    agents = requested_agents(config)
    return agents == {"FireBrigade"}


def validate_fire_only_config(data: MapData, config: dict) -> None:
    if requested_agents(config) != {"FireBrigade"}:
        raise ValueError("Fire-only compatibility requires agents = ['FireBrigade']")

    init = dict(config.get("initial", {}))
    required = [
        "fb_area", "civ_area", "health_Civ", "hp_Civ", "damage_Civ",
        "buriedness_value_Civ", "alive_Civ", "dead_Civ",
        "loaded_Civ", "delivered_Civ", "all_roads_initially_clear",
    ]
    missing = [name for name in required if name not in init]
    if missing:
        raise ValueError(f"fire-only initial JSON is missing required fields: {missing}")

    areas = set(data.areas)
    if int(init["fb_area"]) not in areas:
        raise ValueError(f"initial.fb_area={init['fb_area']} is not a map area id")
    if int(init["civ_area"]) not in areas:
        raise ValueError(f"initial.civ_area={init['civ_area']} is not a map area id")
    if int(init["civ_area"]) not in set(data.buildings):
        raise ValueError("initial.civ_area must be a building for a buried civilian")

    if str(init["health_Civ"]) not in VALID_HEALTH - {"complete"}:
        raise ValueError("fire-only health_Civ must be high, moderate, at_risk, or dead")
    if str(init["damage_Civ"]) not in VALID_DAMAGE:
        raise ValueError("damage_Civ must be none or moderate")
    if not (0 <= int(init["buriedness_value_Civ"]) <= 6):
        raise ValueError("buriedness_value_Civ must be between 0 and 6")
    if int(init["hp_Civ"]) < 0:
        raise ValueError("hp_Civ must be non-negative")
    for key in ["alive_Civ", "dead_Civ", "loaded_Civ", "delivered_Civ", "all_roads_initially_clear"]:
        if not isinstance(init[key], bool):
            raise ValueError(f"initial.{key} must be true or false")

    default_brokenness = str(config.get("building_brokenness_default", "healthy"))
    overrides = {str(k): str(v) for k, v in dict(config.get("building_brokenness", {})).items()}
    if default_brokenness not in VALID_BROKENNESS:
        raise ValueError("building_brokenness_default must be healthy, damaged, or collapsed")
    for raw_id, value in overrides.items():
        if int(raw_id) not in set(data.buildings):
            raise ValueError(f"building_brokenness contains {raw_id}, but it is not a building id")
        if value not in VALID_BROKENNESS:
            raise ValueError(f"brokenness for building {raw_id} must be healthy, damaged, or collapsed")

    model = dict(config.get("health_model", {}))
    if model.get("mode") != "fixed_damage_per_action":
        raise ValueError("fire-only health_model.mode must be fixed_damage_per_action")
    damage = int(model.get("damage_per_action", 0))
    if damage <= 0:
        raise ValueError("health_model.damage_per_action must be positive")
    hp = int(init["hp_Civ"])
    sequence = [str(item) for item in model.get("symbolic_sequence", [])]
    expected_steps = (hp + damage - 1) // damage
    if len(sequence) != expected_steps + 1:
        raise ValueError(
            "health_model.symbolic_sequence must contain one state for the initial HP "
            "plus one state after every damage step"
        )
    if sequence[0] != str(init["health_Civ"]):
        raise ValueError("symbolic_sequence[0] must equal initial.health_Civ")
    if sequence[-1] != "dead":
        raise ValueError("symbolic_sequence must end in dead")
    if any(item not in VALID_HEALTH for item in sequence):
        raise ValueError("symbolic_sequence contains an unsupported health state")


def fire_only_health_steps(config: dict) -> List[Tuple[int, int, str, str]]:
    init = dict(config["initial"])
    model = dict(config["health_model"])
    hp = int(init["hp_Civ"])
    damage = int(model["damage_per_action"])
    sequence = [str(item) for item in model["symbolic_sequence"]]
    steps: List[Tuple[int, int, str, str]] = []
    current_hp = hp
    for current_state, next_state in zip(sequence, sequence[1:]):
        next_hp = max(0, current_hp - damage)
        steps.append((current_hp, next_hp, current_state, next_state))
        current_hp = next_hp
    return steps


def render_config_groups_formulae(config: dict) -> str:
    groups = config.get("groups") or {"fire_only": ["FireBrigade"]}
    group_lines = ["Groups"]
    for name, members in groups.items():
        if not isinstance(members, list):
            raise ValueError(f"group {name} must be a list")
        kept = [str(member) for member in members if str(member) == "FireBrigade"]
        if kept:
            clean = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).strip())
            if not clean or clean[0].isdigit():
                clean = "g_" + clean
            group_lines.append(f"    {clean} = {{{', '.join(kept)}}};")
    if len(group_lines) == 1:
        group_lines.append("    fire_only = {FireBrigade};")
    group_lines.append("end Groups")

    formula_lines = ["Formulae"]
    formulae = config.get("formulae") or ["<fire_only> F surface_alive_Civ_eval;"]
    for formula in formulae:
        value = str(formula).strip()
        if not value:
            continue
        if not value.endswith(";"):
            value += ";"
        formula_lines.append(f"    {value}")
    formula_lines.append("end Formulae")
    return "\n".join(group_lines + [""] + formula_lines) + "\n"


def fire_only_brokenness(data: MapData, config: dict, bid: int) -> str:
    overrides = {str(k): str(v) for k, v in dict(config.get("building_brokenness", {})).items()}
    if str(bid) in overrides:
        return overrides[str(bid)]
    if bid in data.forced_collapsed_buildings:
        return "collapsed"
    return str(config.get("building_brokenness_default", "healthy"))


def generate_fire_only_environment(data: MapData, config: dict) -> str:
    area_enum = wrap_enum(all_area_values(data), width=8)
    init = dict(config["initial"])
    hp_max = int(init["hp_Civ"])

    obs: List[str] = [
        f"fb_area: {area_enum};",
        f"civ_area: {area_enum};",
        "civilian_Civ: boolean;",
    ]
    for rid in data.roads:
        obs.append(f"road_{rid}: boolean;")
    for bid in data.buildings:
        obs.append(f"building_{bid}: boolean;")
        obs.append(f"brokenness_{bid}: {{healthy, damaged, collapsed}};")
    obs += [
        "all_roads_initially_clear: boolean;",
        f"hp_Civ: 0 .. {hp_max};",
        "health_Civ: {complete, high, moderate, at_risk, dead};",
        "damage_Civ: {none, moderate};",
        "buriedness_value_Civ: 0 .. 6;",
        "alive_Civ: boolean;",
        "dead_Civ: boolean;",
        "loaded_Civ: boolean;",
        "delivered_Civ: boolean;",
    ]

    evo: List[str] = ["-- Movement"]
    for dst in data.areas:
        evo.append(f"fb_area = {area_name(dst)} if FireBrigade.Action = {fb_move(dst)};")
    evo.append("fb_area = fb_area if FireBrigade.Action = fb_rest;")
    evo.append("fb_area = fb_area if FireBrigade.Action = fb_rescue_Civ;")

    evo.append("-- Rescue")
    for bid in data.buildings:
        for cur in range(6, 0, -1):
            evo.append(
                f"buriedness_value_Civ = {cur - 1} if alive_Civ = true and buriedness_value_Civ = {cur} "
                f"and civ_area = {area_name(bid)} and fb_area = {area_name(bid)} and FireBrigade.Action = fb_rescue_Civ;"
            )

    evo.append("-- Fixed damage while Civ is in a collapsed building")
    collapsed = collapsed_civ_guard(data)
    for current_hp, next_hp, current_state, next_state in fire_only_health_steps(config):
        guard = (
            f"alive_Civ = true and {collapsed} and hp_Civ = {current_hp} "
            f"and health_Civ = {current_state}"
        )
        evo.append(f"hp_Civ = {next_hp} if {guard};")
        evo.append(f"health_Civ = {next_state} if {guard};")
        if next_hp == 0 or next_state == "dead":
            evo.append(f"alive_Civ = false if {guard};")
            evo.append(f"dead_Civ = true if {guard};")

    return (
        "Agent Environment\n"
        "    Obsvars:\n"
        + indent("\n".join(obs), "        ") + "\n"
        "    end Obsvars\n"
        "    Actions = {env_idle};\n"
        "    Protocol:\n"
        "        Other: {env_idle};\n"
        "    end Protocol\n"
        "    Evolution:\n"
        + indent("\n".join(evo), "        ") + "\n"
        "    end Evolution\n"
        "end Agent\n"
    )


def generate_fire_only_evaluation() -> str:
    return """Evaluation
    Civ_complete if Environment.health_Civ = complete;
    Civ_high if Environment.health_Civ = high;
    Civ_moderate if Environment.health_Civ = moderate;
    Civ_at_risk if Environment.health_Civ = at_risk;
    Civ_dead if Environment.dead_Civ = true;
    Civ_deep if Environment.buriedness_value_Civ = 4 or Environment.buriedness_value_Civ = 5 or Environment.buriedness_value_Civ = 6;
    Civ_shallow if Environment.buriedness_value_Civ = 1 or Environment.buriedness_value_Civ = 2 or Environment.buriedness_value_Civ = 3;
    surface_alive_Civ_eval if Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;
    surface_Civ_eval if Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;
    rescued_Civ_eval if Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.buriedness_value_Civ = 0;
    terminal_dead_Civ_eval if Environment.dead_Civ = true;
    terminal_Civ_eval if Environment.dead_Civ = true;
end Evaluation
"""


def generate_fire_only_init(data: MapData, config: dict) -> str:
    init = dict(config["initial"])
    assignments: List[str] = [
        f"Environment.fb_area = {area_name(int(init['fb_area']))}",
        f"Environment.civ_area = {area_name(int(init['civ_area']))}",
        "Environment.civilian_Civ = true",
    ]
    for rid in data.roads:
        assignments.append(f"Environment.road_{rid} = true")
    for bid in data.buildings:
        assignments.append(f"Environment.building_{bid} = true")
        assignments.append(f"Environment.brokenness_{bid} = {fire_only_brokenness(data, config, bid)}")
    assignments += [
        f"Environment.all_roads_initially_clear = {'true' if init['all_roads_initially_clear'] else 'false'}",
        f"Environment.hp_Civ = {int(init['hp_Civ'])}",
        f"Environment.health_Civ = {init['health_Civ']}",
        f"Environment.damage_Civ = {init['damage_Civ']}",
        f"Environment.buriedness_value_Civ = {int(init['buriedness_value_Civ'])}",
        f"Environment.alive_Civ = {'true' if init['alive_Civ'] else 'false'}",
        f"Environment.dead_Civ = {'true' if init['dead_Civ'] else 'false'}",
        f"Environment.loaded_Civ = {'true' if init['loaded_Civ'] else 'false'}",
        f"Environment.delivered_Civ = {'true' if init['delivered_Civ'] else 'false'}",
        "FireBrigade.dummy = false",
    ]
    lines = ["InitStates", "    -- Init"]
    for index, item in enumerate(assignments):
        suffix = ";" if index == len(assignments) - 1 else " and"
        lines.append(f"    {item}{suffix}")
    lines.append("end InitStates")
    return "\n".join(lines) + "\n"


def generate_fire_only_complete(data: MapData, config: dict) -> str:
    validate_fire_only_config(data, config)
    return "\n".join([
        "Semantics=SingleAssignment;\n",
        generate_fire_only_environment(data, config),
        generate_fb(data),
        generate_fire_only_evaluation(),
        generate_fire_only_init(data, config),
        render_config_groups_formulae(config),
    ])



# ---------- Exact two-agent compatibility ----------

def is_exact_two_agent_config(config: dict) -> bool:
    agents = requested_agents(config)
    return agents == {"FireBrigade", "AmbulanceTeam"} and "health_model" in config


def validate_exact_two_agent_config(data: MapData, config: dict) -> None:
    if requested_agents(config) != {"FireBrigade", "AmbulanceTeam"}:
        raise ValueError(
            "Exact two-agent compatibility requires agents = "
            "['FireBrigade', 'AmbulanceTeam']"
        )
    init = dict(config.get("initial", {}))
    required = [
        "fb_area", "at_area", "civ_area", "refuge_area", "health_Civ", "hp_Civ",
        "damage_Civ", "buriedness_value_Civ", "alive_Civ", "dead_Civ",
        "loaded_Civ", "delivered_Civ", "all_roads_initially_clear",
    ]
    missing = [name for name in required if name not in init]
    if missing:
        raise ValueError(f"exact two-agent initial JSON is missing required fields: {missing}")

    areas = set(data.areas)
    buildings = set(data.buildings)
    for key in ["fb_area", "at_area", "civ_area", "refuge_area"]:
        if int(init[key]) not in areas:
            raise ValueError(f"initial.{key}={init[key]} is not a map area id")
    if int(init["civ_area"]) not in buildings:
        raise ValueError("initial.civ_area must be a building")
    if int(init["refuge_area"]) not in buildings:
        raise ValueError("initial.refuge_area must be a building")
    if str(init["health_Civ"]) not in VALID_HEALTH - {"dead"}:
        raise ValueError("health_Civ must be complete, high, moderate, or at_risk")
    if str(init["damage_Civ"]) not in VALID_DAMAGE:
        raise ValueError("damage_Civ must be none or moderate")
    if not (0 <= int(init["buriedness_value_Civ"]) <= 6):
        raise ValueError("buriedness_value_Civ must be between 0 and 6")
    if int(init["hp_Civ"]) <= 0:
        raise ValueError("hp_Civ must be positive")
    for key in ["alive_Civ", "dead_Civ", "loaded_Civ", "delivered_Civ", "all_roads_initially_clear"]:
        if not isinstance(init[key], bool):
            raise ValueError(f"initial.{key} must be true or false")

    model = dict(config.get("health_model", {}))
    if model.get("mode") != "fixed_damage_per_action":
        raise ValueError("health_model.mode must be fixed_damage_per_action")
    damage = int(model.get("damage_per_action", 0))
    if damage <= 0:
        raise ValueError("health_model.damage_per_action must be positive")
    sequence = [str(item) for item in model.get("symbolic_sequence", [])]
    hp = int(init["hp_Civ"])
    expected_steps = (hp + damage - 1) // damage
    if len(sequence) != expected_steps + 1:
        raise ValueError(
            "health_model.symbolic_sequence must contain the initial state and "
            "one state after each damage step"
        )
    if sequence[0] != str(init["health_Civ"]):
        raise ValueError("symbolic_sequence[0] must equal initial.health_Civ")
    if sequence[-1] != "dead":
        raise ValueError("symbolic_sequence must end in dead")
    if any(item not in VALID_HEALTH for item in sequence):
        raise ValueError("symbolic_sequence contains an unsupported health state")


def exact_health_steps(config: dict) -> List[Tuple[int, int, str, str]]:
    init = dict(config["initial"])
    model = dict(config["health_model"])
    current_hp = int(init["hp_Civ"])
    damage = int(model["damage_per_action"])
    sequence = [str(item) for item in model["symbolic_sequence"]]
    steps: List[Tuple[int, int, str, str]] = []
    for current_state, next_state in zip(sequence, sequence[1:]):
        next_hp = max(0, current_hp - damage)
        steps.append((current_hp, next_hp, current_state, next_state))
        current_hp = next_hp
    return steps


def exact_brokenness(data: MapData, config: dict, bid: int) -> str:
    overrides = {str(k): str(v) for k, v in dict(config.get("building_brokenness", {})).items()}
    if str(bid) in overrides:
        return overrides[str(bid)]
    if bid in data.forced_collapsed_buildings:
        return "collapsed"
    return str(config.get("building_brokenness_default", "healthy"))


def render_exact_groups_formulae(config: dict) -> str:
    groups = config.get("groups") or {
        "fire_only": ["FireBrigade"],
        "ambulance_only": ["AmbulanceTeam"],
        "rescue_team": ["FireBrigade", "AmbulanceTeam"],
    }
    lines = ["Groups"]
    allowed = {"FireBrigade", "AmbulanceTeam"}
    for name, members in groups.items():
        if not isinstance(members, list):
            raise ValueError(f"group {name} must be a list")
        kept = [str(member) for member in members if str(member) in allowed]
        if not kept:
            continue
        clean = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).strip())
        if not clean or clean[0].isdigit():
            clean = "g_" + clean
        lines.append(f"    {clean} = {{{', '.join(kept)}}};")
    lines.append("end Groups")
    lines.append("")
    lines.append("Formulae")
    formulae = config.get("formulae") or [
        "<fire_only> F surface_alive_Civ_eval;",
        "<rescue_team> F delivered_alive_Civ_eval;",
    ]
    for formula in formulae:
        value = str(formula).strip()
        if value:
            lines.append(f"    {value if value.endswith(';') else value + ';'}")
    lines.append("end Formulae")
    return "\n".join(lines) + "\n"


def generate_exact_two_agent_environment(data: MapData, config: dict) -> str:
    area_enum = wrap_enum(all_area_values(data), width=8)
    civ_enum = wrap_enum(all_area_values(data) + ["in_ambulance"], width=8)
    init = dict(config["initial"])
    hp_max = int(init["hp_Civ"])

    obs: List[str] = [
        f"fb_area: {area_enum};",
        f"at_area: {area_enum};",
        f"civ_area: {civ_enum};",
        f"refuge_area: {area_enum};",
        "civilian_Civ: boolean;",
    ]
    for rid in data.roads:
        obs.append(f"road_{rid}: boolean;")
    for bid in data.buildings:
        obs.append(f"building_{bid}: boolean;")
        obs.append(f"brokenness_{bid}: {{healthy, damaged, collapsed}};")
    obs += [
        "all_roads_initially_clear: boolean;",
        f"hp_Civ: 0 .. {hp_max};",
        "health_Civ: {complete, high, moderate, at_risk, dead};",
        "damage_Civ: {none, moderate};",
        "buriedness_value_Civ: 0 .. 6;",
        "alive_Civ: boolean;",
        "dead_Civ: boolean;",
        "loaded_Civ: boolean;",
        "delivered_Civ: boolean;",
    ]

    evo: List[str] = ["-- Movement"]
    for dst in data.areas:
        evo.append(f"fb_area = {area_name(dst)} if FireBrigade.Action = {fb_move(dst)};")
    evo += [
        "fb_area = fb_area if FireBrigade.Action = fb_rest;",
        "fb_area = fb_area if FireBrigade.Action = fb_rescue_Civ;",
    ]
    for dst in data.areas:
        evo.append(f"at_area = {area_name(dst)} if AmbulanceTeam.Action = {at_move(dst)};")
    evo += [
        "at_area = at_area if AmbulanceTeam.Action = at_rest;",
        "at_area = at_area if AmbulanceTeam.Action = at_load_Civ;",
        "at_area = at_area if AmbulanceTeam.Action = at_unload_Civ;",
    ]

    evo.append("-- Rescue")
    for bid in data.buildings:
        for cur in range(6, 0, -1):
            evo.append(
                f"buriedness_value_Civ = {cur - 1} if alive_Civ = true and buriedness_value_Civ = {cur} "
                f"and civ_area = {area_name(bid)} and fb_area = {area_name(bid)} "
                "and FireBrigade.Action = fb_rescue_Civ;"
            )

    evo.append("-- Load")
    for area in data.areas:
        guard = (
            f"alive_Civ = true and dead_Civ = false and delivered_Civ = false and "
            f"buriedness_value_Civ = 0 and loaded_Civ = false and civ_area = {area_name(area)} "
            f"and at_area = {area_name(area)} and AmbulanceTeam.Action = at_load_Civ"
        )
        evo.append(f"loaded_Civ = true if {guard};")
        evo.append(f"civ_area = in_ambulance if {guard};")

    evo.append("-- Unload")
    for area in data.areas:
        guard = (
            f"loaded_Civ = true and alive_Civ = true and dead_Civ = false and delivered_Civ = false "
            f"and at_area = {area_name(area)} and refuge_area = {area_name(area)} "
            "and AmbulanceTeam.Action = at_unload_Civ"
        )
        evo.append(f"loaded_Civ = false if {guard};")
        evo.append(f"delivered_Civ = true if {guard};")
        evo.append(f"civ_area = {area_name(area)} if {guard};")

    evo.append("-- Fixed damage only while Civ remains buried in a collapsed building")
    collapsed = collapsed_civ_guard(data)
    buried = positive_buried("")
    for current_hp, next_hp, current_state, next_state in exact_health_steps(config):
        guard = (
            f"alive_Civ = true and delivered_Civ = false and {collapsed} and {buried} "
            f"and hp_Civ = {current_hp} and health_Civ = {current_state}"
        )
        evo.append(f"hp_Civ = {next_hp} if {guard};")
        evo.append(f"health_Civ = {next_state} if {guard};")
        if next_hp == 0 or next_state == "dead":
            evo.append(f"alive_Civ = false if {guard};")
            evo.append(f"dead_Civ = true if {guard};")

    return (
        "Agent Environment\n"
        "    Obsvars:\n"
        + indent("\n".join(obs), "        ") + "\n"
        "    end Obsvars\n"
        "    Actions = {env_idle};\n"
        "    Protocol:\n"
        "        Other: {env_idle};\n"
        "    end Protocol\n"
        "    Evolution:\n"
        + indent("\n".join(evo), "        ") + "\n"
        "    end Evolution\n"
        "end Agent\n"
    )


def exact_two_agent_terminal_guard(data: MapData, prefix: str = "Environment.") -> str:
    """Terminal when Civ is dead or alive, surface-level, unloaded, and at a refuge."""
    delivered_alive = " or ".join(
        f"({prefix}alive_Civ = true and {prefix}dead_Civ = false and "
        f"{prefix}loaded_Civ = false and {prefix}buriedness_value_Civ = 0 and "
        f"{prefix}civ_area = {area_name(area)} and {prefix}at_area = {area_name(area)} and "
        f"{prefix}refuge_area = {area_name(area)})"
        for area in data.areas
    )
    return f"({prefix}dead_Civ = true or ({delivered_alive}))"


def generate_exact_two_agent_fb(data: MapData) -> str:
    actions = [fb_move(x) for x in data.areas] + ["fb_rescue_Civ", "fb_rest"]
    lines = [
        "Agent FireBrigade", "    Vars:", "        dummy: boolean;", "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=4)};",
        "    Protocol:",
        f"        {exact_two_agent_terminal_guard(data)}: {{fb_rest}};",
    ]
    buried = positive_buried()
    for area in data.areas:
        moves = [fb_move(x) for x in data.neighbours.get(area, [])]
        if area in data.buildings:
            lines += [
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
                f"Environment.fb_area = {area_name(area)} and Environment.alive_Civ = true and "
                f"Environment.civ_area = {area_name(area)} and {buried}:",
                f"            {action_set(moves + ['fb_rescue_Civ', 'fb_rest'])};",
            ]
        lines += [
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
            f"Environment.fb_area = {area_name(area)}:",
            f"            {action_set(moves + ['fb_rest'])};",
        ]
    lines += [
        "        Other: {fb_rest};", "    end Protocol", "    Evolution:",
        "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
        "    end Evolution", "end Agent",
    ]
    return "\n".join(lines) + "\n"


def generate_exact_two_agent_at(data: MapData) -> str:
    actions = [at_move(x) for x in data.areas] + ["at_load_Civ", "at_unload_Civ", "at_rest"]
    lines = [
        "Agent AmbulanceTeam", "    Vars:", "        dummy: boolean;", "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=4)};",
        "    Protocol:",
        f"        {exact_two_agent_terminal_guard(data)}: {{at_rest}};",
    ]
    for area in data.areas:
        moves = [at_move(x) for x in data.neighbours.get(area, [])]
        lines += [
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
            f"Environment.at_area = {area_name(area)} and Environment.alive_Civ = true and "
            f"Environment.civ_area = {area_name(area)} and Environment.buriedness_value_Civ = 0 and "
            "Environment.loaded_Civ = false:",
            f"            {action_set(moves + ['at_load_Civ', 'at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
            f"Environment.at_area = {area_name(area)} and Environment.loaded_Civ = true and "
            f"Environment.alive_Civ = true and Environment.refuge_area = {area_name(area)}:",
            f"            {action_set(moves + ['at_unload_Civ', 'at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
            f"Environment.at_area = {area_name(area)} and Environment.loaded_Civ = true:",
            f"            {action_set(moves + ['at_rest'])};",
            f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and "
            f"Environment.at_area = {area_name(area)}:",
            f"            {action_set(moves + ['at_rest'])};",
        ]
    lines += [
        "        Other: {at_rest};", "    end Protocol", "    Evolution:",
        "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
        "    end Evolution", "end Agent",
    ]
    return "\n".join(lines) + "\n"


def generate_exact_two_agent_evaluation(data: MapData) -> str:
    buried = " or ".join(f"Environment.buriedness_value_Civ = {i}" for i in range(1, 7))
    delivered_terms = " or ".join(
        f"(Environment.delivered_Civ = true and Environment.alive_Civ = true and "
        f"Environment.dead_Civ = false and Environment.loaded_Civ = false and "
        f"Environment.civ_area = {area_name(area)} and Environment.at_area = {area_name(area)} and "
        f"Environment.refuge_area = {area_name(area)})"
        for area in data.areas
    )
    return f"""Evaluation
    Civ_complete if Environment.health_Civ = complete;
    Civ_high if Environment.health_Civ = high;
    Civ_moderate if Environment.health_Civ = moderate;
    Civ_at_risk if Environment.health_Civ = at_risk;
    Civ_dead if Environment.dead_Civ = true;
    Civ_deep if Environment.buriedness_value_Civ = 4 or Environment.buriedness_value_Civ = 5 or Environment.buriedness_value_Civ = 6;
    Civ_shallow if Environment.buriedness_value_Civ = 1 or Environment.buriedness_value_Civ = 2 or Environment.buriedness_value_Civ = 3;
    surface_alive_Civ_eval if Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;
    surface_Civ_eval if Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;
    loaded_Civ_eval if Environment.loaded_Civ = true;
    illegal_buried_load_eval if Environment.loaded_Civ = true and ({buried});
    delivered_alive_Civ_eval if {delivered_terms};
    terminal_dead_Civ_eval if Environment.dead_Civ = true;
    terminal_Civ_eval if {exact_two_agent_terminal_guard(data)};
end Evaluation
"""


def generate_exact_two_agent_init(data: MapData, config: dict) -> str:
    init = dict(config["initial"])
    assignments: List[str] = [
        f"Environment.fb_area = {area_name(int(init['fb_area']))}",
        f"Environment.at_area = {area_name(int(init['at_area']))}",
        f"Environment.civ_area = {area_name(int(init['civ_area']))}",
        f"Environment.refuge_area = {area_name(int(init['refuge_area']))}",
        "Environment.civilian_Civ = true",
    ]
    for rid in data.roads:
        assignments.append(f"Environment.road_{rid} = true")
    for bid in data.buildings:
        assignments.append(f"Environment.building_{bid} = true")
        assignments.append(f"Environment.brokenness_{bid} = {exact_brokenness(data, config, bid)}")
    assignments += [
        f"Environment.all_roads_initially_clear = {'true' if init['all_roads_initially_clear'] else 'false'}",
        f"Environment.hp_Civ = {int(init['hp_Civ'])}",
        f"Environment.health_Civ = {init['health_Civ']}",
        f"Environment.damage_Civ = {init['damage_Civ']}",
        f"Environment.buriedness_value_Civ = {int(init['buriedness_value_Civ'])}",
        f"Environment.alive_Civ = {'true' if init['alive_Civ'] else 'false'}",
        f"Environment.dead_Civ = {'true' if init['dead_Civ'] else 'false'}",
        f"Environment.loaded_Civ = {'true' if init['loaded_Civ'] else 'false'}",
        f"Environment.delivered_Civ = {'true' if init['delivered_Civ'] else 'false'}",
        "FireBrigade.dummy = false",
        "AmbulanceTeam.dummy = false",
    ]
    lines = ["InitStates", "    -- Init"]
    for index, item in enumerate(assignments):
        lines.append(f"    {item}{';' if index == len(assignments) - 1 else ' and'}")
    lines.append("end InitStates")
    return "\n".join(lines) + "\n"


def generate_exact_two_agent_complete(data: MapData, config: dict) -> str:
    validate_exact_two_agent_config(data, config)
    return "\n".join([
        "Semantics=SingleAssignment;\n",
        generate_exact_two_agent_environment(data, config),
        generate_exact_two_agent_fb(data),
        generate_exact_two_agent_at(data),
        generate_exact_two_agent_evaluation(data),
        generate_exact_two_agent_init(data, config),
        render_exact_groups_formulae(config),
    ])

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the baseline MCMAS model used as input to the paper-aligned Jason translation.")
    parser.add_argument("--input", required=True, help="RCRS map zip")
    parser.add_argument("--initial", required=True, help="Initial setup JSON")
    parser.add_argument("--output", required=True, help="Output ISPL")
    args = parser.parse_args()

    data = read_map(Path(args.input))
    config = read_full_initial_config(Path(args.initial))
    if is_fire_only_config(config):
        output = generate_fire_only_complete(data, config)
    elif is_exact_two_agent_config(config):
        output = generate_exact_two_agent_complete(data, config)
    else:
        setup = load_initial(Path(args.initial))
        output = generate_complete(data, setup)
    Path(args.output).write_text(output)
    print(f"Wrote ISPL: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
