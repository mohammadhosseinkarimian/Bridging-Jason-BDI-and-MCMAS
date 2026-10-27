# Jason-to-MCMAS mapping files

## Why the mapping is needed

Jason and MCMAS represent the same decision problem at different levels. In Jason, I write plans using beliefs and actions such as `host_state(Host, _, "privileged")`, `restore(Host)`, or `move_to(Pos)`. In ISPL, I need explicit finite variables and action names, such as `Environment.compromised_Op_Server0` and `restore_Op_Server0`. The translation cannot infer that correspondence from the spelling alone. It also cannot infer which beliefs we intend to remember or which baseline actions should remain available independently of Jason.

The JSON mapping provides those decisions without hard-coding a separate translator for every network or rescue map. It tells the translator **what source to read**, **which Jason decisions to include**, **what each mapped term means in ISPL**, and **where to write the guided model**. A mapping is part of the model specification: changing it can change the reachable states and ATL results without changing the Jason program.

## Top-level structure

```json
{
  "files": {
    "raw": "cage1_baseline.ispl",
    "output": "../generated/cage1_jason_guided.ispl"
  },
  "model": {"environment_agent": "Environment"},
  "jason": {
    "vocabulary": {"actions": {}, "predicates": {}},
    "roles": {"blue": {"program": "../../../agents/blue_agent.asl"}}
  }
}
```

This is an explanatory fragment, not a complete runnable mapping. The specific example files supply the remaining required keys.

| Key | Meaning and use |
| --- | --- |
| `files.raw` | Name or path of the baseline ISPL file. It is resolved relative to the JSON file unless absolute. |
| `files.output` | Destination of the generated ISPL model, usually `../generated/`. |
| `model.environment_agent` | Name of the Environment agent used when building qualified conditions, usually `Environment`. |
| `jason.vocabulary.actions` | Groups Jason action names into categories such as rescue or monitor. Used to recognize task stages and ranking signals. |
| `jason.vocabulary.predicates` | Groups predicate names into categories used in ranking and context recognition. |
| `jason.roles` | Dictionary of translated agent roles. Each key is an internal role identifier, not necessarily the name of an ISPL agent. |
| `format` | Only used in the relation-aware path for action-set indentation and line wrapping. It does not determine policy meaning. |
| `coordination` | Used by relation-aware rescue mappings to name shared memory flags, coordination actions, and the primary and secondary roles. |

## What one `role` means

The keys `blue`, `role_a`, and `role_b` are identifiers used to connect the mapping to the translator. They can be named differently as long as internal references are kept consistent. A role describes **one selected Jason source and one target ISPL agent**.

| Role field | Explanation |
| --- | --- |
| `program` | Relative path to the `.asl` program to read. |
| `ispl_agent` | Exact `Agent ...` name to replace in the baseline. For example, `Blue` or `FireBrigade`. |
| `entry_goal` | Configured entry event, often `step` or `observe_network`. The parser follows its first achievement-goal call to find the main task goal. |
| `goal_var` | Name of the new finite task-control variable, such as `blue_goal_level` or `fb_goal_level`. |
| `plan` | Rules for grounding terms, mapping actions and predicates, selecting the translation path, keeping pass-through choices, and updating goals. |
| `stages` | Relation-aware setting that locates the Jason goals associated with action categories such as rescue, notify, load, or unload. |
| `state_var` | Relation-aware role's location variable in the baseline, such as `fb_area`. |
| `actions` | Relation-aware dictionary containing movement templates and named rescue, report, load, unload, and rest actions. Do not confuse it with `plan.actions` for direct mapping. |
| `marker_var_template` | Pattern used for remembered-visit variables, such as `fb_visited_{member}`. |
| `ranking` | Relation-aware location priority information extracted from Jason plan contexts. |
| `plan.relation` | `true` selects the relation-aware implementation in `relation_translation.py`. Without it, `jason_guided.py` uses the ordinary mapped-plan implementation. |

## The direct-mapping path: CAGE and exact95

Here is a reduced version of the current `Cage1-small` mapping:

