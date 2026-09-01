# Leveraging BDI in ATL Model Checking to Mitigate State-Space Explosion

This repository contains the Jason-to-MCMAS translation used in our work on combining BDI agent programs with ATL model checking.

The idea is simple: the baseline MCMAS model describes what is physically possible, while the Jason programs describe how the agents actually choose between those possibilities. The translator uses the relevant Jason goals, contexts, actions, beliefs, and plan order to generate a Jason-guided MCMAS model.

The physical model stays the same. What changes is the agent decision model.

## Repository structure

```text
.
├── README.md
├── src/
│   └── jason_guided.py
│
├── agents/
│   ├── fire_brigade.asl
│   ├── ambulance_team.asl
│   └── blue_agent.asl
│
└── examples/
    ├── custom2/
    │   ├── input/
    │   │   ├── custom2_raw.ispl
    │   │   └── jason_mapping.json
    │   └── generated/
    │       └── custom2_jason_guided.ispl
    │
    ├── abstract/
    │   ├── input/
    │   │   ├── abstract_raw.ispl
    │   │   └── jason_mapping.json
    │   └── generated/
    │       └── abstract_jason_guided.ispl
    │
    ├── exact95/
    │   ├── input/
    │   │   ├── raw-test.ispl
    │   │   └── jason_mapping.json
    │   └── generated/
    │       └── raw-test_jason_guided.ispl
    │
    └── cage/
        ├── input/
        │   ├── c1.ispl
        │   └── jason_mapping.json
        └── generated/
            └── c1_jason_guided.ispl
```

## Main files

`src/jason_guided.py` is the general translator. It reads a baseline ISPL model, Jason AgentSpeak programs, and a semantic mapping, then generates the corresponding Jason-guided ISPL model.

`agents/` contains the Jason programs used by the examples.

Each folder under `examples/` contains its own baseline model, `jason_mapping.json`, and generated Jason-guided model.

The translator itself is domain-independent. Domain-specific correspondences stay in the mapping files rather than being hard-coded in Python.

## Requirements

Python 3 is enough to run the translator. It uses only the Python standard library.

MCMAS is required to model check the generated `.ispl` files.

Jason itself is not required for translation because the `.asl` source files are read directly.

## Generate the examples

Run the following commands from the repository root.

### Two-location RCRS example

```bash
python3 src/jason_guided.py \
  --config examples/custom2/input/jason_mapping.json
```

### Nine-zone RCRS example

```bash
python3 src/jason_guided.py \
  --config examples/abstract/input/jason_mapping.json
```

### Exact 95-area RCRS example

```bash
python3 src/jason_guided.py \
  --config examples/exact95/input/jason_mapping.json
```

### CAGE example

```bash
python3 src/jason_guided.py \
  --config examples/cage/input/jason_mapping.json
```

The generated files are written directly to the corresponding `generated/` folders.

## Translation

The translator follows five main steps:

1. `BuildGoalControl`
2. `BuildAgentSpec`
3. `GenerateProtocol`
4. `GenerateEvolutionRules`
5. `ReplaceAgentDecisionModel`

Jason provides the decision structure, while the baseline ISPL model remains the source of physical action legality and action effects.

## Running MCMAS

For example:

```bash
mcmas examples/custom2/generated/custom2_jason_guided.ispl
```

The ATL formulae are already included in the ISPL models.

## Citation

If you use this repository, please cite:

**Leveraging BDI in ATL Model Checking to Mitigate State-Space Explosion**

The final BibTeX entry will be added after publication details are available.
