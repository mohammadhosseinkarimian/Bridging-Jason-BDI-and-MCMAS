#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def clean_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    if re.match(r"^\d", name):
        name = "_" + name
    return name


def uniq(vals: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(vals))


def action_set(vals: Sequence[str], indent_spaces: int = 16, per_line: int = 4) -> str:
    vals = uniq([v for v in vals if v])
    chunks = [", ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    if len(chunks) == 1:
        return "{" + chunks[0] + "}"
    pad = " " * indent_spaces
    return "{\n" + ",\n".join(pad + c for c in chunks) + "\n" + " " * (indent_spaces - 4) + "}"


def buried_positive(prefix: str = "Environment.") -> str:
    return "(" + " or ".join(f"{prefix}buriedness_value_Civ = {i}" for i in range(1, 7)) + ")"


def buried_mid_high() -> str:
    return "(" + " or ".join(f"Environment.buriedness_value_Civ = {i}" for i in range(2, 7)) + ")"


def surface_cond(prefix: str = "Environment.") -> str:
    return (
        f"{prefix}alive_Civ = true and {prefix}loaded_Civ = false and "
        f"{prefix}buriedness_value_Civ = 0"
    )


# Jason parsing

@dataclass
class Term:
    op: str
    name: str
    args: List[str]
    raw: str


@dataclass
class Plan:
    goal: str
    context: str
    body: str
    terms: List[Term]
    index: int


@dataclass(frozen=True)
class GoalCall:
    # Directed goal-to-subgoal call recorded from a Jason plan body.

    source: str
    target: str
    plan_index: int


@dataclass
class GoalControl:
    # Reachable goals, ordered control values, and calls.

    top: str
    values: List[str]
    calls: List[GoalCall]
    visited: List[str]


@dataclass
class AgentSpec:
    # Translation data for one agent role.

    top: str
    goals: List[str]
    control: GoalControl
    patrol_goal: str
    major: Dict[str, str]
    patrol_order: List[str]
    plans: List[Plan]


def split_top(s: str, sep: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    quote = False
    for ch in s:
        if ch == '"':
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if not quote and depth == 0 and ch == sep:
            part = "".join(cur).strip()
            if part:
                out.append(part)
            cur = []
        else:
            cur.append(ch)
    part = "".join(cur).strip()
    if part:
        out.append(part)
    return out


def parse_term(raw: str) -> Optional[Term]:
    raw = raw.strip()
    if not raw:
        return None
    op = raw[0] if raw[0] in "+-!?" else ""
    body = raw[1:].strip() if op else raw
    if body.startswith("not "):
        body = body[4:].strip()
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?$", body)
    if not m:
        return None
    args: List[str] = []
    if m.group(2) is not None:
        args = [a.strip() for a in split_top(m.group(2), ",")]
    return Term(op=op, name=clean_name(m.group(1)), args=args, raw=raw)


def parse_body_terms(body: str) -> List[Term]:
    terms: List[Term] = []
    for piece in split_top(body, ";"):
        term = parse_term(piece)
        if term:
            terms.append(term)
    return terms


def strip_comments(asl_text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in asl_text.splitlines())


def read_plans(asl_text: str) -> Tuple[List[Plan], str]:
    # Read achievement-goal plans while preserving source and body order.

    text = strip_comments(asl_text)
    blobs: List[str] = []
    cur: List[str] = []
    active = False
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        if re.match(r"\+!", item):
            active = True
            cur = [item]
        elif active:
            cur.append(item)
        if active and item.endswith("."):
            blobs.append(" ".join(cur).rstrip("."))
            active = False

    plans: List[Plan] = []
    top = "saved_civilians"
    for index, blob in enumerate(blobs):
        match = re.match(
            r"\+!(?P<goal>[A-Za-z_][A-Za-z0-9_]*)(?:\([^)]*\))?\s*:\s*(?P<context>.*?)\s*<-\s*(?P<body>.*)$",
            blob,
        )
        if not match:
            continue
        goal = clean_name(match.group("goal"))
        context = match.group("context").strip()
        body = match.group("body").strip()
        terms = parse_body_terms(body)
        plans.append(Plan(goal=goal, context=context, body=body, terms=terms, index=index))
        if goal == "step":
            for term in terms:
                if term.op == "!":
                    top = clean_name(term.name)
                    break
    return plans, top


def name_in_list(name: str, vals: Sequence[str]) -> bool:
    return clean_name(name) in {clean_name(v) for v in vals}


def action_category(term: Term, bridge: dict) -> Optional[str]:
    for category, names in bridge.get("actions", {}).items():
        if name_in_list(term.name, names):
            return category
    return None


def context_has(context: str, category: str, bridge: dict) -> bool:
    for predicate in bridge.get("predicates", {}).get(category, []):
        if re.search(rf"\b{re.escape(predicate)}\s*\(", context):
            return True
        if re.search(rf"\b{re.escape(predicate)}\b", context):
            return True
    return False


def goal_with_action(plans: Sequence[Plan], bridge: dict, category: str, top: str) -> Optional[str]:
    hits: List[str] = []
    for plan in plans:
        if any(action_category(term, bridge) == category for term in plan.terms):
            hits.append(plan.goal)
    for goal in hits:
        if goal != top:
            return goal
    return hits[0] if hits else None


def identify_major_goals(
    plans: Sequence[Plan],
    top: str,
    bridge: dict,
    agent: str,
) -> Tuple[Dict[str, str], List[str]]:
    """Identify the task stages retained 
    as MCMAS goal-control values."""

    major: Dict[str, str] = {}
    if agent == "fire":
        major["rescue"] = goal_with_action(plans, bridge, "rescue", top) or top
        major["notify_ready"] = goal_with_action(plans, bridge, "notify_ready", top) or top
        ordered = [major["rescue"], major["notify_ready"]]
    elif agent == "ambulance":
        major["report"] = goal_with_action(plans, bridge, "notify_fire", top) or top
        major["load"] = goal_with_action(plans, bridge, "load", top) or top
        major["deliver"] = goal_with_action(plans, bridge, "unload", top) or top
        ordered = [major["report"], major["load"], major["deliver"]]
    else:
        raise ValueError(f"Unsupported agent role: {agent}")
    return major, uniq([goal for goal in ordered if goal and goal != top])


def build_goal_control(
    plans: Sequence[Plan],
    top_goal: str,
    bridge: dict,
    agent: str,
) -> GoalControl:
    # Build the finite goal-control representation.

    plans_by_goal: Dict[str, List[Plan]] = {}
    for plan in plans:
        plans_by_goal.setdefault(plan.goal, []).append(plan)

    calls: List[GoalCall] = []
    visited: List[str] = []
    seen: Set[str] = set()

    def visit(goal: str) -> None:
        if goal in seen:
            return
        seen.add(goal)
        visited.append(goal)
        for plan in plans_by_goal.get(goal, []):
            for term in plan.terms:
                if term.op != "!":
                    continue
                child = clean_name(term.name)
                calls.append(GoalCall(goal, child, plan.index))
                visit(child)

    visit(top_goal)
    _, task_order = identify_major_goals(plans, top_goal, bridge, agent)
    values = uniq([top_goal] + [goal for goal in task_order if goal in seen] + ["done"])
    return GoalControl(top=top_goal, values=values, calls=calls, visited=visited)


def patrol_goal(plans: Sequence[Plan], bridge: dict, top: str) -> str:
    scores: Dict[str, int] = {}
    for plan in plans:
        if plan.goal in ("step", top):
            continue
        score = 0
        for category in ["collapsed", "damaged", "building", "road", "visited", "known_road"]:
            if context_has(plan.context, category, bridge):
                score += 1
        if score:
            scores[plan.goal] = scores.get(plan.goal, 0) + score
    if scores:
        return max(scores, key=scores.get)
    return "patrol"


def patrol_order(plans: Sequence[Plan], bridge: dict, patrol: str) -> List[str]:
    order: List[str] = []
    for plan in plans:
        if plan.goal != patrol:
            continue
        context = plan.context
        if context_has(context, "found", bridge) and context_has(context, "buried", bridge):
            order.append("found_buried")
        elif context_has(context, "buried", bridge):
            order.append("buried")
        elif context_has(context, "loaded", bridge):
            order.append("loaded")
        elif context_has(context, "known_road", bridge):
            order.append("known_road")
        elif context_has(context, "collapsed", bridge):
            order.append("collapsed")
        elif context_has(context, "damaged", bridge):
            order.append("damaged")
        elif context_has(context, "building", bridge):
            order.append("building")
        elif context_has(context, "road", bridge) and "not visited" in context:
            order.append("road_unvisited")
        elif context_has(context, "road", bridge):
            order.append("road")
        elif context.strip() == "true":
            order.append("rest")
    return uniq(order or ["collapsed", "damaged", "building", "road_unvisited", "road", "rest"])


def build_agent_spec(
    plans: Sequence[Plan],
    control: GoalControl,
    bridge: dict,
    agent: str,
) -> AgentSpec:
    # Build the role-specific translation specification.

    major, _ = identify_major_goals(plans, control.top, bridge, agent)
    patrol = patrol_goal(plans, bridge, control.top)
    return AgentSpec(
        top=control.top,
        goals=list(control.values),
        control=control,
        patrol_goal=patrol,
        major=major,
        patrol_order=patrol_order(plans, bridge, patrol),
        plans=list(plans),
    )


# Raw

def block(raw: str, agent: str) -> Tuple[int, int, str]:
    start = raw.find(f"Agent {agent}\n")
    if start < 0:
        raise ValueError(f"Agent {agent} not found")
    end = raw.find("end Agent", start)
    if end < 0:
        raise ValueError(f"end Agent not found for {agent}")
    end += len("end Agent")
    return start, end, raw[start:end]


def replace_agent(raw: str, agent: str, new: str) -> str:
    start, end, _ = block(raw, agent)
    return raw[:start] + new.rstrip() + "\n" + raw[end:]


def zones_from_raw(raw: str) -> List[str]:
    m = re.search(r"fb_zone:\s*\{(?P<body>.*?)\};", raw, re.S)
    if not m:
        raise ValueError("fb_zone enum not found")
    return re.findall(r"z_[A-Za-z0-9_]+", m.group("body"))


def init_value(raw: str, var: str) -> str:
    m0 = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    body = m0.group("body") if m0 else raw
    m = re.search(rf"Environment\.{re.escape(var)}\s*=\s*(z_[A-Za-z0-9_]+|true|false|[A-Za-z0-9_]+)", body)
    if not m:
        raise ValueError(f"Initial value for Environment.{var} not found")
    return m.group(1)


def statuses_from_raw(raw: str, zones: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    init = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    body = init.group("body") if init else raw
    for z in zones:
        m = re.search(rf"Environment\.status_{re.escape(z)}\s*=\s*(healthy|damaged|collapsed)", body)
        out[z] = m.group(1) if m else "healthy"
    return out


def neighbours_from_agent(agent_raw: str, move_prefix: str, zone_var: str) -> Dict[str, List[str]]:
    graph: Dict[str, List[str]] = {}
    lines = agent_raw.splitlines()
    for i, line in enumerate(lines):
        m = re.search(rf"Environment\.dead_Civ = false and Environment\.delivered_Civ = false and Environment\.{zone_var} = (z_[A-Za-z0-9_]+):", line)
        if not m:
            continue
        src = m.group(1)
        body = ""
        for j in range(i + 1, min(i + 10, len(lines))):
            body += lines[j] + "\n"
            if ";" in lines[j]:
                break
        moves = [x.replace(f"{move_prefix}_move_to_", "") for x in re.findall(rf"{move_prefix}_move_to_z_[A-Za-z0-9_]+", body)]
        graph[src] = uniq(moves)
    return graph


def shortest_steps(graph: Dict[str, List[str]], target: str) -> Dict[str, List[str]]:
    rev: Dict[str, List[str]] = {k: [] for k in graph}
    for src, nbs in graph.items():
        for nb in nbs:
            rev.setdefault(nb, []).append(src)
            rev.setdefault(src, [])
    q = deque([target])
    dist: Dict[str, int] = {target: 0}
    while q:
        z = q.popleft()
        for n in rev.get(z, []):
            if n not in dist:
                dist[n] = dist[z] + 1
                q.append(n)
    out: Dict[str, List[str]] = {}
    for z, nbs in graph.items():
        if z == target:
            out[z] = []
            continue
        best = min((dist.get(n, 10**9) for n in nbs), default=10**9)
        choices = [n for n in nbs if dist.get(n, 10**9) == best]
        out[z] = choices[:1]
    return out


def detect_civ_area_var(raw: str) -> str:
    #Return the civilian-location variable used by the baseline model. 

    if re.search(r"\bciv_area\s*:\s*\{", raw):
        return "civ_area"
    if re.search(r"\bat_Civ\s*:\s*\{", raw):
        return "at_Civ"
    raise ValueError("Civilian-area variable not found (expected civ_area or at_Civ)")


@dataclass
class ModelInfo:
    zones: List[str]
    statuses: Dict[str, str]
    fb_graph: Dict[str, List[str]]
    at_graph: Dict[str, List[str]]
    fb_start: str
    at_start: str
    civ_zone: str
    civ_var: str
    refuge_zone: str


def load_model(raw: str) -> ModelInfo:
    zones = zones_from_raw(raw)
    _, _, raw_fb = block(raw, "FireBrigade")
    _, _, raw_at = block(raw, "AmbulanceTeam")
    civ_var = detect_civ_area_var(raw)
    refuge_match = re.search(
        rf"delivered_alive_Civ_eval.*?Environment\.{re.escape(civ_var)} = "
        r"(z_[A-Za-z0-9_]+) and Environment\.at_zone = (z_[A-Za-z0-9_]+)",
        raw,
        re.S,
    )
    return ModelInfo(
        zones=zones,
        statuses=statuses_from_raw(raw, zones),
        fb_graph=neighbours_from_agent(raw_fb, "fb", "fb_zone"),
        at_graph=neighbours_from_agent(raw_at, "at", "at_zone"),
        fb_start=init_value(raw, "fb_zone"),
        at_start=init_value(raw, "at_zone"),
        civ_zone=init_value(raw, civ_var),
        civ_var=civ_var,
        refuge_zone=init_value(raw, "refuge_zone")
        if re.search(r"Environment\.refuge_zone\s*=", raw)
        else refuge_match.group(2),
    )


# Patching
def enum_add(raw: str, var: str, item: str, before: str) -> str:
    pat = rf"({re.escape(var)}:\s*\{{)(.*?)(\}}\s*;)"
    m = re.search(pat, raw, re.S)
    if not m:
        return raw
    body = m.group(2)
    vals = [v.strip() for v in re.split(r",", body.replace("\n", " ")) if v.strip()]
    if item not in vals:
        if before in vals:
            vals.insert(vals.index(before), item)
        else:
            vals.append(item)
    new = m.group(1) + ", ".join(vals) + m.group(3)
    return raw[:m.start()] + new + raw[m.end():]


def add_environment(raw: str, info: ModelInfo) -> str:
    raw = enum_add(raw, "did_action_FB", "fb_notify_ambulance_ready_Civ", "fb_rest")
    raw = enum_add(raw, "did_action_AT", "at_report_buried_Civ", "at_rest")

    obs_add = (
        "        fb_knows_buried_Civ: boolean;\n"
        "        at_knows_buried_Civ: boolean;\n"
        "        buried_Civ_reported_to_FB: boolean;\n"
        "        Civ_ready_reported_to_AT: boolean;\n"
        "        at_knows_refuge: boolean;\n"
    )
    raw = raw.replace("        delivered_Civ: boolean;\n", "        delivered_Civ: boolean;\n" + obs_add, 1)

    raw = raw.replace(
        "        did_action_FB = fb_rest if FireBrigade.Action = fb_rest;\n",
        "        did_action_FB = fb_notify_ambulance_ready_Civ if FireBrigade.Action = fb_notify_ambulance_ready_Civ;\n"
        "        did_action_FB = fb_rest if FireBrigade.Action = fb_rest;\n",
        1,
    )
    raw = raw.replace(
        "        did_action_AT = at_rest if AmbulanceTeam.Action = at_rest;\n",
        "        did_action_AT = at_report_buried_Civ if AmbulanceTeam.Action = at_report_buried_Civ;\n"
        "        did_action_AT = at_rest if AmbulanceTeam.Action = at_rest;\n",
        1,
    )

    raw = raw.replace(
        "        fb_zone = fb_zone if FireBrigade.Action = fb_rest;\n",
        "        fb_zone = fb_zone if FireBrigade.Action = fb_notify_ambulance_ready_Civ;\n"
        "        fb_zone = fb_zone if FireBrigade.Action = fb_rest;\n",
        1,
    )
    raw = raw.replace(
        "        at_zone = at_zone if AmbulanceTeam.Action = at_rest;\n",
        "        at_zone = at_zone if AmbulanceTeam.Action = at_report_buried_Civ;\n"
        "        at_zone = at_zone if AmbulanceTeam.Action = at_rest;\n",
        1,
    )

    b = buried_positive("")
    belief = f"""        -- Beliefs
        fb_knows_buried_Civ = true if fb_knows_buried_Civ = true or (alive_Civ = true and {b} and (fb_zone = {info.civ_zone} or FireBrigade.Action = fb_move_to_{info.civ_zone})) or buried_Civ_reported_to_FB = true;
        at_knows_buried_Civ = true if at_knows_buried_Civ = true or (alive_Civ = true and {b} and (at_zone = {info.civ_zone} or AmbulanceTeam.Action = at_move_to_{info.civ_zone}));
        buried_Civ_reported_to_FB = true if buried_Civ_reported_to_FB = true or (at_knows_buried_Civ = true and AmbulanceTeam.Action = at_report_buried_Civ);
        Civ_ready_reported_to_AT = true if Civ_ready_reported_to_AT = true or (alive_Civ = true and buriedness_value_Civ = 0 and fb_zone = {info.civ_zone} and FireBrigade.Action = fb_notify_ambulance_ready_Civ);
        at_knows_refuge = true if at_knows_refuge = true or at_zone = {info.refuge_zone} or AmbulanceTeam.Action = at_move_to_{info.refuge_zone};
"""
    raw = raw.replace("        -- Health\n", belief + "        -- Health\n", 1)
    return raw


def add_init(raw: str, fb: AgentSpec, at: AgentSpec, info: ModelInfo) -> str:
    additions = [
        "    Environment.fb_knows_buried_Civ = false and",
        "    Environment.at_knows_buried_Civ = false and",
        "    Environment.buried_Civ_reported_to_FB = false and",
        "    Environment.Civ_ready_reported_to_AT = false and",
        f"    Environment.at_knows_refuge = {'true' if info.at_start == info.refuge_zone else 'false'} and",
        f"    FireBrigade.fb_goal_level = {fb.top} and",
    ]
    for z in info.zones:
        additions.append(f"    FireBrigade.fb_visited_{z} = {'true' if z == info.fb_start else 'false'} and")
    additions.append(f"    AmbulanceTeam.at_goal_level = {at.top} and")
    for i, z in enumerate(info.zones):
        suffix = " and"
        additions.append(f"    AmbulanceTeam.at_visited_{z} = {'true' if z == info.at_start else 'false'}{suffix}")
    raw = raw.replace("    FireBrigade.dummy = false and\n", "\n".join(additions) + "\n    FireBrigade.dummy = false and\n", 1)
    return raw


def patch_formulae(raw: str) -> str:
    raw = raw.replace("end Evaluation", "    at_knows_refuge_eval if Environment.at_knows_refuge = true;\nend Evaluation", 1)
    raw = re.sub(
        r"<ambulance_only>\s*F\s*loaded_Civ_eval;",
        "<ambulance_only> F (loaded_Civ_eval and !(Civ_deep or Civ_shallow));",
        raw,
    )
    raw = raw.replace("Formulae\n", "Formulae\n    -- Properties\n", 1)
    return raw


# Protocols 

def status_rank(status: str, order: Sequence[str]) -> int:
    # The ASL patrol order gives the priority categories. For abstract zones, a
    # collapsed zone matches collapsed, a damaged zone matches damaged, and a
    # healthy zone falls through to building/road classes.
    status = status.lower()
    candidates = []
    if status == "collapsed":
        candidates = ["collapsed"]
    elif status == "damaged":
        candidates = ["damaged"]
    else:
        candidates = ["building", "road_unvisited", "road"]
    for i, item in enumerate(order):
        if item in candidates:
            return i
    return 999


def ordered_neighbours(cur: str, graph: Dict[str, List[str]], info: ModelInfo, order: Sequence[str]) -> List[str]:
    nbs = list(graph.get(cur, []))
    return sorted(nbs, key=lambda z: (status_rank(info.statuses.get(z, "healthy"), order), nbs.index(z)))


def local_patrol_rules(
    agent_prefix: str,
    goal_var: str,
    top_goal: str,
    zone_var: str,
    knows_guard: str,
    graph: Dict[str, List[str]],
    info: ModelInfo,
    order: Sequence[str],
    rest: str,
) -> List[str]:
    lines = ["        -- Patrol"]
    for cur in info.zones:
        raw_nbs = graph.get(cur, [])
        prio_nbs = ordered_neighbours(cur, graph, info, order)
        for nb in raw_nbs:
            nb_rank = status_rank(info.statuses.get(nb, "healthy"), order)
            # ASL priority orders predicate classes, not individual neighbours
            # within the same class. Equal-priority neighbours stay concurrent.
            higher = [
                x for x in raw_nbs
                if status_rank(info.statuses.get(x, "healthy"), order) < nb_rank
            ]
            parts = [
                f"{goal_var} = {top_goal}",
                knows_guard,
                "Environment.alive_Civ = true",
                f"Environment.{zone_var} = {cur}",
            ]
            parts += [f"{agent_prefix}_visited_{x} = true" for x in higher]
            parts.append(f"{agent_prefix}_visited_{nb} = false")
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {{{agent_prefix}_move_to_{nb}}};",
            ]
        if raw_nbs:
            parts = [
                f"{goal_var} = {top_goal}",
                knows_guard,
                "Environment.alive_Civ = true",
                f"Environment.{zone_var} = {cur}",
            ] + [f"{agent_prefix}_visited_{x} = true" for x in raw_nbs]
            actions = [f"{agent_prefix}_move_to_{x}" for x in raw_nbs]
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {action_set(actions, indent_spaces=16, per_line=4)};",
            ]
    return lines


def fire_agent(spec: AgentSpec, info: ModelInfo) -> str:
    rescue_g = spec.major["rescue"]
    notify_g = spec.major["notify_ready"]
    to_civ = shortest_steps(info.fb_graph, info.civ_zone)
    actions = [f"fb_move_to_{z}" for z in info.zones] + ["fb_rescue_Civ", "fb_notify_ambulance_ready_Civ", "fb_rest"]
    lines = [
        "Agent FireBrigade",
        "    Vars:",
        "        dummy: boolean;",
        f"        fb_goal_level: {{{', '.join(spec.goals)}}};",
    ]
    lines += [f"        fb_visited_{z}: boolean;" for z in info.zones]
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=6)};",
        "    Protocol:",
        "        Environment.dead_Civ = true: {fb_rest};",
        "        Environment.delivered_Civ = true: {fb_rest};",
        "        fb_goal_level = done: {fb_rest};",
        "        -- Rescue",
        f"        fb_goal_level = {notify_g}: {{fb_notify_ambulance_ready_Civ}};",
        f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_g}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_positive()} and Environment.fb_zone = {info.civ_zone}: {{fb_rescue_Civ}};",
    ]
    for z in info.zones:
        if z == info.civ_zone:
            continue
        choices = [f"fb_move_to_{n}" for n in to_civ.get(z, [])]
        if not choices:
            choices = [f"fb_move_to_{n}" for n in info.fb_graph.get(z, [])]
        lines += [
            f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_g}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_positive()} and Environment.fb_zone = {z}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]
    lines += local_patrol_rules(
        agent_prefix="fb",
        goal_var="fb_goal_level",
        top_goal=spec.top,
        zone_var="fb_zone",
        knows_guard="Environment.fb_knows_buried_Civ = false",
        graph=info.fb_graph,
        info=info,
        order=spec.patrol_order,
        rest="fb_rest",
    )
    lines += [
        "        Other: {fb_rest};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "        fb_goal_level = done if Environment.dead_Civ = true or Environment.delivered_Civ = true;",
        f"        fb_goal_level = {notify_g} if (fb_goal_level = {spec.top} or fb_goal_level = {rescue_g}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and Environment.buriedness_value_Civ = 1 and Environment.fb_zone = {info.civ_zone} and FireBrigade.Action = fb_rescue_Civ;",
        f"        fb_goal_level = {spec.top} if fb_goal_level = {notify_g} and FireBrigade.Action = fb_notify_ambulance_ready_Civ and Environment.dead_Civ = false and Environment.delivered_Civ = false;",
        f"        fb_goal_level = {rescue_g} if fb_goal_level = {spec.top} and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        f"        fb_goal_level = {rescue_g} if fb_goal_level = {rescue_g} and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        "        -- Visited",
    ]
    for z in info.zones:
        lines.append(f"        fb_visited_{z} = true if fb_visited_{z} = true or FireBrigade.Action = fb_move_to_{z};")
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def ambulance_agent(spec: AgentSpec, info: ModelInfo) -> str:
    report_g = spec.major["report"]
    load_g = spec.major["load"]
    deliver_g = spec.major["deliver"]
    to_civ = shortest_steps(info.at_graph, info.civ_zone)
    to_refuge = shortest_steps(info.at_graph, info.refuge_zone)
    actions = [f"at_move_to_{z}" for z in info.zones] + ["at_load_Civ", "at_unload_Civ", "at_report_buried_Civ", "at_rest"]

    lines = [
        "Agent AmbulanceTeam",
        "    Vars:",
        "        dummy: boolean;",
        f"        at_goal_level: {{{', '.join(spec.goals)}}};",
    ]
    lines += [f"        at_visited_{z}: boolean;" for z in info.zones]
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=6)};",
        "    Protocol:",
        "        Environment.dead_Civ = true: {at_rest};",
        "        Environment.delivered_Civ = true: {at_rest};",
        "        at_goal_level = done: {at_rest};",
        "        -- Report",
        f"        at_goal_level = {report_g}: {{at_report_buried_Civ}};",
        "        -- Load",
        f"        at_goal_level = {load_g} and Environment.alive_Civ = true and Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.at_zone = {info.civ_zone}: {{at_load_Civ}};",
    ]
    for z in info.zones:
        if z == info.civ_zone:
            continue
        choices = [f"at_move_to_{n}" for n in to_civ.get(z, [])]
        if not choices:
            choices = [f"at_move_to_{n}" for n in info.at_graph.get(z, [])]
        lines += [
            f"        at_goal_level = {load_g} and Environment.alive_Civ = true and Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and Environment.at_zone = {z}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]
    lines += [
        "        -- Deliver",
        f"        at_goal_level = {deliver_g} and Environment.loaded_Civ = true and Environment.alive_Civ = true and Environment.at_zone = {info.refuge_zone}: {{at_unload_Civ}};",
    ]
    for z in info.zones:
        if z == info.refuge_zone:
            continue
        choices = [f"at_move_to_{n}" for n in to_refuge.get(z, [])]
        if not choices:
            choices = [f"at_move_to_{n}" for n in info.at_graph.get(z, [])]
        lines += [
            f"        at_goal_level = {deliver_g} and Environment.loaded_Civ = true and Environment.alive_Civ = true and Environment.at_knows_refuge = true and Environment.at_zone = {z}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]

    # Loaded but refuge not found yet: keep searching with local raw patrol.
    for cur in info.zones:
        if cur == info.refuge_zone:
            continue
        raw_nbs = info.at_graph.get(cur, [])
        for nb in raw_nbs:
            higher = [
                x for x in raw_nbs
                if status_rank(info.statuses.get(x, "healthy"), spec.patrol_order) < status_rank(info.statuses.get(nb, "healthy"), spec.patrol_order)
            ]
            parts = [
                f"at_goal_level = {deliver_g}",
                "Environment.loaded_Civ = true",
                "Environment.alive_Civ = true",
                "Environment.at_knows_refuge = false",
                f"Environment.at_zone = {cur}",
            ]
            parts += [f"at_visited_{x} = true" for x in higher]
            parts.append(f"at_visited_{nb} = false")
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {{at_move_to_{nb}}};",
            ]
        if raw_nbs:
            parts = [
                f"at_goal_level = {deliver_g}",
                "Environment.loaded_Civ = true",
                "Environment.alive_Civ = true",
                "Environment.at_knows_refuge = false",
                f"Environment.at_zone = {cur}",
            ] + [f"at_visited_{x} = true" for x in raw_nbs]
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {action_set([f'at_move_to_{x}' for x in raw_nbs] + ['at_rest'], indent_spaces=16, per_line=4)};",
            ]

    # If AT has reported/learned the buried civilian, it should not resume patrol.
    # It moves to the civilian zone and waits there until the civilian becomes surface/ready.
    lines += [
        f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and Environment.buried_Civ_reported_to_FB = false and Environment.alive_Civ = true and {buried_positive()}: {{at_rest}};",
        f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and Environment.buried_Civ_reported_to_FB = true and Environment.alive_Civ = true and {buried_positive()} and Environment.at_zone = {info.civ_zone}: {{at_rest}};",
    ]
    for z in info.zones:
        if z == info.civ_zone:
            continue
        choices = [f"at_move_to_{n}" for n in to_civ.get(z, [])]
        if not choices:
            choices = [f"at_move_to_{n}" for n in info.at_graph.get(z, [])]
        lines += [
            f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and Environment.buried_Civ_reported_to_FB = true and Environment.alive_Civ = true and {buried_positive()} and Environment.at_zone = {z}:",
            f"            {action_set(choices + ['at_rest'], indent_spaces=16, per_line=4)};",
        ]
    lines += [
        f"        at_goal_level = {spec.top} and Environment.alive_Civ = true and Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and (Environment.Civ_ready_reported_to_AT = true or Environment.at_zone = {info.civ_zone}): {{at_rest}};",
    ]
    lines += local_patrol_rules(
        agent_prefix="at",
        goal_var="at_goal_level",
        top_goal=spec.top,
        zone_var="at_zone",
        knows_guard="Environment.at_knows_buried_Civ = false",
        graph=info.at_graph,
        info=info,
        order=spec.patrol_order,
        rest="at_rest",
    )
    lines += [
        "        Other: {at_rest};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "        at_goal_level = done if Environment.dead_Civ = true or Environment.delivered_Civ = true;",
        f"        at_goal_level = done if at_goal_level = {deliver_g} and AmbulanceTeam.Action = at_unload_Civ;",
        f"        at_goal_level = {deliver_g} if at_goal_level = {load_g} and AmbulanceTeam.Action = at_load_Civ;",
        f"        at_goal_level = {load_g} if at_goal_level = {spec.top} and Environment.alive_Civ = true and Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and (Environment.Civ_ready_reported_to_AT = true or Environment.at_zone = {info.civ_zone});",
        f"        at_goal_level = {report_g} if at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and Environment.buried_Civ_reported_to_FB = false and Environment.alive_Civ = true and {buried_positive()};",
        f"        at_goal_level = {spec.top} if at_goal_level = {report_g} and AmbulanceTeam.Action = at_report_buried_Civ;",
        "        -- Visited",
    ]
    for z in info.zones:
        lines.append(f"        at_visited_{z} = true if at_visited_{z} = true or AmbulanceTeam.Action = at_move_to_{z};")
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def generate_protocol(
    spec: AgentSpec,
    model_info: object,
    agent: str,
    model_kind: str,
) -> str:

    if model_kind == "abstract":
        if not isinstance(model_info, ModelInfo):
            raise TypeError("abstract protocol generation requires ModelInfo")
        return fire_agent(spec, model_info) if agent == "FireBrigade" else ambulance_agent(spec, model_info)
    if model_kind == "exact_two_agent":
        if not isinstance(model_info, ExactTwoAgentModelInfo):
            raise TypeError("exact two-agent protocol generation requires ExactTwoAgentModelInfo")
        return (
            exact_two_agent_fire_agent(spec, model_info)
            if agent == "FireBrigade"
            else exact_two_agent_ambulance_agent(spec, model_info)
        )
    if model_kind == "exact_fire_only":
        if agent != "FireBrigade" or not isinstance(model_info, ExactFireModelInfo):
            raise TypeError("exact fire-only protocol generation requires FireBrigade and ExactFireModelInfo")
        return exact_fire_agent(spec, model_info)
    raise ValueError(f"Unsupported model kind: {model_kind}")


