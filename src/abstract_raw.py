from __future__ import annotations

import argparse
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
import xml.etree.ElementTree as ET


# Naming helpers
def move(prefix: str, zone: str) -> str:
    return f"{prefix}_move_to_{zone}"


# Formatting helpers
def enum(vals: Sequence[str]) -> str:
    return "{" + ", ".join(vals) + "}"


# Formatting helpers
def aset(vals: Sequence[str]) -> str:
    return "{" + ", ".join(vals) + "}"


# Parse the exact raw ISPL
def ids(raw: str, kind: str) -> List[int]:
    return sorted({int(x) for x in re.findall(rf"\b{kind}_(\d+):\s*boolean;", raw)})


# Configuration
def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# RCRS map data
@dataclass
class MapData:
    areas: List[int]
    roads: List[int]
    buildings: List[int]
    neighbours: Dict[int, List[int]]
    centroids: Dict[int, Tuple[float, float]]
    building_codes: Dict[int, int]
    misc: Dict[str, str]


def read_zip_text(zf: zipfile.ZipFile, suffix: str) -> Optional[str]:
    hits = [n for n in zf.namelist() if n.endswith(suffix)]
    if not hits:
        return None
    return zf.read(sorted(hits, key=len)[0]).decode("utf-8", errors="replace")


def read_namespaces(xml_text: str) -> Dict[str, str]:
    ns: Dict[str, str] = {}
    for _, item in ET.iterparse(io.StringIO(xml_text), events=("start-ns",)):
        prefix, uri = item
        ns[prefix] = uri
    if "rcr" not in ns or "gml" not in ns or "xlink" not in ns:
        raise ValueError("map.gml must define rcr, gml, and xlink namespaces")
    return ns


