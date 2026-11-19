# CAGE verification and ASL cleanup results

## ASL cleanup, verified separately

Removed 25 redundant trailing tests from `fire_brigade.asl` and 43 from `ambulance_team.asl`. These tested task names, already-established contexts, or just-added beliefs, including `?saved_civilians`, `?patrol`, and loading/delivery tests after movement or waiting. Retained the four action-effect tests: `?loaded(Civ)` following load and `?delivered(Civ)` following unload.

Before changing any CAGE baseline or mapping, all seven examples were regenerated to temporary files before and after the cleanup. Each pair was byte-identical, including all three CAGE outputs. The existing generated files were not rewritten during this stage. The exact output SHA-256 values and platform line-ending notes are in [asl_cleanup_verification.json](asl_cleanup_verification.json). The four rescue guided files also remain unchanged in the final working tree.

## CAGE changes

The generated five-host and 13-host baselines now use a directed B-line abstraction of Red: discover the enterprise subnet, scan/exploit/escalate the last numbered enterprise host, then discover and attack `Op_Server0`. Red has no sleep or off-route attack choices. This is a finite directed attack policy, not a full implementation of CybORG's B-line agent. The two-host baseline already followed the direct server attack sequence and is unchanged.

The generated domain includes two retry rules: failed operational discovery after losing the gateway resets its Red access record to `service`, and failed server impact after restoration resets the server record to `service`. Red therefore retries instead of being stuck indefinitely with a stale root record. These rules apply equally to each baseline and its guided model.

The guided mappings select `agents/blue_agent_reactive.asl`. It uses the same `observe_network`, `secure_network`, `host_state`, `restore`, `remove`, and `monitor` vocabulary as the original policy. It prioritizes reported server compromise, then the selected gateway, and responds in one defensive decision. This avoids an extra model turn just to enter the original `secure(Host)` subgoal. The original `blue_agent.asl` is preserved.

The mapping still retains server restoration as an optional recovery choice on Blue turns, plus waiting on Red turns. This permits a preventive restoration strategy when reports are missed. Consequently, the results concern a partially guided policy. The single active goal has no control transitions, so the optional, validated `elide_constant_goal` setting removes unnecessary constant bookkeeping. Existing rescue mappings do not enable that optimization.

Within every CAGE pair, **Environment, Red, initial states, evaluation propositions, agent groups, and formulae are identical**. Only Blue's protocol changes; no actual-access predicate is used as a replacement for a Blue report predicate. All generated baselines and mappings can be reproduced from `tools/cage1/mapping.json` for their documented host counts.

These new baselines use a different Red policy from the historical larger models discussed in the supplied papers. Their state counts must not be presented as a direct reproduction of the papers' old baseline counts.

## Measurements

MCMAS 1.3.0, Ubuntu 24.04 under WSL2, default verification options, no model export. Each model had one excluded warm-up followed by 11 measured runs. Models ran serially and baseline/guided order alternated on each repeat. The table reports median MCMAS execution time and MCMAS BDD memory in decimal MB (`bytes / 1,000,000`).

| Example | Model | Reachable states | Time (s) | BDD memory (MB) |
| --- | --- | ---: | ---: | ---: |
| Cage1-small | Baseline | 20 | 0.018 | 9.177 |
| Cage1-small | Jason-guided | 12 | 0.019 | 9.177 |
| Cage1-simple | Baseline | 3,903 | 0.191 | 11.405 |
| Cage1-simple | Jason-guided | 75 | 0.182 | 10.362 |
| Cage1-complete | Baseline | 32,559 | 2.944 | 18.971 |
| Cage1-complete | Jason-guided | 75 | 2.932 | 14.479 |

Simple reduces states by 98.08%, BDD memory by 9.15%, and median time by 4.71%. Complete reduces states by 99.77%, BDD memory by 23.67%, and median time by 0.41%. Complete's timing difference is small relative to run-to-run variation; it is a measured median improvement, not evidence of a robust speedup across machines or runs.

**The requirement that all three metrics decrease in every example is not fully met.** Small reduces states by 40%, but both models allocate exactly 9,176,656 BDD bytes, and its median time rises by 0.001 seconds. This tiny model is dominated by fixed symbolic setup and allocation costs; fewer reachable states do not imply a lower allocation or shorter runtime. No baseline state or unrelated variable was added to manufacture a performance improvement.

Peak process RAM was measured separately with `/usr/bin/time -v`. Median peak RSS, baseline to guided, was 13,820 -> 13,840 KiB for small, 16,204 -> 15,176 KiB for simple, and 24,232 -> 19,732 KiB for complete. This is distinct from the BDD statistic; small's process-memory result also does not show a reduction.

Machine details, file hashes, every warm-up and measured output, individual timings, and exact memory values are in [cage1_results/results.json](cage1_results/results.json). The compact table is also available as [cage1_results/summary.csv](cage1_results/summary.csv).

## Strategic properties and validation

The following results hold in both members of each CAGE pair:

| Query | Small | Simple | Complete |
| --- | --- | --- | --- |
| Gateway root access is possible | Not applicable | True | True |
| Server root access is possible | True | True | True |
| Service impact is possible | True | True | True |
| Red can force eventual service impact | False | False | False |
| Blue can guarantee service availability | True | True | True |

The small model expresses possibility with the `all_agents` coalition; the generated models use `EF`. Their original formula sections are preserved within each pair. All six CAGE models are deadlock-free. Blue's guarantee uses perfect-information ATL semantics and includes the retained restoration choice. It does not establish an observation-uniform strategy for the original Jason runtime, nor an original CAGE reward or restoration-cost bound.

All 14 supplied baseline/guided models were parsed and model-checked. Rescue counts remain 559,881 / 452 for abstract, 25 / 6 for custom2, 8,041,370 / 19,312 for exact95, and 52 / 22 for three_area. Their generated files remain unchanged. The existing abstract example reports the ambulance-only loading query as false in the baseline and true in the guided model; these unchanged files already had different decision and coordination models. Full outputs are retained in [cage1_results/validation.json](cage1_results/validation.json).

Nine automated tests pass: the original four translation-phase tests plus five regression tests covering regeneration of every example, generator reproducibility, directed-attacker and pair invariants, unsafe control-state elimination, and invalid host counts.

## Reproduce

From the repository root:

```bash
python3 -B -m unittest discover -s src -p 'test_*.py' -v
python3 -B tools/cage1/generate.py --users 1 --enterprises 1 --hosts 1 --output-dir examples/Cage1-simple/input
python3 -B tools/cage1/generate.py --users 5 --enterprises 3 --hosts 3 --output-dir examples/Cage1-complete/input
python3 -B src/jason_guided.py --config examples/Cage1-small/input/jason_mapping.json
python3 -B src/jason_guided.py --config examples/Cage1-simple/input/jason_mapping.json
python3 -B src/jason_guided.py --config examples/Cage1-complete/input/jason_mapping.json
python3 -B tools/cage1/benchmark.py --mcmas mcmas --repeats 11
python3 -B tools/cage1/validate.py --mcmas mcmas
```

Run MCMAS-dependent commands in Linux/WSL. `--require-reductions` can be added to the benchmark to enforce strict decreases in states, BDD bytes, and median MCMAS time for all three scenarios; the current small example correctly causes that check to fail after the measurements are saved. Timing results can vary between repetitions and systems.