def generate_evolution_rules(raw: str, model_info: object, model_kind: str) -> str:

    if model_kind == "abstract":
        if not isinstance(model_info, ModelInfo):
            raise TypeError("abstract evolution generation requires ModelInfo")
        return add_environment(raw, model_info)
    if model_kind == "exact_two_agent":
        if not isinstance(model_info, ExactTwoAgentModelInfo):
            raise TypeError("exact two-agent evolution generation requires ExactTwoAgentModelInfo")
        return add_exact_two_agent_environment(raw, model_info)
    if model_kind == "exact_fire_only":
        if not isinstance(model_info, ExactFireModelInfo):
            raise TypeError("exact fire-only evolution generation requires ExactFireModelInfo")
        return add_exact_fire_belief(raw, model_info)
    raise ValueError(f"Unsupported model kind: {model_kind}")


def replace_agent_decision_model(raw: str, agent_blocks: Dict[str, str]) -> str:
    result = raw
    for agent_name, generated_block in agent_blocks.items():
        result = replace_agent(result, agent_name, generated_block)
    return result


def BuildGoalControl(
    plans: Sequence[Plan], top_goal: str, bridge: dict, agent: str
) -> GoalControl:
    return build_goal_control(plans, top_goal, bridge, agent)


def BuildAgentSpec(
    plans: Sequence[Plan], control: GoalControl, bridge: dict, agent: str
) -> AgentSpec:
    return build_agent_spec(plans, control, bridge, agent)


