# RCRS baseline and mapping generator

## What this tool produces

`generate.py` builds a finite rescue model in ISPL from a selected map and initial locations of FireBrigades, AmbulanceTeams, and civilians. It also writes a matching `jason_mapping.json` for the ordinary Jason-plan translator. This lets us change the number and placement of agents without writing an entire new ISPL file manually.

The generator produces two input files: a **baseline** model describing rescue dynamics and legal actions, and a **translation mapping** describing how the existing rescue `.asl` files relate to those actions. It does not itself run Jason, translate the plans, or model-check the result. Those are separate steps.

This generator's mappings use the **ordinary direct-mapping path**, with configured action and predicate translations and movement pass-through patterns. That is different from the relation-aware mappings already supplied in `examples/three_area`, `examples/custom2`, and `examples/abstract`. The tool does not automatically reuse that relation-aware search-ranking implementation.

## Files in this directory

```text
tools/rcrs/
├── generate.py
└── maps/
    ├── 3area.json
    ├── 9area.json
    ├── 95area.json
    └── custom_2.json
```

Each map file specifies `areas`, `adjacency`, `refuge`, and `status`. `areas` is an ordered list of actual area identifiers. `adjacency` tells us which moves are legal from each area. `refuge` identifies the delivery location. `status` classifies the areas as road, healthy, damaged, or collapsed as configured.

The map JSON controls topology and initial area labels. It is not a set of Jason plans. The agent decision programs remain in `agents/fire_brigade.asl` and `agents/ambulance_team.asl`.

## Creating a baseline

An interactive run is:

```bash
python3 tools/rcrs/generate.py
```

The script prompts for one of four maps, a FireBrigade count, an AmbulanceTeam count, a civilian count, and the starting map position of every entity. Each count is between **1 and 5**. Positions use the **1-based index displayed by the script**. The index selects an entry in the map's ordered `areas` list; it is not necessarily the numeric suffix in the actual area name. Multiple agents can start in the same area.

For a reproducible non-interactive run:

```bash
python3 tools/rcrs/generate.py \
  --map 3 \
  --fire-brigades 1 \
  --ambulances 2 \
  --civilians 2 \
  --fire-positions 1 \
  --ambulance-positions 1 3 \
  --civilian-positions 2 3
```

Here `--map 3` selects `3area`; the four numbered choices are `1=95area`, `2=9area`, `3=3area`, and `4=custom_2`. The map name can also be supplied directly through `--map`. `--examples-dir` changes the directory in which the new experiment is written.

The example command writes:

```text
examples/3area_f1_a2_c2/
└── input/
    ├── 3area_f1_a2_c2.ispl
    └── jason_mapping.json
```

The generated directory name records the selected map and number of FireBrigades, AmbulanceTeams, and civilians.

To produce the guided model:

```bash
python3 src/jason_guided.py --config examples/3area_f1_a2_c2/input/jason_mapping.json
```

The mapping's `files.output` normally points to a new `generated/` subdirectory. Check the resulting `.ispl` file using MCMAS and compare it with its baseline.

## The main Python functions

### `ask_choice`, `ask_count`, `ask_positions`, and `validate_positions`

These functions handle user input. `ask_choice` selects one of the four fixed maps. `ask_count` accepts an integer from 1 to 5 for each kind of entity. `ask_positions` shows valid area indices and asks for a position for every agent or civilian. `validate_positions` handles supplied command-line lists, verifies their lengths and ranges, and converts the 1-based indices to actual map area identifiers. This keeps the model builder from confusing display indices with map identifiers.

### `action_set`

This is a small helper that prints a list of ISPL action names inside braces. It does not alter their legality or meaning.

### `baseline_model`

`baseline_model(layout, fire_positions, ambulance_positions, civilian_positions)` constructs an ISPL model with the requested instances. It names agents `FireBrigade0`, `FireBrigade1`, etc., and `AmbulanceTeam0`, `AmbulanceTeam1`, etc. Civilians are represented in Environment fields as `Civ0`, `Civ1`, and so on.

The model is built in these steps:

