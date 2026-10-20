# Leveraging BDI in ATL Model Checking to Mitigate State-Space Explosion

This repository implements a translation from selected **Jason/AgentSpeak BDI plans** into **MCMAS ISPL decision models**. It supports the work *Leveraging BDI in ATL Model Checking to Mitigate State-Space Explosion*.

A baseline ISPL model specifies the environment, action availability, physical transitions, initial states, and temporal properties. The Jason-guided model retains that domain model but introduces finite goal-control information and restricts the translated agents' decisions according to selected Jason goals, plan contexts, actions, and priorities. Both models are checked using the same ATL formulae.

**The objective is not just to minimize a state graph.** The comparison tests whether strategies that are possible in the baseline remain possible under the implemented (or selected) BDI plans. A guided model may be smaller while losing a strategic guarantee; that finding must be interpreted in light of the mapping and its abstractions.

## Repository layout

```text
.
├── agents/
│   ├── fire_brigade.asl
│   ├── ambulance_team.asl
│   └── blue_agent.asl
├── src/
│   ├── jason_guided.py
│   ├── formatting.py
│   ├── relation_translation.py
│   └── test_jason_guided.py
├── examples/
│   ├── three_area/
│   ├── custom2/
│   ├── abstract/
│   ├── exact95/
│   ├── Cage1-simple/
│   ├── Cage1-complete/
│   └── <generated RCRS examples>/
└── tools/
    ├── cage1/
    │   ├── generate.py
    │   └── mapping.json
    └── rcrs/
        ├── generate.py
        └── maps/
            ├── 95area.json
            ├── 9area.json
            ├── 3area.json
            └── custom_2.json
```

Each configured example ordinarily contains `input/` with a baseline `.ispl` and `jason_mapping.json`, and `generated/` with the Jason-guided `.ispl`. The two generators create baseline/mapping pairs; the **shared translator** generates their guided counterparts.

The RCRS generator is distributed separately in `tools/rcrs/` for repositories that do not yet include it. If you are applying the RCRS patch, extract it at the repository root before using the related commands.

## Requirements

- Python 3.9 or later; the generator and translator use the standard library.
- MCMAS 1.3.0 (or a compatible version) to check `.ispl` models.
- Jason is **not** required to run the translation, because the translator reads the `.asl` source files directly.

Run commands from the **repository root** so that all relative paths match their example configurations.

## Translate an existing example

The command pattern is always:

```bash
python3 src/jason_guided.py --config examples/<example>/input/jason_mapping.json
```

Examples:

```bash
# Small RCRS scenarios
python3 src/jason_guided.py --config examples/three_area/input/jason_mapping.json
python3 src/jason_guided.py --config examples/custom2/input/jason_mapping.json

# Nine-zone and exact 95-area RCRS scenarios
python3 src/jason_guided.py --config examples/abstract/input/jason_mapping.json
python3 src/jason_guided.py --config examples/exact95/input/jason_mapping.json

# CAGE Challenge 1 scenarios
python3 src/jason_guided.py --config examples/Cage1-simple/input/jason_mapping.json
python3 src/jason_guided.py --config examples/Cage1-complete/input/jason_mapping.json
```

Each mapping's `files.raw` points to the baseline relative to its input folder; `files.output` controls the output path, usually in `../generated/`.

## Generate an RCRS scenario

```bash
python3 tools/rcrs/generate.py
```

Select one of four **fixed** layouts: `95area`, `9area`, `3area`, or `custom_2`. The generator asks for the number of FireBrigades, AmbulanceTeams, and civilians (**1 to 5 of each**), then for the initial map position of every instance. Positions are 1-based indices shown by the generator, and multiple entities can occupy the same area.

For reproducible runs, all choices are available as arguments:

```bash
python3 tools/rcrs/generate.py \
  --map 3 --fire-brigades 1 --ambulances 2 --civilians 2 \
  --fire-positions 1 \
  --ambulance-positions 1 3 \
  --civilian-positions 2 3
```

This creates:

```text
examples/3area_f1_a2_c2/
└── input/
    ├── 3area_f1_a2_c2.ispl
    └── jason_mapping.json
```

Translate it with:

```bash
python3 src/jason_guided.py --config examples/3area_f1_a2_c2/input/jason_mapping.json
```