def GenerateProtocol(
    spec: AgentSpec, model_info: object, agent: str, model_kind: str
) -> str:
    return generate_protocol(spec, model_info, agent, model_kind)


def GenerateEvolutionRules(raw: str, model_info: object, model_kind: str) -> str:
    return generate_evolution_rules(raw, model_info, model_kind)


def ReplaceAgentDecisionModel(raw: str, agent_blocks: Dict[str, str]) -> str:
    return replace_agent_decision_model(raw, agent_blocks)


# ---------- Driver ----------

def translate(raw_path: Path, fire_path: Path, ambulance_path: Path, bridge_path: Path, output_path: Path) -> None:
    raw = read_text(raw_path)
    bridge = json.loads(read_text(bridge_path))
    fb_plans, fb_top = read_plans(read_text(fire_path))
    at_plans, at_top = read_plans(read_text(ambulance_path))
    fb_control = BuildGoalControl(fb_plans, fb_top, bridge, "fire")
    at_control = BuildGoalControl(at_plans, at_top, bridge, "ambulance")
    fb = BuildAgentSpec(fb_plans, fb_control, bridge, "fire")
    at = BuildAgentSpec(at_plans, at_control, bridge, "ambulance")
    info = load_model(raw)

    raw = GenerateEvolutionRules(raw, info, "abstract")
    raw = add_init(raw, fb, at, info)
    raw = patch_formulae(raw)
    agent_blocks = {
        "FireBrigade": GenerateProtocol(fb, info, "FireBrigade", "abstract"),
        "AmbulanceTeam": GenerateProtocol(at, info, "AmbulanceTeam", "abstract"),
    }
    raw = ReplaceAgentDecisionModel(raw, agent_blocks)
    output_path.write_text(raw, encoding="utf-8")

    print(f"Wrote ISPL: {output_path}")
    print("Fire top:", fb.top)
    print("Fire goals:", ", ".join(fb.goals))
    print("Fire patrol priority:", ", ".join(fb.patrol_order))
    print("Ambulance top:", at.top)
    print("Ambulance goals:", ", ".join(at.goals))
    print("Ambulance patrol priority:", ", ".join(at.patrol_order))


