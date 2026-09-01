import argparse
import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')
def clean_name(name: str) -> str:
    value = re.sub('[^A-Za-z0-9_]+', '_', name.strip())
    if re.match('^\\d', value):
        value = '_' + value
    return value

def uniq(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(values))
def action_set(values: Sequence[str], indent_spaces: int=16, per_line: int=4) -> str:
    vals = uniq((v for v in values if v))
    chunks = [', '.join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    if len(chunks) == 1:
        return '{' + chunks[0] + '}'
    pad = ' ' * indent_spaces
    return '{\n' + ',\n'.join((pad + chunk for chunk in chunks)) + '\n' + ' ' * (indent_spaces - 4) + '}'
def split_top(text: str, sep: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    quote = False
    for ch in text:
        if ch == '"':
            quote = not quote
        elif not quote and ch == '(':
            depth += 1
        elif not quote and ch == ')':
            depth -= 1
        if not quote and depth == 0 and (ch == sep):
            item = ''.join(cur).strip()
            if item:
                out.append(item)
            cur = []
        else:
            cur.append(ch)
    item = ''.join(cur).strip()
    if item:
        out.append(item)
    return out

def parse_ispl_block(raw: str, agent_name: str) -> Tuple[int, int, str]:
    pattern = re.compile(f'(?ms)^Agent[ \\t]+{re.escape(agent_name)}[ \\t]*$.*?^end[ \\t]+Agent[ \\t]*$')
    match = pattern.search(raw)
    if not match:
        raise ValueError(f'Agent block not found: {agent_name}')
    return (match.start(), match.end(), match.group(0))
def replace_ispl_agent(raw: str, agent_name: str, new_block: str) -> str:
    start, end, _ = parse_ispl_block(raw, agent_name)
    return raw[:start] + new_block.rstrip() + '\n' + raw[end:]
def init_body(raw: str) -> str:
    match = re.search('InitStates(?P<body>.*?)end InitStates', raw, re.S)
    if not match:
        raise ValueError('InitStates block not found')
    return match.group('body')

def init_value(raw: str, environment_name: str, variable: str, value_pattern: str='[A-Za-z0-9_]+') -> str:
    body = init_body(raw)
    match = re.search(f'{re.escape(environment_name)}\\.{re.escape(variable)}\\s*=\\s*(?P<value>{value_pattern})', body)
    if not match:
        raise ValueError(f'Initial value not found for {environment_name}.{variable}')
    return match.group('value')
def relation_steps(relation: Mapping[str, Sequence[str]], focus: str) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {member: [] for member in relation}
    distances: Dict[str, int] = {focus: 0}
    reverse: Dict[str, List[str]] = {member: [] for member in relation}
    for src, neighbours in relation.items():
        for dst in neighbours:
            reverse.setdefault(dst, []).append(src)
    queue: deque[str] = deque([focus])
    while queue:
        member = queue.popleft()
        for predecessor in reverse.get(member, []):
            if predecessor not in distances:
                distances[predecessor] = distances[member] + 1
                queue.append(predecessor)
    for src, neighbours in relation.items():
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
    reachable: List[str]

@dataclass
class AgentSpec:
    role_key: str
    plans: List[Plan]
    control: GoalControl
    stages: Dict[str, str]
    ranking_goal: str
    ranking_order: List[str]
@dataclass
class RoleContext:
    role_key: str
    agent_name: str
    state_var: str
    start: str
    relation: Dict[str, List[str]]
    base_vars: List[str]
@dataclass
class ModelContext:
    environment_name: str
    members: List[str]
    anchors: Dict[str, str]
    roles: Dict[str, RoleContext]
    labels: Dict[str, str]

def parse_term(raw: str) -> Optional[Term]:
    item = raw.strip()
    if not item:
        return None
    op = item[0] if item[0] in '+-!?' else ''
    body = item[1:].strip() if op else item
    if body.startswith('not '):
        body = body[4:].strip()
    match = re.match('([A-Za-z_][A-Za-z0-9_]*)\\s*(?:\\((.*)\\))?$', body)
    if not match:
        return None
    args = [] if match.group(2) is None else [part.strip() for part in split_top(match.group(2), ',')]
    return Term(op=op, name=clean_name(match.group(1)), args=args, raw=item)
def parse_body_terms(body: str) -> List[Term]:
    out: List[Term] = []
    for piece in split_top(body, ';'):
        term = parse_term(piece)
        if term:
            out.append(term)
    return out
def strip_asl_comments(text: str) -> str:
    return '\n'.join((line.split('//', 1)[0] for line in text.splitlines()))

def read_plans(asl_text: str, entry_goal: str) -> Tuple[List[Plan], str]:
    text = strip_asl_comments(asl_text)
    blobs: List[str] = []
    current: List[str] = []
    active = False
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        if re.match('\\+!', item):
            active = True
            current = [item]
        elif active:
            current.append(item)
        if active and item.endswith('.'):
            blobs.append(' '.join(current).rstrip('.'))
            active = False
    plans: List[Plan] = []
    top: Optional[str] = None
    entry_clean = clean_name(entry_goal)
    for index, blob in enumerate(blobs):
        match = re.match('\\+!(?P<goal>[A-Za-z_][A-Za-z0-9_]*)(?:\\([^)]*\\))?\\s*:\\s*(?P<context>.*?)\\s*<-\\s*(?P<body>.*)$', blob)
        if not match:
            continue
        goal = clean_name(match.group('goal'))
        context = match.group('context').strip()
        body = match.group('body').strip()
        terms = parse_body_terms(body)
        plans.append(Plan(goal=goal, context=context, body=body, terms=terms, index=index))
        if goal == entry_clean:
            for term in terms:
                if term.op == '!':
                    top = clean_name(term.name)
                    break
    if top is None:
        entry_match = re.search(f'(?ms)^\\s*\\+!?{re.escape(entry_goal)}(?:\\([^)]*\\))?\\s*:\\s*.*?\\s*<-\\s*(?P<body>.*?)\\.\\s*$', text)
        if entry_match:
            for term in parse_body_terms(entry_match.group('body')):
                if term.op == '!':
                    top = clean_name(term.name)
                    break
    if top is None:
        raise ValueError(f'Could not derive top goal from configured entry goal {entry_goal!r}')
    return (plans, top)
def name_in_list(name: str, values: Sequence[str]) -> bool:
    focus = clean_name(name)
    return focus in {clean_name(value) for value in values}
def action_category(term: Term, vocabulary: Mapping[str, Any]) -> Optional[str]:
    for category, names in vocabulary.get('actions', {}).items():
        if name_in_list(term.name, names):
            return str(category)
    return None

def context_has(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get('predicates', {}).get(category, []):
        if re.search(f'\\b{re.escape(str(predicate))}\\s*\\(', context) or re.search(f'\\b{re.escape(str(predicate))}\\b', context):
            return True
    return False
def context_has_negative(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get('predicates', {}).get(category, []):
        if re.search(f'\\bnot\\s+{re.escape(str(predicate))}(?:\\s*\\(|\\b)', context):
            return True
    return False
def goal_with_action(plans: Sequence[Plan], vocabulary: Mapping[str, Any], category: str, top: str) -> Optional[str]:
    hits: List[str] = []
    for plan in plans:
        if any((action_category(term, vocabulary) == category for term in plan.terms)):
            hits.append(plan.goal)
    for goal in hits:
        if goal != top:
            return goal
    return hits[0] if hits else None

def infer_ranking_goal(plans: Sequence[Plan], top: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> str:
    configured = role_cfg.get('ranking', {}).get('goal')
    if configured and configured != 'auto':
        return clean_name(str(configured))
    categories = role_cfg.get('ranking', {}).get('signal_categories', [])
    scores: Dict[str, int] = {}
    for plan in plans:
        if plan.goal in (clean_name(str(role_cfg.get('entry_goal', ''))), top):
            continue
        score = sum((1 for category in categories if context_has(plan.context, str(category), vocabulary)))
        if score:
            scores[plan.goal] = scores.get(plan.goal, 0) + score
    if scores:
        return max(scores, key=scores.get)
    fallback = role_cfg.get('ranking', {}).get('fallback_goal')
    if fallback:
        return clean_name(str(fallback))
    raise ValueError('Could not infer ranking goal')
def infer_ranking_order(plans: Sequence[Plan], ranking_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> List[str]:
    order: List[str] = []
    classifiers = role_cfg.get('ranking', {}).get('classifiers', [])
    for plan in plans:
        if plan.goal != ranking_goal:
            continue
        context = plan.context
        for classifier in classifiers:
            if classifier.get('context_equals') is not None:
                if context.strip() == str(classifier['context_equals']):
                    order.append(str(classifier['name']))
                    break
                continue
            required = [str(x) for x in classifier.get('all', [])]
            negative = [str(x) for x in classifier.get('negative', [])]
            if all((context_has(context, category, vocabulary) for category in required)) and all((context_has_negative(context, category, vocabulary) for category in negative)):
                order.append(str(classifier['name']))
                break
    return uniq(order or [str(x) for x in role_cfg.get('ranking', {}).get('fallback_order', [])])
def BuildGoalControl(plans: Sequence[Plan], top_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> GoalControl:
    plans_by_goal: Dict[str, List[Plan]] = {}
    for plan in plans:
        plans_by_goal.setdefault(plan.goal, []).append(plan)
    calls: List[GoalCall] = []
    reachable: List[str] = []
    seen: Set[str] = set()

    def visit(goal: str) -> None:
        if goal in seen:
            return
        seen.add(goal)
        reachable.append(goal)
        for plan in plans_by_goal.get(goal, []):
            for term in plan.terms:
                if term.op != '!':
                    continue
                child = clean_name(term.name)
                calls.append(GoalCall(goal, child, plan.index))
                visit(child)
    visit(top_goal)
    values = [top_goal]
    for stage in role_cfg.get('stages', []):
        category = str(stage['action_category'])
        goal = goal_with_action(plans, vocabulary, category, top_goal)
        if goal and goal in seen:
            values.append(goal)
    plan_cfg = role_cfg.get('plan')
    if plan_cfg is not None:
        mapped = {clean_name(str(name)) for name in plan_cfg.get('actions', {})}
        for goal in reachable:
            if goal != top_goal and any((plan.goal == goal and any((clean_name(term.name) in mapped for term in plan.terms)) for plan in plans)):
                values.append(goal)
    values.append('done')
    return GoalControl(top=top_goal, values=uniq(values), calls=calls, reachable=reachable)
def BuildAgentSpec(role_key: str, plans: Sequence[Plan], control: GoalControl, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> AgentSpec:
    stages: Dict[str, str] = {}
    for stage in role_cfg.get('stages', []):
        key = str(stage['key'])
        category = str(stage['action_category'])
        goal = goal_with_action(plans, vocabulary, category, control.top)
        if goal is None:
            raise ValueError(f'No Jason goal found for stage {key!r} / action category {category!r}')
        stages[key] = goal
    if role_cfg.get('ranking'):
        ranking_goal = infer_ranking_goal(plans, control.top, role_cfg, vocabulary)
        ranking_order = infer_ranking_order(plans, ranking_goal, role_cfg, vocabulary)
    else:
        ranking_goal = ''
        ranking_order = []
    return AgentSpec(role_key=role_key, plans=list(plans), control=control, stages=stages, ranking_goal=ranking_goal, ranking_order=ranking_order)
def member_token(member: str, domain_cfg: Mapping[str, Any]) -> Dict[str, str]:
    pattern = str(domain_cfg['token_regex'])
    match = re.fullmatch(pattern, member)
    if not match:
        raise ValueError(f'Member {member!r} does not match token_regex {pattern!r}')
    result = {'member': member}
    result.update({key: value for key, value in match.groupdict().items() if value is not None})
    for index, value in enumerate(match.groups(), start=1):
        result[str(index)] = value
    return result

def action_for_member(member: str, role_cfg: Mapping[str, Any], domain_cfg: Mapping[str, Any]) -> str:
    values = member_token(member, domain_cfg)
    template = str(role_cfg['actions']['move_template'])
    return re.sub('\\{([A-Za-z0-9_]+)\\}', lambda m: values[m.group(1)], template)
def parse_members(raw: str, model_cfg: Mapping[str, Any]) -> List[str]:
    variable = str(model_cfg['domain']['enum_var'])
    value_regex = str(model_cfg['domain']['value_regex'])
    match = re.search(f'\\b{re.escape(variable)}\\s*:\\s*\\{{(?P<body>.*?)\\}}\\s*;', raw, re.S)
    if not match:
        raise ValueError(f'Domain enum variable not found: {variable}')
    return uniq(re.findall(value_regex, match.group('body')))
def parse_base_vars(agent_raw: str) -> List[str]:
    match = re.search('\\bVars:(?P<body>.*?)\\bend Vars', agent_raw, re.S)
    if not match:
        return []
    out: List[str] = []
    for line in match.group('body').splitlines():
        item = line.strip()
        if item:
            out.append(item)
    return out

def parse_relation(raw: str, environment_name: str, members: Sequence[str], role_cfg: Mapping[str, Any], domain_cfg: Mapping[str, Any]) -> Dict[str, List[str]]:
    agent_name = str(role_cfg['ispl_agent'])
    state_var = str(role_cfg['state_var'])
    _, _, agent_raw = parse_ispl_block(raw, agent_name)
    protocol_match = re.search('\\bProtocol:(.*?)\\bend Protocol', agent_raw, re.S)
    body = protocol_match.group(1) if protocol_match else agent_raw
    rule_re = re.compile('(?P<condition>[^;]*?):\\s*(?P<actions>\\{.*?\\})\\s*;', re.S)
    relation: Dict[str, List[str]] = {member: [] for member in members}
    move_regex = re.compile(str(role_cfg['actions']['move_regex']))
    endpoint_template = str(role_cfg['actions']['move_endpoint_template'])
    for rule in rule_re.finditer(body):
        sources = re.findall(f"{re.escape(environment_name)}\\.{re.escape(state_var)}\\s*=\\s*({str(domain_cfg['value_regex'])})", rule.group('condition'))
        if not sources:
            continue
        source = sources[-1]
        if source not in relation:
            continue
        endpoints: List[str] = []
        for match in move_regex.finditer(rule.group('actions')):
            values = {str(i): v for i, v in enumerate(match.groups(), start=1)}
            values.update({k: v for k, v in match.groupdict().items() if v is not None})
            endpoint = re.sub('\\{([A-Za-z0-9_]+)\\}', lambda m: values[m.group(1)], endpoint_template)
            if endpoint in relation:
                endpoints.append(endpoint)
        relation[source] = uniq(relation[source] + endpoints)
    return relation
def parse_member_labels(raw: str, members: Sequence[str], model_cfg: Mapping[str, Any]) -> Dict[str, str]:
    cfg = model_cfg.get('member_labels', {})
    body = init_body(raw)
    out: Dict[str, str] = {}
    for member in members:
        tokens = member_token(member, model_cfg['domain'])
        selected: Optional[str] = None
        for rule in cfg.get('rules', []):
            declaration = str(rule.get('declaration_regex', ''))
            if declaration:
                pattern = re.sub('\\{([A-Za-z0-9_]+)\\}', lambda m: re.escape(tokens[m.group(1)]), declaration)
                if not re.search(pattern, raw):
                    continue
            state_pattern = str(rule.get('state_regex', ''))
            if state_pattern:
                pattern = re.sub('\\{([A-Za-z0-9_]+)\\}', lambda m: re.escape(tokens[m.group(1)]), state_pattern)
                match = re.search(pattern, body)
                if not match:
                    continue
                value = match.groupdict().get('value') or (match.group(1) if match.groups() else None)
                selected = {str(k): str(v) for k, v in rule.get('value_map', {}).items()}.get(str(value), str(value))
            else:
                selected = str(rule['class'])
            if selected is not None:
                break
        out[member] = selected if selected is not None else str(cfg.get('default', 'default'))
    return out
def inspect_model(raw: str, mapping: Mapping[str, Any]) -> ModelContext:
    model_cfg = mapping['model']
    env = str(model_cfg.get('environment_agent', 'Environment'))
    members = parse_members(raw, model_cfg)
    named: Dict[str, str] = {}
    for name, spec in model_cfg.get('anchors', {}).items():
        if 'value' in spec:
            named[str(name)] = str(spec['value'])
        else:
            named[str(name)] = init_value(raw, env, str(spec['initial_var']), str(spec.get('value_pattern', model_cfg['domain']['value_regex'])))
    roles: Dict[str, RoleContext] = {}
    for role_key, role_cfg in mapping['jason']['roles'].items():
        agent_name = str(role_cfg['ispl_agent'])
        _, _, agent_raw = parse_ispl_block(raw, agent_name)
        state_var = str(role_cfg['state_var'])
        roles[role_key] = RoleContext(role_key=role_key, agent_name=agent_name, state_var=state_var, start=init_value(raw, env, state_var, str(model_cfg['domain']['value_regex'])), relation=parse_relation(raw, env, members, role_cfg, model_cfg['domain']), base_vars=parse_base_vars(agent_raw))
    return ModelContext(environment_name=env, members=members, anchors=named, roles=roles, labels=parse_member_labels(raw, members, model_cfg))

def var_name(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping['model']['variables'][key])
def env_ref(mapping: Mapping[str, Any], info: ModelContext, key: str) -> str:
    return f'{info.environment_name}.{var_name(mapping, key)}'
def role_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str) -> str:
    return info.roles[role_key].agent_name

def role_action_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str) -> str:
    return f'{role_ref(mapping, info, role_key)}.Action'
def role_state_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str, env_prefix: bool=True) -> str:
    name = info.roles[role_key].state_var
    return f'{info.environment_name}.{name}' if env_prefix else name
def action_name(mapping: Mapping[str, Any], role_key: str, key: str) -> str:
    return str(mapping['jason']['roles'][role_key]['actions'][key])

def level_condition(mapping: Mapping[str, Any], info: ModelContext, values: Sequence[Any], env_prefix: bool=True) -> str:
    reference = env_ref(mapping, info, 'level') if env_prefix else var_name(mapping, 'level')
    return '(' + ' or '.join((f'{reference} = {value}' for value in values)) + ')'
def level_positive(mapping: Mapping[str, Any], info: ModelContext, env_prefix: bool=True) -> str:
    return level_condition(mapping, info, mapping['model']['level']['positive_values'], env_prefix)
def level_continuing(mapping: Mapping[str, Any], info: ModelContext) -> str:
    return level_condition(mapping, info, mapping['model']['level']['continuing_values'], True)

def coordinated_roles(mapping: Mapping[str, Any]) -> Tuple[str, str]:
    cfg = mapping['coordination']
    return (str(cfg['primary_role']), str(cfg['secondary_role']))
def coord_var(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping['coordination'][key])
def final_guard(mapping: Mapping[str, Any], info: ModelContext) -> str:
    _, secondary = coordinated_roles(mapping)
    endpoint = info.anchors[str(mapping['coordination']['endpoint_name'])]
    zero = mapping['model']['level']['zero_value']
    complete_alive = f"{env_ref(mapping, info, 'active')} = true and {env_ref(mapping, info, 'failed')} = false and {env_ref(mapping, info, 'holding')} = false and {env_ref(mapping, info, 'level')} = {zero} and {env_ref(mapping, info, 'focus_state')} = {endpoint} and {role_state_ref(mapping, info, secondary)} = {endpoint} and {env_ref(mapping, info, 'endpoint_state')} = {endpoint}"
    return f"({env_ref(mapping, info, 'failed')} = true or ({complete_alive}))"

def completion_guard(mapping: Mapping[str, Any], info: ModelContext) -> str:
    _, secondary = coordinated_roles(mapping)
    cfg = mapping['coordination']
    endpoint = info.anchors[str(cfg['endpoint_name'])]
    return f"{env_ref(mapping, info, 'holding')} = true and {env_ref(mapping, info, 'active')} = true and {env_ref(mapping, info, 'failed')} = false and {env_ref(mapping, info, 'complete')} = false and {role_state_ref(mapping, info, secondary)} = {endpoint} and {env_ref(mapping, info, 'endpoint_state')} = {endpoint} and {role_action_ref(mapping, info, secondary)} = {action_name(mapping, secondary, str(cfg['secondary_finish_action_key']))}"
def ranking_rank(member: str, info: ModelContext, role_cfg: Mapping[str, Any], order: Sequence[str]) -> int:
    cls = info.labels.get(member, str(role_cfg.get('ranking', {}).get('default_class', 'default')))
    candidates = role_cfg.get('ranking', {}).get('class_categories', {}).get(cls, [cls])
    for index, item in enumerate(order):
        if item in candidates:
            return index
    return 999
def ranking_protocol_lines(mapping: Mapping[str, Any], info: ModelContext, spec: AgentSpec, known_var: str) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    goal_var = str(role_cfg['goal_var'])
    marker_template = str(role_cfg['marker_var_template'])
    alive = env_ref(mapping, info, 'active')
    state_ref = role_state_ref(mapping, info, role_key)
    out = [f"        -- {role_cfg.get('ranking', {}).get('label', 'Ranking')}"]
    for current in info.members:
        neighbours = info.roles[role_key].relation.get(current, [])
        for neighbour in neighbours:
            rank = ranking_rank(neighbour, info, role_cfg, spec.ranking_order)
            higher = [candidate for candidate in neighbours if ranking_rank(candidate, info, role_cfg, spec.ranking_order) < rank]
            parts = [f'{goal_var} = {spec.control.top}', f'{info.environment_name}.{known_var} = false', f'{alive} = true', f'{state_ref} = {current}']
            for candidate in higher:
                parts.append(f"{marker_template.replace('{member}', candidate)} = true")
            parts.append(f"{marker_template.replace('{member}', neighbour)} = false")
            move = action_for_member(neighbour, role_cfg, mapping['model']['domain'])
            out.append(f"        {' and '.join(parts)}:")
            out.append(f'            {{{move}}};')
        if neighbours:
            parts = [f'{goal_var} = {spec.control.top}', f'{info.environment_name}.{known_var} = false', f'{alive} = true', f'{state_ref} = {current}']
            for candidate in neighbours:
                parts.append(f"{marker_template.replace('{member}', candidate)} = true")
            moves = [action_for_member(candidate, role_cfg, mapping['model']['domain']) for candidate in neighbours]
            out.append(f"        {' and '.join(parts)}:")
            out.append(f"            {action_set(moves, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out

def path_protocol_lines(mapping: Mapping[str, Any], info: ModelContext, role_key: str, focus: str, condition_builder, append_rest: bool=False) -> List[str]:
    role_cfg = mapping['jason']['roles'][role_key]
    paths = relation_steps(info.roles[role_key].relation, focus)
    out: List[str] = []
    for member in info.members:
        if member == focus:
            continue
        choices = [action_for_member(dst, role_cfg, mapping['model']['domain']) for dst in paths.get(member, [])]
        if not choices:
            choices = [action_for_member(dst, role_cfg, mapping['model']['domain']) for dst in info.roles[role_key].relation.get(member, [])]
        if not choices:
            choices = [action_name(mapping, role_key, str(mapping['coordination']['idle_action_key']))]
        if append_rest:
            choices.append(action_name(mapping, role_key, str(mapping['coordination']['idle_action_key'])))
        out.append(f'        {condition_builder(member)}:')
        out.append(f"            {action_set(choices, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out
def _relation_protocol(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    primary_role, secondary_role = coordinated_roles(mapping)
    cfg = mapping['coordination']
    goal_var = str(role_cfg['goal_var'])
    top = spec.control.top
    rest = action_name(mapping, role_key, str(cfg['idle_action_key']))
    focus = info.anchors[str(cfg['focus_name'])]
    alive = env_ref(mapping, info, 'active')
    holding = env_ref(mapping, info, 'holding')
    level = env_ref(mapping, info, 'level')
    zero = mapping['model']['level']['zero_value']
    out = [f'        {final_guard(mapping, info)}: {{{rest}}};', f'        {goal_var} = done: {{{rest}}};']
    if role_key == primary_role:
        known_var = coord_var(mapping, 'primary_knows_focus_var')
        work_key = str(cfg['primary_action_key'])
        notify_key = str(cfg['primary_signal_action_key'])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = action_name(mapping, role_key, work_key)
        notify_action = action_name(mapping, role_key, notify_key)
        state_ref = role_state_ref(mapping, info, role_key)
        active = f'({goal_var} = {top} or {goal_var} = {work_stage})'
        out.append(f'        {goal_var} = {notify_stage}: {{{notify_action}}};')
        out.append(f'        {active} and {info.environment_name}.{known_var} = true and {alive} = true and {level_positive(mapping, info)} and {state_ref} = {focus}: {{{work_action}}};')
        out += path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{active} and {info.environment_name}.{known_var} = true and {alive} = true and {level_positive(mapping, info)} and {state_ref} = {member}')
        out += ranking_protocol_lines(mapping, info, spec, known_var)
        out.append(f'        Other: {{{rest}}};')
        return out
    if role_key == secondary_role:
        known_var = coord_var(mapping, 'secondary_knows_focus_var')
        report_flag = coord_var(mapping, 'focus_report_flag_var')
        ready_flag = coord_var(mapping, 'ready_flag_var')
        knows_endpoint = coord_var(mapping, 'secondary_knows_endpoint_var')
        primary, _ = coordinated_roles(mapping)
        report_key = str(cfg['secondary_signal_action_key'])
        acquire_key = str(cfg['secondary_take_action_key'])
        finish_key = str(cfg['secondary_finish_action_key'])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = action_name(mapping, role_key, report_key)
        acquire_action = action_name(mapping, role_key, acquire_key)
        finish_action = action_name(mapping, role_key, finish_key)
        state_ref = role_state_ref(mapping, info, role_key)
        primary_state = role_state_ref(mapping, info, primary)
        endpoint = info.anchors[str(cfg['endpoint_name'])]
        out.append(f'        {goal_var} = {report_stage}: {{{report_action}}};')
        out.append(f'        {goal_var} = {acquire_stage} and {alive} = true and {holding} = false and {level} = {zero} and {state_ref} = {focus}: {{{acquire_action}}};')
        out += path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{goal_var} = {acquire_stage} and {alive} = true and {holding} = false and {level} = {zero} and {state_ref} = {member}')
        out.append(f'        {goal_var} = {finish_stage} and {holding} = true and {alive} = true and {state_ref} = {endpoint}: {{{finish_action}}};')
        out += path_protocol_lines(mapping, info, role_key, endpoint, lambda member: f'{goal_var} = {finish_stage} and {holding} = true and {alive} = true and {info.environment_name}.{knows_endpoint} = true and {state_ref} = {member}')
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {alive} = true and {level_positive(mapping, info)} and {primary_state} = {focus}: {{{rest}}};')
        elsewhere = [member for member in info.members if member != focus]
        elsewhere_expr = '(' + ' or '.join((f'{primary_state} = {member}' for member in elsewhere)) + ')'
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = false and {alive} = true and {level_positive(mapping, info)} and {elsewhere_expr}: {{{rest}}};')
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = true and {alive} = true and {level_positive(mapping, info)} and {state_ref} = {focus}: {{{rest}}};')
        out += path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = true and {alive} = true and {level_positive(mapping, info)} and {state_ref} = {member}', append_rest=True)
        out.append(f'        {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {zero} and ({info.environment_name}.{ready_flag} = true or {state_ref} = {focus}): {{{rest}}};')
        out += ranking_protocol_lines(mapping, info, spec, known_var)
        out.append(f'        Other: {{{rest}}};')
        return out
    raise ValueError(f'Role {role_key!r} is not part of the configured coordinated relation')
def marker_evolution_lines(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_cfg = mapping['jason']['roles'][spec.role_key]
    template = str(role_cfg['marker_var_template'])
    action_ref = role_action_ref(mapping, info, spec.role_key)
    out = [f"        -- {role_cfg.get('marker_label', 'Memory')}"]
    for member in info.members:
        reachable = template.replace('{member}', member)
        move = action_for_member(member, role_cfg, mapping['model']['domain'])
        out.append(f'        {reachable} = true if {reachable} = true or {action_ref} = {move};')
    return out

def _relation_evolution(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    primary_role, secondary_role = coordinated_roles(mapping)
    cfg = mapping['coordination']
    goal_var = str(role_cfg['goal_var'])
    top = spec.control.top
    alive = env_ref(mapping, info, 'active')
    dead = env_ref(mapping, info, 'failed')
    complete = env_ref(mapping, info, 'complete')
    holding = env_ref(mapping, info, 'holding')
    level = env_ref(mapping, info, 'level')
    focus = info.anchors[str(cfg['focus_name'])]
    zero = mapping['model']['level']['zero_value']
    final_value = mapping['model']['level']['final_value']
    action_ref = role_action_ref(mapping, info, role_key)
    out = ['        dummy = dummy if dummy = true;', '        dummy = dummy if dummy = false;']
    if role_key == primary_role:
        known_var = coord_var(mapping, 'primary_knows_focus_var')
        work_key = str(cfg['primary_action_key'])
        notify_key = str(cfg['primary_signal_action_key'])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = action_name(mapping, role_key, work_key)
        notify_action = action_name(mapping, role_key, notify_key)
        state_ref = role_state_ref(mapping, info, role_key)
        out.append(f'        {goal_var} = done if {dead} = true;')
        out.append(f'        {goal_var} = done if {completion_guard(mapping, info)};')
        out.append(f'        {goal_var} = {notify_stage} if ({goal_var} = {top} or {goal_var} = {work_stage}) and {info.environment_name}.{known_var} = true and {alive} = true and {level} = {final_value} and {state_ref} = {focus} and {action_ref} = {work_action};')
        out.append(f'        {goal_var} = {top} if {goal_var} = {notify_stage} and {action_ref} = {notify_action} and {dead} = false and {complete} = false;')
        out.append(f'        {goal_var} = {work_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and {alive} = true and {level_continuing(mapping, info)};')
        out.append(f'        {goal_var} = {work_stage} if {goal_var} = {work_stage} and {info.environment_name}.{known_var} = true and {alive} = true and {level_continuing(mapping, info)};')
        out += marker_evolution_lines(spec, mapping, info)
        return out
    if role_key == secondary_role:
        known_var = coord_var(mapping, 'secondary_knows_focus_var')
        report_flag = coord_var(mapping, 'focus_report_flag_var')
        ready_flag = coord_var(mapping, 'ready_flag_var')
        primary, _ = coordinated_roles(mapping)
        report_key = str(cfg['secondary_signal_action_key'])
        acquire_key = str(cfg['secondary_take_action_key'])
        finish_key = str(cfg['secondary_finish_action_key'])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = action_name(mapping, role_key, report_key)
        acquire_action = action_name(mapping, role_key, acquire_key)
        finish_action = action_name(mapping, role_key, finish_key)
        state_ref = role_state_ref(mapping, info, role_key)
        primary_state = role_state_ref(mapping, info, primary)
        primary_action_ref = role_action_ref(mapping, info, primary)
        primary_action = action_name(mapping, primary, str(cfg['primary_action_key']))
        out.append(f'        {goal_var} = done if {dead} = true;')
        out.append(f'        {goal_var} = done if {goal_var} = {finish_stage} and {action_ref} = {finish_action};')
        out.append(f'        {goal_var} = {finish_stage} if {goal_var} = {acquire_stage} and {action_ref} = {acquire_action};')
        out.append(f'        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {final_value} and {state_ref} = {focus} and {primary_state} = {focus} and {primary_action_ref} = {primary_action};')
        out.append(f'        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {zero} and ({info.environment_name}.{ready_flag} = true or {state_ref} = {focus});')
        elsewhere = [member for member in info.members if member != focus]
        elsewhere_expr = '(' + ' or '.join((f'{primary_state} = {member}' for member in elsewhere)) + ')'
        out.append(f'        {goal_var} = {report_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = false and {alive} = true and {level_positive(mapping, info)} and {elsewhere_expr};')
        out.append(f'        {goal_var} = {top} if {goal_var} = {report_stage} and {action_ref} = {report_action};')
        out += marker_evolution_lines(spec, mapping, info)
        return out
    raise ValueError(f'Role {role_key!r} is not part of the configured coordinated relation')
def uses_relation(role_cfg: Mapping[str, Any]) -> bool:
    return bool(role_cfg.get('plan', {}).get('relation'))
def GenerateProtocol(spec: AgentSpec, mapping: Mapping[str, Any], info: Optional[ModelContext]=None, baseline_protocol: Optional[Sequence[Tuple[str, List[str]]]]=None, environment_name: Optional[str]=None):
    role_cfg = mapping['jason']['roles'][spec.role_key]
    if uses_relation(role_cfg):
        if info is None:
            raise ValueError('Relation-aware plan compilation requires model relation data')
        return _relation_protocol(spec, mapping, info)
    if baseline_protocol is None or environment_name is None:
        raise ValueError('Plan compilation requires the baseline protocol and environment name')
    return _plain_protocol(spec, role_cfg, baseline_protocol, environment_name)

def GenerateEvolutionRules(spec: AgentSpec, mapping: Mapping[str, Any], info: Optional[ModelContext]=None, environment_name: Optional[str]=None):
    role_cfg = mapping['jason']['roles'][spec.role_key]
    if uses_relation(role_cfg):
        if info is None:
            raise ValueError('Relation-aware evolution compilation requires model relation data')
        return _relation_evolution(spec, mapping, info)
    if environment_name is None:
        raise ValueError('Evolution compilation requires the environment name')
    return _plain_evolution(spec, role_cfg, environment_name)
def generate_agent_block(spec: AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> str:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    role_info = info.roles[role_key]
    goal_var = str(role_cfg['goal_var'])
    marker_template = str(role_cfg['marker_var_template'])
    actions = [action_for_member(member, role_cfg, mapping['model']['domain']) for member in info.members]
    actions += [action_name(mapping, role_key, key) for key in role_cfg.get('action_order', [])]
    lines = [f'Agent {role_info.agent_name}', '    Vars:']
    lines += [f'        {line}' for line in role_info.base_vars]
    lines.append(f"        {goal_var}: {{{', '.join(spec.control.values)}}};")
    for member in info.members:
        lines.append(f"        {marker_template.replace('{member}', member)}: boolean;")
    lines += ['    end Vars', f"    Actions = {action_set(actions, int(mapping['format']['actions_indent']), int(mapping['format']['actions_per_line']))};", '    Protocol:']
    lines += GenerateProtocol(spec, mapping, info)
    lines += ['    end Protocol', '    Evolution:']
    lines += GenerateEvolutionRules(spec, mapping, info)
    lines += ['    end Evolution', 'end Agent']
    return '\n'.join(lines) + '\n'
def shared_memory_variables(mapping: Mapping[str, Any]) -> List[str]:
    cfg = mapping['coordination']
    return [str(cfg['primary_knows_focus_var']), str(cfg['secondary_knows_focus_var']), str(cfg['focus_report_flag_var']), str(cfg['ready_flag_var']), str(cfg['secondary_knows_endpoint_var'])]

def GenerateSharedEvolutionRules(mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    cfg = mapping['coordination']
    primary, secondary = coordinated_roles(mapping)
    focus = info.anchors[str(cfg['focus_name'])]
    endpoint = info.anchors[str(cfg['endpoint_name'])]
    primary_known = str(cfg['primary_knows_focus_var'])
    secondary_known = str(cfg['secondary_knows_focus_var'])
    report_flag = str(cfg['focus_report_flag_var'])
    ready_flag = str(cfg['ready_flag_var'])
    knows_endpoint = str(cfg['secondary_knows_endpoint_var'])
    primary_move = action_for_member(focus, mapping['jason']['roles'][primary], mapping['model']['domain'])
    secondary_move_focus = action_for_member(focus, mapping['jason']['roles'][secondary], mapping['model']['domain'])
    secondary_move_endpoint = action_for_member(endpoint, mapping['jason']['roles'][secondary], mapping['model']['domain'])
    secondary_signal = action_name(mapping, secondary, str(cfg['secondary_signal_action_key']))
    primary_signal = action_name(mapping, primary, str(cfg['primary_signal_action_key']))
    return ['        -- Beliefs', f"        {primary_known} = true if {primary_known} = true or ({var_name(mapping, 'active')} = true and {level_positive(mapping, info, False)} and {var_name(mapping, 'focus_state')} = {focus} and ({info.roles[primary].state_var} = {focus} or {role_action_ref(mapping, info, primary)} = {primary_move})) or {report_flag} = true;", f"        {secondary_known} = true if {secondary_known} = true or ({var_name(mapping, 'active')} = true and {level_positive(mapping, info, False)} and {var_name(mapping, 'focus_state')} = {focus} and ({info.roles[secondary].state_var} = {focus} or {role_action_ref(mapping, info, secondary)} = {secondary_move_focus}));", f'        {report_flag} = true if {report_flag} = true or ({secondary_known} = true and {role_action_ref(mapping, info, secondary)} = {secondary_signal});', f"        {ready_flag} = true if {ready_flag} = true or ({var_name(mapping, 'active')} = true and {var_name(mapping, 'level')} = {mapping['model']['level']['zero_value']} and {role_action_ref(mapping, info, primary)} = {primary_signal});", f'        {knows_endpoint} = true if {knows_endpoint} = true or {info.roles[secondary].state_var} = {endpoint} or {role_action_ref(mapping, info, secondary)} = {secondary_move_endpoint};']
def patch_environment(raw: str, mapping: Mapping[str, Any], info: ModelContext) -> str:
    env_start, env_end, env_block = parse_ispl_block(raw, info.environment_name)
    obs_match = re.search('\\bObsvars:(?P<body>.*?)\\bend Obsvars', env_block, re.S)
    if not obs_match:
        raise ValueError('Environment Obsvars block not found')
    cfg = mapping['coordination']
    anchor_var = var_name(mapping, str(cfg['memory_declaration_after_var']))
    variables = shared_memory_variables(mapping)
    declaration_text = ''.join((f'        {name}: boolean;\n' for name in variables))
    if not all((re.search(f'\\b{re.escape(name)}\\s*:\\s*boolean\\s*;', env_block) for name in variables)):
        anchor = re.search(f'(?m)^        {re.escape(anchor_var)}\\s*:[^;]+;\\s*$', env_block)
        if not anchor:
            raise ValueError(f'Environment declaration anchor variable not found: {anchor_var}')
        pos = anchor.end()
        env_block = env_block[:pos] + '\n' + declaration_text.rstrip('\n') + env_block[pos:]
    primary, secondary = coordinated_roles(mapping)
    for role_key, extra_action_key in [(primary, str(cfg['primary_signal_action_key'])), (secondary, str(cfg['secondary_signal_action_key']))]:
        state_var = info.roles[role_key].state_var
        rest = action_name(mapping, role_key, str(cfg['idle_action_key']))
        extra = action_name(mapping, role_key, extra_action_key)
        action_ref = role_action_ref(mapping, info, role_key)
        extra_line = f'        {state_var} = {state_var} if {action_ref} = {extra};'
        if extra_line not in env_block:
            rest_line = f'        {state_var} = {state_var} if {action_ref} = {rest};'
            if rest_line not in env_block:
                raise ValueError(f'Could not find no-op movement anchor for {role_key}')
            env_block = env_block.replace(rest_line, extra_line + '\n' + rest_line, 1)
    shared = '\n'.join(GenerateSharedEvolutionRules(mapping, info)) + '\n'
    if '        -- Beliefs\n' not in env_block:
        marker = str(cfg.get('environment_evolution_insert_before', ''))
        if marker and marker in env_block:
            env_block = env_block.replace(marker, shared + marker, 1)
        else:
            env_block = env_block.replace('    end Evolution', shared + '    end Evolution', 1)
    return raw[:env_start] + env_block + raw[env_end:]
def rewrite_init(raw: str, mapping: Mapping[str, Any], info: ModelContext, specs: Mapping[str, AgentSpec]) -> str:
    match = re.search('InitStates(?P<body>.*?)end InitStates', raw, re.S)
    if not match:
        raise ValueError('InitStates block not found')
    assignments: List[str] = []
    for line in match.group('body').splitlines():
        item = line.strip()
        if not item or item.startswith('--'):
            continue
        item = re.sub('\\s+and\\s*$', '', item)
        item = re.sub(';\\s*$', '', item)
        assignments.append(item)
    cfg = mapping['coordination']
    primary, secondary = coordinated_roles(mapping)
    endpoint = info.anchors[str(cfg['endpoint_name'])]
    additions = [f"{info.environment_name}.{cfg['primary_knows_focus_var']} = false", f"{info.environment_name}.{cfg['secondary_knows_focus_var']} = false", f"{info.environment_name}.{cfg['focus_report_flag_var']} = false", f"{info.environment_name}.{cfg['ready_flag_var']} = false", f"{info.environment_name}.{cfg['secondary_knows_endpoint_var']} = {('true' if info.roles[secondary].start == endpoint else 'false')}"]
    for role_key in mapping['jason']['roles']:
        role_cfg = mapping['jason']['roles'][role_key]
        spec = specs[role_key]
        additions.append(f"{info.roles[role_key].agent_name}.{role_cfg['goal_var']} = {spec.control.top}")
        template = str(role_cfg['marker_var_template'])
        for member in info.members:
            additions.append(f"{info.roles[role_key].agent_name}.{template.replace('{member}', member)} = {('true' if member == info.roles[role_key].start else 'false')}")
    first_agent = next(iter(mapping['jason']['roles']))
    prefix = info.roles[first_agent].agent_name + '.'
    output: List[str] = []
    inserted = False
    for item in assignments:
        if item.startswith(prefix) and (not inserted):
            output.extend(additions)
            inserted = True
        output.append(item)
    if not inserted:
        output.extend(additions)
    lines = ['InitStates']
    for index, item in enumerate(output):
        lines.append(f"    {item}{(';' if index == len(output) - 1 else ' and')}")
    lines.append('end InitStates')
    return raw[:match.start()] + '\n'.join(lines) + raw[match.end():]

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

def parse_agent_decision(raw: str, agent_name: str) -> Tuple[List[str], List[str], List[Tuple[str, List[str]]], List[str]]:
    _, _, text = parse_ispl_block(raw, agent_name)
    vm = re.search('\\bVars:(?P<body>.*?)\\bend Vars', text, re.S)
    variables = [line.strip() for line in vm.group('body').splitlines() if line.strip()] if vm else []
    am = re.search('\\bActions\\s*=\\s*\\{(?P<body>.*?)\\}\\s*;', text, re.S)
    actions = [x.strip() for x in am.group('body').replace('\n', ' ').split(',') if x.strip()] if am else []
    pm = re.search('\\bProtocol:(?P<body>.*?)\\bend Protocol', text, re.S)
    protocol: List[Tuple[str, List[str]]] = []
    if pm:
        rule_re = re.compile('(?P<condition>[^;]*?):\\s*\\{(?P<actions>.*?)\\}\\s*;', re.S)
        for match in rule_re.finditer(pm.group('body')):
            condition = ' '.join(match.group('condition').split())
            enabled = [x.strip() for x in match.group('actions').replace('\n', ' ').split(',') if x.strip()]
            protocol.append((condition, enabled))
    em = re.search('\\bEvolution:(?P<body>.*?)\\bend Evolution', text, re.S)
    evolution = [x.strip() + ';' for x in em.group('body').split(';') if x.strip()] if em else []
    return (variables, actions, protocol, evolution)
def semantic_operand(member: Any, environment_name: str) -> str:
    if isinstance(member, bool):
        return 'true' if member else 'false'
    if isinstance(member, (int, float)):
        return str(member)
    if isinstance(member, str):
        return member
    if 'env' in member:
        return f"{environment_name}.{member['env']}"
    if 'value' in member:
        return semantic_operand(member['value'], environment_name)
    raise ValueError(f'Invalid semantic operand: {member}')
def semantic_expr(member: Any, environment_name: str) -> str:
    if member is None or member is True:
        return 'true'
    if member is False:
        return 'false'
    if isinstance(member, str):
        return member
    if 'eq' in member:
        left, right = member['eq']
        return f'{semantic_operand(left, environment_name)} = {semantic_operand(right, environment_name)}'
    if 'neq' in member:
        left, right = member['neq']
        return f'!({semantic_operand(left, environment_name)} = {semantic_operand(right, environment_name)})'
    if 'all' in member:
        parts = [semantic_expr(x, environment_name) for x in member['all']]
        if 'false' in parts:
            return 'false'
        parts = [x for x in parts if x != 'true']
        return 'true' if not parts else ' and '.join(parts)
    if 'any' in member:
        parts = [semantic_expr(x, environment_name) for x in member['any']]
        if 'true' in parts:
            return 'true'
        parts = [x for x in parts if x != 'false']
        return 'false' if not parts else '(' + ' or '.join(parts) + ')'
    if 'not' in member:
        inner = semantic_expr(member['not'], environment_name)
        if inner == 'true':
            return 'false'
        if inner == 'false':
            return 'true'
        m = re.fullmatch('!\\((.*)\\)', inner)
        return m.group(1) if m else f'!({inner})'
    raise ValueError(f'Invalid semantic expression: {member}')

def _logic_parts(text: str, word: str) -> List[str]:
    out: List[str] = []
    start = 0
    depth = 0
    i = 0
    token = f' {word} '
    while i < len(text):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
        elif depth == 0 and text.startswith(token, i):
            out.append(text[start:i].strip())
            i += len(token)
            start = i
            continue
        i += 1
    out.append(text[start:].strip())
    return [x for x in out if x]
def _outer(text: str) -> str:
    value = text.strip()
    while value.startswith('(') and value.endswith(')'):
        depth = 0
        whole = True
        for i, ch in enumerate(value):
            depth += ch == '('
            depth -= ch == ')'
            if depth == 0 and i != len(value) - 1:
                whole = False
                break
        if not whole:
            break
        value = value[1:-1].strip()
    return value
def conjunction(parts: Sequence[str]) -> str:
    vals = [x.strip() for x in parts if x and x.strip() != 'true']
    if any(x == 'false' for x in vals):
        return 'false'
    return 'true' if not vals else ' and '.join(vals)

def negate_condition(text: str) -> str:
    value = text.strip()
    if value == 'true':
        return 'false'
    if value == 'false':
        return 'true'
    match = re.fullmatch(r'!\((.*)\)', value)
    if match:
        return match.group(1)
    core = _outer(value)
    parts = _logic_parts(core, 'and')
    if len(parts) > 1:
        return '(' + ' or '.join(negate_condition(x) for x in parts) + ')'
    parts = _logic_parts(core, 'or')
    if len(parts) > 1:
        return conjunction([negate_condition(x) for x in parts])
    return f'!({value})'
def semantic_context(context: str, role_cfg: Mapping[str, Any], environment_name: str) -> Optional[str]:
    predicates = role_cfg.get('plan', {}).get('predicates', {})
    parts: List[str] = []
    for piece in split_top(context, '&'):
        item = piece.strip()
        if not item or item == 'true':
            continue
        negated = item.startswith('not ')
        term = parse_term(item)
        if term is None or term.name not in predicates:
            return None
        expr = semantic_expr(predicates[term.name], environment_name)
        value = negate_condition(expr) if negated else expr
        if value == 'false':
            return 'false'
        if value != 'true':
            parts.append(value)
    return conjunction(parts)
def semantic_action(terms: Sequence[Term], role_cfg: Mapping[str, Any]) -> Optional[str]:
    actions = role_cfg.get('plan', {}).get('actions', {})
    ignored = set(role_cfg.get('plan', {}).get('ignore_actions', []))
    for term in terms:
        if term.name in actions:
            return str(actions[term.name])
        if term.op in {'+', '-', '?'} or term.name in ignored:
            continue
        if term.op == '!':
            return None
    return None

def _plain_protocol(spec: AgentSpec, role_cfg: Mapping[str, Any], baseline_protocol: Sequence[Tuple[str, List[str]]], environment_name: str) -> List[Tuple[str, List[str]]]:
    by_goal: Dict[str, List[Plan]] = {}
    for plan in spec.plans:
        by_goal.setdefault(plan.goal, []).append(plan)
    physical: Dict[str, List[str]] = {}
    for condition, actions in baseline_protocol:
        for action in actions:
            physical.setdefault(action, []).append(condition)
    out: List[Tuple[str, List[str]]] = []
    goal_var = str(role_cfg['goal_var'])
    for goal in [value for value in spec.control.values if value != 'done']:
        higher: List[str] = []
        for plan in by_goal.get(goal, []):
            guard = semantic_context(plan.context, role_cfg, environment_name)
            action = semantic_action(plan.terms, role_cfg)
            if guard is None:
                continue
            effective = guard
            if guard != 'false':
                if any(x == 'true' for x in higher):
                    effective = 'false'
                else:
                    effective = conjunction([guard] + [negate_condition(x) for x in higher if x != 'false'])
            if action is not None and effective != 'false':
                base_guards = physical.get(action, ['true'] if action in role_cfg.get('plan', {}).get('extra_actions', []) else [])
                for base in base_guards:
                    condition = conjunction([f'{goal_var} = {goal}', effective, base])
                    if condition != 'false':
                        out.append((condition, [action]))
            higher.append(guard)
    for action in role_cfg.get('plan', {}).get('pass_through', []):
        for condition in physical.get(str(action), []):
            out.append((condition, [str(action)]))
    for pattern in role_cfg.get('plan', {}).get('pass_through_patterns', []):
        rx = re.compile(str(pattern))
        for action, conditions in physical.items():
            if rx.fullmatch(action):
                for condition in conditions:
                    out.append((condition, [action]))
    unique: List[Tuple[str, List[str]]] = []
    seen = set()
    for condition, actions in out:
        key = (condition, tuple(actions))
        if key not in seen:
            seen.add(key)
            unique.append((condition, actions))
    return unique
def _plain_evolution(spec: AgentSpec, role_cfg: Mapping[str, Any], environment_name: str) -> List[str]:
    goal_var = str(role_cfg['goal_var'])
    values = set(spec.control.values)
    rules: List[str] = []
    for plan in spec.plans:
        if plan.goal not in values:
            continue
        guard = semantic_context(plan.context, role_cfg, environment_name)
        if guard in (None, 'false'):
            continue
        child = next((clean_name(term.name) for term in plan.terms if term.op == '!' and clean_name(term.name) in values), None)
        if child is not None:
            rules.append(f"        {goal_var} = {child} if {conjunction([f'{goal_var} = {plan.goal}', guard])};")
    for item in role_cfg.get('plan', {}).get('transitions', []):
        source = str(item['from'])
        target = str(item['to'])
        action = item.get('action')
        condition = semantic_expr(item.get('when', True), environment_name)
        if condition == 'false':
            continue
        parts = [f'{goal_var} = {source}']
        if action is not None:
            mapped = role_cfg.get('plan', {}).get('actions', {}).get(str(action), action)
            parts.append(f"{role_cfg['ispl_agent']}.Action = {mapped}")
        rules.append(f"        {goal_var} = {target} if {conjunction(parts + [condition])};")
    return uniq(rules)
def generate_plain_agent_block(spec: AgentSpec, mapping: Mapping[str, Any], raw: str, environment_name: str) -> str:
    role_cfg = mapping['jason']['roles'][spec.role_key]
    _, _, block = parse_ispl_block(raw, str(role_cfg['ispl_agent']))
    _, _, baseline_protocol, _ = parse_agent_decision(raw, str(role_cfg['ispl_agent']))
    goal_var = str(role_cfg['goal_var'])
    declaration = f"        {goal_var}: {{{', '.join(spec.control.values)}}};"
    if not re.search(f'\\b{re.escape(goal_var)}\\s*:', block):
        if re.search('\\bVars:', block):
            block = block.replace('    end Vars', declaration + '\n    end Vars', 1)
        else:
            marker = re.search('(?m)^\\s*Actions\\s*=', block)
            if not marker:
                raise ValueError(f"Actions block not found for {role_cfg['ispl_agent']}")
            block = block[:marker.start()] + '    Vars:\n' + declaration + '\n    end Vars\n' + block[marker.start():]
    plan_cfg = role_cfg.get('plan', {})
    extra = [str(x) for x in plan_cfg.get('extra_actions', [])]
    if extra:
        action_match = re.search('\\bActions\\s*=\\s*\\{(?P<body>.*?)\\}\\s*;', block, re.S)
        if not action_match:
            raise ValueError(f"Actions block not found for {role_cfg['ispl_agent']}")
        actions = [x.strip() for x in action_match.group('body').replace('\n', ' ').split(',') if x.strip()]
        actions = uniq(actions + extra)
        replacement = f'Actions = {action_set(actions, 12, 6)};'
        block = block[:action_match.start()] + replacement + block[action_match.end():]
    rules = GenerateProtocol(spec, mapping, baseline_protocol=baseline_protocol, environment_name=environment_name)
    protocol_lines = ['    Protocol:']
    for condition, enabled in rules:
        protocol_lines.append(f'        {condition}: {action_set(enabled, 16, 6)};')
    fallback = plan_cfg.get('fallback')
    if fallback:
        protocol_lines.append(f'        Other: {{{fallback}}};')
    protocol_lines.append('    end Protocol')
    block = re.sub('    Protocol:.*?    end Protocol', '\n'.join(protocol_lines), block, count=1, flags=re.S)
    evolution_rules = GenerateEvolutionRules(spec, mapping, environment_name=environment_name)
    if not evolution_rules:
        evolution_rules = [f'        {goal_var} = {value} if {goal_var} = {value};' for value in spec.control.values]
    insertion = '\n'.join((rule for rule in evolution_rules if rule not in block))
    if insertion:
        block = block.replace('    end Evolution', insertion + '\n    end Evolution', 1)
    return block if block.endswith('\n') else block + '\n'

def rewrite_plain_init(raw: str, specs: Mapping[str, AgentSpec], roles: Mapping[str, Any]) -> str:
    match = re.search('InitStates(?P<body>.*?)end InitStates', raw, re.S)
    if not match:
        raise ValueError('InitStates block not found')
    assignments: List[str] = []
    for line in match.group('body').splitlines():
        item = line.strip()
        if not item:
            continue
        item = re.sub('\\s+and\\s*$', '', item)
        item = re.sub(';\\s*$', '', item)
        assignments.append(item)
    additions = [(str(roles[key]['ispl_agent']), f"{roles[key]['ispl_agent']}.{roles[key]['goal_var']} = {spec.control.top}") for key, spec in specs.items()]
    for agent, addition in reversed(additions):
        index = next((i for i, item in enumerate(assignments) if item.startswith(agent + '.')), len(assignments))
        assignments.insert(index, addition)
    lines = ['InitStates']
    for i, item in enumerate(assignments):
        lines.append(f"    {item}{(';' if i == len(assignments) - 1 else ' and')}")
    lines.append('end InitStates')
    return raw[:match.start()] + '\n'.join(lines) + raw[match.end():]
def translate(config_path: Path, raw_override: Optional[Path]=None, output_override: Optional[Path]=None, program_overrides: Optional[Mapping[str, Path]]=None) -> Tuple[Path, Dict[str, AgentSpec]]:
    mapping = load_mapping(config_path)
    files = mapping['files']
    raw_path = raw_override or resolve_path(config_path, str(files['raw']))
    output_path = output_override or resolve_path(config_path, str(files['output']))
    raw = read_text(raw_path)
    vocabulary = mapping['jason'].get('vocabulary', {'actions': {}, 'predicates': {}})
    roles = mapping['jason']['roles']
    overrides = dict(program_overrides or {})
    specs: Dict[str, AgentSpec] = {}
    for role_key, role_cfg in roles.items():
        program_path = overrides.get(role_key) or resolve_path(config_path, str(role_cfg['program']))
        plans, top = read_plans(read_text(program_path), str(role_cfg['entry_goal']))
        control = BuildGoalControl(plans, top, role_cfg, vocabulary)
        specs[role_key] = BuildAgentSpec(role_key, plans, control, role_cfg, vocabulary)
    relation_roles = [key for key, cfg in roles.items() if uses_relation(cfg)]
    info = inspect_model(raw, mapping) if relation_roles else None
    out = raw
    if relation_roles:
        if 'coordination' in mapping:
            out = patch_environment(out, mapping, info)
            out = rewrite_init(out, mapping, info, specs)
        blocks = {info.roles[key].agent_name: generate_agent_block(specs[key], mapping, info) for key in relation_roles}
        out = ReplaceAgentDecisionModel(out, blocks)
    environment_name = str(mapping.get('model', {}).get('environment_agent', 'Environment'))
    plain_roles = [key for key in roles if key not in relation_roles]
    if plain_roles:
        blocks = {}
        for key in plain_roles:
            agent = str(roles[key]['ispl_agent'])
            blocks[agent] = generate_plain_agent_block(specs[key], mapping, out, environment_name)
        out = ReplaceAgentDecisionModel(out, blocks)
        out = rewrite_plain_init(out, {key: specs[key] for key in plain_roles}, roles)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out, encoding='utf-8')
    return (output_path, specs)
def main() -> int:
    parser = argparse.ArgumentParser(description='Jason-guided ISPL translator')
    parser.add_argument('--config', required=True, help='mapping JSON')
    parser.add_argument('--raw', help='baseline override')
    parser.add_argument('--program', action='append', default=[], metavar='ROLE=PATH', help='program override')
    parser.add_argument('--output', help='output override')
    args = parser.parse_args()
    overrides: Dict[str, Path] = {}
    for item in args.program:
        if '=' not in item:
            parser.error('--program must use ROLE=PATH')
        role, value = item.split('=', 1)
        overrides[role.strip()] = Path(value.strip()).resolve()
    output_path, specs = translate(Path(args.config).resolve(), Path(args.raw).resolve() if args.raw else None, Path(args.output).resolve() if args.output else None, overrides)
    print(f'Wrote ISPL: {output_path}')
    for role_key, spec in specs.items():
        print(f'{role_key} top: {spec.control.top}')
        print(f"{role_key} control: {', '.join(spec.control.values)}")
        print(f"{role_key} priority: {', '.join(spec.ranking_order)}")
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
