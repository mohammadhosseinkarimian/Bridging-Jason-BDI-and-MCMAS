# `jason_guided.py`: main translation workflow

## Purpose

This is the entry point for producing a Jason-guided MCMAS model. It reads one baseline ISPL file and a JSON mapping, extracts the relevant Jason plans, builds finite task-control information, generates restricted decision rules, and writes a new ISPL model. The baseline supplies the environment and legal domain actions. The mapping supplies the correspondence to Jason. The output is a **guided decision model**, not a complete execution trace of the original Jason program.

The translation follows four main phases: building task control, generating a protocol, generating control evolution rules, and replacing the selected agent decision blocks. The file also contains the configuration and command-line handling that joins those phases.

## Main command and output

From the repository root:

```bash
python3 src/jason_guided.py --config examples/Cage1-small/input/jason_mapping.json
```

The program prints the output path, the entry task goal, the control values, and the ranking order when the role uses ranking. It writes the guided ISPL to the location given by `files.output` in the mapping.

The command supports three optional overrides:

```bash
python3 src/jason_guided.py \
  --config examples/Cage1-small/input/jason_mapping.json \
  --raw /path/to/other_baseline.ispl \
  --output /path/to/new_guided.ispl \
  --program blue=/path/to/blue_agent.asl
```

`--program` takes `ROLE=PATH`, where `ROLE` must match a key in `jason.roles`. It may be repeated for multiple roles. An override changes the source used by this run, not the JSON on disk.

## Data carried between phases

The parser in `formatting.py` gives us `Plan` records containing a triggering goal, context, body terms, and original order. `GoalCall` represents one achievement-goal call. `GoalControl` stores the entry task, reachable goals, goal-call edges, and the subset of goals that need distinct task stages. `AgentSpec` combines this information with the translation role and any extracted ranking order. The main file passes these records to the protocol and evolution-rule generators.

## Phase 1: `build_goal_control`

The function groups plans by triggering goal and starts at the configured top-level task. Its nested `visit` function recursively follows achievement-goal body terms, recognized by `!`. The `seen` set avoids revisiting a goal. It records the reachable goals and parent-child calls in source and body order.

It does **not** give every reachable goal an ISPL state variable. The list of goal-control *values* starts with the top goal, adds goals requested by configured stage categories, adds reachable goals containing directly mapped actions when the role has a direct `plan` mapping, and finally adds `done`. This distinction matters because a helper goal can be needed for discovering a primitive action without needing its own control state.

The helpers `_goal_with_action`, `_infer_ranking_goal`, and `_infer_ranking_order` support stage selection and relation-aware ranking. The ranking function examines relevant Jason plan contexts in source order and matches them against configured categories such as collapsed building, damaged building, road, or visited area. `AgentSpec` stores the result for later use. CAGE direct mappings generally do not use this ranking branch.

## Mapping plan contexts and actions

The direct-mapping path uses `_map_context` to turn a Jason context into a condition over the ISPL model. It splits top-level `&` conditions, reads each predicate, looks it up under `role.plan.predicates`, and converts the configured semantic expression through `formatting.semantic_expr`. The helpers `_logic_parts`, `_outer`, `_conjunction`, and `_negate_condition` keep simple conjunctions, disjunctions, and negations in a form suitable for ISPL.

If a required predicate has no mapping, `_map_context` returns `None`. The corresponding direct-mapping plan is skipped. If a mapped condition is explicitly false, the corresponding rule is not generated. This is important when interpreting the output: a missing rule can reflect an incomplete mapping, rather than a judgment that the plan is impossible in Jason.

`_map_action` examines the parsed plan body and returns the first primitive action with an entry in `role.plan.actions`. Belief updates and test goals are skipped; listed diagnostic or communication calls may be ignored through `ignore_actions`. A subgoal can interrupt this direct lookup because following helper-goal execution is not the same as having a directly mapped primitive action in the current body. We only model what the configured translation represents.

## Phase 2: `generate_protocol`

For the ordinary path, the function first parses baseline protocol rules into a table of **action to legal guards**. It then visits the selected plans for each goal-control value. For each mapped plan, it combines three conditions:

1. The translated task-control variable is at the relevant goal.
2. The Jason plan context is satisfied, excluding the mapped contexts of earlier applicable plans for the same goal.
3. The action was already enabled under a corresponding baseline guard.

The third condition is necessary because Jason plan selection should not invent new physical or network actions. A rescue action that is not legal in the baseline cannot be made legal merely by writing a Jason plan that chooses it.

