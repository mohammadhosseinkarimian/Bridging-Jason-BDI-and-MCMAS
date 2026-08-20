#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def clean_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    if re.match(r"^\d", value):
        value = "_" + value
    return value


def uniq(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(values))


def action_set(values: Sequence[str], indent_spaces: int = 16, per_line: int = 4) -> str:
    vals = uniq(v for v in values if v)
    chunks = [", ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    if len(chunks) == 1:
        return "{" + chunks[0] + "}"
    pad = " " * indent_spaces
    return "{\n" + ",\n".join(pad + chunk for chunk in chunks) + "\n" + " " * (indent_spaces - 4) + "}"


def split_top(text: str, sep: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    quote = False
    for ch in text:
        if ch == '"':
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if not quote and depth == 0 and ch == sep:
            item = "".join(cur).strip()
            if item:
                out.append(item)
            cur = []
        else:
            cur.append(ch)
    item = "".join(cur).strip()
    if item:
        out.append(item)
    return out


def parse_ispl_block(raw: str, agent_name: str) -> Tuple[int, int, str]:
    pattern = re.compile(rf"(?ms)^Agent[ \t]+{re.escape(agent_name)}[ \t]*$.*?^end[ \t]+Agent[ \t]*$")
    match = pattern.search(raw)
    if not match:
        raise ValueError(f"Agent block not found: {agent_name}")
    return match.start(), match.end(), match.group(0)


def replace_ispl_agent(raw: str, agent_name: str, new_block: str) -> str:
    start, end, _ = parse_ispl_block(raw, agent_name)
    return raw[:start] + new_block.rstrip() + "\n" + raw[end:]


def init_body(raw: str) -> str:
    match = re.search(r"InitStates(?P<body>.*?)end InitStates", raw, re.S)
    if not match:
        raise ValueError("InitStates block not found")
    return match.group("body")


def init_value(raw: str, environment_name: str, variable: str, value_pattern: str = r"[A-Za-z0-9_]+") -> str:
    body = init_body(raw)
    match = re.search(rf"{re.escape(environment_name)}\.{re.escape(variable)}\s*=\s*(?P<value>{value_pattern})", body)
    if not match:
        raise ValueError(f"Initial value not found for {environment_name}.{variable}")
    return match.group("value")


def shortest_steps(graph: Mapping[str, Sequence[str]], target: str) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {node: [] for node in graph}
    distances: Dict[str, int] = {target: 0}
    reverse: Dict[str, List[str]] = {node: [] for node in graph}
    for src, neighbours in graph.items():
        for dst in neighbours:
            reverse.setdefault(dst, []).append(src)
    queue: deque[str] = deque([target])
    while queue:
        node = queue.popleft()
        for predecessor in reverse.get(node, []):
            if predecessor not in distances:
                distances[predecessor] = distances[node] + 1
                queue.append(predecessor)
    for src, neighbours in graph.items():
        if src not in distances:
            continue
        best = distances[src] - 1
        result[src] = [dst for dst in neighbours if distances.get(dst) == best]
    return result


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


@dataclass
class GoalCall:
    parent: str
    child: str
    plan_index: int


@dataclass
class GoalControl:
    top: str
    values: List[str]
    calls: List[GoalCall]
    visited: List[str]


@dataclass
class AgentSpec:
    role_key: str
    plans: List[Plan]
    control: GoalControl
    stages: Dict[str, str]
    patrol_goal: str
    patrol_order: List[str]


@dataclass
class RoleModel:
    role_key: str
    agent_name: str
    location_var: str
    start: str
    graph: Dict[str, List[str]]
    base_vars: List[str]


@dataclass
class ModelInfo:
    environment_name: str
    locations: List[str]
    named_locations: Dict[str, str]
    roles: Dict[str, RoleModel]
    classes: Dict[str, str]


def parse_term(raw: str) -> Optional[Term]:
    item = raw.strip()
    if not item:
        return None
    op = item[0] if item[0] in "+-!?" else ""
    body = item[1:].strip() if op else item
    if body.startswith("not "):
        body = body[4:].strip()
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?$", body)
    if not match:
        return None
    args = [] if match.group(2) is None else [part.strip() for part in split_top(match.group(2), ",")]
    return Term(op=op, name=clean_name(match.group(1)), args=args, raw=item)


def parse_body_terms(body: str) -> List[Term]:
    out: List[Term] = []
    for piece in split_top(body, ";"):
        term = parse_term(piece)
        if term:
            out.append(term)
    return out


def strip_asl_comments(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def read_plans(asl_text: str, entry_goal: str) -> Tuple[List[Plan], str]:
    text = strip_asl_comments(asl_text)
    blobs: List[str] = []
    current: List[str] = []
    active = False
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        if re.match(r"\+!", item):
            active = True
            current = [item]
        elif active:
            current.append(item)
        if active and item.endswith("."):
            blobs.append(" ".join(current).rstrip("."))
            active = False

    plans: List[Plan] = []
    top: Optional[str] = None
    entry_clean = clean_name(entry_goal)
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
        if goal == entry_clean:
            for term in terms:
                if term.op == "!":
                    top = clean_name(term.name)
                    break
    if top is None:
        entry_match = re.search(
            rf"(?ms)^\s*\+!?{re.escape(entry_goal)}(?:\([^)]*\))?\s*:\s*.*?\s*<-\s*(?P<body>.*?)\.\s*$",
            text,
        )
        if entry_match:
            for term in parse_body_terms(entry_match.group("body")):
                if term.op == "!":
                    top = clean_name(term.name)
                    break
    if top is None:
        raise ValueError(f"Could not derive top goal from configured entry goal {entry_goal!r}")
    return plans, top


def name_in_list(name: str, values: Sequence[str]) -> bool:
    target = clean_name(name)
    return target in {clean_name(value) for value in values}


def action_category(term: Term, vocabulary: Mapping[str, Any]) -> Optional[str]:
    for category, names in vocabulary.get("actions", {}).items():
        if name_in_list(term.name, names):
            return str(category)
    return None


def context_has(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get("predicates", {}).get(category, []):
        if re.search(rf"\b{re.escape(str(predicate))}\s*\(", context) or re.search(rf"\b{re.escape(str(predicate))}\b", context):
            return True
    return False


def context_has_negative(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get("predicates", {}).get(category, []):
        if re.search(rf"\bnot\s+{re.escape(str(predicate))}(?:\s*\(|\b)", context):
            return True
    return False


def goal_with_action(plans: Sequence[Plan], vocabulary: Mapping[str, Any], category: str, top: str) -> Optional[str]:
    hits: List[str] = []
    for plan in plans:
        if any(action_category(term, vocabulary) == category for term in plan.terms):
            hits.append(plan.goal)
    for goal in hits:
        if goal != top:
            return goal
    return hits[0] if hits else None


def infer_patrol_goal(plans: Sequence[Plan], top: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> str:
    configured = role_cfg.get("patrol", {}).get("goal")
    if configured and configured != "auto":
        return clean_name(str(configured))
    categories = role_cfg.get("patrol", {}).get("signal_categories", [])
    scores: Dict[str, int] = {}
    for plan in plans:
        if plan.goal in (clean_name(str(role_cfg.get("entry_goal", ""))), top):
            continue
        score = sum(1 for category in categories if context_has(plan.context, str(category), vocabulary))
        if score:
            scores[plan.goal] = scores.get(plan.goal, 0) + score
    if scores:
        return max(scores, key=scores.get)
    fallback = role_cfg.get("patrol", {}).get("fallback_goal")
    if fallback:
        return clean_name(str(fallback))
    raise ValueError("Could not infer patrol goal")


def infer_patrol_order(plans: Sequence[Plan], patrol_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> List[str]:
    order: List[str] = []
    classifiers = role_cfg.get("patrol", {}).get("classifiers", [])
    for plan in plans:
        if plan.goal != patrol_goal:
            continue
        context = plan.context
        for classifier in classifiers:
            if classifier.get("context_equals") is not None:
                if context.strip() == str(classifier["context_equals"]):
                    order.append(str(classifier["name"]))
                    break
                continue
            required = [str(x) for x in classifier.get("all", [])]
            negative = [str(x) for x in classifier.get("negative", [])]
            if all(context_has(context, category, vocabulary) for category in required) and all(
                context_has_negative(context, category, vocabulary) for category in negative
            ):
                order.append(str(classifier["name"]))
                break
    return uniq(order or [str(x) for x in role_cfg.get("patrol", {}).get("fallback_order", [])])


def BuildGoalControl(plans: Sequence[Plan], top_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> GoalControl:
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
    values = [top_goal]
    for stage in role_cfg.get("stages", []):
        category = str(stage["action_category"])
        goal = goal_with_action(plans, vocabulary, category, top_goal)
        if goal and goal in seen:
            values.append(goal)
    values.append("done")
    return GoalControl(top=top_goal, values=uniq(values), calls=calls, visited=visited)


def BuildAgentSpec(role_key: str, plans: Sequence[Plan], control: GoalControl, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> AgentSpec:
    stages: Dict[str, str] = {}
    for stage in role_cfg.get("stages", []):
        key = str(stage["key"])
        category = str(stage["action_category"])
        goal = goal_with_action(plans, vocabulary, category, control.top)
        if goal is None:
            raise ValueError(f"No Jason goal found for stage {key!r} / action category {category!r}")
        stages[key] = goal
    patrol_goal = infer_patrol_goal(plans, control.top, role_cfg, vocabulary)
    return AgentSpec(
        role_key=role_key,
        plans=list(plans),
        control=control,
        stages=stages,
        patrol_goal=patrol_goal,
        patrol_order=infer_patrol_order(plans, patrol_goal, role_cfg, vocabulary),
    )


def location_token(location: str, location_cfg: Mapping[str, Any]) -> Dict[str, str]:
    pattern = str(location_cfg["token_regex"])
    match = re.fullmatch(pattern, location)
    if not match:
        raise ValueError(f"Location {location!r} does not match token_regex {pattern!r}")
    result = {"location": location}
    result.update({key: value for key, value in match.groupdict().items() if value is not None})
    for index, value in enumerate(match.groups(), start=1):
        result[str(index)] = value
    return result


def action_for_location(location: str, role_cfg: Mapping[str, Any], location_cfg: Mapping[str, Any]) -> str:
    values = location_token(location, location_cfg)
    template = str(role_cfg["actions"]["move_template"])
    return re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: values[m.group(1)], template)


def parse_locations(raw: str, model_cfg: Mapping[str, Any]) -> List[str]:
    variable = str(model_cfg["location"]["enum_var"])
    value_regex = str(model_cfg["location"]["value_regex"])
    match = re.search(rf"\b{re.escape(variable)}\s*:\s*\{{(?P<body>.*?)\}}\s*;", raw, re.S)
    if not match:
        raise ValueError(f"Location enum variable not found: {variable}")
    return uniq(re.findall(value_regex, match.group("body")))


def parse_base_vars(agent_raw: str) -> List[str]:
    match = re.search(r"\bVars:(?P<body>.*?)\bend Vars", agent_raw, re.S)
    if not match:
        return []
    out: List[str] = []
    for line in match.group("body").splitlines():
        item = line.strip()
        if item:
            out.append(item)
    return out


def parse_role_graph(raw: str, environment_name: str, locations: Sequence[str], role_cfg: Mapping[str, Any], location_cfg: Mapping[str, Any]) -> Dict[str, List[str]]:
    agent_name = str(role_cfg["ispl_agent"])
    location_var = str(role_cfg["location_var"])
    _, _, agent_raw = parse_ispl_block(raw, agent_name)
    protocol_match = re.search(r"\bProtocol:(.*?)\bend Protocol", agent_raw, re.S)
    body = protocol_match.group(1) if protocol_match else agent_raw
    rule_re = re.compile(r"(?P<condition>[^;]*?):\s*(?P<actions>\{.*?\})\s*;", re.S)
    graph: Dict[str, List[str]] = {location: [] for location in locations}
    move_regex = re.compile(str(role_cfg["actions"]["move_regex"]))
    destination_template = str(role_cfg["actions"]["move_destination_template"])
    for rule in rule_re.finditer(body):
        sources = re.findall(
            rf"{re.escape(environment_name)}\.{re.escape(location_var)}\s*=\s*({str(location_cfg['value_regex'])})",
            rule.group("condition"),
        )
        if not sources:
            continue
        source = sources[-1]
        if source not in graph:
            continue
        destinations: List[str] = []
        for match in move_regex.finditer(rule.group("actions")):
            values = {str(i): v for i, v in enumerate(match.groups(), start=1)}
            values.update({k: v for k, v in match.groupdict().items() if v is not None})
            destination = re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: values[m.group(1)], destination_template)
            if destination in graph:
                destinations.append(destination)
        graph[source] = uniq(graph[source] + destinations)
    return graph


def parse_location_classes(raw: str, locations: Sequence[str], model_cfg: Mapping[str, Any]) -> Dict[str, str]:
    cfg = model_cfg.get("location_classes", {})
    body = init_body(raw)
    out: Dict[str, str] = {}
    for location in locations:
        tokens = location_token(location, model_cfg["location"])
        selected: Optional[str] = None
        for rule in cfg.get("rules", []):
            declaration = str(rule.get("declaration_regex", ""))
            if declaration:
                pattern = re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: re.escape(tokens[m.group(1)]), declaration)
                if not re.search(pattern, raw):
                    continue
            state_pattern = str(rule.get("state_regex", ""))
            if state_pattern:
                pattern = re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: re.escape(tokens[m.group(1)]), state_pattern)
                match = re.search(pattern, body)
                if not match:
                    continue
                value = match.groupdict().get("value") or (match.group(1) if match.groups() else None)
                selected = {str(k): str(v) for k, v in rule.get("value_map", {}).items()}.get(str(value), str(value))
            else:
                selected = str(rule["class"])
            if selected is not None:
                break
        out[location] = selected if selected is not None else str(cfg.get("default", "default"))
    return out


def inspect_model(raw: str, mapping: Mapping[str, Any]) -> ModelInfo:
    model_cfg = mapping["model"]
    env = str(model_cfg.get("environment_agent", "Environment"))
    locations = parse_locations(raw, model_cfg)
    named: Dict[str, str] = {}
    for name, spec in model_cfg.get("named_locations", {}).items():
        named[str(name)] = init_value(raw, env, str(spec["initial_var"]), str(spec.get("value_pattern", model_cfg["location"]["value_regex"])))
    roles: Dict[str, RoleModel] = {}
    for role_key, role_cfg in mapping["jason"]["roles"].items():
        agent_name = str(role_cfg["ispl_agent"])
        _, _, agent_raw = parse_ispl_block(raw, agent_name)
        location_var = str(role_cfg["location_var"])
        roles[role_key] = RoleModel(
            role_key=role_key,
            agent_name=agent_name,
            location_var=location_var,
            start=init_value(raw, env, location_var, str(model_cfg["location"]["value_regex"])),
            graph=parse_role_graph(raw, env, locations, role_cfg, model_cfg["location"]),
            base_vars=parse_base_vars(agent_raw),
        )
    return ModelInfo(
        environment_name=env,
        locations=locations,
        named_locations=named,
        roles=roles,
        classes=parse_location_classes(raw, locations, model_cfg),
    )


def var_name(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping["model"]["variables"][key])


def env_ref(mapping: Mapping[str, Any], info: ModelInfo, key: str) -> str:
    return f"{info.environment_name}.{var_name(mapping, key)}"


def role_ref(mapping: Mapping[str, Any], info: ModelInfo, role_key: str) -> str:
    return info.roles[role_key].agent_name


def role_action_ref(mapping: Mapping[str, Any], info: ModelInfo, role_key: str) -> str:
    return f"{role_ref(mapping, info, role_key)}.Action"


def role_location_ref(mapping: Mapping[str, Any], info: ModelInfo, role_key: str, env_prefix: bool = True) -> str:
    name = info.roles[role_key].location_var
    return f"{info.environment_name}.{name}" if env_prefix else name


def action_name(mapping: Mapping[str, Any], role_key: str, key: str) -> str:
    return str(mapping["jason"]["roles"][role_key]["actions"][key])


def progress_condition(mapping: Mapping[str, Any], info: ModelInfo, values: Sequence[Any], env_prefix: bool = True) -> str:
    reference = env_ref(mapping, info, "progress") if env_prefix else var_name(mapping, "progress")
    return "(" + " or ".join(f"{reference} = {value}" for value in values) + ")"


def progress_positive(mapping: Mapping[str, Any], info: ModelInfo, env_prefix: bool = True) -> str:
    return progress_condition(mapping, info, mapping["model"]["progress"]["positive_values"], env_prefix)


def progress_continuing(mapping: Mapping[str, Any], info: ModelInfo) -> str:
    return progress_condition(mapping, info, mapping["model"]["progress"]["continuing_values"], True)


def coordination_roles(mapping: Mapping[str, Any]) -> Tuple[str, str]:
    cfg = mapping["coordination"]
    return str(cfg["operator_role"]), str(cfg["carrier_role"])


def coordination_var(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping["coordination"][key])


def terminal_guard(mapping: Mapping[str, Any], info: ModelInfo) -> str:
    _, carrier = coordination_roles(mapping)
    destination = info.named_locations[str(mapping["coordination"]["destination_name"])]
    surface = mapping["model"]["progress"]["surface_value"]
    delivered_alive = (
        f"{env_ref(mapping, info, 'alive')} = true and {env_ref(mapping, info, 'dead')} = false and "
        f"{env_ref(mapping, info, 'loaded')} = false and {env_ref(mapping, info, 'progress')} = {surface} and "
        f"{env_ref(mapping, info, 'target_location_state')} = {destination} and "
        f"{role_location_ref(mapping, info, carrier)} = {destination} and "
        f"{env_ref(mapping, info, 'destination_location_state')} = {destination}"
    )
    return f"({env_ref(mapping, info, 'dead')} = true or ({delivered_alive}))"


def finish_guard(mapping: Mapping[str, Any], info: ModelInfo) -> str:
    _, carrier = coordination_roles(mapping)
    cfg = mapping["coordination"]
    destination = info.named_locations[str(cfg["destination_name"])]
    return (
        f"{env_ref(mapping, info, 'loaded')} = true and {env_ref(mapping, info, 'alive')} = true and "
        f"{env_ref(mapping, info, 'dead')} = false and {env_ref(mapping, info, 'delivered')} = false and "
        f"{role_location_ref(mapping, info, carrier)} = {destination} and "
        f"{env_ref(mapping, info, 'destination_location_state')} = {destination} and "
        f"{role_action_ref(mapping, info, carrier)} = {action_name(mapping, carrier, str(cfg['carrier_finish_action_key']))}"
    )


def patrol_rank(location: str, info: ModelInfo, role_cfg: Mapping[str, Any], order: Sequence[str]) -> int:
    cls = info.classes.get(location, str(role_cfg.get("patrol", {}).get("default_class", "default")))
    candidates = role_cfg.get("patrol", {}).get("class_categories", {}).get(cls, [cls])
    for index, item in enumerate(order):
        if item in candidates:
            return index
    return 999


def patrol_protocol_lines(mapping: Mapping[str, Any], info: ModelInfo, spec: AgentSpec, known_var: str) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping["jason"]["roles"][role_key]
    goal_var = str(role_cfg["goal_var"])
    visited_template = str(role_cfg["visited_var_template"])
    alive = env_ref(mapping, info, "alive")
    location_ref = role_location_ref(mapping, info, role_key)
    out = ["        -- Patrol"]
    for current in info.locations:
        neighbours = info.roles[role_key].graph.get(current, [])
        for neighbour in neighbours:
            rank = patrol_rank(neighbour, info, role_cfg, spec.patrol_order)
            higher = [candidate for candidate in neighbours if patrol_rank(candidate, info, role_cfg, spec.patrol_order) < rank]
            parts = [
                f"{goal_var} = {spec.control.top}",
                f"{info.environment_name}.{known_var} = false",
                f"{alive} = true",
                f"{location_ref} = {current}",
            ]
            for candidate in higher:
                parts.append(f"{visited_template.replace('{location}', candidate)} = true")
            parts.append(f"{visited_template.replace('{location}', neighbour)} = false")
            move = action_for_location(neighbour, role_cfg, mapping["model"]["location"])
            out.append(f"        {' and '.join(parts)}:")
            out.append(f"            {{{move}}};")
        if neighbours:
            parts = [
                f"{goal_var} = {spec.control.top}",
                f"{info.environment_name}.{known_var} = false",
                f"{alive} = true",
                f"{location_ref} = {current}",
            ]
            for candidate in neighbours:
                parts.append(f"{visited_template.replace('{location}', candidate)} = true")
            moves = [action_for_location(candidate, role_cfg, mapping["model"]["location"]) for candidate in neighbours]
            out.append(f"        {' and '.join(parts)}:")
            out.append(f"            {action_set(moves, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out


def path_protocol_lines(mapping: Mapping[str, Any], info: ModelInfo, role_key: str, target: str, condition_builder, append_rest: bool = False) -> List[str]:
    role_cfg = mapping["jason"]["roles"][role_key]
    paths = shortest_steps(info.roles[role_key].graph, target)
    out: List[str] = []
    for location in info.locations:
        if location == target:
            continue
        choices = [action_for_location(dst, role_cfg, mapping["model"]["location"]) for dst in paths.get(location, [])]
        if not choices:
            choices = [action_for_location(dst, role_cfg, mapping["model"]["location"]) for dst in info.roles[role_key].graph.get(location, [])]
        if not choices:
            choices = [action_name(mapping, role_key, str(mapping["coordination"]["rest_action_key"]))]
        if append_rest:
            choices.append(action_name(mapping, role_key, str(mapping["coordination"]["rest_action_key"])))
        out.append(f"        {condition_builder(location)}:")
        out.append(f"            {action_set(choices, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out


def GenerateProtocol(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelInfo) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping["jason"]["roles"][role_key]
    kind = str(role_cfg["policy_kind"])
    cfg = mapping["coordination"]
    goal_var = str(role_cfg["goal_var"])
    top = spec.control.top
    rest = action_name(mapping, role_key, str(cfg["rest_action_key"]))
    target = info.named_locations[str(cfg["target_name"])]
    alive = env_ref(mapping, info, "alive")
    loaded = env_ref(mapping, info, "loaded")
    progress = env_ref(mapping, info, "progress")
    surface = mapping["model"]["progress"]["surface_value"]
    out = [f"        {terminal_guard(mapping, info)}: {{{rest}}};", f"        {goal_var} = done: {{{rest}}};"]

    if kind == "target_operator":
        known_var = coordination_var(mapping, "operator_knows_target_var")
        work_key = str(cfg["operator_work_action_key"])
        notify_key = str(cfg["operator_notify_action_key"])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = action_name(mapping, role_key, work_key)
        notify_action = action_name(mapping, role_key, notify_key)
        location_ref = role_location_ref(mapping, info, role_key)
        active = f"({goal_var} = {top} or {goal_var} = {work_stage})"
        out.append(f"        {goal_var} = {notify_stage}: {{{notify_action}}};")
        out.append(
            f"        {active} and {info.environment_name}.{known_var} = true and {alive} = true and "
            f"{progress_positive(mapping, info)} and {location_ref} = {target}: {{{work_action}}};"
        )
        out += path_protocol_lines(
            mapping,
            info,
            role_key,
            target,
            lambda location: (
                f"{active} and {info.environment_name}.{known_var} = true and {alive} = true and "
                f"{progress_positive(mapping, info)} and {location_ref} = {location}"
            ),
        )
        out += patrol_protocol_lines(mapping, info, spec, known_var)
        out.append(f"        Other: {{{rest}}};")
        return out

    if kind == "target_carrier":
        known_var = coordination_var(mapping, "carrier_knows_target_var")
        report_flag = coordination_var(mapping, "target_report_flag_var")
        ready_flag = coordination_var(mapping, "ready_report_flag_var")
        knows_destination = coordination_var(mapping, "carrier_knows_destination_var")
        operator, _ = coordination_roles(mapping)
        report_key = str(cfg["carrier_report_action_key"])
        acquire_key = str(cfg["carrier_acquire_action_key"])
        finish_key = str(cfg["carrier_finish_action_key"])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = action_name(mapping, role_key, report_key)
        acquire_action = action_name(mapping, role_key, acquire_key)
        finish_action = action_name(mapping, role_key, finish_key)
        location_ref = role_location_ref(mapping, info, role_key)
        operator_location = role_location_ref(mapping, info, operator)
        destination = info.named_locations[str(cfg["destination_name"])]
        out.append(f"        {goal_var} = {report_stage}: {{{report_action}}};")
        out.append(
            f"        {goal_var} = {acquire_stage} and {alive} = true and {loaded} = false and "
            f"{progress} = {surface} and {location_ref} = {target}: {{{acquire_action}}};"
        )
        out += path_protocol_lines(
            mapping,
            info,
            role_key,
            target,
            lambda location: (
                f"{goal_var} = {acquire_stage} and {alive} = true and {loaded} = false and "
                f"{progress} = {surface} and {location_ref} = {location}"
            ),
        )
        out.append(
            f"        {goal_var} = {finish_stage} and {loaded} = true and {alive} = true and "
            f"{location_ref} = {destination}: {{{finish_action}}};"
        )
        out += path_protocol_lines(
            mapping,
            info,
            role_key,
            destination,
            lambda location: (
                f"{goal_var} = {finish_stage} and {loaded} = true and {alive} = true and "
                f"{info.environment_name}.{knows_destination} = true and {location_ref} = {location}"
            ),
        )
        out.append(
            f"        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {alive} = true and "
            f"{progress_positive(mapping, info)} and {operator_location} = {target}: {{{rest}}};"
        )
        elsewhere = [location for location in info.locations if location != target]
        elsewhere_expr = "(" + " or ".join(f"{operator_location} = {location}" for location in elsewhere) + ")"
        out.append(
            f"        {goal_var} = {top} and {info.environment_name}.{known_var} = true and "
            f"{info.environment_name}.{report_flag} = false and {alive} = true and {progress_positive(mapping, info)} and "
            f"{elsewhere_expr}: {{{rest}}};"
        )
        out.append(
            f"        {goal_var} = {top} and {info.environment_name}.{known_var} = true and "
            f"{info.environment_name}.{report_flag} = true and {alive} = true and {progress_positive(mapping, info)} and "
            f"{location_ref} = {target}: {{{rest}}};"
        )
        out += path_protocol_lines(
            mapping,
            info,
            role_key,
            target,
            lambda location: (
                f"{goal_var} = {top} and {info.environment_name}.{known_var} = true and "
                f"{info.environment_name}.{report_flag} = true and {alive} = true and {progress_positive(mapping, info)} and "
                f"{location_ref} = {location}"
            ),
            append_rest=True,
        )
        out.append(
            f"        {goal_var} = {top} and {alive} = true and {loaded} = false and {progress} = {surface} and "
            f"({info.environment_name}.{ready_flag} = true or {location_ref} = {target}): {{{rest}}};"
        )
        out += patrol_protocol_lines(mapping, info, spec, known_var)
        out.append(f"        Other: {{{rest}}};")
        return out

    raise ValueError(f"Unsupported policy_kind: {kind}")


def visited_evolution_lines(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelInfo) -> List[str]:
    role_cfg = mapping["jason"]["roles"][spec.role_key]
    template = str(role_cfg["visited_var_template"])
    action_ref = role_action_ref(mapping, info, spec.role_key)
    out = ["        -- Visited"]
    for location in info.locations:
        visited = template.replace("{location}", location)
        move = action_for_location(location, role_cfg, mapping["model"]["location"])
        out.append(f"        {visited} = true if {visited} = true or {action_ref} = {move};")
    return out


def GenerateEvolutionRules(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelInfo) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping["jason"]["roles"][role_key]
    kind = str(role_cfg["policy_kind"])
    cfg = mapping["coordination"]
    goal_var = str(role_cfg["goal_var"])
    top = spec.control.top
    alive = env_ref(mapping, info, "alive")
    dead = env_ref(mapping, info, "dead")
    delivered = env_ref(mapping, info, "delivered")
    loaded = env_ref(mapping, info, "loaded")
    progress = env_ref(mapping, info, "progress")
    target = info.named_locations[str(cfg["target_name"])]
    surface = mapping["model"]["progress"]["surface_value"]
    final_active = mapping["model"]["progress"]["final_active_value"]
    action_ref = role_action_ref(mapping, info, role_key)
    out = ["        dummy = dummy if dummy = true;", "        dummy = dummy if dummy = false;"]

    if kind == "target_operator":
        known_var = coordination_var(mapping, "operator_knows_target_var")
        work_key = str(cfg["operator_work_action_key"])
        notify_key = str(cfg["operator_notify_action_key"])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = action_name(mapping, role_key, work_key)
        notify_action = action_name(mapping, role_key, notify_key)
        location_ref = role_location_ref(mapping, info, role_key)
        out.append(f"        {goal_var} = done if {dead} = true;")
        out.append(f"        {goal_var} = done if {finish_guard(mapping, info)};")
        out.append(
            f"        {goal_var} = {notify_stage} if ({goal_var} = {top} or {goal_var} = {work_stage}) and "
            f"{info.environment_name}.{known_var} = true and {alive} = true and {progress} = {final_active} and "
            f"{location_ref} = {target} and {action_ref} = {work_action};"
        )
        out.append(
            f"        {goal_var} = {top} if {goal_var} = {notify_stage} and {action_ref} = {notify_action} and "
            f"{dead} = false and {delivered} = false;"
        )
        out.append(
            f"        {goal_var} = {work_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and "
            f"{alive} = true and {progress_continuing(mapping, info)};"
        )
        out.append(
            f"        {goal_var} = {work_stage} if {goal_var} = {work_stage} and {info.environment_name}.{known_var} = true and "
            f"{alive} = true and {progress_continuing(mapping, info)};"
        )
        out += visited_evolution_lines(spec, mapping, info)
        return out

    if kind == "target_carrier":
        known_var = coordination_var(mapping, "carrier_knows_target_var")
        report_flag = coordination_var(mapping, "target_report_flag_var")
        ready_flag = coordination_var(mapping, "ready_report_flag_var")
        operator, _ = coordination_roles(mapping)
        report_key = str(cfg["carrier_report_action_key"])
        acquire_key = str(cfg["carrier_acquire_action_key"])
        finish_key = str(cfg["carrier_finish_action_key"])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = action_name(mapping, role_key, report_key)
        acquire_action = action_name(mapping, role_key, acquire_key)
        finish_action = action_name(mapping, role_key, finish_key)
        location_ref = role_location_ref(mapping, info, role_key)
        operator_location = role_location_ref(mapping, info, operator)
        operator_action_ref = role_action_ref(mapping, info, operator)
        operator_work = action_name(mapping, operator, str(cfg["operator_work_action_key"]))
        out.append(f"        {goal_var} = done if {dead} = true;")
        out.append(f"        {goal_var} = done if {goal_var} = {finish_stage} and {action_ref} = {finish_action};")
        out.append(f"        {goal_var} = {finish_stage} if {goal_var} = {acquire_stage} and {action_ref} = {acquire_action};")
        out.append(
            f"        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {loaded} = false and "
            f"{progress} = {final_active} and {location_ref} = {target} and {operator_location} = {target} and "
            f"{operator_action_ref} = {operator_work};"
        )
        out.append(
            f"        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {loaded} = false and "
            f"{progress} = {surface} and ({info.environment_name}.{ready_flag} = true or {location_ref} = {target});"
        )
        elsewhere = [location for location in info.locations if location != target]
        elsewhere_expr = "(" + " or ".join(f"{operator_location} = {location}" for location in elsewhere) + ")"
        out.append(
            f"        {goal_var} = {report_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and "
            f"{info.environment_name}.{report_flag} = false and {alive} = true and {progress_positive(mapping, info)} and {elsewhere_expr};"
        )
        out.append(f"        {goal_var} = {top} if {goal_var} = {report_stage} and {action_ref} = {report_action};")
        out += visited_evolution_lines(spec, mapping, info)
        return out

    raise ValueError(f"Unsupported policy_kind: {kind}")


def generate_agent_block(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelInfo) -> str:
    role_key = spec.role_key
    role_cfg = mapping["jason"]["roles"][role_key]
    role_info = info.roles[role_key]
    goal_var = str(role_cfg["goal_var"])
    visited_template = str(role_cfg["visited_var_template"])
    actions = [action_for_location(location, role_cfg, mapping["model"]["location"]) for location in info.locations]
    actions += [action_name(mapping, role_key, key) for key in role_cfg.get("action_order", [])]
    lines = [f"Agent {role_info.agent_name}", "    Vars:"]
    lines += [f"        {line}" for line in role_info.base_vars]
    lines.append(f"        {goal_var}: {{{', '.join(spec.control.values)}}};")
    for location in info.locations:
        lines.append(f"        {visited_template.replace('{location}', location)}: boolean;")
    lines += [
        "    end Vars",
        f"    Actions = {action_set(actions, int(mapping['format']['actions_indent']), int(mapping['format']['actions_per_line']))};",
        "    Protocol:",
    ]
    lines += GenerateProtocol(spec, mapping, info)
    lines += ["    end Protocol", "    Evolution:"]
    lines += GenerateEvolutionRules(spec, mapping, info)
    lines += ["    end Evolution", "end Agent"]
    return "\n".join(lines) + "\n"


def environment_memory_variables(mapping: Mapping[str, Any]) -> List[str]:
    cfg = mapping["coordination"]
    return [
        str(cfg["operator_knows_target_var"]),
        str(cfg["carrier_knows_target_var"]),
        str(cfg["target_report_flag_var"]),
        str(cfg["ready_report_flag_var"]),
        str(cfg["carrier_knows_destination_var"]),
    ]


def GenerateSharedEvolutionRules(mapping: Mapping[str, Any], info: ModelInfo) -> List[str]:
    cfg = mapping["coordination"]
    operator, carrier = coordination_roles(mapping)
    target = info.named_locations[str(cfg["target_name"])]
    destination = info.named_locations[str(cfg["destination_name"])]
    operator_known = str(cfg["operator_knows_target_var"])
    carrier_known = str(cfg["carrier_knows_target_var"])
    report_flag = str(cfg["target_report_flag_var"])
    ready_flag = str(cfg["ready_report_flag_var"])
    knows_destination = str(cfg["carrier_knows_destination_var"])
    operator_move = action_for_location(target, mapping["jason"]["roles"][operator], mapping["model"]["location"])
    carrier_move_target = action_for_location(target, mapping["jason"]["roles"][carrier], mapping["model"]["location"])
    carrier_move_destination = action_for_location(destination, mapping["jason"]["roles"][carrier], mapping["model"]["location"])
    carrier_report = action_name(mapping, carrier, str(cfg["carrier_report_action_key"]))
    operator_notify = action_name(mapping, operator, str(cfg["operator_notify_action_key"]))
    return [
        "        -- Beliefs",
        f"        {operator_known} = true if {operator_known} = true or ({var_name(mapping, 'alive')} = true and {progress_positive(mapping, info, False)} and "
        f"{var_name(mapping, 'target_location_state')} = {target} and ({info.roles[operator].location_var} = {target} or "
        f"{role_action_ref(mapping, info, operator)} = {operator_move})) or {report_flag} = true;",
        f"        {carrier_known} = true if {carrier_known} = true or ({var_name(mapping, 'alive')} = true and {progress_positive(mapping, info, False)} and "
        f"{var_name(mapping, 'target_location_state')} = {target} and ({info.roles[carrier].location_var} = {target} or "
        f"{role_action_ref(mapping, info, carrier)} = {carrier_move_target}));",
        f"        {report_flag} = true if {report_flag} = true or ({carrier_known} = true and {role_action_ref(mapping, info, carrier)} = {carrier_report});",
        f"        {ready_flag} = true if {ready_flag} = true or ({var_name(mapping, 'alive')} = true and "
        f"{var_name(mapping, 'progress')} = {mapping['model']['progress']['surface_value']} and {role_action_ref(mapping, info, operator)} = {operator_notify});",
        f"        {knows_destination} = true if {knows_destination} = true or {info.roles[carrier].location_var} = {destination} or "
        f"{role_action_ref(mapping, info, carrier)} = {carrier_move_destination};",
    ]


def patch_environment(raw: str, mapping: Mapping[str, Any], info: ModelInfo) -> str:
    env_start, env_end, env_block = parse_ispl_block(raw, info.environment_name)
    obs_match = re.search(r"\bObsvars:(?P<body>.*?)\bend Obsvars", env_block, re.S)
    if not obs_match:
        raise ValueError("Environment Obsvars block not found")
    cfg = mapping["coordination"]
    anchor_var = var_name(mapping, str(cfg["memory_declaration_after_var"]))
    variables = environment_memory_variables(mapping)
    declaration_text = "".join(f"        {name}: boolean;\n" for name in variables)
    if not all(re.search(rf"\b{re.escape(name)}\s*:\s*boolean\s*;", env_block) for name in variables):
        anchor = re.search(rf"(?m)^        {re.escape(anchor_var)}\s*:[^;]+;\s*$", env_block)
        if not anchor:
            raise ValueError(f"Environment declaration anchor variable not found: {anchor_var}")
        pos = anchor.end()
        env_block = env_block[:pos] + "\n" + declaration_text.rstrip("\n") + env_block[pos:]

    operator, carrier = coordination_roles(mapping)
    for role_key, extra_action_key in [
        (operator, str(cfg["operator_notify_action_key"])),
        (carrier, str(cfg["carrier_report_action_key"])),
    ]:
        location_var = info.roles[role_key].location_var
        rest = action_name(mapping, role_key, str(cfg["rest_action_key"]))
        extra = action_name(mapping, role_key, extra_action_key)
        action_ref = role_action_ref(mapping, info, role_key)
        extra_line = f"        {location_var} = {location_var} if {action_ref} = {extra};"
        if extra_line not in env_block:
            rest_line = f"        {location_var} = {location_var} if {action_ref} = {rest};"
            if rest_line not in env_block:
                raise ValueError(f"Could not find no-op movement anchor for {role_key}")
            env_block = env_block.replace(rest_line, extra_line + "\n" + rest_line, 1)

    shared = "\n".join(GenerateSharedEvolutionRules(mapping, info)) + "\n"
    if "        -- Beliefs\n" not in env_block:
        marker = str(cfg.get("environment_evolution_insert_before", ""))
        if marker and marker in env_block:
            env_block = env_block.replace(marker, shared + marker, 1)
        else:
            env_block = env_block.replace("    end Evolution", shared + "    end Evolution", 1)
    return raw[:env_start] + env_block + raw[env_end:]


def rewrite_init(raw: str, mapping: Mapping[str, Any], info: ModelInfo, specs: Mapping[str, AgentSpec]) -> str:
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

    cfg = mapping["coordination"]
    operator, carrier = coordination_roles(mapping)
    destination = info.named_locations[str(cfg["destination_name"])]
    additions = [
        f"{info.environment_name}.{cfg['operator_knows_target_var']} = false",
        f"{info.environment_name}.{cfg['carrier_knows_target_var']} = false",
        f"{info.environment_name}.{cfg['target_report_flag_var']} = false",
        f"{info.environment_name}.{cfg['ready_report_flag_var']} = false",
        f"{info.environment_name}.{cfg['carrier_knows_destination_var']} = {'true' if info.roles[carrier].start == destination else 'false'}",
    ]
    for role_key in mapping["jason"]["roles"]:
        role_cfg = mapping["jason"]["roles"][role_key]
        spec = specs[role_key]
        additions.append(f"{info.roles[role_key].agent_name}.{role_cfg['goal_var']} = {spec.control.top}")
        template = str(role_cfg["visited_var_template"])
        for location in info.locations:
            additions.append(
                f"{info.roles[role_key].agent_name}.{template.replace('{location}', location)} = "
                f"{'true' if location == info.roles[role_key].start else 'false'}"
            )

    first_agent = next(iter(mapping["jason"]["roles"]))
    prefix = info.roles[first_agent].agent_name + "."
    output: List[str] = []
    inserted = False
    for item in assignments:
        if item.startswith(prefix) and not inserted:
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


def ReplaceAgentDecisionModel(raw: str, agent_blocks: Mapping[str, str]) -> str:
    out = raw
    for agent_name, block in agent_blocks.items():
        out = replace_ispl_agent(out, agent_name, block)
    return out


def resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def load_mapping(config_path: Path) -> Dict[str, Any]:
    return json.loads(read_text(config_path))


def translate(
    config_path: Path,
    raw_override: Optional[Path] = None,
    output_override: Optional[Path] = None,
    program_overrides: Optional[Mapping[str, Path]] = None,
) -> Tuple[Path, Dict[str, AgentSpec]]:
    mapping = load_mapping(config_path)
    files = mapping["files"]
    raw_path = raw_override or resolve_path(config_path, str(files["raw"]))
    output_path = output_override or resolve_path(config_path, str(files["output"]))
    raw = read_text(raw_path)
    vocabulary = mapping["jason"]["vocabulary"]
    overrides = dict(program_overrides or {})
    specs: Dict[str, AgentSpec] = {}

    for role_key, role_cfg in mapping["jason"]["roles"].items():
        program_path = overrides.get(role_key) or resolve_path(config_path, str(role_cfg["program"]))
        plans, top = read_plans(read_text(program_path), str(role_cfg["entry_goal"]))
        control = BuildGoalControl(plans, top, role_cfg, vocabulary)
        specs[role_key] = BuildAgentSpec(role_key, plans, control, role_cfg, vocabulary)

    info = inspect_model(raw, mapping)
    raw = patch_environment(raw, mapping, info)
    raw = rewrite_init(raw, mapping, info, specs)
    blocks = {
        info.roles[role_key].agent_name: generate_agent_block(spec, mapping, info)
        for role_key, spec in specs.items()
    }
    raw = ReplaceAgentDecisionModel(raw, blocks)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(raw, encoding="utf-8")
    return output_path, specs


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Jason-guided ISPL model from Jason programs, a baseline ISPL model, and a semantic mapping.")
    parser.add_argument("--config", required=True, help="semantic translation mapping JSON")
    parser.add_argument("--raw", help="optional baseline ISPL override")
    parser.add_argument("--program", action="append", default=[], metavar="ROLE=PATH", help="optional Jason program override")
    parser.add_argument("--output", help="optional output ISPL override")
    args = parser.parse_args()

    overrides: Dict[str, Path] = {}
    for item in args.program:
        if "=" not in item:
            parser.error("--program must use ROLE=PATH")
        role, value = item.split("=", 1)
        overrides[role.strip()] = Path(value.strip()).resolve()

    output_path, specs = translate(
        Path(args.config).resolve(),
        Path(args.raw).resolve() if args.raw else None,
        Path(args.output).resolve() if args.output else None,
        overrides,
    )
    print(f"Wrote ISPL: {output_path}")
    for role_key, spec in specs.items():
        print(f"{role_key} top: {spec.control.top}")
        print(f"{role_key} control: {', '.join(spec.control.values)}")
        print(f"{role_key} patrol priority: {', '.join(spec.patrol_order)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
