import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# Read a UTF-8 file.
def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')

# Normalize one identifier.
def clean_name(name: str) -> str:
    value = re.sub('[^A-Za-z0-9_]+', '_', name.strip())
    if re.match('^\\d', value):
        value = '_' + value
    return value

# Keep values in order.
def unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(values))

# Format an MCMAS action set.
def action_set(values: Sequence[str], indent_spaces: int=16, per_line: int=4) -> str:
    vals = unique((v for v in values if v))
    chunks = [', '.join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    if len(chunks) == 1:
        return '{' + chunks[0] + '}'
    pad = ' ' * indent_spaces
    return '{\n' + ',\n'.join((pad + chunk for chunk in chunks)) + '\n' + ' ' * (indent_spaces - 4) + '}'

# Split outside nested terms.
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

# Find one agent block.
def parse_ispl_block(raw: str, agent_name: str) -> Tuple[int, int, str]:
    pattern = re.compile(f'(?ms)^Agent[ \\t]+{re.escape(agent_name)}[ \\t]*$.*?^end[ \\t]+Agent[ \\t]*$')
    match = pattern.search(raw)
    if not match:
        raise ValueError(f'Agent block not found: {agent_name}')
    return (match.start(), match.end(), match.group(0))

# Replace one agent block.
def replace_ispl_agent(raw: str, agent_name: str, new_block: str) -> str:
    start, end, _ = parse_ispl_block(raw, agent_name)
    return raw[:start] + new_block.rstrip() + '\n' + raw[end:]

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

# Parse one AgentSpeak term.
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

# Parse a plan body.
def _parse_body_terms(body: str) -> List[Term]:
    out: List[Term] = []
    for piece in split_top(body, ';'):
        term = parse_term(piece)
        if term:
            out.append(term)
    return out

# Remove AgentSpeak line comments.
def _strip_asl_comments(text: str) -> str:
    return '\n'.join((line.split('//', 1)[0] for line in text.splitlines()))

# Instantiate parameterized terms.
def ground_program(text: str, config: Mapping[str, Any]) -> str:
    variable = str(config['variable'])
    members = [str(x) for x in config['members']]
    signatures = config['signatures']
    def normalize(block: str) -> str:
        def term(match: re.Match) -> str:
            name, arguments = match.group(1), split_top(match.group(2), ',')
            if name not in signatures:
                return match.group(0)
            indexes = signatures[name]
            if not all(i < len(arguments) for i in indexes):
                return match.group(0)
            selected = [arguments[i].strip('" ') for i in indexes]
            if any(value != '_' and value not in members and value not in config.get('values', []) for value in selected):
                return match.group(0)
            return name + '_' + '_'.join('any' if x == '_' else x for x in selected)
        return re.sub(r'\b([A-Za-z_]\w*)\(([^()]*)\)', term, block)
    parts = re.split(r'(?=^\s*\+!)', text, flags=re.M)
    output = []
    for part in parts:
        if re.search(r'\b' + re.escape(variable) + r'\b', part):
            for member in members:
                grounded = re.sub(r'\b' + re.escape(variable) + r'\b', '"' + member + '"', part)
                grounded = re.sub(r'"([^"]+)"\s*==\s*"([^"]+)"', lambda m: 'true' if m.group(1) == m.group(2) else 'false', grounded)
                output.append(normalize(grounded))
        else:
            output.append(normalize(part))
    return re.sub(r'(?m)^(\s*\+!\w+(?:\([^()]*\))?)\s*<-', r'\1 : true <-', '\n'.join(output))

# Parse the selected plans.
def read_plans(asl_text: str, entry_goal: str) -> Tuple[List[Plan], str]:
    text = _strip_asl_comments(asl_text)
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
        terms = _parse_body_terms(body)
        plans.append(Plan(goal=goal, context=context, body=body, terms=terms, index=index))
        if goal == entry_clean:
            for term in terms:
                if term.op == '!':
                    top = clean_name(term.name)
                    break
    if top is None:
        entry_match = re.search(f'(?ms)^\\s*\\+!?{re.escape(entry_goal)}(?:\\([^)]*\\))?\\s*:\\s*.*?\\s*<-\\s*(?P<body>.*?)\\.\\s*$', text)
        if entry_match:
            for term in _parse_body_terms(entry_match.group('body')):
                if term.op == '!':
                    top = clean_name(term.name)
                    break
    if top is None:
        raise ValueError(f'Could not derive top goal from configured entry goal {entry_goal!r}')
    return (plans, top)

# Match normalized vocabulary names.
def _name_in_list(name: str, values: Sequence[str]) -> bool:
    focus = clean_name(name)
    return focus in {clean_name(value) for value in values}

# Find an action category.
def action_category(term: Term, vocabulary: Mapping[str, Any]) -> Optional[str]:
    for category, names in vocabulary.get('actions', {}).items():
        if _name_in_list(term.name, names):
            return str(category)
    return None

# Check a context predicate.
def context_has(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get('predicates', {}).get(category, []):
        if re.search(f'\\b{re.escape(str(predicate))}\\s*\\(', context) or re.search(f'\\b{re.escape(str(predicate))}\\b', context):
            return True
    return False

# Check a negated predicate.
def context_has_negative(context: str, category: str, vocabulary: Mapping[str, Any]) -> bool:
    for predicate in vocabulary.get('predicates', {}).get(category, []):
        if re.search(f'\\bnot\\s+{re.escape(str(predicate))}(?:\\s*\\(|\\b)', context):
            return True
    return False

# Resolve configured file paths.
def resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()

# Load the translation mapping.
def load_mapping(config_path: Path) -> Dict[str, Any]:
    return json.loads(read_text(config_path))

# Parse one agent decision block.
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

# Format one semantic operand.
def _semantic_operand(member: Any, environment_name: str) -> str:
    if isinstance(member, bool):
        return 'true' if member else 'false'
    if isinstance(member, (int, float)):
        return str(member)
    if isinstance(member, str):
        return member
    if 'env' in member:
        return f"{environment_name}.{member['env']}"
    if 'value' in member:
        return _semantic_operand(member['value'], environment_name)
    raise ValueError(f'Invalid semantic operand: {member}')

# Format one semantic condition.
def semantic_expr(member: Any, environment_name: str) -> str:
    if member is None or member is True:
        return 'true'
    if member is False:
        return 'false'
    if isinstance(member, str):
        return member
    if 'eq' in member:
        left, right = member['eq']
        return f'{_semantic_operand(left, environment_name)} = {_semantic_operand(right, environment_name)}'
    if 'neq' in member:
        left, right = member['neq']
        return f'!({_semantic_operand(left, environment_name)} = {_semantic_operand(right, environment_name)})'
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

# Build a plain agent block.
def build_plain_agent_block(
    spec: AgentSpec,
    mapping: Mapping[str, Any],
    raw: str,
    protocol_rules: Sequence[Tuple[str, List[str]]],
    evolution_rules: Sequence[str],
) -> str:
    """Format a plain translated agent block."""
    role_cfg = mapping['jason']['roles'][spec.role_key]
    _, _, block = parse_ispl_block(raw, str(role_cfg['ispl_agent']))

    goal_var = str(role_cfg['goal_var'])
    declaration = f"        {goal_var}: {{{', '.join(spec.control.values)}}};"
    if not re.search(f'\\b{re.escape(goal_var)}\\s*:', block):
        if re.search('\\bVars:', block):
            block = block.replace('    end Vars', declaration + '\n    end Vars', 1)
        else:
            marker = re.search('(?m)^\\s*Actions\\s*=', block)
            if not marker:
                raise ValueError(f"Actions block not found for {role_cfg['ispl_agent']}")
            block = (
                block[:marker.start()]
                + '    Vars:\n'
                + declaration
                + '\n    end Vars\n'
                + block[marker.start():]
            )

    plan_cfg = role_cfg.get('plan', {})
    extra_actions = [str(x) for x in plan_cfg.get('extra_actions', [])]
    if extra_actions:
        action_match = re.search(
            '\\bActions\\s*=\\s*\\{(?P<body>.*?)\\}\\s*;', block, re.S
        )
        if not action_match:
            raise ValueError(f"Actions block not found for {role_cfg['ispl_agent']}")
        actions = [
            x.strip()
            for x in action_match.group('body').replace('\n', ' ').split(',')
            if x.strip()
        ]
        actions = unique(actions + extra_actions)
        replacement = f'Actions = {action_set(actions, 12, 6)};'
        block = block[:action_match.start()] + replacement + block[action_match.end():]

    protocol_lines = ['    Protocol:']
    for condition, enabled in protocol_rules:
        protocol_lines.append(f'        {condition}: {action_set(enabled, 16, 6)};')
    fallback = plan_cfg.get('fallback')
    if fallback:
        protocol_lines.append(f'        Other: {{{fallback}}};')
    protocol_lines.append('    end Protocol')
    block = re.sub(
        '    Protocol:.*?    end Protocol',
        '\n'.join(protocol_lines),
        block,
        count=1,
        flags=re.S,
    )

    rules = list(evolution_rules)
    if not rules:
        rules = [
            f'        {goal_var} = {value} if {goal_var} = {value};'
            for value in spec.control.values
        ]
    insertion = '\n'.join(rule for rule in rules if rule not in block)
    if insertion:
        block = block.replace('    end Evolution', insertion + '\n    end Evolution', 1)
    return block if block.endswith('\n') else block + '\n'

# Add initial goal values.
def rewrite_plain_init(
    raw: str,
    specs: Mapping[str, AgentSpec],
    roles: Mapping[str, Any],
) -> str:
    """Add initial goal-control values."""
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

    additions = [
        (
            str(roles[key]['ispl_agent']),
            f"{roles[key]['ispl_agent']}.{roles[key]['goal_var']} = {spec.control.top}",
        )
        for key, spec in specs.items()
    ]
    for agent, addition in reversed(additions):
        index = next(
            (i for i, item in enumerate(assignments) if item.startswith(agent + '.')),
            len(assignments),
        )
        assignments.insert(index, addition)

    lines = ['InitStates']
    for i, item in enumerate(assignments):
        lines.append(f"    {item}{(';' if i == len(assignments) - 1 else ' and')}")
    lines.append('end InitStates')
    return raw[:match.start()] + '\n'.join(lines) + raw[match.end():]