```json
{
  "jason": {
    "roles": {
      "blue": {
        "program": "../../../agents/blue_agent.asl",
        "ispl_agent": "Blue",
        "entry_goal": "observe_network",
        "goal_var": "blue_goal_level",
        "plan": {
          "ground": {
            "variable": "Host",
            "members": ["User0", "Op_Server0"],
            "values": ["no", "user", "privileged"],
            "signatures": {
              "secure": [0],
              "host_state": [0, 2],
              "restore": [0],
              "remove": [0]
            }
          },
          "actions": {
            "monitor": "monitor",
            "restore_Op_Server0": "restore_Op_Server0",
            "remove_Op_Server0": "remove_Op_Server0"
          },
          "predicates": {
            "secure_User0": true,
            "secure_Op_Server0": {"eq": [{"env": "compromised_Op_Server0"}, "no"]},
            "host_state_Op_Server0_privileged": {"eq": [{"env": "compromised_Op_Server0"}, "privileged"]}
          },
          "pass_through": ["blue_wait", "restore_Op_Server0"],
          "fallback": "monitor",
          "transitions": [
            {"from": "secure_Op_Server0", "to": "secure_network", "action": "restore_Op_Server0"}
          ]
        }
      }
    }
  }
}
```

This example shows the meaning of the keys but omits some mappings and transitions. Use the full JSON file to run the translator.

### `plan.ground`

The Jason policy uses a parameter such as `Host`. `ground.variable` tells the code which variable to substitute, and `members` lists the concrete values to use in the selected model. In `Cage1-small`, this is `User0` and `Op_Server0`. The translator expands relevant `+!` plans and normalizes configured predicates and actions into names it can match.

`signatures` maps a predicate or action name to **argument indexes counted from zero**. For example, `host_state: [0,2]` means the host argument and the reported compromise argument, while `restore: [0]` means the host argument only. The generated normalized names resemble `host_state_Op_Server0_privileged` and `restore_Op_Server0`. `values` lists additional non-host values that are allowed while normalizing arguments, here `no`, `user`, and `privileged`.

Grounding is a configured textual transformation, not a complete AgentSpeak unification engine. Only the selected signatures and parseable terms are included. If the mapping omits a needed predicate or action, that part of the plan is not automatically recovered.

### `plan.actions` and `plan.predicates`

`plan.actions` maps normalized Jason primitive actions to existing ISPL action names. For example, `restore_Op_Server0` maps to the Blue action with the same name. The generated protocol must also respect the baseline guard for that action.

`plan.predicates` maps normalized Jason context predicates to ISPL conditions. Its values may be `true`, `false`, a condition string, or a structured expression. A structured expression such as

```json
{"eq": [{"env": "compromised_Op_Server0"}, "privileged"]}
```

becomes `Environment.compromised_Op_Server0 = privileged`. The formatter also supports `neq`, `all`, `any`, and `not`. Here `{"env": "x"}` identifies an Environment variable, while an ordinary string or `{"value": "x"}` represents a value or expression. These conditions express the *modeled meaning* of the belief. They do not recreate the full Jason belief base.

### `plan.transitions`, `fallback`, and pass-through choices

A `transitions` entry gives a task-stage update. Its `from` and `to` are values of the new goal-control variable. Its optional `action` requires a matching agent action, and `when` adds a condition if supplied. For example, after `restore_Op_Server0`, Blue can move from `secure_Op_Server0` back to `secure_network`.

`fallback` is an ISPL action emitted as `Other: {action}` when building the guided protocol. `pass_through` copies the baseline guards for specific actions, regardless of whether a translated plan selected them. `pass_through_patterns` does the same for baseline actions matching a regular expression. `ignore_actions` excludes specified source actions when looking for mapped primitive actions. `extra_actions` can add actions to the generated agent declaration in the ordinary path, and should only be used when intentionally extending that declaration.

This is a substantive modeling choice. In `Cage1-small`, `restore_Op_Server0` is retained as a pass-through action, so it can remain available outside the plan condition for restoration. It would be wrong to describe every guided restore action as a decision forced by Jason. Likewise, several `exact95` movements are passed through rather than generated from a navigation algorithm.

