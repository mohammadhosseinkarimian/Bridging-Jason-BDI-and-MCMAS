# `relation_translation.py`: movement relations and coordinated rescue decisions

## Why this module exists

`jason_guided.py` contains the translation workflow. `formatting.py` parses source files and assembles the resulting ISPL. Neither is enough for the **relation-aware rescue examples**, because their movement actions are tied to an actual map and their plan priorities refer to classes of destinations rather than directly to one fixed ISPL action. This module handles that additional problem.

For example, a FireBrigade Jason plan may prefer an unvisited collapsed building. But the ISPL action set contains concrete names such as `fb_move_to_2`, and movement between locations must follow the existing roads. To translate that plan we need to know which areas are connected, what kind of area each destination is, whether it has already been visited, and how to reach a known civilian or a refuge. Those decisions cannot be produced by renaming `move_to(Pos)` alone.

This file is therefore a **specialized protocol and control-rule generator**, not just a formatting utility or a collection of unrelated helpers. It is selected by `role.plan.relation: true`. In this repository that is the path used by `three_area`, `custom2`, and `abstract`. The CAGE examples and `exact95` use the ordinary direct-mapping path instead. The module is significant implementation code, but the main translation phases are still orchestrated by `jason_guided.py`.

## Information collected from the baseline

`inspect_model(raw, mapping)` constructs a `ModelContext`. Its fields are the Environment agent name, location/domain members, important target and endpoint anchors, role-specific movement information, and the inferred labels of locations.

Each `RoleContext` records an internal role key, target MCMAS agent name, location state variable, starting location, available movement relation, and any original local-variable declarations. The context makes it possible to generate agent rules without hard-coding one specific map or set of area identifiers into the Python file.

The supporting functions do the following:

- `_init_body` and `_init_value` read initial assignments from `InitStates`.
- `_parse_members` reads possible location names from the configured environment enumeration, for example `area_1`, `area_2`, and `area_3`.
- `_member_token` applies the configured `token_regex`, while `_action_for_member` turns a location name into an action using `move_template`.
- `_parse_base_vars` retains existing local variables from the original agent.
- `_parse_relation` examines each role's baseline protocol guards and movement actions to build a location adjacency relation. The output is a dictionary from a current location to the destinations allowed by that role's baseline movement rules.
- `_parse_member_labels` classifies locations using configured declaration patterns or initial-state fields. The classification can distinguish roads, collapsed buildings, damaged buildings, and other location types.

A crucial point is that the map comes from the **baseline protocol**, not from arbitrary destinations mentioned in Jason. Consequently, the relation-aware translator can restrict search preferences without simply allowing illegal moves across disconnected locations.

## Finding paths through the relation

`_relation_steps(relation, focus)` computes distance information using a breadth-first traversal from a target over the reverse movement relation. For every starting location, it then identifies the available neighbours that reduce the distance to the target. Keeping all equally good neighbours matters because more than one shortest next step may be legal.

`_path_protocol_lines` uses those steps to produce rules toward a selected target, such as the civilian's location or the refuge. If no shortest-path step is available, it falls back to outgoing baseline neighbours; if there are none, it falls back to the configured idle action. For some AmbulanceTeam states, the method can also append `rest` to the available choices.

This part of the module solves a concrete task: move toward a known objective while respecting the movement graph supplied by the baseline. It does not plan over the entire future network or optimize an arbitrary reward function.

## Converting Jason patrol priority to movement rules

The main translator has already extracted a `ranking_order` from Jason plans and the JSON classifiers. This module turns that order into guards on concrete movement actions.

`_ranking_rank` maps a destination's model label to its position in that extracted ranking. `_ranking_protocol_lines` iterates over all current locations and their baseline neighbours. It builds a movement rule for an unvisited neighbour when the agent is in its top-level task and has not yet learned the civilian's location. Higher-ranked alternatives must already have been marked visited before lower-ranked options become eligible. Neighbours of equal rank are not automatically excluded from one another.

The resulting rules also use a `marker_var_template`, such as `fb_visited_{member}`. `_marker_evolution_lines` updates these Boolean markers when the corresponding movement action occurs. This creates the finite exploration memory needed to represent search preferences in MCMAS.

In the three-area example, two collapsed buildings can have the same rank. Both movement rules are then enabled in the initial state. This is intentional. ATL still has alternative strategies to compare, rather than a single hard-coded search trace.

## Coordinating the two rescue roles

