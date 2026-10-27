# CAGE Challenge 1 baseline generator

## What this tool produces

`generate.py` creates an ISPL baseline for a configured CAGE-style network and a matching `jason_mapping.json` for the Blue translator. It does **not** itself translate Jason plans or run MCMAS. We generate the domain model first, then use `src/jason_guided.py` to obtain the guided Blue decision model.

The generator makes the number of user, enterprise, and operational hosts configurable while keeping the modeling rules in one place. The result is a finite abstraction of selected CAGE Challenge 1 interactions with Blue, Red, and Environment agents, not a generated copy of every CybORG simulator mechanic. In particular, these models do not include a Green agent or the original challenge reward calculation.

## Files in this directory

| File | Role |
| --- | --- |
| `generate.py` | Reads host counts and the domain template, writes a baseline ISPL and Jason translation mapping. |
| `mapping.json` | The generator's **domain template**: subnet names, variables, action templates, protocols, evolution rules, initial values, evaluation propositions, and source-to-model translation settings. |
| `cage1_baseline.ispl` | A baseline ISPL file supplied with this tool directory. It is separate from newly generated files unless explicitly selected as output. |
| `jason_mapping.json` | A translator mapping supplied in this directory. A new run of `generate.py` creates another mapping at the requested output location. |

**Do not confuse `mapping.json` with `jason_mapping.json`.** The first is used by the generator to *build* a network model. The second is used by the Jason translator to *restrict* an existing baseline model. The generator creates the second from the first and the selected host counts.

## Running the generator

From the repository root:

```bash
python3 tools/cage1/generate.py \
  --users 5 --enterprises 3 --hosts 3 \
  --output-dir examples/Cage1-complete/input
```

Here `--users` is the number of dynamically numbered User hosts, `--enterprises` is the number of numbered Enterprise hosts, and `--hosts` is the number of numbered operational hosts. Each must be at least 1. If a count is omitted, the script asks for it interactively. The tool also adds fixed hosts described by the template, including the operational server and defender host. With the counts above, it produces 13 hosts in total.

Other options:

| Option | Meaning |
| --- | --- |
| `--mapping PATH` | Use a different domain-template JSON instead of `tools/cage1/mapping.json`. |
| `--output-dir PATH` | Directory receiving both output files. The default is the current working directory. |
| `--baseline-name NAME` | Name of the generated baseline, by default `cage1_baseline.ispl`. |
| `--program PATH` | Program path placed in the generated Jason mapping, by default `../../../agents/blue_agent.asl`. This path is later interpreted relative to the JSON location. |

The last detail matters. If the output directory is moved or is not under `examples/<name>/input`, the default `--program` relative path may no longer find the Blue source. Check `jason.roles.blue.program` before translating.

To translate the generated model:

```bash
python3 src/jason_guided.py --config examples/Cage1-complete/input/jason_mapping.json
```

To verify the baseline and guided models separately:

```bash
mcmas examples/Cage1-complete/input/cage1_baseline.ispl
mcmas examples/Cage1-complete/generated/cage1_jason_guided.ispl
```

Larger host counts may make the state space too large for the available memory. File generation and successful translation do not imply that MCMAS can exhaustively check the configuration.

## Reading `mapping.json`

The template is organized into a number of sections. Each section is read by `generate.py` when rendering the model:

| Section | Contents |
| --- | --- |
| `roles` | Names special hosts such as the initial foothold, the critical server, and a gateway-related host. |
| `subnets` | Defines user, enterprise, and operational host prefixes, fixed hosts, decoy variables, discovery markers, and subnet-specific guards. |
| `state` | Declares public and private Environment variables, per-host access/state variables, and per-host observation variables. |
| `initial` | Supplies starting values for common state, the foothold, ordinary hosts, observations, decoys, and agent variables. |
| `actions` | Lists Environment actions and templates for Blue's common/host actions and Red's discovery, exploit, escalation, and service actions. |
| `protocols` | Defines the conditions under which Environment and Red actions are enabled. Blue's broad baseline protocol is assembled from its configured action sets. |
| `evolution` | Defines how turn changes, restoration, removal, discovery, exploitation, privilege changes, service impact, decoys, and observation updates affect the next state. |
| `evaluation` | Defines atomic propositions for verification, including access and service status. |
| `formulae` | Temporal properties copied into the resulting ISPL. These need to be checked for the exact semantics intended in each experiment. |
| `jason` | Supplies settings from which `render_jason` produces the host-specific Blue translation mapping. |

