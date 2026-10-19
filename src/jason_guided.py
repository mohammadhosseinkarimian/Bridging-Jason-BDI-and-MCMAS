import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import formatting as fmt
import relation_translation as relation
from formatting import AgentSpec, GoalCall, GoalControl, Plan, Term
from relation_translation import ModelContext

# Find a goal by action category.
def _goal_with_action(plans: Sequence[Plan], vocabulary: Mapping[str, Any], category: str, top: str) -> Optional[str]:
    hits = [plan.goal for plan in plans if any(fmt.action_category(term, vocabulary) == category for term in plan.terms)]
    return next((goal for goal in hits if goal != top), hits[0] if hits else None)

##### Phase 1: Build goal control #####
# Track which Jason task stage is active.
# Test input: top=saved and the four small Jason plans from the paper.
# Test output: reachable=[saved,rescued,notified], calls=[saved->rescued,saved->notified], values=[saved,rescued,notified,done].
def build_goal_control(plans: Sequence[Plan], top_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> GoalControl:
    # P <- group plans by triggering goal.
    plans_by_goal: Dict[str, List[Plan]] = {}
    for plan in plans:
        plans_by_goal.setdefault(plan.goal, []).append(plan)

    # calls <- [], reachable <- [], seen <- empty.
    calls: List[GoalCall] = []
    reachable: List[str] = []
    seen: Set[str] = set()

    def visit(goal: str) -> None:
        # If g is already seen, return.
        if goal in seen:
            return
        # Add g to seen and reachable.
        seen.add(goal)
        reachable.append(goal)
        # Follow achievement goals in source/body order.
        for plan in plans_by_goal.get(goal, []):
            for term in plan.terms:
                if term.op != '!':
                    continue
                child = fmt.clean_name(term.name)
                # Append (g,h,p.index), then Visit(h).
                calls.append(GoalCall(goal, child, plan.index))
                visit(child)

    # Visit(top).
    visit(top_goal)

    # values <- [top].
    values = [top_goal]

    # Add configured reachable task stages.
    for stage in role_cfg.get('stages', []):
        goal = _goal_with_action(plans, vocabulary, str(stage['action_category']), top_goal)
        if goal and goal in seen:
            values.append(goal)

    # A <- mapped Jason actions.
    plan_cfg = role_cfg.get('plan')
    if plan_cfg is not None:
        mapped_actions = {fmt.clean_name(str(name)) for name in plan_cfg.get('actions', {})}
        # Add reachable goals containing an action in A.
        for goal in reachable:
            if goal != top_goal and any(plan.goal == goal and any(fmt.clean_name(term.name) in mapped_actions for term in plan.terms) for plan in plans):
                values.append(goal)

    # Append done and return the control structure.
    values.append('done')
    return GoalControl(top=top_goal, values=fmt.unique(values), calls=calls, reachable=reachable)

# Infer the configured ranking goal.
def _infer_ranking_goal(plans: Sequence[Plan], top: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> str:
    configured = role_cfg.get('ranking', {}).get('goal')
    if configured and configured != 'auto':
        return fmt.clean_name(str(configured))
    categories = role_cfg.get('ranking', {}).get('signal_categories', [])
    scores: Dict[str, int] = {}
    for plan in plans:
        if plan.goal in (fmt.clean_name(str(role_cfg.get('entry_goal', ''))), top):
            continue
        score = sum(1 for category in categories if fmt.context_has(plan.context, str(category), vocabulary))
        if score:
            scores[plan.goal] = scores.get(plan.goal, 0) + score
    if scores:
        return max(scores, key=scores.get)
    fallback = role_cfg.get('ranking', {}).get('fallback_goal')
    if fallback:
        return fmt.clean_name(str(fallback))
    raise ValueError('Could not infer ranking goal')

# Infer source-order ranking classes.
def _infer_ranking_order(plans: Sequence[Plan], ranking_goal: str, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> List[str]:
    order: List[str] = []
    for plan in plans:
        if plan.goal != ranking_goal:
            continue
        for classifier in role_cfg.get('ranking', {}).get('classifiers', []):
            if classifier.get('context_equals') is not None:
                if plan.context.strip() == str(classifier['context_equals']):
                    order.append(str(classifier['name']))
                    break
                continue
            required = [str(x) for x in classifier.get('all', [])]
            negative = [str(x) for x in classifier.get('negative', [])]
            if all(fmt.context_has(plan.context, category, vocabulary) for category in required) and all(fmt.context_has_negative(plan.context, category, vocabulary) for category in negative):
                order.append(str(classifier['name']))
                break
    return fmt.unique(order or [str(x) for x in role_cfg.get('ranking', {}).get('fallback_order', [])])

# Build the per-agent record.
def _build_agent_spec(role_key: str, plans: Sequence[Plan], control: GoalControl, role_cfg: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> AgentSpec:
    stages: Dict[str, str] = {}
    for stage in role_cfg.get('stages', []):
        key = str(stage['key'])
        category = str(stage['action_category'])
        goal = _goal_with_action(plans, vocabulary, category, control.top)
        if goal is None:
            raise ValueError(f'No Jason goal found for stage {key!r} / action category {category!r}')
        stages[key] = goal
    if role_cfg.get('ranking'):
        ranking_goal = _infer_ranking_goal(plans, control.top, role_cfg, vocabulary)
        ranking_order = _infer_ranking_order(plans, ranking_goal, role_cfg, vocabulary)
    else:
        ranking_goal, ranking_order = '', []
    return AgentSpec(role_key=role_key, plans=list(plans), control=control, stages=stages, ranking_goal=ranking_goal, ranking_order=ranking_order)

# Split a top-level logic expression.
def _logic_parts(text: str, word: str) -> List[str]:
    out: List[str] = []
    start = depth = i = 0
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

# Remove whole outer parentheses.
def _outer(text: str) -> str:
    value = text.strip()
    while value.startswith('(') and value.endswith(')'):
        depth, whole = 0, True
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

# Join mapped AND conditions.
def _conjunction(parts: Sequence[str]) -> str:
    values = [x.strip() for x in parts if x and x.strip() != 'true']
    if any(x == 'false' for x in values):
        return 'false'
    return 'true' if not values else ' and '.join(values)

# Negate one mapped condition.
def _negate_condition(text: str) -> str:
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
        return '(' + ' or '.join(_negate_condition(x) for x in parts) + ')'
    parts = _logic_parts(core, 'or')
    if len(parts) > 1:
        return _conjunction([_negate_condition(x) for x in parts])
    return f'!({value})'

# Map one Jason plan context.
def _map_context(context: str, role_cfg: Mapping[str, Any], environment_name: str) -> Optional[str]:
    predicates = role_cfg.get('plan', {}).get('predicates', {})
    parts: List[str] = []
    for piece in fmt.split_top(context, '&'):
        item = piece.strip()
        if not item or item == 'true':
            continue
        negated = item.startswith('not ')
        term = fmt.parse_term(item)
        if term is None or term.name not in predicates:
            return None
        expr = fmt.semantic_expr(predicates[term.name], environment_name)
        value = _negate_condition(expr) if negated else expr
        if value == 'false':
            return 'false'
        if value != 'true':
            parts.append(value)
    return _conjunction(parts)

# Map the plan's primitive action.
def _map_action(terms: Sequence[Term], role_cfg: Mapping[str, Any]) -> Optional[str]:
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

##### Phase 2: Generate protocol #####
# Keep only Jason-selected legal actions.
# Test input: baseline true:{move,rescue,rest}, goal=rescued, context=buried & at_area_2, action=rescue.
# Test output: goal=rescued and Environment.buried=true and Environment.area=area_2 : {rescue}.
def generate_protocol(spec: AgentSpec, mapping: Mapping[str, Any], info: Optional[ModelContext] = None, baseline_protocol: Optional[Sequence[Tuple[str, List[str]]]] = None, environment_name: Optional[str] = None):
    role_cfg = mapping['jason']['roles'][spec.role_key]
    if relation.uses_relation(role_cfg):
        if info is None:
            raise ValueError('Relation-aware plan compilation requires model relation data')
        return relation.generate_protocol(spec, mapping, info)
    if baseline_protocol is None or environment_name is None:
        raise ValueError('Plan compilation requires the baseline protocol and environment name')

    # B <- baseline guards indexed by action.
    baseline_by_action: Dict[str, List[str]] = {}
    for condition, actions in baseline_protocol:
        for action in actions:
            baseline_by_action.setdefault(action, []).append(condition)

    # P <- empty; group plans by triggering goal.
    protocol_rules: List[Tuple[str, List[str]]] = []
    plans_by_goal: Dict[str, List[Plan]] = {}
    for plan in spec.plans:
        plans_by_goal.setdefault(plan.goal, []).append(plan)

    # For every goal-control value except done.
    for goal in [value for value in spec.control.values if value != 'done']:
        # higher <- contexts of earlier plans for this goal.
        higher: List[str] = []
        # Process plans in source order.
        for plan in plans_by_goal.get(goal, []):
            # c <- MapContext; a <- MapAction.
            context = _map_context(plan.context, role_cfg, environment_name)
            action = _map_action(plan.terms, role_cfg)
            if context is None:
                continue

            # e <- c AND NOT each higher-priority context.
            effective_guard = context
            if context != 'false':
                effective_guard = _conjunction([context] + [_negate_condition(previous) for previous in higher if previous != 'false'])

            # If a exists and e is possible, combine it with B[a].
            if action is not None and effective_guard != 'false':
                baseline_guards = baseline_by_action.get(action, ['true'] if action in role_cfg.get('plan', {}).get('extra_actions', []) else [])
                for baseline_guard in baseline_guards:
                    # q <- (goal=g) AND e AND b.
                    condition = _conjunction([f"{role_cfg['goal_var']} = {goal}", effective_guard, baseline_guard])
                    if condition != 'false':
                        protocol_rules.append((condition, [action]))
            # Append c to higher.
            higher.append(context)

    # Add configured pass-through actions.
    for action in role_cfg.get('plan', {}).get('pass_through', []):
        for condition in baseline_by_action.get(str(action), []):
            protocol_rules.append((condition, [str(action)]))
    for pattern in role_cfg.get('plan', {}).get('pass_through_patterns', []):
        rx = re.compile(str(pattern))
        for action, conditions in baseline_by_action.items():
            if rx.fullmatch(action):
                protocol_rules.extend((condition, [action]) for condition in conditions)

    # Return Unique(P).
    unique_rules: List[Tuple[str, List[str]]] = []
    seen = set()
    for condition, actions in protocol_rules:
        key = (condition, tuple(actions))
        if key not in seen:
            seen.add(key)
            unique_rules.append((condition, actions))
    return unique_rules

# Map an optional transition condition.
def _map_condition(condition: Any, environment_name: str) -> str:
    return fmt.semantic_expr(condition, environment_name)

##### Phase 3: Generate evolution rules #####
# Update the active Jason task stage.
# Test input: saved calls rescued; configured transitions are rescued--rescue->notified and notified--notify->done.
# Test output: the three goal evolution rules shown in the paper and unit test.
def generate_evolution_rules(spec: AgentSpec, mapping: Mapping[str, Any], info: Optional[ModelContext] = None, environment_name: Optional[str] = None):
    role_cfg = mapping['jason']['roles'][spec.role_key]
    if relation.uses_relation(role_cfg):
        if info is None:
            raise ValueError('Relation-aware evolution compilation requires model relation data')
        return relation.generate_evolution_rules(spec, mapping, info)
    if environment_name is None:
        raise ValueError('Evolution compilation requires the environment name')

    # R <- empty; V <- spec.control.values.
    rules: List[str] = []
    goal_values = set(spec.control.values)
    goal_var = str(role_cfg['goal_var'])

    # For each plan represented in V.
    prior: Dict[str, List[str]] = {}
    for plan in spec.plans:
        if plan.goal not in goal_values:
            continue
        # c <- MapContext(p.context, role).
        context = _map_context(plan.context, role_cfg, environment_name)
        if context in (None, 'false'):
            continue
        # h <- first achievement goal in Body(p) that is in V.
        child = next((fmt.clean_name(term.name) for term in plan.terms if term.op == '!' and fmt.clean_name(term.name) in goal_values), None)
        # Add goal <- h if (goal=p.goal) AND c.
        if child is not None:
            guards = [f'{goal_var} = {plan.goal}', context]
            if role_cfg.get('plan', {}).get('ground'):
                guards.extend(_negate_condition(x) for x in prior.get(plan.goal, []))
            condition = _conjunction(guards)
            if condition != 'false':
                rules.append(f'        {goal_var} = {child} if {condition};')
        prior.setdefault(plan.goal, []).append(context)

    # For each configured transition tau.
    for transition in role_cfg.get('plan', {}).get('transitions', []):
        # w <- MapCondition(tau.when), true when omitted.
        when = _map_condition(transition.get('when', True), environment_name)
        if when == 'false':
            continue
        # c <- (goal=tau.from), plus Action when configured.
        condition_parts = [f"{goal_var} = {transition['from']}"]
        action = transition.get('action')
        if action is not None:
            mapped_action = role_cfg.get('plan', {}).get('actions', {}).get(str(action), action)
            condition_parts.append(f"{role_cfg['ispl_agent']}.Action = {mapped_action}")
        # Add goal <- tau.to if c AND w.
        condition = _conjunction(condition_parts + [when])
        rules.append(f"        {goal_var} = {transition['to']} if {condition};")

    # Return Unique(R).
    return fmt.unique(rules)

##### Phase 4: Replace agent decision model #####
# Insert generated decision blocks into the baseline model.
# Test input: baseline Rescuer + Observer and one replacement block for Rescuer.
# Test output: Rescuer is replaced and Observer is unchanged.
def replace_agent_decision_model(baseline_model: str, agent_blocks: Mapping[str, str]) -> str:
    # M_J <- M_B.
    guided_model = baseline_model
    # Replace each translated agent block.
    for agent_name, block in agent_blocks.items():
        guided_model = fmt.replace_ispl_agent(guided_model, agent_name, block)
    # Return M_J.
    return guided_model

def translate(config_path: Path, raw_override: Optional[Path] = None, output_override: Optional[Path] = None, program_overrides: Optional[Mapping[str, Path]] = None) -> Tuple[Path, Dict[str, AgentSpec]]:
    mapping = fmt.load_mapping(config_path)
    files = mapping['files']
    raw_path = raw_override or fmt.resolve_path(config_path, str(files['raw']))
    output_path = output_override or fmt.resolve_path(config_path, str(files['output']))
    raw = fmt.read_text(raw_path)
    vocabulary = mapping['jason'].get('vocabulary', {'actions': {}, 'predicates': {}})
    roles = mapping['jason']['roles']
    overrides = dict(program_overrides or {})

    specs: Dict[str, AgentSpec] = {}
    for role_key, role_cfg in roles.items():
        program_path = overrides.get(role_key) or fmt.resolve_path(config_path, str(role_cfg['program']))
        program = fmt.read_text(program_path)
        if role_cfg.get('plan', {}).get('ground'):
            program = fmt.ground_program(program, role_cfg['plan']['ground'])
        plans, top = fmt.read_plans(program, str(role_cfg['entry_goal']))
        control = build_goal_control(plans, top, role_cfg, vocabulary)
        specs[role_key] = _build_agent_spec(role_key, plans, control, role_cfg, vocabulary)

    relation_roles = [key for key, cfg in roles.items() if relation.uses_relation(cfg)]
    info = relation.inspect_model(raw, mapping) if relation_roles else None
    out = raw
    if relation_roles:
        if 'coordination' in mapping:
            out = relation.patch_environment(out, mapping, info)
            out = relation.rewrite_init(out, mapping, info, specs)
        blocks = {}
        for key in relation_roles:
            protocol = generate_protocol(specs[key], mapping, info)
            evolution = generate_evolution_rules(specs[key], mapping, info)
            blocks[info.roles[key].agent_name] = relation.build_agent_block(specs[key], mapping, info, protocol, evolution)
        out = replace_agent_decision_model(out, blocks)

    environment_name = str(mapping.get('model', {}).get('environment_agent', 'Environment'))
    plain_roles = [key for key in roles if key not in relation_roles]
    if plain_roles:
        blocks = {}
        for key in plain_roles:
            spec = specs[key]
            agent = str(roles[key]['ispl_agent'])
            _, _, baseline_protocol, _ = fmt.parse_agent_decision(out, agent)
            protocol = generate_protocol(spec, mapping, baseline_protocol=baseline_protocol, environment_name=environment_name)
            evolution = generate_evolution_rules(spec, mapping, environment_name=environment_name)
            blocks[agent] = fmt.build_plain_agent_block(spec, mapping, out, protocol, evolution)
        out = replace_agent_decision_model(out, blocks)
        out = fmt.rewrite_plain_init(out, {key: specs[key] for key in plain_roles}, roles)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out, encoding='utf-8')
    return output_path, specs

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