# Exact / missing-agent compatibility

@dataclass
class ExactFireModelInfo:
    areas: List[str]
    statuses: Dict[str, str]
    building_areas: Set[str]
    fb_graph: Dict[str, List[str]]
    fb_start: str
    civ_area: str
    civ_var: str


def is_normal_abstract_two_agent(raw: str) -> bool:
    return (
        "Agent FireBrigade\n" in raw
        and "Agent AmbulanceTeam\n" in raw
        and re.search(r"fb_zone:\s*\{", raw) is not None
        and re.search(r"at_zone:\s*\{", raw) is not None
    )


def exact_area_values(raw: str) -> List[str]:
    match = re.search(r"\bfb_area:\s*\{(?P<body>.*?)\};", raw, re.S)
    if not match:
        civ_var = detect_civ_area_var(raw)
        match = re.search(rf"\b{re.escape(civ_var)}:\s*\{{(?P<body>.*?)\}};", raw, re.S)
    if not match:
        raise ValueError("Exact compatibility requires an fb_area or civilian-area enum")
    return uniq(re.findall(r"\barea_\d+\b", match.group("body")))


def exact_init_value(raw: str, var: str) -> str:
    init = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    body = init.group("body") if init else raw
    match = re.search(rf"Environment\.{re.escape(var)}\s*=\s*(area_\d+|true|false|[A-Za-z0-9_]+)", body)
    if not match:
        raise ValueError(f"Initial value for Environment.{var} not found")
    return match.group(1)


