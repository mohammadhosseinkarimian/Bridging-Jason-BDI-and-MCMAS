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

The smallest cyber-defence example, with `User0` and `Op_Server0`. Its original baseline is unchanged: Red exploits, escalates, impacts the service, and retries after losing access. Recorded compromise remains separate from actual access, and Environment can report or miss activity. The reactive mapping retains server restoration as a recovery choice. Reachable states decrease from 20 to 12, but BDD memory is unchanged and runtime does not improve reliably.

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

### `Cage1-simple/`

A five-host network. Its directed Red policy attacks `Enterprise0` and then `Op_Server0`. Blue's reactive mapping selects those two targets. The input and output preserve identical attacker and Environment blocks. Reachable states decrease from 3,903 to 75.

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

### `Cage1-complete/`

The 13-host network: five users, three enterprises, three operational hosts, Defender, and the server. Red follows the directed route through `Enterprise2` to `Op_Server0`; the other hosts remain in the physical model. Blue's mapping focuses on the two attacked targets. Both models have been checked with MCMAS 1.3.0, including deadlock freedom and the five unchanged properties. Reachable states decrease from 32,559 to 75. Full timing, memory, logs, and limitations are in [`../docs/cage1_results.md`](../docs/cage1_results.md).

Files: `input/cage1_baseline.ispl`, `input/jason_mapping.json`, and `generated/cage1_jason_guided.ispl`.

## What `jason_mapping.json` is doing

Every scenario has its own mapping because the same Jason source can be translated against different ISPL variables, action names, and host or location sets. The mapping specifies the source and output files, names the translated agent roles, chooses the Jason entry goal, defines the goal-control variable, and connects Jason terms to conditions and actions that exist in the baseline.

For example, the CAGE mappings use `roles.blue` to connect `agents/blue_agent_reactive.asl` to `Agent Blue`, while the three-area rescue mapping uses `roles.role_a` and `roles.role_b` for FireBrigade and AmbulanceTeam. The name `role_a` is a **configuration identifier**, not an MCMAS agent type. It lets the program find the correct role-specific settings.

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