The four original map topologies are kept; extra rescue agents and civilians are represented using separate state/action variables. This is a finite multi-agent abstraction, not a byte-identical expansion of the original single-rescuer examples. Large 95-area configurations can require considerable memory.

## Generate a CAGE Challenge 1 scenario

```bash
python3 tools/cage1/generate.py \
  --users 5 --enterprises 3 --hosts 3 \
  --output-dir examples/Cage1-complete/input
```

Omit the counts to be prompted interactively. Each count must be **at least 1**. The operational server (`Op_Server0`) and the monitoring host (`Defender`) are added automatically; they are **not** included in these input counts. With 5 User, 3 Enterprise, and 3 Operational hosts, the model has 13 hosts in total.

The generator writes the matching `cage1_baseline.ispl` and `jason_mapping.json`. To produce the guided model:

```bash
python3 src/jason_guided.py --config examples/Cage1-complete/input/jason_mapping.json
```

The CAGE abstraction includes Blue and Red action models, a separate hidden host-compromise state, Red knowledge, Blue observations, and nondeterministic Environment outcomes. The exact variables, action inventory, and translation scope depend on the chosen scenario and mapping.

## What the translator does

The configurable translation follows the approach used in the paper:

1. **BuildGoalControl:** extract the selected, reachable Jason goal structure and create finite task-control states.
2. **GenerateProtocol:** map relevant plan contexts/actions and restrict baseline-legal actions while observing plan priority.
3. **GenerateEvolutionRules:** add updates that advance the goal-control state after subgoals or mapped actions.
4. **ReplaceAgentDecisionModel:** assemble the revised agent block while retaining the baseline's physical domain transitions.

The implementation also builds internal per-agent specifications and supports configuration-driven grounding of selected parameterized Jason terms. Domain-specific action and predicate meanings belong in `jason_mapping.json`, not in a separate domain-specific translator.

**Translation scope:** A mapping may intentionally select only part of an ASL program. For example, some RCRS movement/unloading choices and some CAGE recovery actions can be kept as `pass_through` choices. Such models are **partially Jason-guided**. Pass-through decisions must not be presented as evidence that the original Jason agent always makes those decisions. The translator does not reproduce all Jason event scheduling, belief-base updates, or runtime execution semantics.

## Model checking and reproducible measurements

Run MCMAS **without model export** to check the ATL formulae and measure verification costs:

```bash
mcmas examples/Cage1-simple/input/cage1_baseline.ispl
mcmas examples/Cage1-simple/generated/cage1_jason_guided.ispl
```

MCMAS reports the checked properties, elapsed execution time, number of reachable states, and BDD memory in use. For research comparisons, use the **same MCMAS version, flags, hardware, and measurement procedure** for both models. Record repeated runs (for example, five) and report a summary statistic such as the median execution time. Smaller reachable sets do not necessarily produce shorter BDD verification times: goal-control encoding, BDD ordering, and transition-relation operations also affect runtime.

`-exportmodel` is **not a timing benchmark for symbolic ATL verification**. It additionally writes the entire explicit reachable transition system to `model.dot` and `model.info` and can be much slower:

```bash
mcmas -exportmodel examples/Cage1-simple/generated/cage1_jason_guided.ispl
```

Use export only to inspect traces, graph structure, or reachable-state details. For independent peak process RAM measurements on Linux/WSL, run `/usr/bin/time -v mcmas <model.ispl>`; this is different from MCMAS's internal BDD memory statistic. Use `mcmas -u <model.ispl>` if detailed BDD statistics are needed. Do not mix exported and non-exported measurements in one comparison.

The CAGE models may preserve the same physical transitions yet have different strategic results because the Blue protocol is restricted. A failed guided ATL property should be analyzed against the selected mapping and the available observations before attributing it to the full Jason program.

## Tests

Run the translator tests from the repository root:

```bash
python3 -m unittest discover -s src -p 'test_*.py'
```

For regression testing, regenerate unchanged examples and compare the output ISPL files against known snapshots. For generated scenarios, test both input boundaries and translator output, then use MCMAS to validate syntax and strategic properties. Translation success alone is not a substitute for model checking.

## Citation

If you use the research methodology or the examples, cite *Leveraging BDI in ATL Model Checking to Mitigate State-Space Explosion*. A publication-specific BibTeX entry can be added when bibliographic details are available.