The mapping names a `primary_role` and `secondary_role`. In the supplied RCRS configuration these correspond to FireBrigade and AmbulanceTeam. `_coordinated_roles` reads those keys. The functions `_env_ref`, `_role_ref`, `_role_action_ref`, `_role_state_ref`, `_action_name`, and `_var_name` turn configured concepts into the appropriate ISPL variable or action names.

The other small guard helpers use the same configuration: `_level_condition` and its positive/continuing forms handle buriedness values, `_final_guard` identifies completed or failed rescue states, and `_completion_guard` identifies the relevant final delivery action. These helpers keep the large generated protocol rules consistent with the variable names supplied by the example.

`generate_protocol` has one branch for each coordinated role:

**FireBrigade branch.** The agent can rest in terminal states, report that a civilian is ready, rescue when it knows the civilian is buried and is at the correct location, and move toward the civilian when it knows the target but has not arrived. When the target is unknown, it uses the ranked patrol movement rules. A fallback `Other` rule keeps an idle option where the mapped task rules do not apply.

**AmbulanceTeam branch.** The agent can report a buried civilian to FireBrigade, move toward the civilian for pickup, load when the civilian is at the surface, move toward the refuge, and unload at the endpoint. It also includes states for waiting while rescue or reports are still needed and ranked search rules when the civilian has not been found.

These branches are why the file is relatively large. They implement actual movement and coordination cases, not merely utilities for `jason_guided.py`.

## Updating task stages

`generate_evolution_rules` produces updates for the role's goal-control variable and its visited markers. A FireBrigade can move from search into rescue, from rescue into a notification stage, and eventually to `done`. The AmbulanceTeam has stages for reporting, pickup, and delivery. The updates depend on mapped actions such as rescue, notify, load, and unload, as well as the relevant rescue-state conditions.

For instance, after a successful load action, the AmbulanceTeam's control state can move from its pickup stage to its delivery stage. When it unloads, that stage can complete. If the civilian dies, the appropriate end condition can terminate the task. Those control transitions sit alongside the physical evolution rules already present in the baseline Environment block; they do not replace the physical meaning of loading or rescue.

## Shared memory and communication

`_shared_memory_variables` lists the Environment Boolean flags required for communication and remembered knowledge. The names come from the mapping and include both roles' knowledge of the civilian's buried location, a report flag to FireBrigade, a readiness flag to AmbulanceTeam, and the AmbulanceTeam's knowledge of the refuge.

`_generate_shared_evolution_rules` writes the corresponding persistence and learning rules. For example, an agent can remember a buried civilian after being at the right location or receiving the relevant report. The readiness flag can be set by FireBrigade's notification action. `patch_environment` adds the Boolean declarations and rules to the Environment block. It also adds position-preserving evolution cases for the new notification actions so they do not accidentally change an agent's location.

`rewrite_init` initializes these shared memory flags, each translated agent's goal-control variable, and visited-location markers. A starting location is marked visited; the remaining markers start false. For the refuge knowledge flag, the initialization also takes account of whether the AmbulanceTeam starts at the refuge.

This is more than text assembly. These extra Boolean variables are the actual finite memory the generated MCMAS model uses for the selected beliefs and coordination state.

## Constructing the final relation-aware agents

`build_agent_block` assembles a replacement `Agent` block with the original local variables, a new goal-control variable, visited-location Booleans, the configured movement and non-movement actions, the generated protocol, and the generated evolution rules. It uses `formatting.action_set` for the action declaration layout.

The overall sequence is:

```text
Baseline ISPL and relation mapping
  -> inspect locations, movement rules, labels, anchors and starts
  -> read Jason-derived stage and priority information
  -> generate ranked patrol and target-path protocols
  -> generate task and visited-marker evolution rules
  -> add shared rescue communication memory
  -> initialize new variables
  -> replace the selected agent blocks
```

## What is general and what is rescue-specific

The general idea is reusable: inspect a structured relation in the baseline, map Jason priorities to its members, and produce rules that preserve legal alternatives. The **current code**, however, is specifically configured around two coordinated rescue roles and state concepts such as buriedness, alive/dead, loading, reporting, and refuge delivery. It would be misleading to describe it as a generic relation translator for arbitrary domains without adding new role and state handling.

For a new domain whose Jason actions already map directly to finite ISPL actions, `plan.relation` is normally unnecessary. The ordinary path in `jason_guided.py` is simpler. This module is needed only when the policy depends on relational information such as map connectivity and ranked search that is not captured by one-to-one action names.

See [`jason_guided.md`](jason_guided.md) for the overall algorithm and [`../examples/MAPPING_GUIDE.md`](../examples/MAPPING_GUIDE.md) for the relation mapping's fields.
