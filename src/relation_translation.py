import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import formatting as fmt

# Read the InitStates body.
def _init_body(raw: str) -> str:
    match = re.search('InitStates(?P<body>.*?)end InitStates', raw, re.S)
    if not match:
        raise ValueError('InitStates block not found')
    return match.group('body')

# Read one initial value.
def _init_value(raw: str, environment_name: str, variable: str, value_pattern: str='[A-Za-z0-9_]+') -> str:
    body = _init_body(raw)
    match = re.search(f'{re.escape(environment_name)}\\.{re.escape(variable)}\\s*=\\s*(?P<value>{value_pattern})', body)
    if not match:
        raise ValueError(f'Initial value not found for {environment_name}.{variable}')
    return match.group('value')

# Find shortest relation steps.
def _relation_steps(relation: Mapping[str, Sequence[str]], focus: str) -> Dict[str, List[str]]:
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

# Extract member-name tokens.
def _member_token(member: str, domain_cfg: Mapping[str, Any]) -> Dict[str, str]:
    pattern = str(domain_cfg['token_regex'])
    match = re.fullmatch(pattern, member)
    if not match:
        raise ValueError(f'Member {member!r} does not match token_regex {pattern!r}')
    result = {'member': member}
    result.update({key: value for key, value in match.groupdict().items() if value is not None})
    for index, value in enumerate(match.groups(), start=1):
        result[str(index)] = value
    return result

# Build a movement action.
def _action_for_member(member: str, role_cfg: Mapping[str, Any], domain_cfg: Mapping[str, Any]) -> str:
    values = _member_token(member, domain_cfg)
    template = str(role_cfg['actions']['move_template'])
    return re.sub('\\{([A-Za-z0-9_]+)\\}', lambda m: values[m.group(1)], template)

# Read domain enum members.
def _parse_members(raw: str, model_cfg: Mapping[str, Any]) -> List[str]:
    variable = str(model_cfg['domain']['enum_var'])
    value_regex = str(model_cfg['domain']['value_regex'])
    match = re.search(f'\\b{re.escape(variable)}\\s*:\\s*\\{{(?P<body>.*?)\\}}\\s*;', raw, re.S)
    if not match:
        raise ValueError(f'Domain enum variable not found: {variable}')
    return fmt.unique(re.findall(value_regex, match.group('body')))

# Read existing agent variables.
def _parse_base_vars(agent_raw: str) -> List[str]:
    match = re.search('\\bVars:(?P<body>.*?)\\bend Vars', agent_raw, re.S)
    if not match:
        return []
    out: List[str] = []
    for line in match.group('body').splitlines():
        item = line.strip()
        if item:
            out.append(item)
    return out

# Read the movement relation.
def _parse_relation(raw: str, environment_name: str, members: Sequence[str], role_cfg: Mapping[str, Any], domain_cfg: Mapping[str, Any]) -> Dict[str, List[str]]:
    agent_name = str(role_cfg['ispl_agent'])
    state_var = str(role_cfg['state_var'])
    _, _, agent_raw = fmt.parse_ispl_block(raw, agent_name)
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
        relation[source] = fmt.unique(relation[source] + endpoints)
    return relation

# Infer configured member labels.
def _parse_member_labels(raw: str, members: Sequence[str], model_cfg: Mapping[str, Any]) -> Dict[str, str]:
    cfg = model_cfg.get('member_labels', {})
    body = _init_body(raw)
    out: Dict[str, str] = {}
    for member in members:
        tokens = _member_token(member, model_cfg['domain'])
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

# Inspect relation-aware model data.
def inspect_model(raw: str, mapping: Mapping[str, Any]) -> ModelContext:
    model_cfg = mapping['model']
    env = str(model_cfg.get('environment_agent', 'Environment'))
    members = _parse_members(raw, model_cfg)
    named: Dict[str, str] = {}
    for name, spec in model_cfg.get('anchors', {}).items():
        if 'value' in spec:
            named[str(name)] = str(spec['value'])
        else:
            named[str(name)] = _init_value(raw, env, str(spec['initial_var']), str(spec.get('value_pattern', model_cfg['domain']['value_regex'])))
    roles: Dict[str, RoleContext] = {}
    for role_key, role_cfg in mapping['jason']['roles'].items():
        agent_name = str(role_cfg['ispl_agent'])
        _, _, agent_raw = fmt.parse_ispl_block(raw, agent_name)
        state_var = str(role_cfg['state_var'])
        roles[role_key] = RoleContext(role_key=role_key, agent_name=agent_name, state_var=state_var, start=_init_value(raw, env, state_var, str(model_cfg['domain']['value_regex'])), relation=_parse_relation(raw, env, members, role_cfg, model_cfg['domain']), base_vars=_parse_base_vars(agent_raw))
    return ModelContext(environment_name=env, members=members, anchors=named, roles=roles, labels=_parse_member_labels(raw, members, model_cfg))