For example, if the baseline allows `{move, rescue, rest}`, but the mapped rescue plan applies when `goal = rescued`, the resulting rule can enable `{rescue}` under that guard. Higher-priority applicable plans exclude lower-priority mapped alternatives in the direct-mapping case.

After generating those plan rules, the function adds the baseline guards of any actions in `pass_through` or matching `pass_through_patterns`. It then removes duplicate `(condition, actions)` pairs. **Pass-through actions are not evidence that the Jason policy selected them.** In `Cage1-small`, restoration is kept as a pass-through option, which is why the small model can retain more than one action on Blue's first turn.

If `role.plan.relation` is true, this function hands protocol generation to `relation_translation.generate_protocol` instead. That specialized branch does not follow the same direct guard-building loop.

## Phase 3: `generate_evolution_rules`

A protocol determines which action is available; it does not keep track of which part of a task is active next. The evolution generator supplies that missing task-control memory.

The ordinary path handles two kinds of updates. First, a plan whose body calls a reachable achievement subgoal can enter that subgoal when its context holds. Second, `role.plan.transitions` explicitly specifies changes that happen after a mapped action or an optional `when` condition. The function produces ISPL evolution-rule text such as:

```ispl
blue_goal_level = secure_network if
    blue_goal_level = secure_Op_Server0 and
    Blue.Action = restore_Op_Server0;
```

For grounded plans, it also uses recorded prior contexts when generating relevant subgoal transitions. It does not infer all runtime goal completion rules from Jason syntax; the mapping supplies the transitions that are needed by the finite model.

When the role uses `plan.relation`, evolution generation is delegated to `relation_translation.generate_evolution_rules`, because rescue, reporting, loading, and map exploration need their own coordination logic.

## Phase 4: `replace_agent_decision_model`

This function starts with the baseline text and replaces each translated `Agent ... end Agent` block with the assembled guided block. It does not replace unselected agents. In the plain branch, `formatting.build_plain_agent_block` adds the goal variable, optional extra actions, the new protocol, and the task evolution rules. `formatting.rewrite_plain_init` inserts the initial goal state into `InitStates`.

In the relation-aware branch, the program additionally uses `relation_translation.inspect_model` to read the movement domain, `patch_environment` to insert shared memory and communication rules, `rewrite_init` to initialize those variables and visited markers, and `build_agent_block` to assemble the role-specific agents. These extra environment changes implement **mapped knowledge and task state**; the original physical effects are not redefined from Jason.

## `translate`: the orchestration function

`translate` puts the steps together:

```text
Read the mapping and baseline
  -> read and optionally ground each Jason program
  -> parse selected plans
  -> extract goal-control and role specifications
  -> inspect relation-aware models, when configured
  -> generate protocols and evolution rules
  -> replace translated agent blocks
  -> add goal and memory initializations
  -> write the resulting ISPL
```

It processes relation-aware roles first and ordinary roles afterwards. The direct branch parses the baseline agent's own protocol to recover action legality. The relation-aware branch obtains the movement relation from the baseline and uses the configured semantic roles and shared memory variables. Both routes produce an output file that MCMAS can check.

## `main`: command-line interface

`main` defines the `--config`, `--raw`, `--program`, and `--output` arguments, resolves the supplied paths, calls `translate`, and prints a short summary. It is intentionally thin: the translation logic stays in functions that can be called and tested independently.

## Assumptions and limitations

The parser and context mapper handle the supported subset of AgentSpeak syntax, not the entire Jason language. In particular, grounding is configured, plan priority is approximated through mapped source order, and unrecognized contexts are not translated automatically. The output can include fallback and pass-through decisions outside the selected plans. A successful run confirms that the generated ISPL file was written; it does not confirm an ATL property or that every behavior of the actual Jason interpreter was reproduced.

There is also a separate `test_jason_guided.py` file in this directory. It uses four unit tests to check the four main translation phases on small constructed inputs. Run it with:

```bash
python3 -m unittest discover -s src -p 'test_*.py' -v
```

Those tests cover the basic phase behavior. For complete experiments, I also compare the generated ISPL with the intended baseline and run MCMAS on both versions.

See [`formatting.md`](formatting.md) for parser and ISPL assembly details, [`relation_translation.md`](relation_translation.md) for map-aware behavior, and [`../examples/MAPPING_GUIDE.md`](../examples/MAPPING_GUIDE.md) for the meaning of configuration fields.