def exact_move(area: str) -> str:
    match = re.fullmatch(r"area_(\d+)", area)
    if not match:
        raise ValueError(f"Invalid exact area value: {area}")
    return f"fb_move_to_{match.group(1)}"


def exact_neighbours_from_fire(agent_raw: str, areas: Sequence[str]) -> Dict[str, List[str]]:
    graph: Dict[str, List[str]] = {area: [] for area in areas}
    for area in areas:
        match = re.search(
            rf"Environment\.fb_area\s*=\s*{re.escape(area)}\s*:\s*(?P<actions>\{{.*?\}})\s*;",
            agent_raw,
            re.S,
        )
        if not match:
            continue
        ids = re.findall(r"\bfb_move_to_(\d+)\b", match.group("actions"))
        graph[area] = uniq([f"area_{area_id}" for area_id in ids if f"area_{area_id}" in areas])
    return graph


def exact_statuses_from_raw(raw: str, areas: Sequence[str]) -> Tuple[Dict[str, str], Set[str]]:
    building_ids = set(re.findall(r"\bbuilding_(\d+):\s*boolean;", raw))
    building_areas = {f"area_{area_id}" for area_id in building_ids}
    init = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    body = init.group("body") if init else raw
    statuses: Dict[str, str] = {}
    for area in areas:
        area_id = area.split("_", 1)[1]
        if area in building_areas:
            match = re.search(
                rf"Environment\.brokenness_{re.escape(area_id)}\s*=\s*(healthy|damaged|collapsed)",
                body,
            )
            statuses[area] = match.group(1) if match else "healthy"
        else:
            statuses[area] = "road"
    return statuses, building_areas


def load_exact_fire_model(raw: str) -> ExactFireModelInfo:
    areas = exact_area_values(raw)
    _, _, raw_fb = block(raw, "FireBrigade")
    statuses, building_areas = exact_statuses_from_raw(raw, areas)
    return ExactFireModelInfo(
        areas=areas,
        statuses=statuses,
        building_areas=building_areas,
        fb_graph=exact_neighbours_from_fire(raw_fb, areas),
        fb_start=exact_init_value(raw, "fb_area"),
        civ_area=exact_init_value(raw, detect_civ_area_var(raw)),
        civ_var=detect_civ_area_var(raw),
    )


def exact_area_rank(area: str, info: ExactFireModelInfo, order: Sequence[str]) -> int:
    status = info.statuses.get(area, "road")
    if status == "collapsed":
        candidates = ["collapsed"]
    elif status == "damaged":
        candidates = ["damaged"]
    elif area in info.building_areas:
        candidates = ["building"]
    else:
        candidates = ["road_unvisited", "road", "known_road"]
    for index, item in enumerate(order):
        if item in candidates:
            return index
    return 999


def exact_fire_patrol_rules(spec: AgentSpec, info: ExactFireModelInfo) -> List[str]:
    lines = ["        -- Patrol"]
    for current in info.areas:
        neighbours = info.fb_graph.get(current, [])
        for neighbour in neighbours:
            neighbour_rank = exact_area_rank(neighbour, info, spec.patrol_order)
            higher = [
                candidate
                for candidate in neighbours
                if exact_area_rank(candidate, info, spec.patrol_order) < neighbour_rank
            ]
            parts = [
                f"fb_goal_level = {spec.top}",
                "Environment.fb_knows_buried_Civ = false",
                "Environment.alive_Civ = true",
                f"Environment.fb_area = {current}",
            ]
            parts += [f"fb_visited_{candidate} = true" for candidate in higher]
            parts.append(f"fb_visited_{neighbour} = false")
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {{{exact_move(neighbour)}}};",
            ]
        if neighbours:
            parts = [
                f"fb_goal_level = {spec.top}",
                "Environment.fb_knows_buried_Civ = false",
                "Environment.alive_Civ = true",
                f"Environment.fb_area = {current}",
            ] + [f"fb_visited_{candidate} = true" for candidate in neighbours]
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {action_set([exact_move(candidate) for candidate in neighbours], indent_spaces=16, per_line=4)};",
            ]
    return lines


def exact_fire_agent(spec: AgentSpec, info: ExactFireModelInfo) -> str:
    rescue_goal = spec.major["rescue"]
    goals = uniq([spec.top, rescue_goal, "done"])
    to_civilian = shortest_steps(info.fb_graph, info.civ_area)
    actions = [exact_move(area) for area in info.areas] + ["fb_rescue_Civ", "fb_rest"]
    lines = [
        "Agent FireBrigade",
        "    Vars:",
        "        dummy: boolean;",
        f"        fb_goal_level: {{{', '.join(goals)}}};",
    ]
    lines += [f"        fb_visited_{area}: boolean;" for area in info.areas]
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=6)};",
        "    Protocol:",
        "        Environment.dead_Civ = true: {fb_rest};",
        "        Environment.delivered_Civ = true: {fb_rest};",
        "        fb_goal_level = done: {fb_rest};",
        "        -- Rescue",
        f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_positive()} and Environment.fb_area = {info.civ_area}: {{fb_rescue_Civ}};",
    ]
    for area in info.areas:
        if area == info.civ_area:
            continue
        choices = [exact_move(next_area) for next_area in to_civilian.get(area, [])]
        if not choices:
            choices = [exact_move(next_area) for next_area in info.fb_graph.get(area, [])]
        if not choices:
            choices = ["fb_rest"]
        lines += [
            f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_positive()} and Environment.fb_area = {area}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]
    lines += exact_fire_patrol_rules(spec, info)
    lines += [
        "        Other: {fb_rest};",
        "    end Protocol",
        "    Evolution:",
        "        dummy = dummy if dummy = true;",
        "        dummy = dummy if dummy = false;",
        "        fb_goal_level = done if Environment.dead_Civ = true or Environment.delivered_Civ = true;",
        f"        fb_goal_level = done if (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and Environment.buriedness_value_Civ = 1 and Environment.fb_area = {info.civ_area} and FireBrigade.Action = fb_rescue_Civ;",
        f"        fb_goal_level = {rescue_goal} if fb_goal_level = {spec.top} and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        f"        fb_goal_level = {rescue_goal} if fb_goal_level = {rescue_goal} and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        "        -- Visited",
    ]
    for area in info.areas:
        lines.append(f"        fb_visited_{area} = true if fb_visited_{area} = true or FireBrigade.Action = {exact_move(area)};")
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def remove_obsvar(raw: str, var: str) -> str:
    return re.sub(
        rf"(?ms)^[ \t]*{re.escape(var)}\s*:\s*(?:\{{.*?\}}|[^;]+)\s*;[ \t]*\n?",
        "",
        raw,
        count=1,
    )


def remove_ambulance_from_exact(raw: str) -> str:
    if "Agent AmbulanceTeam\n" in raw:
        start, end, _ = block(raw, "AmbulanceTeam")
        raw = raw[:start] + raw[end:]
    raw = remove_obsvar(raw, "did_action_AT")
    raw = "\n".join(
        line for line in raw.splitlines() if "AmbulanceTeam.Action" not in line
    ) + ("\n" if raw.endswith("\n") else "")
    return raw


def add_exact_fire_belief(raw: str, info: ExactFireModelInfo) -> str:
    if not re.search(r"\bfb_knows_buried_Civ:\s*boolean;", raw):
        pattern = re.compile(r"(?m)^(?P<indent>[ \t]*)delivered_Civ:\s*boolean;[ \t]*$")
        match = pattern.search(raw)
        if not match:
            raise ValueError("Environment.delivered_Civ declaration not found")
        replacement = match.group(0) + "\n" + match.group("indent") + "fb_knows_buried_Civ: boolean;"
        raw = raw[:match.start()] + replacement + raw[match.end():]

    belief = (
        "        -- Beliefs\n"
        f"        fb_knows_buried_Civ = true if fb_knows_buried_Civ = true or (alive_Civ = true and {buried_positive('')} and (fb_area = {info.civ_area} or FireBrigade.Action = {exact_move(info.civ_area)}));\n"
    )
    if "        -- Beliefs\n" not in raw:
        if "        -- Health\n" in raw:
            raw = raw.replace("        -- Health\n", belief + "        -- Health\n", 1)
        else:
            env_start, env_end, env_block = block(raw, "Environment")
            patched = env_block.replace("    end Evolution", belief + "    end Evolution", 1)
            raw = raw[:env_start] + patched + raw[env_end:]
    return raw


def rewrite_exact_init(raw: str, spec: AgentSpec, info: ExactFireModelInfo) -> str:
    match = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    if not match:
        raise ValueError("InitStates block not found")
    assignments: List[str] = []
    for line in match.group("body").splitlines():
        item = line.strip()
        if not item or item.startswith("--"):
            continue
        item = re.sub(r"\s+and\s*$", "", item)
        item = re.sub(r";\s*$", "", item)
        if item.startswith("AmbulanceTeam.") or item.startswith("Environment.did_action_AT"):
            continue
        assignments.append(item)

    additions = [
        "Environment.fb_knows_buried_Civ = false",
        f"FireBrigade.fb_goal_level = {spec.top}",
    ] + [
        f"FireBrigade.fb_visited_{area} = {'true' if area == info.fb_start else 'false'}"
        for area in info.areas
    ]

    output: List[str] = []
    inserted = False
    for item in assignments:
        if item == "FireBrigade.dummy = false" and not inserted:
            output.extend(additions)
            inserted = True
        output.append(item)
    if not inserted:
        output.extend(additions)

    lines = ["InitStates"]
    for index, item in enumerate(output):
        suffix = ";" if index == len(output) - 1 else " and"
        lines.append(f"    {item}{suffix}")
    lines.append("end InitStates")
    new_block = "\n".join(lines)
    return raw[:match.start()] + new_block + raw[match.end():]