A template rule can contain placeholders such as `{host}`, `{server}`, `{gateway}`, or `{decoy}`. The script substitutes those values for each instantiated host. This makes it possible to use one source rule for many host-specific ISPL evolution rules.

## The Python functions

### `read_count` and `build_hosts`

`read_count` accepts a command-line number or asks for one and rejects non-positive values. `build_hosts` uses each subnet's prefix and fixed-host list to construct the final host names. It also returns the host selected as a gateway and the configured critical server. These names become available to the later rule-expansion code.

### `expand`, `add_rules`, `field`, and `action_set`

These are the text-construction helpers. `expand` replaces named placeholders with their current values. `add_rules` appends expanded lines with a specified indentation. `field` makes an ISPL state-variable declaration, and `action_set` wraps the action list in braces. They do not decide when an action is legal; the template's conditions do that.

### `render`

`render(mapping, counts)` constructs the complete baseline ISPL in order:

1. Declares the Environment's observable state and private variables. It creates host-specific fields and the configured decoy variables.
2. Declares Environment actions, protocol rules, and evolution rules. It expands the network dynamics for each host and subnet, including Blue response effects, Red discovery and access changes, decoy behavior, and the information reported to the agents.
3. Declares `Agent Blue`. Its `Lobsvars` reference the configured observation variables. On Blue turns, the baseline protocol offers the configured common and per-host defensive actions; on Red turns, Blue takes its wait action.
4. Declares `Agent Red`. Its `Lobsvars` represent Red's recorded information. It receives its configured discovery, exploit, privilege, impact, and wait choices under their baseline guards.
5. Writes evaluation propositions, all initial assignments, the `blue_team` and `red_team` groups, and the selected formulae.

The Environment evolution rules are where the modeled effects and alternative outcomes are defined. The presence of separate actual-state and reported-state fields allows an attack to change the network without necessarily updating Blue's view. Alternative Environment actions represent nondeterministic outcomes, without assigning probabilities.

### `render_jason`

`render_jason(mapping, counts, baseline_name, program)` builds the *second* JSON file. It creates the Blue `role` using the chosen program, entry goal, and `blue_goal_level`. It grounds selected host-dependent terms, adds mappings for per-host `restore` and `remove`, maps host reports and secure beliefs to the generated ISPL fields, and creates task-stage transitions that return a host-security goal to the network-security goal after a mapped response.

The function also applies configured exclusions such as the initial foothold and Defender, carries over pass-through choices, and substitutes the chosen server name where required. Thus, the generated Jason mapping is specific to the host list produced by the same run. It should not be casually reused for a different host count.

### `main`

`main` reads command-line arguments, loads the JSON domain template, calls `render` and `render_jason`, creates the output directory, and writes the two files. It prints both output paths.

## What to check when changing the model

The network variables and action templates in `mapping.json` must agree with the action and predicate names generated in `render_jason`. If a host-specific action is renamed in the baseline but not in the Jason mapping, the translator may be unable to use it. Likewise, a mismatch between a report variable and the intended compromise level changes the defensive policy being checked.

After generating a new network, inspect the Blue and Red `Protocol` sections, the Environment observation updates, the `InitStates` block, and the mapping's `plan.actions`, `plan.predicates`, `pass_through`, and `transitions`. Then generate the guided file and run MCMAS on **both** versions. See [`../../examples/MAPPING_GUIDE.md`](../../examples/MAPPING_GUIDE.md) for the mapping syntax and [`../../src/jason_guided.md`](../../src/jason_guided.md) for translation behavior.
