# Combining BDI and ATL Model Checking to Mitigate State Space Explosion

This repository contains the implementation and the small reproducible example used for our Jason and MCMAS workflow.

The idea is simple. We first build a raw MCMAS model that contains the physically available behavior of the rescue domain. We then read the Jason AgentSpeak programs and use their goals, contexts, beliefs, plan order, and movement priorities to generate a more constrained MCMAS protocol. The resulting Jason-guided model is checked with the same ATL properties.

The raw model tells us what is physically possible. The Jason-guided model tells us what remains possible under the decisions encoded by the Jason programs.

## Repository structure

```text
.
├── README.md
├── .gitignore
├── src/
│   ├── raw_translator.py
│   ├── abstract_raw.py
│   └── jason_guided.py
├── agents/
│   ├── fire_brigade.asl
│   └── ambulance_team.asl
├── config/
│   └── jason_translation.json
├── examples/
│   └── custom2/
│       ├── input/
│       │   ├── custom2_two_agent.zip
│       │   └── initial.json
│       └── generated/
│           ├── custom2_raw.ispl
│           └── custom2_jason_guided.ispl
├── docs/
│   └── figures/
│       ├── raw_state_trace.pdf
│       └── jason_guided_state_trace.pdf
```

## Main files

`src/raw_translator.py` reads an RCRS map zip and an initial-state JSON file and generates the baseline exact ISPL model.

`src/abstract_raw.py` builds the zone-level abstraction used when the exact RCRS model becomes too large. The abstraction is derived from the physical map graph and the configured initial state.

`src/jason_guided.py` reads the raw ISPL model together with the Jason programs and the translation dictionary. It extracts the relevant Jason goal structure, contexts, plan priorities, communication behavior, and movement decisions, then replaces the raw agent protocols with Jason-guided protocols.

`agents/` contains the FireBrigade and AmbulanceTeam AgentSpeak programs used by the translator.

`config/jason_translation.json` defines the correspondence between Jason actions and predicates and the categories used by the translator.

`examples/custom2/` contains the two-location example. The checked-in raw and Jason-guided ISPL files can be regenerated exactly from the input map, initial state, Jason programs, and translation dictionary.

## Requirements

The Python scripts use only the Python standard library. Python 3 is enough for model generation.

MCMAS is required to model check the generated ISPL files. It is not included in this repository.

Jason itself is not required just to run the translator because the translator reads the `.asl` source files directly. Jason is only needed if you also want to execute the AgentSpeak programs in the Jason runtime.

## Quick reproduction of the two-location example

From the repository root:

```bash
mkdir -p build/custom2

python3 src/raw_translator.py \
  --input examples/custom2/input/custom2_two_agent.zip \
  --initial examples/custom2/input/initial.json \
  --output build/custom2/custom2_raw.ispl

python3 src/jason_guided.py \
  --raw build/custom2/custom2_raw.ispl \
  --fire-jason agents/fire_brigade.asl \
  --ambulance-jason agents/ambulance_team.asl \
  --bridge config/jason_translation.json \
  --initial examples/custom2/input/initial.json \
  --output build/custom2/custom2_jason_guided.ispl
```

## Running MCMAS directly

```bash
mcmas examples/custom2/generated/custom2_raw.ispl
mcmas examples/custom2/generated/custom2_jason_guided.ispl
```

The ATL formulae are already included at the end of each ISPL file.

## Large-map workflow

For a larger RCRS map, the workflow used in the paper is:

```text
RCRS map + initial state
        |
        v
raw_translator.py
        |
        v
exact raw ISPL
        |
        v
abstract_raw.py
        |
        v
abstract raw ISPL
        |
        + Jason AgentSpeak programs
        + translation dictionary
        |
        v
jason_guided.py
        |
        v
Jason-guided ISPL
        |
        v
MCMAS + ATL
```

A generic abstraction command is:

```bash
python3 src/abstract_raw.py \
  --raw path/to/raw.ispl \
  --initial path/to/initial.json \
  --map path/to/rcrs_map.zip \
  --output path/to/abstract_raw.ispl
```

The generated abstract model can then be passed to `jason_guided.py` using the same Jason programs and translation dictionary.

## Notes on the checked-in example

The two-location example is intentionally small enough to inspect directly. The raw model allows all physically valid rescue choices. The Jason-guided model restricts those choices using the order and conditions of the Jason plans. The two PDFs in `docs/figures/` show the corresponding state traces used to inspect this difference.

## Citation

If you use this repository, please cite the paper:

**Combining BDI and ATL Model Checking to Mitigate State Space Explosion**

Add the final BibTeX entry here once the proceedings citation and DOI are available.
