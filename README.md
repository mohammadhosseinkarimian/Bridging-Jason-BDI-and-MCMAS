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
