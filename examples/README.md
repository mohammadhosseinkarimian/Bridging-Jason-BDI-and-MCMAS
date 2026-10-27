# Example models and experiment directories

This directory holds ready-to-translate examples. Each experiment has a baseline MCMAS model, the configuration connecting it to Jason, and a generated Jason-guided model. The baseline says what the agents *can* do under the modeled domain rules. The guided model restricts selected decisions according to the mapped Jason plans. We use the same verification questions on both models to see which strategic abilities remain.

## Standard directory layout

```text
examples/<scenario>/
├── input/
│   ├── <baseline>.ispl
│   └── jason_mapping.json
└── generated/
    └── <baseline>_jason_guided.ispl
```

`input/` contains the model that we translate, along with its mapping. `generated/` contains the translator's output. The mapping's `files.raw` and `files.output` are relative to the folder containing the mapping. Some experiment directories contain additional model-checker outputs; those are inspection artifacts rather than translator inputs.

## RCRS examples

### `three_area/`

The three-area rescue running example, with a refuge at `area_1` and two collapsed buildings at `area_2` and `area_3`. It includes FireBrigade and AmbulanceTeam roles and a buried civilian. We use it to inspect the relation-aware translation in a small setting. Importantly, the two search movements can remain enabled together when they have equal priority. The mapping contains a movement domain, location ranking, an objective location, a refuge, and shared communication memory.

Files: `input/three_area_raw.ispl`, `input/jason_mapping.json`, and `generated/three_area_jason_guided.ispl`.

### `custom2/`

Another compact rescue configuration, useful for checking how movement relations, map anchors, and translated goal stages behave on a different small topology. It also uses the relation-aware translation path. Its mapping still identifies the primary rescue role, the secondary transport role, and the memory flags that allow them to coordinate.

Files: `input/custom2_raw.ispl`, `input/jason_mapping.json`, and `generated/custom2_jason_guided.ispl`.

### `abstract/`

An abstract RCRS model with more domain locations and a relation-aware translation. It is useful for studying the search rules beyond the three-area running example. The translator reads the movement relation from the baseline protocols, classifies areas according to the configured map-label rules, and writes ranked search and task-stage updates.

Files: `input/abstract_raw.ispl`, `input/jason_mapping.json`, and `generated/abstract_jason_guided.ispl`.

### `exact95/`

The exact 95-area RCRS Test-map model. This example does **not** use `plan.relation: true`. Instead, it uses the ordinary mapped-plan path. The mapping selects rescue, loading, and unloading actions, while allowing configured movement actions to pass through. This distinction is important: `exact95` and `three_area` do not exercise the same protocol-generation branch, even though both are rescue scenarios.

Files: `input/raw-test.ispl`, `input/jason_mapping.json`, and `generated/raw-test_jason_guided.ispl`.

## CAGE Challenge 1 examples

### `Cage1-small/`

The smallest cyber-defence example, with `User0` and `Op_Server0`. The baseline contains Blue, Red, and Environment. Its recorded Blue compromise status is separate from the actual server access. The Environment can report or miss attacker activity. The mapping selects a small part of Blue's Jason program and retains a recovery action through `pass_through`, so the output should be interpreted as a partially guided policy.

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

### `Cage1-simple/`

A generated CAGE network with a larger set of host types than `Cage1-small`, but still convenient for inspecting the ISPL code. Its mapping contains grounded host-specific actions and compromise predicates. The input and output models are compared under the same attacker and Environment rules.

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

### `Cage1-complete/`

The larger generated CAGE network. Its mapping covers user, enterprise, operational, defender, and server hosts, with corresponding Blue actions and observations. It demonstrates how the baseline generator and grounding configuration scale to more hosts. A generated file is **not** evidence that the complete model has been successfully model-checked within a particular resource budget; measured results still require MCMAS output.

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

## What `jason_mapping.json` is doing

Every scenario has its own mapping because the same Jason source can be translated against different ISPL variables, action names, and host or location sets. The mapping specifies the source and output files, names the translated agent roles, chooses the Jason entry goal, defines the goal-control variable, and connects Jason terms to conditions and actions that exist in the baseline.

For example, the CAGE mappings use `roles.blue` to connect `agents/blue_agent.asl` to `Agent Blue`, while the three-area rescue mapping uses `roles.role_a` and `roles.role_b` for FireBrigade and AmbulanceTeam. The name `role_a` is a **configuration identifier**, not an MCMAS agent type. It lets the program find the correct role-specific settings.

The mapping also controls **how much of the Jason policy is represented**. `plan.actions` and `plan.predicates` describe directly translated decisions. `pass_through` preserves configured baseline actions even if they are not selected by a translated plan. `fallback` gives an action for otherwise unmatched states. `plan.relation` selects the relation-aware RCRS path. Consequently, two mappings pointing at the same `.asl` file can produce different guided decision models.

The full key-by-key explanation and examples are in [**MAPPING_GUIDE.md**](MAPPING_GUIDE.md).

## How to regenerate a model

Run these commands from the repository root:

```bash
python3 src/jason_guided.py --config examples/three_area/input/jason_mapping.json
python3 src/jason_guided.py --config examples/exact95/input/jason_mapping.json
python3 src/jason_guided.py --config examples/Cage1-small/input/jason_mapping.json
python3 src/jason_guided.py --config examples/Cage1-simple/input/jason_mapping.json
python3 src/jason_guided.py --config examples/Cage1-complete/input/jason_mapping.json
```

The translator prints the output path, discovered top goal, control values, and any extracted ranking order. `mcmas` then checks the `.ispl` files. Translation itself does not evaluate the ATL formulae.

To create **new baselines**, rather than translating the examples already supplied here, use `tools/rcrs/generate.py` or `tools/cage1/generate.py`. Their README files explain the inputs and resulting files.