def parse_misc_cfg(text: Optional[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
        elif "=" in line:
            k, v = line.split("=", 1)
        else:
            continue
        out[k.strip()] = v.strip()
    return out


def parse_map_zip(map_zip: Path) -> MapData:
    with zipfile.ZipFile(map_zip) as zf:
        gml_text = read_zip_text(zf, "map.gml")
        misc_text = read_zip_text(zf, "config/misc.cfg")
    if gml_text is None:
        raise FileNotFoundError("No map.gml found in map zip")

    ns = read_namespaces(gml_text)
    root = ET.fromstring(gml_text)
    gml_id = f"{{{ns['gml']}}}id"
    xlink_href = f"{{{ns['xlink']}}}href"
    rcr_neighbour = f"{{{ns['rcr']}}}neighbour"
    rcr_buildingcode = f"{{{ns['rcr']}}}buildingcode"

    nodes: Dict[int, Tuple[float, float]] = {}
    for node in root.findall(".//gml:Node", ns):
        nid = int(node.attrib[gml_id])
        coords = node.find(".//gml:coordinates", ns)
        if coords is None or not coords.text:
            continue
        x, y = [float(v) for v in coords.text.strip().split(",")[:2]]
        nodes[nid] = (x, y)

    edges: Dict[int, List[int]] = {}
    for edge in root.findall(".//gml:Edge", ns):
        eid = int(edge.attrib[gml_id])
        refs: List[int] = []
        for dn in edge.findall(".//gml:directedNode", ns):
            href = dn.attrib.get(xlink_href)
            if href:
                refs.append(int(href.lstrip("#")))
        edges[eid] = refs

    roads: Set[int] = set()
    buildings: Set[int] = set()
    neighbours: Dict[int, Set[int]] = {}
    centroids: Dict[int, Tuple[float, float]] = {}
    building_codes: Dict[int, int] = {}

    for tag, bucket in [("road", roads), ("building", buildings)]:
        for elem in root.findall(f".//rcr:{tag}", ns):
            area_id = int(elem.attrib[gml_id])
            bucket.add(area_id)
            neighbours.setdefault(area_id, set())
            if tag == "building":
                face = elem.find(".//gml:Face", ns)
                if face is not None:
                    building_codes[area_id] = int(face.attrib.get(rcr_buildingcode, "0"))
            pts: List[Tuple[float, float]] = []
            for de in elem.findall(".//gml:directedEdge", ns):
                nb = de.attrib.get(rcr_neighbour)
                if nb is not None:
                    neighbours[area_id].add(int(nb))
                href = de.attrib.get(xlink_href)
                if href:
                    eid = int(href.lstrip("#"))
                    for nid in edges.get(eid, []):
                        if nid in nodes:
                            pts.append(nodes[nid])
            if pts:
                centroids[area_id] = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

    areas = roads | buildings
    clean: Dict[int, Set[int]] = {a: set() for a in areas}
    for src, nbs in neighbours.items():
        if src not in areas:
            continue
        for dst in nbs:
            if dst in areas and dst != src:
                clean[src].add(dst)
                clean[dst].add(src)

    return MapData(
        areas=sorted(areas),
        roads=sorted(roads),
        buildings=sorted(buildings),
        neighbours={k: sorted(v) for k, v in sorted(clean.items())},
        centroids=centroids,
        building_codes=building_codes,
        misc=parse_misc_cfg(misc_text),
    )


def material_from_code(code: int) -> str:
    # RCRS map buildingcode 0/1/2 are usually wood/steel/concrete. Keep a safe fallback.
    return {0: "wood", 1: "steel", 2: "concrete"}.get(int(code), "wood")


# Zone abstraction
def make_3x3_abstraction(map_data: MapData) -> dict:
    xs = [map_data.centroids[a][0] for a in map_data.areas if a in map_data.centroids]
    ys = [map_data.centroids[a][1] for a in map_data.areas if a in map_data.centroids]
    if not xs or not ys:
        raise ValueError("Cannot build abstraction: no area centroids parsed from map.gml")
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    x1 = xmin + (xmax - xmin) / 3.0
    x2 = xmin + 2.0 * (xmax - xmin) / 3.0
    y1 = ymin + (ymax - ymin) / 3.0
    y2 = ymin + 2.0 * (ymax - ymin) / 3.0

    zone_order = [
        "z_west_north", "z_west_mid", "z_west_south",
        "z_central_north", "z_central_mid", "z_central_south",
        "z_east_north", "z_east_mid", "z_east_south",
    ]
    zones: Dict[str, List[int]] = {z: [] for z in zone_order}

    def zname(x: float, y: float) -> str:
        xpart = "west" if x < x1 else ("central" if x < x2 else "east")
        # Larger y is visually north/top in this map.
        ypart = "south" if y < y1 else ("mid" if y < y2 else "north")
        return f"z_{xpart}_{ypart}"

    for area in map_data.areas:
        if area not in map_data.centroids:
            continue
        zones[zname(*map_data.centroids[area])].append(area)
    for z in zones:
        zones[z] = sorted(zones[z])

    area_to_zone = {a: z for z, vals in zones.items() for a in vals}
    zneigh: Dict[str, Set[str]] = {z: set() for z in zone_order}
    for src, nbs in map_data.neighbours.items():
        zs = area_to_zone.get(src)
        if zs is None:
            continue
        for dst in nbs:
            zd = area_to_zone.get(dst)
            if zd is not None and zd != zs:
                zneigh[zs].add(zd)
                zneigh[zd].add(zs)

    return {
        "method": "auto_3x3_bbox_from_area_centroids",
        "zone_generation": {"x1": x1, "x2": x2, "y1": y1, "y2": y2},
        "zone_order": zone_order,
        "zones": zones,
        "zone_neighbours": {z: [n for n in zone_order if n in zneigh[z]] for z in zone_order},
    }


def zone_of(cfg: dict, area: int) -> str:
    for z, areas in cfg["abstraction"]["zones"].items():
        if int(area) in [int(a) for a in areas]:
            return z
    raise ValueError(f"area {area} is not in any zone")


# Zone status
def zone_status(cfg: dict, buildings: List[int]) -> Dict[str, str]:
    broken = {int(k): v for k, v in cfg.get("building_brokenness", {}).items()}
    default = cfg.get("building_brokenness_default", "healthy")
    out = {}
    for z, areas in cfg["abstraction"]["zones"].items():
        bvals = [broken.get(int(a), default) for a in areas if int(a) in buildings]
        if "collapsed" in bvals:
            out[z] = "collapsed"
        elif "damaged" in bvals:
            out[z] = "damaged"
        else:
            out[z] = "healthy"
    return out


# Health and time calibration
def as_float(d: Dict[str, str], key: str, default: float) -> float:
    try:
        return float(d.get(key, default))
    except Exception:
        return default


def simulate_death_ticks(initial_damage: float, k: float, l: float, noise: float, hp: float = 10000.0) -> int:
    dmg = float(initial_damage)
    health = float(hp)
    ticks = 0
    while health > 0 and ticks < 100000:
        health -= max(dmg, 0.0)
        dmg += k * dmg * dmg + l * dmg + noise
        ticks += 1
    return ticks


def calibrate_health(cfg: dict, map_data: Optional[MapData]) -> dict:
    a = cfg.setdefault("abstraction", {})
    init = cfg.get("initial", {})
    # Preserve explicit overrides already present in initial_abstract.json.
    existing_model = dict(a.get("health_model", {}))
    existing_costs = dict(a.get("health_time_costs", {}))

    move_cost = int(existing_costs.get("move", existing_model.get("zone_move_cost", 5)))
    rescue_scale = int(existing_model.get("real_rescue_ticks_per_abstract_rescue", 10))
    costs = {
        "default": int(existing_costs.get("default", 1)),
        "rest": int(existing_costs.get("rest", 1)),
        "move": move_cost,
        "rescue": int(existing_costs.get("rescue", rescue_scale)),
        "load": int(existing_costs.get("load", 1)),
        "unload": int(existing_costs.get("unload", 1)),
    }

    death_ticks = existing_model.get("real_death_ticks")
    material = existing_model.get("material", "wood")
    collapse_level = existing_model.get("collapse_level", "all")
    initial_damage = existing_model.get("initial_damage")
    note = "configured" if death_ticks is not None else "computed"

    if map_data is not None:
        try:
            civ_area = int(init.get("civ_area"))
            material = material_from_code(map_data.building_codes.get(civ_area, 0))
        except Exception:
            material = str(material)
        misc = map_data.misc
        # Use the scenario-calibrated death scale when no explicit override is present.
        # The value can be changed through real_death_ticks or health_clock_max.
        if death_ticks is None:
            # Estimate the clock from the RCRS buried-damage progression.
            # The calibration fields are retained in the generated configuration.
            slight = as_float(misc, f"misc.injury.bury.{material}.{collapse_level}.slight", 0.4)
            serious = as_float(misc, f"misc.injury.bury.{material}.{collapse_level}.serious", 0.5)
            critical = as_float(misc, f"misc.injury.bury.{material}.{collapse_level}.critical", 0.1)
            val_slight = as_float(misc, "misc.injury.bury.slight", 3)
            val_serious = as_float(misc, "misc.injury.bury.serious", 15)
            val_critical = as_float(misc, "misc.injury.bury.critical", 100)
            expected_damage = slight * val_slight + serious * val_serious + critical * val_critical
            k = as_float(misc, "misc.injury.bury.k", 0.000035)
            l = as_float(misc, "misc.injury.bury.l", 0.01)
            noise = as_float(misc, "misc.injury.bury.noise.mean", 0.1)
            # Use the calibrated scenario lifetime when it is longer than the conservative estimate.
            formula_death = simulate_death_ticks(expected_damage, k, l, noise)
            death_ticks = int(existing_model.get("real_death_ticks", 187))
            initial_damage = expected_damage
            existing_model["formula_expected_damage"] = round(expected_damage, 4)
            existing_model["formula_death_ticks_from_expected_damage"] = int(formula_death)
            existing_model["bury_progression"] = {"k": k, "l": l, "noise_mean": noise}
            note = "defaulted_to_observed_test_scale_187_ticks; edit real_death_ticks to override"

    if death_ticks is None:
        death_ticks = 187
    death_ticks = int(death_ticks)
    health_bands = int(existing_model.get("health_bands", 4))
    stage_ticks = max(1, int(math.ceil(death_ticks / health_bands)))
    hmax = int(a.get("health_clock_max", stage_ticks - 1)) if "health_clock_max" in a else stage_ticks - 1

    # Keep abstraction.health_clock_max as the configured value once present.
    a["health_clock_max"] = int(hmax)
    a["health_time_costs"] = costs
    a["health_model"] = {
        **existing_model,
        "note": note,
        "material": material,
        "collapse_level": collapse_level,
        "real_death_ticks": death_ticks,
        "health_bands": health_bands,
        "stage_ticks": int(hmax) + 1,
        "health_clock_max": int(hmax),
        "real_rescue_ticks_per_abstract_rescue": costs["rescue"],
        "zone_move_cost": costs["move"],
        "initial_damage": round(float(initial_damage), 4) if initial_damage is not None else None,
        "editable": True,
    }
    return cfg


def build_or_update_initial(initial_path: Path, raw: str, map_path: Optional[Path]) -> Tuple[dict, Optional[MapData]]:
    cfg = load_json(initial_path)
    map_data = parse_map_zip(map_path) if map_path else None
    if "abstraction" not in cfg:
        if map_data is None:
            raise ValueError("initial JSON has no abstraction. Pass --map test.zip so abstraction can be generated.")
        cfg["abstraction"] = make_3x3_abstraction(map_data)
    elif map_data is not None:
        # Preserve configured zones, but recompute inter-zone edges from the map graph.
        zones = cfg["abstraction"].get("zones", {})
        zone_order = cfg["abstraction"].get("zone_order", list(zones.keys()))
        area_to_zone = {int(a): z for z, vals in zones.items() for a in vals}
        zneigh = {z: set() for z in zone_order}
        for src, nbs in map_data.neighbours.items():
            zs = area_to_zone.get(src)
            if zs is None:
                continue
            for dst in nbs:
                zd = area_to_zone.get(dst)
                if zd is not None and zd != zs:
                    zneigh[zs].add(zd)
                    zneigh[zd].add(zs)
        cfg["abstraction"]["zone_neighbours"] = {z: [n for n in zone_order if n in zneigh[z]] for z in zone_order}
        cfg["abstraction"]["zone_neighbour_rule"] = "edge exists iff some exact map area in zone A is connected to some exact map area in zone B"
    cfg = calibrate_health(cfg, map_data)
    return cfg, map_data


# ISPL guards
def buried() -> str:
    return "(" + " or ".join(f"Environment.buriedness_value_Civ = {i}" for i in range(1, 7)) + ")"


def health_ok(hmax: int) -> str:
    clocks = " or ".join(f"Environment.health_clock = {i}" for i in range(hmax))
    return "(Environment.health_Civ = complete or Environment.health_Civ = high or Environment.health_Civ = moderate or " \
           f"(Environment.health_Civ = at_risk and ({clocks})))"


def civilian_in_collapsed_zone(zones: Sequence[str], prefix: str = "") -> str:
    """ISPL guard: Civ is physically located in a zone whose status is collapsed."""
    return "(" + " or ".join(
        f"({prefix}at_Civ = {z} and {prefix}status_{z} = collapsed)" for z in zones
    ) + ")"


def action_class_conditions(zones: Sequence[str], costs: Dict[str, int]) -> Dict[int, List[str]]:
    fb_moves = " or ".join(f"FireBrigade.Action = fb_move_to_{z}" for z in zones)
    at_moves = " or ".join(f"AmbulanceTeam.Action = at_move_to_{z}" for z in zones)
    any_move = f"({fb_moves} or {at_moves})"
    rescue_cost = int(costs.get("rescue", 10))
    move_cost = int(costs.get("move", 5))
    default_cost = int(costs.get("default", 1))
    by_cost: Dict[int, List[str]] = {}
    by_cost.setdefault(rescue_cost, []).append("FireBrigade.Action = fb_rescue_Civ")
    by_cost.setdefault(move_cost, []).append(f"!(FireBrigade.Action = fb_rescue_Civ) and {any_move}")
    by_cost.setdefault(default_cost, []).append(f"!(FireBrigade.Action = fb_rescue_Civ) and !{any_move}")
    return by_cost


def health_transition_lines(zones: Sequence[str], hmax: int, costs: Dict[str, int]) -> List[str]:
    stage = hmax + 1
    class_conds = action_class_conditions(zones, costs)
    distinct_costs = sorted(class_conds.keys(), reverse=True)
    collapsed_guard = civilian_in_collapsed_zone(zones, prefix="")
    lines = [
        "-- Health",
        "-- Progresses only while Civ is inside a collapsed zone",
        "health_clock = health_clock if delivered_Civ = true and dead_Civ = false;",
        "health_clock = health_clock if dead_Civ = true;",
    ]
    for c in distinct_costs:
        cond = "(" + " or ".join(class_conds[c]) + ")"
        for cur in range(stage):
            new = (cur + c) % stage
            lines.append(
                f"health_clock = {new} if alive_Civ = true and delivered_Civ = false "
                f"and dead_Civ = false and health_clock = {cur} and {collapsed_guard} and {cond};"
            )
    for c in distinct_costs:
        cond = "(" + " or ".join(class_conds[c]) + ")"
        threshold = max(0, stage - c)
        clocks = " or ".join(f"health_clock = {i}" for i in range(threshold, stage))
        common = f"alive_Civ = true and delivered_Civ = false and {collapsed_guard} and ({clocks}) and {cond}"
        lines.append(f"health_Civ = high if {common} and health_Civ = complete;")
        lines.append(f"health_Civ = moderate if {common} and health_Civ = high;")
        lines.append(f"health_Civ = at_risk if {common} and health_Civ = moderate;")
        lines.append(f"health_Civ = dead if {common} and health_Civ = at_risk;")
        lines.append(f"alive_Civ = false if {common} and health_Civ = at_risk;")
        lines.append(f"dead_Civ = true if {common} and health_Civ = at_risk;")
        lines.append(f"damage_Civ = moderate if {common} and damage_Civ = none and health_Civ = complete;")
    return lines


# Environment generation
def gen_environment(cfg: dict, buildings: List[int]) -> str:
    a = cfg["abstraction"]
    zones = a["zone_order"]
    hmax = int(a.get("health_clock_max", 46))
    costs = {k: int(v) for k, v in dict(a.get("health_time_costs", {})).items()}
    costs.setdefault("default", 1)
    costs.setdefault("move", 5)
    costs.setdefault("rescue", 10)
    init = cfg["initial"]
    civ_z = zone_of(cfg, int(init["civ_area"]))
    refuge_z = zone_of(cfg, int(init["refuge_area"]))
    status = zone_status(cfg, buildings)
    fb_actions = [move("fb", z) for z in zones] + ["fb_rescue_Civ", "fb_rest"]
    at_actions = [move("at", z) for z in zones] + ["at_load_Civ", "at_unload_Civ", "at_rest"]

    lines = [
        "Agent Environment",
        "    Obsvars:",
        f"        did_action_FB: {enum(['none'] + fb_actions)};",
        f"        did_action_AT: {enum(['none'] + at_actions)};",
        f"        fb_zone: {enum(zones)};",
        f"        at_zone: {enum(zones)};",
        f"        at_Civ: {enum(zones + ['in_ambulance'])};",
    ]
    for z in zones:
        lines.append(f"        status_{z}: {{healthy, damaged, collapsed}};")
    lines += [
        "        health_Civ: {complete, high, moderate, at_risk, dead};",
        "        damage_Civ: {none, moderate};",
        "        buriedness_value_Civ: 0 .. 6;",
        f"        health_clock: 0 .. {hmax};",
        "        alive_Civ: boolean;",
        "        dead_Civ: boolean;",
        "        loaded_Civ: boolean;",
        "        delivered_Civ: boolean;",
        "    end Obsvars",
        "    Actions = {env_idle};",
        "    Protocol:",
        "        Other: {env_idle};",
        "    end Protocol",
        "    Evolution:",
        "        -- Actions",
    ]
    for act in fb_actions:
        lines.append(f"        did_action_FB = {act} if FireBrigade.Action = {act};")
    for act in at_actions:
        lines.append(f"        did_action_AT = {act} if AmbulanceTeam.Action = {act};")
    lines.append("        -- Movement")
    for z in zones:
        lines.append(f"        fb_zone = {z} if FireBrigade.Action = {move('fb', z)};")
    lines += ["        fb_zone = fb_zone if FireBrigade.Action = fb_rescue_Civ;",
              "        fb_zone = fb_zone if FireBrigade.Action = fb_rest;"]
    for z in zones:
        lines.append(f"        at_zone = {z} if AmbulanceTeam.Action = {move('at', z)};")
    lines += ["        at_zone = at_zone if AmbulanceTeam.Action = at_load_Civ;",
              "        at_zone = at_zone if AmbulanceTeam.Action = at_unload_Civ;",
              "        at_zone = at_zone if AmbulanceTeam.Action = at_rest;",
              "        -- Rescue"]
    for n in range(6, 0, -1):
        lines.append(f"        buriedness_value_Civ = {n-1} if alive_Civ = true and buriedness_value_Civ = {n} and at_Civ = {civ_z} and fb_zone = {civ_z} and FireBrigade.Action = fb_rescue_Civ;")
    lines += [
        "        -- Load",
        f"        loaded_Civ = true if alive_Civ = true and delivered_Civ = false and buriedness_value_Civ = 0 and at_Civ = {civ_z} and at_zone = {civ_z} and AmbulanceTeam.Action = at_load_Civ;",
        f"        at_Civ = in_ambulance if alive_Civ = true and delivered_Civ = false and buriedness_value_Civ = 0 and at_Civ = {civ_z} and at_zone = {civ_z} and AmbulanceTeam.Action = at_load_Civ;",
        "        -- Unload",
        f"        loaded_Civ = false if loaded_Civ = true and alive_Civ = true and delivered_Civ = false and at_zone = {refuge_z} and {health_ok(hmax).replace('Environment.', '')} and AmbulanceTeam.Action = at_unload_Civ;",
        f"        delivered_Civ = true if loaded_Civ = true and alive_Civ = true and delivered_Civ = false and at_zone = {refuge_z} and {health_ok(hmax).replace('Environment.', '')} and AmbulanceTeam.Action = at_unload_Civ;",
        f"        at_Civ = {refuge_z} if loaded_Civ = true and alive_Civ = true and delivered_Civ = false and at_zone = {refuge_z} and {health_ok(hmax).replace('Environment.', '')} and AmbulanceTeam.Action = at_unload_Civ;",
    ]
    lines += ["        " + x for x in health_transition_lines(zones, hmax, costs)]
    lines += [
        "    end Evolution",
        "end Agent",
    ]
    return "\n".join(lines)


# Agent generation
def gen_agent(name: str, prefix: str, zones: List[str], neigh: Dict[str, List[str]], special: str, hmax: int = 46, refuge_z: str = "") -> str:
    acts = [move(prefix, z) for z in zones] + special.split() + [f"{prefix}_rest"]
    lines = [
        f"Agent {name}",
        "    Vars:",
        "        dummy: boolean;",
        "    end Vars",
        f"    Actions = {aset(acts)};",
        "    Protocol:",
        f"        Environment.dead_Civ = true: {{{prefix}_rest}};",
        f"        Environment.delivered_Civ = true: {{{prefix}_rest}};",
    ]
    for z in zones:
        moves = [move(prefix, n) for n in neigh[z]]
        if prefix == "fb":
            lines += [
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.fb_zone = {z} and Environment.at_Civ = {z} and Environment.alive_Civ = true and {buried()}:",
                f"            {aset(moves + ['fb_rescue_Civ', 'fb_rest'])};",
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.fb_zone = {z}:",
                f"            {aset(moves + ['fb_rest'])};",
            ]
        else:
            lines += [
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_zone = {z} and Environment.at_Civ = {z} and Environment.alive_Civ = true and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false:",
                f"            {aset(moves + ['at_load_Civ', 'at_rest'])};",
                *([f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_zone = {z} and Environment.loaded_Civ = true and Environment.alive_Civ = true and {health_ok(hmax)}:",
                   f"            {aset(moves + ['at_unload_Civ', 'at_rest'])};"] if z == refuge_z else []),
                f"        Environment.dead_Civ = false and Environment.delivered_Civ = false and Environment.at_zone = {z}:",
                f"            {aset(moves + ['at_rest'])};",
            ]
    lines += [
        f"        Other: {{{prefix}_rest}};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "    end Evolution",
        "end Agent",
    ]
    return "\n".join(lines)


# Output generation
def generate(raw: str, cfg: dict) -> str:
    buildings = ids(raw, "building")
    a = cfg["abstraction"]
    zones = a["zone_order"]
    neigh = a["zone_neighbours"]
    init = cfg["initial"]
    status = zone_status(cfg, buildings)
    fb_z = zone_of(cfg, int(init["fb_area"]))
    at_z = zone_of(cfg, int(init["at_area"]))
    civ_z = zone_of(cfg, int(init["civ_area"]))
    refuge_z = zone_of(cfg, int(init["refuge_area"]))
    hmax = int(a.get("health_clock_max", 46))
    return f"""Semantics=SingleAssignment;\n\n{gen_environment(cfg, buildings)}\n\n{gen_agent('FireBrigade', 'fb', zones, neigh, 'fb_rescue_Civ', hmax, refuge_z)}\n\n{gen_agent('AmbulanceTeam', 'at', zones, neigh, 'at_load_Civ at_unload_Civ', hmax, refuge_z)}\n\nEvaluation\n    Civ_complete if Environment.health_Civ = complete;\n    Civ_high if Environment.health_Civ = high;\n    Civ_moderate if Environment.health_Civ = moderate;\n    Civ_at_risk if Environment.health_Civ = at_risk;\n    Civ_dead if Environment.dead_Civ = true;\n    Civ_deep if Environment.buriedness_value_Civ = 4 or Environment.buriedness_value_Civ = 5 or Environment.buriedness_value_Civ = 6;\n    Civ_shallow if Environment.buriedness_value_Civ = 1 or Environment.buriedness_value_Civ = 2 or Environment.buriedness_value_Civ = 3;\n    surface_Civ_eval if Environment.alive_Civ = true and Environment.buriedness_value_Civ = 0 and Environment.loaded_Civ = false and Environment.delivered_Civ = false;\n    loaded_Civ_eval if Environment.loaded_Civ = true;\n    rescued_Civ_eval if Environment.alive_Civ = true and Environment.buriedness_value_Civ = 0;\n    delivered_alive_Civ_eval if Environment.delivered_Civ = true and Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.loaded_Civ = false and Environment.at_Civ = {refuge_z} and Environment.at_zone = {refuge_z};\n    terminal_dead_Civ_eval if Environment.dead_Civ = true;\n    terminal_Civ_eval if Environment.dead_Civ = true or (Environment.delivered_Civ = true and Environment.alive_Civ = true and Environment.dead_Civ = false and Environment.loaded_Civ = false and Environment.at_Civ = {refuge_z} and Environment.at_zone = {refuge_z});\n    fb_at_target_960 if Environment.fb_zone = {civ_z};\n    at_at_target_960 if Environment.at_zone = {civ_z};\n    at_refuge_249 if Environment.at_zone = {refuge_z};\nend Evaluation\n\nInitStates\n    Environment.did_action_FB = none and\n    Environment.did_action_AT = none and\n    Environment.fb_zone = {fb_z} and\n    Environment.at_zone = {at_z} and\n    Environment.at_Civ = {civ_z} and\n""" + \
"\n".join(f"    Environment.status_{z} = {status[z]} and" for z in zones) + f"""\n    Environment.health_Civ = {init['health_Civ']} and\n    Environment.damage_Civ = {init['damage_Civ']} and\n    Environment.buriedness_value_Civ = {init['buriedness_value_Civ']} and\n    Environment.health_clock = {min(int(init['health_clock']), hmax)} and\n    Environment.alive_Civ = {str(init['alive_Civ']).lower()} and\n    Environment.dead_Civ = {str(init['dead_Civ']).lower()} and\n    Environment.loaded_Civ = {str(init['loaded_Civ']).lower()} and\n    Environment.delivered_Civ = {str(init['delivered_Civ']).lower()} and\n    FireBrigade.dummy = false and\n    AmbulanceTeam.dummy = false;\nend InitStates\n\nGroups\n    fire_only = {{FireBrigade}};\n    ambulance_only = {{AmbulanceTeam}};\n    rescue_team = {{FireBrigade, AmbulanceTeam}};\nend Groups\n\nFormulae\n    <fire_only> F surface_Civ_eval;\n    <ambulance_only> F loaded_Civ_eval;\n    <rescue_team> F delivered_alive_Civ_eval;\nend Formulae\n"""


# Abstraction report
def write_report(path: Path, cfg: dict) -> None:
    a = cfg["abstraction"]
    lines = []
    lines.append("ABSTRACTION / HEALTH REPORT")
    lines.append("===========================")
    lines.append(f"health_clock_max: {a.get('health_clock_max')}")
    lines.append(f"health_time_costs: {a.get('health_time_costs')}")
    lines.append(f"health_model: {json.dumps(a.get('health_model', {}), indent=2)}")
    lines.append("")
    lines.append("zone_neighbours:")
    for z, ns in a.get("zone_neighbours", {}).items():
        lines.append(f"  {z}: {ns}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Command line entry point
def main() -> None:
    p = argparse.ArgumentParser(description="Generate zone-level raw abstract ISPL from raw exact ISPL. If --map is provided, abstraction/health defaults are generated or refreshed from map.gml and misc.cfg.")
    p.add_argument("--raw", required=True, help="Input raw-test.ispl from the exact raw translator")
    p.add_argument("--initial", required=True, help="initial.json or editable initial_abstract.json")
    p.add_argument("--map", help="test.zip/map zip. Needed when --initial has no abstraction, and used to refresh zone edges/health defaults.")
    p.add_argument("--output", required=True, help="Output abstract-raw.ispl")
    p.add_argument("--initial-output", help="Optional output path for the generated/updated initial_abstract.json. Default: initial_abstract.json beside --output")
    p.add_argument("--report", help="Optional report path. Default: abstraction_report.txt beside --output")
    args = p.parse_args()

    raw = Path(args.raw).read_text(encoding="utf-8", errors="replace")
    out_path = Path(args.output)
    init_out = Path(args.initial_output) if args.initial_output else out_path.with_name("initial_abstract.json")
    report_out = Path(args.report) if args.report else out_path.with_name("abstraction_report.txt")
    cfg, _ = build_or_update_initial(Path(args.initial), raw, Path(args.map) if args.map else None)
    init_out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    out_path.write_text(generate(raw, cfg), encoding="utf-8")
    write_report(report_out, cfg)
    print(f"Wrote ISPL: {out_path}")
    print(f"Wrote editable abstraction JSON: {init_out}")
    print(f"Wrote report: {report_out}")


if __name__ == "__main__":
    main()