## The relation-aware path: RCRS three_area, custom2, and abstract

In these configurations `plan.relation` is `true`. The translator uses the baseline movement protocols and configured domain naming to find a graph of locations and possible moves. It then uses Jason plan priorities to rank candidate destinations, chooses legal next steps toward a target, and builds shared communication and task-control updates. This behavior belongs to the rescue-specific relation translation module.

The keys are related as follows:

| Setting | What it represents |
| --- | --- |
| `model.domain.enum_var` | An enumerated baseline variable from which location names are extracted, such as `fb_area`. |
| `model.domain.value_regex` | Regular expression matching valid location values, for example `area_\d+`. |
| `model.domain.token_regex` | Parses a location name into pieces used to generate a movement action. |
| `model.anchors` | Identifies the target civilian location and endpoint/refuge, either from fixed values or initial-state variables. |
| `model.variables` | Correspondence for semantic concepts such as alive, dead, loaded, delivered, buriedness, civilian position, and refuge. |
| `model.level` | Names the zero, final, positive, and continuing buriedness levels used in rescue guards. |
| `model.member_labels` | Classifies locations as road, collapsed building, damaged building, etc., using declarations or initial-state values. |
| `roles.<role>.state_var` | The role's position variable, `fb_area` or `at_area`. |
| `roles.<role>.actions.move_template` | Creates actions such as `fb_move_to_2` from a location token. |
| `roles.<role>.actions.move_regex` | Recognizes movement actions in baseline protocol rules so that connectivity can be read from the model. |
| `roles.<role>.stages` | Associates a stage key such as `work` or `finish` with an action category from Jason. |
| `roles.<role>.ranking` | Configures which Jason plan contexts indicate movement preference and how locations are grouped into classes. |
| `roles.<role>.marker_var_template` | Defines visited-location Boolean variables. |
| `format` | Controls ISPL action-list layout only. |
| `coordination` | Connects the two rescue roles and names notification, readiness, and remembered-location flags. |

### Why there are two roles

In `three_area`, `role_a` maps to `Agent FireBrigade` and `role_b` to `Agent AmbulanceTeam`. The mapping's `coordination.primary_role` and `coordination.secondary_role` refer to these role keys. The translator needs that relation to know which role performs the rescue and readiness notification and which role handles pickup, transport, and reports. The role labels are not automatically inferred from the Python function names or the Jason filenames.

### Ranking and paths

The translator extracts the movement graph from baseline rules, rather than assuming all locations are connected. It uses the configured classifiers to relate Jason patrol conditions such as `collapsed`, `damaged`, `building`, `road`, and `not visited` to the location labels in the model. It can leave two equally ranked alternatives available, which is important for ATL: the guided model is not reduced to a single predetermined path.

When a task has a known target, it computes shortest paths in the extracted relation and enables movement toward that target. It also remembers visited locations, sets mapped communication flags when agents report information, and adds goal-stage transitions for rescue, notification, pickup, and delivery. These are finite approximations of the relevant planning and communication state, not the entire Jason runtime.

## Editing a mapping safely

1. Check that `files.raw` points to the intended baseline and `files.output` goes to a separate generated file.
2. Check that every `ispl_agent` exists in that baseline and every mapped action is declared in the corresponding agent.
3. Check that the `entry_goal` exists in the selected `.asl` program and that reachable `+!` plans can be parsed.
4. Check the semantics of each predicate translation. An incorrectly mapped belief changes the policy being verified.
5. Review `pass_through` and `fallback`, since they can retain choices that are not selected by the Jason plans.
6. For relation-aware mappings, check the anchors, location name patterns, movement action patterns, and shared memory variable names.
7. Regenerate the guided file, inspect the changed protocols and initial conditions, and check both models with MCMAS.

A successful translation means the output file was written. It does not by itself establish model equivalence, the correctness of an ATL result, or full correspondence to the runtime behavior of a Jason agent.