def render_custom_groups_formulae(config: dict) -> str:
    groups = config.get("groups") or {"fire_only": ["FireBrigade"]}
    group_lines = ["Groups"]
    for name, members in groups.items():
        kept = [str(member) for member in members if str(member) == "FireBrigade"]
        if kept:
            group_lines.append(f"    {clean_name(str(name))} = {{{', '.join(kept)}}};")
    if len(group_lines) == 1:
        group_lines.append("    fire_only = {FireBrigade};")
    group_lines.append("end Groups")

    formulae = config.get("formulae") or ["<fire_only> F surface_Civ_eval;"]
    formula_lines = ["Formulae"]
    for formula in formulae:
        value = str(formula).strip()
        if value and not value.endswith(";"):
            value += ";"
        if value:
            formula_lines.append(f"    {value}")
    formula_lines.append("end Formulae")
    return "\n".join(group_lines + [""] + formula_lines)


def replace_groups_formulae(raw: str, config: dict) -> str:
    replacement = render_custom_groups_formulae(config)
    match = re.search(r"Groups.*?end Groups\s*Formulae.*?end Formulae", raw, re.S)
    if match:
        return raw[:match.start()] + replacement + raw[match.end():]
    return raw.rstrip() + "\n\n" + replacement + "\n"



# ---------- Exact two-agent compatibility ----------

@dataclass
class ExactTwoAgentModelInfo:
    areas: List[str]
    statuses: Dict[str, str]
    building_areas: Set[str]
    fb_graph: Dict[str, List[str]]
    at_graph: Dict[str, List[str]]
    fb_start: str
    at_start: str
    civ_area: str
    civ_var: str
    refuge_area: str


def is_exact_two_agent(raw: str) -> bool:
    return (
        "Agent FireBrigade\n" in raw
        and "Agent AmbulanceTeam\n" in raw
        and re.search(r"\bfb_area:\s*\{", raw) is not None
        and re.search(r"\bat_area:\s*\{", raw) is not None
        and re.search(r"\bfb_zone:\s*\{", raw) is None
    )


def exact_at_move(area: str) -> str:
    match = re.fullmatch(r"area_(\d+)", area)
    if not match:
        raise ValueError(f"Invalid exact area value: {area}")
    return f"at_move_to_{match.group(1)}"


def exact_neighbours_from_agent(
    agent_raw: str,
    areas: Sequence[str],
    zone_var: str,
    move_prefix: str,
) -> Dict[str, List[str]]:
    graph: Dict[str, List[str]] = {area: [] for area in areas}
    protocol = re.search(r"\bProtocol:(.*?)\bend Protocol", agent_raw, re.S)
    body = protocol.group(1) if protocol else agent_raw
    rule_re = re.compile(r"(?P<condition>[^;]*?):\s*(?P<actions>\{.*?\})\s*;", re.S)
    for rule in rule_re.finditer(body):
        sources = re.findall(
            rf"Environment\.{re.escape(zone_var)}\s*=\s*(area_\d+)",
            rule.group("condition"),
        )
        if not sources:
            continue
        source = sources[-1]
        if source not in graph:
            continue
        ids = re.findall(rf"\b{re.escape(move_prefix)}_move_to_(\d+)\b", rule.group("actions"))
        graph[source] = uniq(graph[source] + [f"area_{item}" for item in ids if f"area_{item}" in areas])
    return graph


def load_exact_two_agent_model(raw: str) -> ExactTwoAgentModelInfo:
    areas = exact_area_values(raw)
    statuses, building_areas = exact_statuses_from_raw(raw, areas)
    _, _, raw_fb = block(raw, "FireBrigade")
    _, _, raw_at = block(raw, "AmbulanceTeam")
    return ExactTwoAgentModelInfo(
        areas=areas,
        statuses=statuses,
        building_areas=building_areas,
        fb_graph=exact_neighbours_from_agent(raw_fb, areas, "fb_area", "fb"),
        at_graph=exact_neighbours_from_agent(raw_at, areas, "at_area", "at"),
        fb_start=exact_init_value(raw, "fb_area"),
        at_start=exact_init_value(raw, "at_area"),
        civ_area=exact_init_value(raw, detect_civ_area_var(raw)),
        civ_var=detect_civ_area_var(raw),
        refuge_area=exact_init_value(raw, "refuge_area"),
    )


def exact_generic_area_rank(
    area: str,
    statuses: Dict[str, str],
    building_areas: Set[str],
    order: Sequence[str],
) -> int:
    status = statuses.get(area, "road")
    if status == "collapsed":
        candidates = ["collapsed"]
    elif status == "damaged":
        candidates = ["damaged"]
    elif area in building_areas:
        candidates = ["building"]
    else:
        candidates = ["road_unvisited", "road", "known_road"]
    for index, item in enumerate(order):
        if item in candidates:
            return index
    return 999


def exact_patrol_rules(
    prefix: str,
    goal_var: str,
    top_goal: str,
    area_var: str,
    knows_guard: str,
    graph: Dict[str, List[str]],
    info: ExactTwoAgentModelInfo,
    order: Sequence[str],
) -> List[str]:
    lines = ["        -- Patrol"]
    for current in info.areas:
        neighbours = graph.get(current, [])
        for neighbour in neighbours:
            rank = exact_generic_area_rank(neighbour, info.statuses, info.building_areas, order)
            higher = [
                candidate for candidate in neighbours
                if exact_generic_area_rank(candidate, info.statuses, info.building_areas, order) < rank
            ]
            parts = [
                f"{goal_var} = {top_goal}",
                knows_guard,
                "Environment.alive_Civ = true",
                f"Environment.{area_var} = {current}",
            ]
            parts += [f"{prefix}_visited_{candidate} = true" for candidate in higher]
            parts.append(f"{prefix}_visited_{neighbour} = false")
            action = exact_move(neighbour) if prefix == "fb" else exact_at_move(neighbour)
            lines += [f"        {' and '.join(parts)}:", f"            {{{action}}};"]
        if neighbours:
            parts = [
                f"{goal_var} = {top_goal}",
                knows_guard,
                "Environment.alive_Civ = true",
                f"Environment.{area_var} = {current}",
            ] + [f"{prefix}_visited_{candidate} = true" for candidate in neighbours]
            actions = [exact_move(item) if prefix == "fb" else exact_at_move(item) for item in neighbours]
            lines += [
                f"        {' and '.join(parts)}:",
                f"            {action_set(actions, indent_spaces=16, per_line=4)};",
            ]
    return lines


def exact_two_agent_terminal_guard(info: ExactTwoAgentModelInfo, prefix: str = "Environment.") -> str:
    """Terminal when Civ is dead or alive, surface-level, unloaded, and at the refuge."""
    delivered_alive = (
        f"{prefix}alive_Civ = true and {prefix}dead_Civ = false and "
        f"{prefix}loaded_Civ = false and {prefix}buriedness_value_Civ = 0 and "
        f"{prefix}{info.civ_var} = {info.refuge_area} and {prefix}at_area = {info.refuge_area} and "
        f"{prefix}refuge_area = {info.refuge_area}"
    )
    return f"({prefix}dead_Civ = true or ({delivered_alive}))"


def exact_two_agent_unload_guard(info: ExactTwoAgentModelInfo, prefix: str = "Environment.") -> str:
    """Source-state guard for unloading Civ alive at the refuge."""
    return (
        f"{prefix}loaded_Civ = true and {prefix}alive_Civ = true and "
        f"{prefix}dead_Civ = false and {prefix}delivered_Civ = false and "
        f"{prefix}at_area = {info.refuge_area} and {prefix}refuge_area = {info.refuge_area} and "
        "AmbulanceTeam.Action = at_unload_Civ"
    )