1. **Environment variables.** It declares one position variable per FireBrigade and AmbulanceTeam, the refuge position, per-area status variables, and per-civilian location, health, buriedness, alive/dead, loaded, carrier, and delivery fields.
2. **Movement updates.** It creates the Environment evolution rules that change each agent's position when it takes a configured movement action. The matching agent protocols later restrict those actions to destinations listed in the map's adjacency relation.
3. **Civilian health.** A civilian who remains buried progresses through high, moderate, and at-risk health toward death. The model uses finite levels, rather than continuous health values.
4. **Rescue.** A FireBrigade can reduce buriedness from 1 to 0 when it is in the same area as the living buried civilian and selects the corresponding rescue action.
5. **Pickup and delivery.** An AmbulanceTeam can load a living unburied civilian when co-located, becoming its carrier. A loaded civilian moves with that carrier. Unloading at the refuge clears the carrier/loaded state and marks delivery complete. The generated conditions also resolve competing simultaneous load attempts by giving precedence to an earlier ambulance index.
6. **Agent protocols.** Each FireBrigade has movement actions, one rescue action per civilian, and rest. Each AmbulanceTeam has movement, load, unload, and rest actions. A move is available only along configured adjacency edges; rescue and transport actions have appropriate state guards.
7. **Evaluation and initial states.** The generator defines propositions for a civilian being alive at the surface and delivered alive, initializes agents and civilians at their selected locations, declares coalitions (`fire_only`, `ambulance_only`, and `rescue_team`), and adds ATL reachability properties for the relevant civilians.

This is a finite abstraction for checking rescue coordination. The code does not claim to reproduce all the dynamics and infrastructure of the full RoboCup Rescue Simulation.

### `jason_mapping`

`jason_mapping(name, fire_positions, ambulance_positions, civilian_positions, output_directory)` generates one translator role for each FireBrigade and AmbulanceTeam instance. Each role points to its corresponding rescue `.asl` file and the exact agent name used in the generated baseline. Its goal-control variable also includes the instance index, for example `fb0_goal_level` or `at1_goal_level`.

The role's `plan.ground` section expands the selected civilian-related terms over `Civ0`, `Civ1`, and so on. `plan.actions` maps rescue, load, and some unload actions to instance-specific ISPL action names. `plan.predicates` connects the supported source beliefs to finite Environment variables or to configured Boolean approximations. `transitions` tells the generated goal control when to return to the main rescue task after a rescue or load stage.

The mapping also contains `ignore_actions`, mainly to leave out diagnostic and communication calls that are not separately represented as direct primitive actions in this generated model. `pass_through_patterns` retains movement choices, and for AmbulanceTeams selected unload actions, under their original baseline conditions. `fallback` sets the appropriate rest action. These choices mean the output is only partially restricted by the selected plans.

For multiple civilians, review the generated action mappings carefully, particularly the source `unload` action, whose target action is not selected in the same way as a uniquely civilian-specific `load(Civ)` call. The script does not establish full execution correspondence for every multi-civilian Jason plan.

### `main`

`main` parses the command-line options, loads the chosen map JSON, obtains the instance counts and starting positions, constructs the output directory name, calls `baseline_model` and `jason_mapping`, and writes the two generated files. It then prints a ready-to-use translation command.

## How the generated model differs from the repository's fixed examples

The fixed `examples/three_area` model uses `relation_translation.py` and translates map-sensitive patrol ordering using a relation extracted from the baseline. This generator instead produces instance-specific direct mappings with movement actions retained through pass-through patterns. Both are useful, but they represent different amounts of Jason decision logic. A new generated `3area_f1_a1_c1` model is therefore not automatically identical to the fixed `examples/three_area` experiment, and its state counts should be measured separately.

The exact 95-area fixed example also has its own original baseline and mapping. Generating a new `95area_f...` case does not recreate the fixed file byte for byte. The goal of this generator is to vary instance counts and placements while keeping the configured topology.

## Checking a new scenario

Before using any generated experiment in a result table, check the agent names, enabled movement actions, civilian initial positions, and `InitStates` assignments. Inspect which behaviors the mapping chooses directly and which remain as pass-through choices. Regenerate the guided ISPL and run MCMAS on **both** models under the same options. For large maps or multiple civilians, the state space can grow quickly even when the translator restricts some decisions.

For mapping syntax see [`../../examples/MAPPING_GUIDE.md`](../../examples/MAPPING_GUIDE.md), and for the direct translation process see [`../../src/jason_guided.md`](../../src/jason_guided.md).