# Read a model variable name.
def _var_name(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping['model']['variables'][key])

# Build environment variable reference.
def _env_ref(mapping: Mapping[str, Any], info: ModelContext, key: str) -> str:
    return f'{info.environment_name}.{_var_name(mapping, key)}'

# Get the mapped agent name.
def _role_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str) -> str:
    return info.roles[role_key].agent_name

# Build agent action reference.
def _role_action_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str) -> str:
    return f'{_role_ref(mapping, info, role_key)}.Action'

# Build agent state reference.
def _role_state_ref(mapping: Mapping[str, Any], info: ModelContext, role_key: str, env_prefix: bool=True) -> str:
    name = info.roles[role_key].state_var
    return f'{info.environment_name}.{name}' if env_prefix else name

# Read a mapped action name.
def _action_name(mapping: Mapping[str, Any], role_key: str, key: str) -> str:
    return str(mapping['jason']['roles'][role_key]['actions'][key])

# Build a level condition.
def _level_condition(mapping: Mapping[str, Any], info: ModelContext, values: Sequence[Any], env_prefix: bool=True) -> str:
    reference = _env_ref(mapping, info, 'level') if env_prefix else _var_name(mapping, 'level')
    return '(' + ' or '.join((f'{reference} = {value}' for value in values)) + ')'

# Build positive-level condition.
def _level_positive(mapping: Mapping[str, Any], info: ModelContext, env_prefix: bool=True) -> str:
    return _level_condition(mapping, info, mapping['model']['level']['positive_values'], env_prefix)

# Build continuing-level condition.
def _level_continuing(mapping: Mapping[str, Any], info: ModelContext) -> str:
    return _level_condition(mapping, info, mapping['model']['level']['continuing_values'], True)

# Read coordinated role names.
def _coordinated_roles(mapping: Mapping[str, Any]) -> Tuple[str, str]:
    cfg = mapping['coordination']
    return (str(cfg['primary_role']), str(cfg['secondary_role']))

# Read a coordination variable.
def _coord_var(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping['coordination'][key])

# Build the final-state guard.
def _final_guard(mapping: Mapping[str, Any], info: ModelContext) -> str:
    _, secondary = _coordinated_roles(mapping)
    endpoint = info.anchors[str(mapping['coordination']['endpoint_name'])]
    zero = mapping['model']['level']['zero_value']
    complete_alive = f"{_env_ref(mapping, info, 'active')} = true and {_env_ref(mapping, info, 'failed')} = false and {_env_ref(mapping, info, 'holding')} = false and {_env_ref(mapping, info, 'level')} = {zero} and {_env_ref(mapping, info, 'focus_state')} = {endpoint} and {_role_state_ref(mapping, info, secondary)} = {endpoint} and {_env_ref(mapping, info, 'endpoint_state')} = {endpoint}"
    return f"({_env_ref(mapping, info, 'failed')} = true or ({complete_alive}))"

# Build the completion guard.
def _completion_guard(mapping: Mapping[str, Any], info: ModelContext) -> str:
    _, secondary = _coordinated_roles(mapping)
    cfg = mapping['coordination']
    endpoint = info.anchors[str(cfg['endpoint_name'])]
    return f"{_env_ref(mapping, info, 'holding')} = true and {_env_ref(mapping, info, 'active')} = true and {_env_ref(mapping, info, 'failed')} = false and {_env_ref(mapping, info, 'complete')} = false and {_role_state_ref(mapping, info, secondary)} = {endpoint} and {_env_ref(mapping, info, 'endpoint_state')} = {endpoint} and {_role_action_ref(mapping, info, secondary)} = {_action_name(mapping, secondary, str(cfg['secondary_finish_action_key']))}"