def exact_two_agent_fire_agent(spec: AgentSpec, info: ExactTwoAgentModelInfo) -> str:
    rescue_goal = spec.major["rescue"]
    notify_goal = spec.major["notify_ready"]
    goals = uniq([spec.top, rescue_goal, notify_goal, "done"])
    to_civ = shortest_steps(info.fb_graph, info.civ_area)
    actions = [exact_move(area) for area in info.areas] + [
        "fb_rescue_Civ", "fb_notify_ambulance_ready_Civ", "fb_rest"
    ]
    lines = [
        "Agent FireBrigade", "    Vars:", "        dummy: boolean;",
        f"        fb_goal_level: {{{', '.join(goals)}}};",
    ]
    lines += [f"        fb_visited_{area}: boolean;" for area in info.areas]
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=6)};",
        "    Protocol:",
        f"        {exact_two_agent_terminal_guard(info)}: {{fb_rest}};",
        "        fb_goal_level = done: {fb_rest};",
        f"        fb_goal_level = {notify_goal}: {{fb_notify_ambulance_ready_Civ}};",
        f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) and "
        f"Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and "
        f"{buried_positive()} and Environment.fb_area = {info.civ_area}: {{fb_rescue_Civ}};",
    ]
    for area in info.areas:
        if area == info.civ_area:
            continue
        choices = [exact_move(item) for item in to_civ.get(area, [])]
        if not choices:
            choices = [exact_move(item) for item in info.fb_graph.get(area, [])] or ["fb_rest"]
        lines += [
            f"        (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) and "
            f"Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and "
            f"{buried_positive()} and Environment.fb_area = {area}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]
    lines += exact_patrol_rules(
        "fb", "fb_goal_level", spec.top, "fb_area",
        "Environment.fb_knows_buried_Civ = false", info.fb_graph, info, spec.patrol_order,
    )
    lines += [
        "        Other: {fb_rest};", "    end Protocol", "    Evolution:",
        "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
        "        fb_goal_level = done if Environment.dead_Civ = true;",
        f"        fb_goal_level = done if {exact_two_agent_unload_guard(info)};",
        f"        fb_goal_level = {notify_goal} if (fb_goal_level = {spec.top} or fb_goal_level = {rescue_goal}) "
        f"and Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and "
        f"Environment.buriedness_value_Civ = 1 and Environment.fb_area = {info.civ_area} "
        "and FireBrigade.Action = fb_rescue_Civ;",
        f"        fb_goal_level = {spec.top} if fb_goal_level = {notify_goal} and "
        "FireBrigade.Action = fb_notify_ambulance_ready_Civ and Environment.dead_Civ = false and "
        "Environment.delivered_Civ = false;",
        f"        fb_goal_level = {rescue_goal} if fb_goal_level = {spec.top} and "
        f"Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        f"        fb_goal_level = {rescue_goal} if fb_goal_level = {rescue_goal} and "
        f"Environment.fb_knows_buried_Civ = true and Environment.alive_Civ = true and {buried_mid_high()};",
        "        -- Visited",
    ]
    for area in info.areas:
        lines.append(
            f"        fb_visited_{area} = true if fb_visited_{area} = true or "
            f"FireBrigade.Action = {exact_move(area)};"
        )
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def exact_two_agent_ambulance_agent(spec: AgentSpec, info: ExactTwoAgentModelInfo) -> str:
    report_goal = spec.major["report"]
    load_goal = spec.major["load"]
    deliver_goal = spec.major["deliver"]
    goals = uniq([spec.top, report_goal, load_goal, deliver_goal, "done"])
    to_civ = shortest_steps(info.at_graph, info.civ_area)
    to_refuge = shortest_steps(info.at_graph, info.refuge_area)
    actions = [exact_at_move(area) for area in info.areas] + [
        "at_load_Civ", "at_unload_Civ", "at_report_buried_Civ", "at_rest"
    ]
    lines = [
        "Agent AmbulanceTeam", "    Vars:", "        dummy: boolean;",
        f"        at_goal_level: {{{', '.join(goals)}}};",
    ]
    lines += [f"        at_visited_{area}: boolean;" for area in info.areas]
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, indent_spaces=12, per_line=6)};",
        "    Protocol:",
        f"        {exact_two_agent_terminal_guard(info)}: {{at_rest}};",
        "        at_goal_level = done: {at_rest};",
        f"        at_goal_level = {report_goal}: {{at_report_buried_Civ}};",
        f"        at_goal_level = {load_goal} and Environment.alive_Civ = true and "
        f"Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and "
        f"Environment.at_area = {info.civ_area}: {{at_load_Civ}};",
    ]
    for area in info.areas:
        if area == info.civ_area:
            continue
        choices = [exact_at_move(item) for item in to_civ.get(area, [])]
        if not choices:
            choices = [exact_at_move(item) for item in info.at_graph.get(area, [])] or ["at_rest"]
        lines += [
            f"        at_goal_level = {load_goal} and Environment.alive_Civ = true and "
            f"Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and "
            f"Environment.at_area = {area}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]
    lines += [
        f"        at_goal_level = {deliver_goal} and Environment.loaded_Civ = true and "
        f"Environment.alive_Civ = true and Environment.at_area = {info.refuge_area}: {{at_unload_Civ}};",
    ]
    for area in info.areas:
        if area == info.refuge_area:
            continue
        choices = [exact_at_move(item) for item in to_refuge.get(area, [])]
        if not choices:
            choices = [exact_at_move(item) for item in info.at_graph.get(area, [])] or ["at_rest"]
        lines += [
            f"        at_goal_level = {deliver_goal} and Environment.loaded_Civ = true and "
            f"Environment.alive_Civ = true and Environment.at_knows_refuge = true and "
            f"Environment.at_area = {area}:",
            f"            {action_set(choices, indent_spaces=16, per_line=4)};",
        ]

    # The FireBrigade is already at the civilian, so AT waits instead of sending a redundant report.
    lines += [
        f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and "
        f"Environment.alive_Civ = true and {buried_positive()} and "
        f"Environment.fb_area = {info.civ_area}: {{at_rest}};",
    ]
    other_fb_areas = [area for area in info.areas if area != info.civ_area]
    if other_fb_areas:
        fb_elsewhere = "(" + " or ".join(f"Environment.fb_area = {area}" for area in other_fb_areas) + ")"
        lines += [
            f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and "
            f"Environment.buried_Civ_reported_to_FB = false and Environment.alive_Civ = true and "
            f"{buried_positive()} and {fb_elsewhere}: {{at_rest}};",
            f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and "
            f"Environment.buried_Civ_reported_to_FB = true and Environment.alive_Civ = true and "
            f"{buried_positive()} and Environment.at_area = {info.civ_area}: {{at_rest}};",
        ]
        for area in info.areas:
            if area == info.civ_area:
                continue
            choices = [exact_at_move(item) for item in to_civ.get(area, [])]
            if not choices:
                choices = [exact_at_move(item) for item in info.at_graph.get(area, [])] or ["at_rest"]
            lines += [
                f"        at_goal_level = {spec.top} and Environment.at_knows_buried_Civ = true and "
                f"Environment.buried_Civ_reported_to_FB = true and Environment.alive_Civ = true and "
                f"{buried_positive()} and Environment.at_area = {area}:",
                f"            {action_set(choices + ['at_rest'], indent_spaces=16, per_line=4)};",
            ]
    lines += [
        f"        at_goal_level = {spec.top} and Environment.alive_Civ = true and "
        f"Environment.loaded_Civ = false and Environment.buriedness_value_Civ = 0 and "
        f"(Environment.Civ_ready_reported_to_AT = true or Environment.at_area = {info.civ_area}): {{at_rest}};",
    ]
    lines += exact_patrol_rules(
        "at", "at_goal_level", spec.top, "at_area",
        "Environment.at_knows_buried_Civ = false", info.at_graph, info, spec.patrol_order,
    )
    lines += [
        "        Other: {at_rest};", "    end Protocol", "    Evolution:",
        "        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;",
        "        at_goal_level = done if Environment.dead_Civ = true;",
        f"        at_goal_level = done if at_goal_level = {deliver_goal} and AmbulanceTeam.Action = at_unload_Civ;",
        f"        at_goal_level = {deliver_goal} if at_goal_level = {load_goal} and AmbulanceTeam.Action = at_load_Civ;",
        # Direct observation of the final rescue lets AT load on the next step, while FB notifies concurrently.
        f"        at_goal_level = {load_goal} if at_goal_level = {spec.top} and "
        f"Environment.alive_Civ = true and Environment.loaded_Civ = false and "
        f"Environment.buriedness_value_Civ = 1 and Environment.at_area = {info.civ_area} and "
        f"Environment.fb_area = {info.civ_area} and FireBrigade.Action = fb_rescue_Civ;",
        f"        at_goal_level = {load_goal} if at_goal_level = {spec.top} and "
        f"Environment.alive_Civ = true and Environment.loaded_Civ = false and "
        f"Environment.buriedness_value_Civ = 0 and "
        f"(Environment.Civ_ready_reported_to_AT = true or Environment.at_area = {info.civ_area});",
    ]
    if other_fb_areas:
        fb_elsewhere = "(" + " or ".join(f"Environment.fb_area = {area}" for area in other_fb_areas) + ")"
        lines += [
            f"        at_goal_level = {report_goal} if at_goal_level = {spec.top} and "
            f"Environment.at_knows_buried_Civ = true and Environment.buried_Civ_reported_to_FB = false and "
            f"Environment.alive_Civ = true and {buried_positive()} and {fb_elsewhere};",
        ]
    lines += [
        f"        at_goal_level = {spec.top} if at_goal_level = {report_goal} and "
        "AmbulanceTeam.Action = at_report_buried_Civ;",
        "        -- Visited",
    ]
    for area in info.areas:
        lines.append(
            f"        at_visited_{area} = true if at_visited_{area} = true or "
            f"AmbulanceTeam.Action = {exact_at_move(area)};"
        )
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def add_exact_two_agent_environment(raw: str, info: ExactTwoAgentModelInfo) -> str:
    declarations = (
        "        fb_knows_buried_Civ: boolean;\n"
        "        at_knows_buried_Civ: boolean;\n"
        "        buried_Civ_reported_to_FB: boolean;\n"
        "        Civ_ready_reported_to_AT: boolean;\n"
        "        at_knows_refuge: boolean;\n"
    )
    if "fb_knows_buried_Civ: boolean;" not in raw:
        raw = raw.replace("        delivered_Civ: boolean;\n", "        delivered_Civ: boolean;\n" + declarations, 1)

    raw = raw.replace(
        "        fb_area = fb_area if FireBrigade.Action = fb_rest;\n",
        "        fb_area = fb_area if FireBrigade.Action = fb_notify_ambulance_ready_Civ;\n"
        "        fb_area = fb_area if FireBrigade.Action = fb_rest;\n",
        1,
    )
    raw = raw.replace(
        "        at_area = at_area if AmbulanceTeam.Action = at_rest;\n",
        "        at_area = at_area if AmbulanceTeam.Action = at_report_buried_Civ;\n"
        "        at_area = at_area if AmbulanceTeam.Action = at_rest;\n",
        1,
    )
    belief = (
        "        -- Beliefs\n"
        f"        fb_knows_buried_Civ = true if fb_knows_buried_Civ = true or "
        f"(alive_Civ = true and {buried_positive('')} and {info.civ_var} = {info.civ_area} and "
        f"(fb_area = {info.civ_area} or FireBrigade.Action = {exact_move(info.civ_area)})) or "
        "buried_Civ_reported_to_FB = true;\n"
        f"        at_knows_buried_Civ = true if at_knows_buried_Civ = true or "
        f"(alive_Civ = true and {buried_positive('')} and {info.civ_var} = {info.civ_area} and "
        f"(at_area = {info.civ_area} or AmbulanceTeam.Action = {exact_at_move(info.civ_area)}));\n"
        "        buried_Civ_reported_to_FB = true if buried_Civ_reported_to_FB = true or "
        "(at_knows_buried_Civ = true and AmbulanceTeam.Action = at_report_buried_Civ);\n"
        f"        Civ_ready_reported_to_AT = true if Civ_ready_reported_to_AT = true or "
        "(alive_Civ = true and buriedness_value_Civ = 0 and "
        "FireBrigade.Action = fb_notify_ambulance_ready_Civ);\n"
        f"        at_knows_refuge = true if at_knows_refuge = true or at_area = {info.refuge_area} or "
        f"AmbulanceTeam.Action = {exact_at_move(info.refuge_area)};\n"
    )
    marker = "        -- Fixed damage"
    if marker in raw and "        -- Beliefs\n" not in raw:
        raw = raw.replace(marker, belief + marker, 1)
    elif "        -- Beliefs\n" not in raw:
        env_start, env_end, env_block = block(raw, "Environment")
        patched = env_block.replace("    end Evolution", belief + "    end Evolution", 1)
        raw = raw[:env_start] + patched + raw[env_end:]
    return raw


def rewrite_exact_two_agent_init(
    raw: str,
    fb: AgentSpec,
    at: AgentSpec,
    info: ExactTwoAgentModelInfo,
) -> str:
    match = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    if not match:
        raise ValueError("InitStates block not found")
    assignments: List[str] = []
    for line in match.group("body").splitlines():
        item = line.strip()
        if not item or item.startswith("--"):
            continue
        item = re.sub(r"\s+and\s*$", "", item)
        item = re.sub(r";\s*$", "", item)
        assignments.append(item)

    additions = [
        "Environment.fb_knows_buried_Civ = false",
        "Environment.at_knows_buried_Civ = false",
        "Environment.buried_Civ_reported_to_FB = false",
        "Environment.Civ_ready_reported_to_AT = false",
        f"Environment.at_knows_refuge = {'true' if info.at_start == info.refuge_area else 'false'}",
        f"FireBrigade.fb_goal_level = {fb.top}",
    ]
    additions += [
        f"FireBrigade.fb_visited_{area} = {'true' if area == info.fb_start else 'false'}"
        for area in info.areas
    ]
    additions.append(f"AmbulanceTeam.at_goal_level = {at.top}")
    additions += [
        f"AmbulanceTeam.at_visited_{area} = {'true' if area == info.at_start else 'false'}"
        for area in info.areas
    ]

    output: List[str] = []
    inserted = False
    for item in assignments:
        if item == "FireBrigade.dummy = false" and not inserted:
            output.extend(additions)
            inserted = True
        output.append(item)
    if not inserted:
        output.extend(additions)
    lines = ["InitStates"]
    for index, item in enumerate(output):
        lines.append(f"    {item}{';' if index == len(output) - 1 else ' and'}")
    lines.append("end InitStates")
    return raw[:match.start()] + "\n".join(lines) + raw[match.end():]


def translate_exact_two_agent(
    raw_path: Path,
    fire_path: Path,
    ambulance_path: Path,
    bridge_path: Path,
    output_path: Path,
) -> None:
    raw = read_text(raw_path)
    bridge = json.loads(read_text(bridge_path))
    fb_plans, fb_top = read_plans(read_text(fire_path))
    at_plans, at_top = read_plans(read_text(ambulance_path))
    fb_control = BuildGoalControl(fb_plans, fb_top, bridge, "fire")
    at_control = BuildGoalControl(at_plans, at_top, bridge, "ambulance")
    fb = BuildAgentSpec(fb_plans, fb_control, bridge, "fire")
    at = BuildAgentSpec(at_plans, at_control, bridge, "ambulance")

    info = load_exact_two_agent_model(raw)

    raw = GenerateEvolutionRules(raw, info, "exact_two_agent")
    raw = rewrite_exact_two_agent_init(raw, fb, at, info)
    agent_blocks = {
        "FireBrigade": GenerateProtocol(fb, info, "FireBrigade", "exact_two_agent"),
        "AmbulanceTeam": GenerateProtocol(at, info, "AmbulanceTeam", "exact_two_agent"),
    }
    raw = ReplaceAgentDecisionModel(raw, agent_blocks)
    output_path.write_text(raw, encoding="utf-8")

    print(f"Wrote ISPL: {output_path}")
    print("Compatibility path: exact two-agent")
    print("Fire goals:", ", ".join(uniq([fb.top, fb.major['rescue'], fb.major['notify_ready'], 'done'])))
    print("Ambulance goals:", ", ".join(uniq([at.top, at.major['report'], at.major['load'], at.major['deliver'], 'done'])))


def translate_custom_compat(
    raw_path: Path,
    fire_path: Path,
    bridge_path: Path,
    output_path: Path,
    initial_path: Optional[Path],
) -> None:
    raw = read_text(raw_path)
    config = json.loads(read_text(initial_path)) if initial_path else {}
    requested_agents = config.get("agents")
    if requested_agents is not None and "FireBrigade" not in {str(x) for x in requested_agents}:
        raise ValueError("The exact compatibility branch requires FireBrigade in initial.agents")
    if requested_agents is not None and "AmbulanceTeam" in {str(x) for x in requested_agents}:
        raise ValueError("The exact compatibility branch is for fire-only custom maps")
    if "Agent FireBrigade\n" not in raw:
        raise ValueError("Agent FireBrigade not found in exact raw ISPL")
    if re.search(r"\bfb_area:\s*\{", raw) is None:
        raise ValueError("Unsupported non-normal model: exact compatibility requires fb_area")

    bridge = json.loads(read_text(bridge_path))
    fb_plans, fb_top = read_plans(read_text(fire_path))
    fb_control = BuildGoalControl(fb_plans, fb_top, bridge, "fire")
    fb = BuildAgentSpec(fb_plans, fb_control, bridge, "fire")
    info = load_exact_fire_model(raw)

    raw = remove_ambulance_from_exact(raw)
    raw = GenerateEvolutionRules(raw, info, "exact_fire_only")
    raw = rewrite_exact_init(raw, fb, info)
    agent_blocks = {
        "FireBrigade": GenerateProtocol(fb, info, "FireBrigade", "exact_fire_only"),
    }
    raw = ReplaceAgentDecisionModel(raw, agent_blocks)
    raw = replace_groups_formulae(raw, config)
    output_path.write_text(raw, encoding="utf-8")

    print(f"Wrote ISPL: {output_path}")
    print("Compatibility path: exact fire-only")
    print("Fire top:", fb.top)
    print("Fire goals:", ", ".join(uniq([fb.top, fb.major['rescue'], 'done'])))
    print("Fire patrol priority:", ", ".join(fb.patrol_order))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Jason-guided ISPL from raw ISPL and ASL files.")
    parser.add_argument("--raw", required=True, help="raw abstract or exact ISPL")
    parser.add_argument("--fire-jason", required=True, help="FireBrigade ASL")
    parser.add_argument("--ambulance-jason", help="AmbulanceTeam ASL; required for the normal two-agent abstract model")
    parser.add_argument("--bridge", "--jason-translation", dest="bridge", required=True, help="ASL translation JSON")
    parser.add_argument("--initial", help="Initial JSON for custom exact/missing-agent compatibility")
    parser.add_argument("--output", required=True, help="Output ISPL")
    args = parser.parse_args()

    raw_path = Path(args.raw)
    raw = read_text(raw_path)
    if is_normal_abstract_two_agent(raw):
        if not args.ambulance_jason:
            parser.error("--ambulance-jason is required for the normal abstract two-agent model")
        translate(
            raw_path,
            Path(args.fire_jason),
            Path(args.ambulance_jason),
            Path(args.bridge),
            Path(args.output),
        )
    elif is_exact_two_agent(raw):
        if not args.ambulance_jason:
            parser.error("--ambulance-jason is required for the exact two-agent model")
        translate_exact_two_agent(
            raw_path,
            Path(args.fire_jason),
            Path(args.ambulance_jason),
            Path(args.bridge),
            Path(args.output),
        )
    else:
        translate_custom_compat(
            raw_path,
            Path(args.fire_jason),
            Path(args.bridge),
            Path(args.output),
            Path(args.initial) if args.initial else None,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