# Rank one neighbouring member.
def _ranking_rank(member: str, info: ModelContext, role_cfg: Mapping[str, Any], order: Sequence[str]) -> int:
    cls = info.labels.get(member, str(role_cfg.get('ranking', {}).get('default_class', 'default')))
    candidates = role_cfg.get('ranking', {}).get('class_categories', {}).get(cls, [cls])
    for index, item in enumerate(order):
        if item in candidates:
            return index
    return 999

# Generate ranked movement rules.
def _ranking_protocol_lines(mapping: Mapping[str, Any], info: ModelContext, spec: fmt.AgentSpec, known_var: str) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    goal_var = str(role_cfg['goal_var'])
    marker_template = str(role_cfg['marker_var_template'])
    alive = _env_ref(mapping, info, 'active')
    state_ref = _role_state_ref(mapping, info, role_key)
    out = [f"        -- {role_cfg.get('ranking', {}).get('label', 'Ranking')}"]
    for current in info.members:
        neighbours = info.roles[role_key].relation.get(current, [])
        for neighbour in neighbours:
            rank = _ranking_rank(neighbour, info, role_cfg, spec.ranking_order)
            higher = [candidate for candidate in neighbours if _ranking_rank(candidate, info, role_cfg, spec.ranking_order) < rank]
            parts = [f'{goal_var} = {spec.control.top}', f'{info.environment_name}.{known_var} = false', f'{alive} = true', f'{state_ref} = {current}']
            for candidate in higher:
                parts.append(f"{marker_template.replace('{member}', candidate)} = true")
            parts.append(f"{marker_template.replace('{member}', neighbour)} = false")
            move = _action_for_member(neighbour, role_cfg, mapping['model']['domain'])
            out.append(f"        {' and '.join(parts)}:")
            out.append(f'            {{{move}}};')
        if neighbours:
            parts = [f'{goal_var} = {spec.control.top}', f'{info.environment_name}.{known_var} = false', f'{alive} = true', f'{state_ref} = {current}']
            for candidate in neighbours:
                parts.append(f"{marker_template.replace('{member}', candidate)} = true")
            moves = [_action_for_member(candidate, role_cfg, mapping['model']['domain']) for candidate in neighbours]
            out.append(f"        {' and '.join(parts)}:")
            out.append(f"            {fmt.action_set(moves, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out

# Generate path movement rules.
def _path_protocol_lines(mapping: Mapping[str, Any], info: ModelContext, role_key: str, focus: str, condition_builder, append_rest: bool=False) -> List[str]:
    role_cfg = mapping['jason']['roles'][role_key]
    paths = _relation_steps(info.roles[role_key].relation, focus)
    out: List[str] = []
    for member in info.members:
        if member == focus:
            continue
        choices = [_action_for_member(dst, role_cfg, mapping['model']['domain']) for dst in paths.get(member, [])]
        if not choices:
            choices = [_action_for_member(dst, role_cfg, mapping['model']['domain']) for dst in info.roles[role_key].relation.get(member, [])]
        if not choices:
            choices = [_action_name(mapping, role_key, str(mapping['coordination']['idle_action_key']))]
        if append_rest:
            choices.append(_action_name(mapping, role_key, str(mapping['coordination']['idle_action_key'])))
        out.append(f'        {condition_builder(member)}:')
        out.append(f"            {fmt.action_set(choices, int(mapping['format']['path_indent']), int(mapping['format']['path_actions_per_line']))};")
    return out

# Generate relation-aware protocol rules.
def generate_protocol(spec: fmt.AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    primary_role, secondary_role = _coordinated_roles(mapping)
    cfg = mapping['coordination']
    goal_var = str(role_cfg['goal_var'])
    top = spec.control.top
    rest = _action_name(mapping, role_key, str(cfg['idle_action_key']))
    focus = info.anchors[str(cfg['focus_name'])]
    alive = _env_ref(mapping, info, 'active')
    holding = _env_ref(mapping, info, 'holding')
    level = _env_ref(mapping, info, 'level')
    zero = mapping['model']['level']['zero_value']
    out = [f'        {_final_guard(mapping, info)}: {{{rest}}};', f'        {goal_var} = done: {{{rest}}};']
    if role_key == primary_role:
        known_var = _coord_var(mapping, 'primary_knows_focus_var')
        work_key = str(cfg['primary_action_key'])
        notify_key = str(cfg['primary_signal_action_key'])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = _action_name(mapping, role_key, work_key)
        notify_action = _action_name(mapping, role_key, notify_key)
        state_ref = _role_state_ref(mapping, info, role_key)
        active = f'({goal_var} = {top} or {goal_var} = {work_stage})'
        out.append(f'        {goal_var} = {notify_stage}: {{{notify_action}}};')
        out.append(f'        {active} and {info.environment_name}.{known_var} = true and {alive} = true and {_level_positive(mapping, info)} and {state_ref} = {focus}: {{{work_action}}};')
        out += _path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{active} and {info.environment_name}.{known_var} = true and {alive} = true and {_level_positive(mapping, info)} and {state_ref} = {member}')
        out += _ranking_protocol_lines(mapping, info, spec, known_var)
        out.append(f'        Other: {{{rest}}};')
        return out
    if role_key == secondary_role:
        known_var = _coord_var(mapping, 'secondary_knows_focus_var')
        report_flag = _coord_var(mapping, 'focus_report_flag_var')
        ready_flag = _coord_var(mapping, 'ready_flag_var')
        knows_endpoint = _coord_var(mapping, 'secondary_knows_endpoint_var')
        primary, _ = _coordinated_roles(mapping)
        report_key = str(cfg['secondary_signal_action_key'])
        acquire_key = str(cfg['secondary_take_action_key'])
        finish_key = str(cfg['secondary_finish_action_key'])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = _action_name(mapping, role_key, report_key)
        acquire_action = _action_name(mapping, role_key, acquire_key)
        finish_action = _action_name(mapping, role_key, finish_key)
        state_ref = _role_state_ref(mapping, info, role_key)
        primary_state = _role_state_ref(mapping, info, primary)
        endpoint = info.anchors[str(cfg['endpoint_name'])]
        out.append(f'        {goal_var} = {report_stage}: {{{report_action}}};')
        out.append(f'        {goal_var} = {acquire_stage} and {alive} = true and {holding} = false and {level} = {zero} and {state_ref} = {focus}: {{{acquire_action}}};')
        out += _path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{goal_var} = {acquire_stage} and {alive} = true and {holding} = false and {level} = {zero} and {state_ref} = {member}')
        out.append(f'        {goal_var} = {finish_stage} and {holding} = true and {alive} = true and {state_ref} = {endpoint}: {{{finish_action}}};')
        out += _path_protocol_lines(mapping, info, role_key, endpoint, lambda member: f'{goal_var} = {finish_stage} and {holding} = true and {alive} = true and {info.environment_name}.{knows_endpoint} = true and {state_ref} = {member}')
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {alive} = true and {_level_positive(mapping, info)} and {primary_state} = {focus}: {{{rest}}};')
        elsewhere = [member for member in info.members if member != focus]
        elsewhere_expr = '(' + ' or '.join((f'{primary_state} = {member}' for member in elsewhere)) + ')'
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = false and {alive} = true and {_level_positive(mapping, info)} and {elsewhere_expr}: {{{rest}}};')
        out.append(f'        {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = true and {alive} = true and {_level_positive(mapping, info)} and {state_ref} = {focus}: {{{rest}}};')
        out += _path_protocol_lines(mapping, info, role_key, focus, lambda member: f'{goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = true and {alive} = true and {_level_positive(mapping, info)} and {state_ref} = {member}', append_rest=True)
        out.append(f'        {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {zero} and ({info.environment_name}.{ready_flag} = true or {state_ref} = {focus}): {{{rest}}};')
        out += _ranking_protocol_lines(mapping, info, spec, known_var)
        out.append(f'        Other: {{{rest}}};')
        return out
    raise ValueError(f'Role {role_key!r} is not part of the configured coordinated relation')

# Generate visited-marker updates.
def _marker_evolution_lines(spec: fmt.AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_cfg = mapping['jason']['roles'][spec.role_key]
    template = str(role_cfg['marker_var_template'])
    action_ref = _role_action_ref(mapping, info, spec.role_key)
    out = [f"        -- {role_cfg.get('marker_label', 'Memory')}"]
    for member in info.members:
        reachable = template.replace('{member}', member)
        move = _action_for_member(member, role_cfg, mapping['model']['domain'])
        out.append(f'        {reachable} = true if {reachable} = true or {action_ref} = {move};')
    return out

# Generate relation-aware evolution rules.
def generate_evolution_rules(spec: fmt.AgentSpec, mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    primary_role, secondary_role = _coordinated_roles(mapping)
    cfg = mapping['coordination']
    goal_var = str(role_cfg['goal_var'])
    top = spec.control.top
    alive = _env_ref(mapping, info, 'active')
    dead = _env_ref(mapping, info, 'failed')
    complete = _env_ref(mapping, info, 'complete')
    holding = _env_ref(mapping, info, 'holding')
    level = _env_ref(mapping, info, 'level')
    focus = info.anchors[str(cfg['focus_name'])]
    zero = mapping['model']['level']['zero_value']
    final_value = mapping['model']['level']['final_value']
    action_ref = _role_action_ref(mapping, info, role_key)
    out = ['        dummy = dummy if dummy = true;', '        dummy = dummy if dummy = false;']
    if role_key == primary_role:
        known_var = _coord_var(mapping, 'primary_knows_focus_var')
        work_key = str(cfg['primary_action_key'])
        notify_key = str(cfg['primary_signal_action_key'])
        work_stage = spec.stages[work_key]
        notify_stage = spec.stages[notify_key]
        work_action = _action_name(mapping, role_key, work_key)
        notify_action = _action_name(mapping, role_key, notify_key)
        state_ref = _role_state_ref(mapping, info, role_key)
        out.append(f'        {goal_var} = done if {dead} = true;')
        out.append(f'        {goal_var} = done if {_completion_guard(mapping, info)};')
        out.append(f'        {goal_var} = {notify_stage} if ({goal_var} = {top} or {goal_var} = {work_stage}) and {info.environment_name}.{known_var} = true and {alive} = true and {level} = {final_value} and {state_ref} = {focus} and {action_ref} = {work_action};')
        out.append(f'        {goal_var} = {top} if {goal_var} = {notify_stage} and {action_ref} = {notify_action} and {dead} = false and {complete} = false;')
        out.append(f'        {goal_var} = {work_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and {alive} = true and {_level_continuing(mapping, info)};')
        out.append(f'        {goal_var} = {work_stage} if {goal_var} = {work_stage} and {info.environment_name}.{known_var} = true and {alive} = true and {_level_continuing(mapping, info)};')
        out += _marker_evolution_lines(spec, mapping, info)
        return out
    if role_key == secondary_role:
        known_var = _coord_var(mapping, 'secondary_knows_focus_var')
        report_flag = _coord_var(mapping, 'focus_report_flag_var')
        ready_flag = _coord_var(mapping, 'ready_flag_var')
        primary, _ = _coordinated_roles(mapping)
        report_key = str(cfg['secondary_signal_action_key'])
        acquire_key = str(cfg['secondary_take_action_key'])
        finish_key = str(cfg['secondary_finish_action_key'])
        report_stage = spec.stages[report_key]
        acquire_stage = spec.stages[acquire_key]
        finish_stage = spec.stages[finish_key]
        report_action = _action_name(mapping, role_key, report_key)
        acquire_action = _action_name(mapping, role_key, acquire_key)
        finish_action = _action_name(mapping, role_key, finish_key)
        state_ref = _role_state_ref(mapping, info, role_key)
        primary_state = _role_state_ref(mapping, info, primary)
        primary_action_ref = _role_action_ref(mapping, info, primary)
        primary_action = _action_name(mapping, primary, str(cfg['primary_action_key']))
        out.append(f'        {goal_var} = done if {dead} = true;')
        out.append(f'        {goal_var} = done if {goal_var} = {finish_stage} and {action_ref} = {finish_action};')
        out.append(f'        {goal_var} = {finish_stage} if {goal_var} = {acquire_stage} and {action_ref} = {acquire_action};')
        out.append(f'        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {final_value} and {state_ref} = {focus} and {primary_state} = {focus} and {primary_action_ref} = {primary_action};')
        out.append(f'        {goal_var} = {acquire_stage} if {goal_var} = {top} and {alive} = true and {holding} = false and {level} = {zero} and ({info.environment_name}.{ready_flag} = true or {state_ref} = {focus});')
        elsewhere = [member for member in info.members if member != focus]
        elsewhere_expr = '(' + ' or '.join((f'{primary_state} = {member}' for member in elsewhere)) + ')'
        out.append(f'        {goal_var} = {report_stage} if {goal_var} = {top} and {info.environment_name}.{known_var} = true and {info.environment_name}.{report_flag} = false and {alive} = true and {_level_positive(mapping, info)} and {elsewhere_expr};')
        out.append(f'        {goal_var} = {top} if {goal_var} = {report_stage} and {action_ref} = {report_action};')
        out += _marker_evolution_lines(spec, mapping, info)
        return out
    raise ValueError(f'Role {role_key!r} is not part of the configured coordinated relation')

# Check relation-aware configuration.
def uses_relation(role_cfg: Mapping[str, Any]) -> bool:
    return bool(role_cfg.get('plan', {}).get('relation'))

# List shared memory variables.
def _shared_memory_variables(mapping: Mapping[str, Any]) -> List[str]:
    cfg = mapping['coordination']
    return [str(cfg['primary_knows_focus_var']), str(cfg['secondary_knows_focus_var']), str(cfg['focus_report_flag_var']), str(cfg['ready_flag_var']), str(cfg['secondary_knows_endpoint_var'])]

# Generate shared memory updates.
def _generate_shared_evolution_rules(mapping: Mapping[str, Any], info: ModelContext) -> List[str]:
    cfg = mapping['coordination']
    primary, secondary = _coordinated_roles(mapping)
    focus = info.anchors[str(cfg['focus_name'])]
    endpoint = info.anchors[str(cfg['endpoint_name'])]
    primary_known = str(cfg['primary_knows_focus_var'])
    secondary_known = str(cfg['secondary_knows_focus_var'])
    report_flag = str(cfg['focus_report_flag_var'])
    ready_flag = str(cfg['ready_flag_var'])
    knows_endpoint = str(cfg['secondary_knows_endpoint_var'])
    primary_move = _action_for_member(focus, mapping['jason']['roles'][primary], mapping['model']['domain'])
    secondary_move_focus = _action_for_member(focus, mapping['jason']['roles'][secondary], mapping['model']['domain'])
    secondary_move_endpoint = _action_for_member(endpoint, mapping['jason']['roles'][secondary], mapping['model']['domain'])
    secondary_signal = _action_name(mapping, secondary, str(cfg['secondary_signal_action_key']))
    primary_signal = _action_name(mapping, primary, str(cfg['primary_signal_action_key']))
    return ['        -- Beliefs', f"        {primary_known} = true if {primary_known} = true or ({_var_name(mapping, 'active')} = true and {_level_positive(mapping, info, False)} and {_var_name(mapping, 'focus_state')} = {focus} and ({info.roles[primary].state_var} = {focus} or {_role_action_ref(mapping, info, primary)} = {primary_move})) or {report_flag} = true;", f"        {secondary_known} = true if {secondary_known} = true or ({_var_name(mapping, 'active')} = true and {_level_positive(mapping, info, False)} and {_var_name(mapping, 'focus_state')} = {focus} and ({info.roles[secondary].state_var} = {focus} or {_role_action_ref(mapping, info, secondary)} = {secondary_move_focus}));", f'        {report_flag} = true if {report_flag} = true or ({secondary_known} = true and {_role_action_ref(mapping, info, secondary)} = {secondary_signal});', f"        {ready_flag} = true if {ready_flag} = true or ({_var_name(mapping, 'active')} = true and {_var_name(mapping, 'level')} = {mapping['model']['level']['zero_value']} and {_role_action_ref(mapping, info, primary)} = {primary_signal});", f'        {knows_endpoint} = true if {knows_endpoint} = true or {info.roles[secondary].state_var} = {endpoint} or {_role_action_ref(mapping, info, secondary)} = {secondary_move_endpoint};']

# Add shared environment state.
def patch_environment(raw: str, mapping: Mapping[str, Any], info: ModelContext) -> str:
    env_start, env_end, env_block = fmt.parse_ispl_block(raw, info.environment_name)
    obs_match = re.search('\\bObsvars:(?P<body>.*?)\\bend Obsvars', env_block, re.S)
    if not obs_match:
        raise ValueError('Environment Obsvars block not found')
    cfg = mapping['coordination']
    anchor_var = _var_name(mapping, str(cfg['memory_declaration_after_var']))
    variables = _shared_memory_variables(mapping)
    declaration_text = ''.join((f'        {name}: boolean;\n' for name in variables))
    if not all((re.search(f'\\b{re.escape(name)}\\s*:\\s*boolean\\s*;', env_block) for name in variables)):
        anchor = re.search(f'(?m)^        {re.escape(anchor_var)}\\s*:[^;]+;\\s*$', env_block)
        if not anchor:
            raise ValueError(f'Environment declaration anchor variable not found: {anchor_var}')
        pos = anchor.end()
        env_block = env_block[:pos] + '\n' + declaration_text.rstrip('\n') + env_block[pos:]
    primary, secondary = _coordinated_roles(mapping)
    for role_key, extra_action_key in [(primary, str(cfg['primary_signal_action_key'])), (secondary, str(cfg['secondary_signal_action_key']))]:
        state_var = info.roles[role_key].state_var
        rest = _action_name(mapping, role_key, str(cfg['idle_action_key']))
        extra = _action_name(mapping, role_key, extra_action_key)
        action_ref = _role_action_ref(mapping, info, role_key)
        extra_line = f'        {state_var} = {state_var} if {action_ref} = {extra};'
        if extra_line not in env_block:
            rest_line = f'        {state_var} = {state_var} if {action_ref} = {rest};'
            if rest_line not in env_block:
                raise ValueError(f'Could not find no-op movement anchor for {role_key}')
            env_block = env_block.replace(rest_line, extra_line + '\n' + rest_line, 1)
    shared = '\n'.join(_generate_shared_evolution_rules(mapping, info)) + '\n'
    if '        -- Beliefs\n' not in env_block:
        marker = str(cfg.get('environment_evolution_insert_before', ''))
        if marker and marker in env_block:
            env_block = env_block.replace(marker, shared + marker, 1)
        else:
            env_block = env_block.replace('    end Evolution', shared + '    end Evolution', 1)
    return raw[:env_start] + env_block + raw[env_end:]

# Add relation-aware initial values.
def rewrite_init(raw: str, mapping: Mapping[str, Any], info: ModelContext, specs: Mapping[str, fmt.AgentSpec]) -> str:
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
    primary, secondary = _coordinated_roles(mapping)
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

# Build a relation agent block.
def build_agent_block(
    spec: fmt.AgentSpec,
    mapping: Mapping[str, Any],
    info: ModelContext,
    protocol_lines: Sequence[str],
    evolution_lines: Sequence[str],
) -> str:
    """Format a relation-aware agent block."""
    role_key = spec.role_key
    role_cfg = mapping['jason']['roles'][role_key]
    role_info = info.roles[role_key]
    goal_var = str(role_cfg['goal_var'])
    marker_template = str(role_cfg['marker_var_template'])

    actions = [
        _action_for_member(member, role_cfg, mapping['model']['domain'])
        for member in info.members
    ]
    actions += [
        _action_name(mapping, role_key, key)
        for key in role_cfg.get('action_order', [])
    ]

    lines = [f'Agent {role_info.agent_name}', '    Vars:']
    lines += [f'        {line}' for line in role_info.base_vars]
    lines.append(f"        {goal_var}: {{{', '.join(spec.control.values)}}};")
    for member in info.members:
        lines.append(f"        {marker_template.replace('{member}', member)}: boolean;")

    lines += [
        '    end Vars',
        f"    Actions = {fmt.action_set(actions, int(mapping['format']['actions_indent']), int(mapping['format']['actions_per_line']))};",
        '    Protocol:',
    ]
    lines += list(protocol_lines)
    lines += ['    end Protocol', '    Evolution:']
    lines += list(evolution_lines)
    lines += ['    end Evolution', 'end Agent']
    return '\n'.join(lines) + '\n'
