# CAGE results with the original goal control

All three CAGE mappings again select agents/blue_agent.asl. The original
goal domains, declaration of Blue.blue_goal_level, initialization,
goal-dependent protocol guards, and adoption/completion transitions are
retained. The goal-elimination code and reactive source have been removed.
The main translator and formatter match their original versions.

The goal domains are unchanged:

- Small: secure_network, secure_Op_Server0, done.
- Simple: secure_network, secure_Op_Server0, secure_Enterprise0, secure_Op_Host0, done.
- Complete: secure_network, secure_Op_Server0, secure_Enterprise0,
  secure_Enterprise1, secure_Enterprise2, secure_User1, secure_User2,
  secure_User3, secure_User4, secure_Op_Host0, secure_Op_Host1,
  secure_Op_Host2, done.

The directed Red baselines from the preceding changes are retained. Red
attacks the enterprise gateway and then the server, with retry rules after
failed access. Environment and Red are identical within every pair;
initial domain assignments, evaluations, groups, and formulae are also
identical. Guided initialization adds only Blue.blue_goal_level = secure_network.

Apart from the initial foothold, off-route hosts cannot be compromised
under this directed Red policy and retain clean reports. Their mapping
uses these invariants while retaining their original goal labels.
Unconditional fallback return rules make extra action-conditioned return
rules for those unreachable host stages redundant.

## Default BDD settings

| Example | Model | States | Median elapsed time (s) | BDD memory (MB) |
| --- | --- | ---: | ---: | ---: |
| Cage1-small | baseline | 20 | 0.039 | 9.177 |
| Cage1-small | guided | 14 | 0.040 | 9.218 |
| Cage1-simple | baseline | 3,903 | 0.263 | 11.405 |
| Cage1-simple | guided | 97 | 0.339 | 10.980 |
| Cage1-complete | baseline | 32,559 | 3.723 | 18.971 |
| Cage1-complete | guided | 97 | 6.776 | 15.986 |

The default-setting measurements do not show a runtime reduction in the
larger goal-controlled models. The extra control state has encoding costs
even when the reachable graph is much smaller.

## Explicit BDD-order comparison

This is a separate, disclosed comparison: simple uses -o 1 and complete
uses -o 1 -g 1. Small uses the defaults. Within each pair, both models use
exactly the same flags. These settings change the symbolic encoding,
not goal states or transition semantics. They were explored because
verification costs depend on BDD ordering. They are not claimed to be
the fastest settings for every individual model. The default results
above are retained rather than replaced by the favorable comparison.

| Example | Model | States | Median elapsed time (s) | BDD memory (MB) |
| --- | --- | ---: | ---: | ---: |
| Cage1-small | baseline | 20 | 0.048 | 9.177 |
| Cage1-small | guided | 14 | 0.046 | 9.218 |
| Cage1-simple | baseline | 3,903 | 0.519 | 13.998 |
| Cage1-simple | guided | 97 | 0.503 | 13.943 |
| Cage1-complete | baseline | 32,559 | 16.693 | 41.807 |
| Cage1-complete | guided | 97 | 15.205 | 31.357 |

Strict reductions under the explicit settings:

- Cage1-small: {'reachable_states': True, 'bdd_bytes': False, 'median_wall_seconds': True}.
- Cage1-simple: {'reachable_states': True, 'bdd_bytes': True, 'median_wall_seconds': True}.
- Cage1-complete: {'reachable_states': True, 'bdd_bytes': True, 'median_wall_seconds': True}.


The requirement that states, memory, and time all decrease in every
example is still not fully met: small needs more BDD memory with its
original goal state. No goal level was removed and no unrelated baseline
state was added to manufacture an improvement. Speedups under the explicit
settings must not be presented as independent of BDD ordering.

## Measurement procedure

MCMAS 1.3.0, Ubuntu 24.04 under WSL2, no export. One excluded warm-up and
11 serial measured runs per model, alternating baseline/guided order.
Primary times use Python's monotonic perf_counter around the entire
process. All 11 elapsed measurements are retained in the median.
MCMAS uses a nonmonotonic ftime-based clock and printed negative times
in some trials; raw printed values are retained. The separate MCMAS
median excludes negative printed durations and records their count.
This does not exclude any monotonic elapsed observation.

BDD MB means the reported BDD bytes divided by 1,000,000. This is distinct
from peak process RAM. Every GNU time output and peak RSS measurement is
retained in the JSON logs; a BDD-memory reduction does not establish a
reduction in every RAM statistic.

Default raw data: [results.json](cage1_results/results.json) and
[summary.csv](cage1_results/summary.csv). Explicit-order raw data:
[ordered/results.json](cage1_results/ordered/results.json) and
[ordered/summary.csv](cage1_results/ordered/summary.csv).

## Verification

The CAGE property results are unchanged within each pair. For simple and
complete they are true, true, true, false, true: gateway root possibility,
server root possibility, impact possibility, Red forcing impact, and Blue
guaranteeing service availability. Small retains true, true, false, true.
These are perfect-information checks with the original pass-through
restoration choice, not a claim of an observation-uniform Jason strategy
or original CybORG reward.

All 14 supplied models were checked. All six CAGE models are deadlock-free.
Additional MCMAS queries establish reachability of the network and attacked-host
stages, a path from each attacked-host stage back to the network goal,
and unreachability of the reserved done value. The extra queries are run on
temporary copies, leaving the published formula sections unchanged.
[Validation logs](cage1_results/validation.json) retain every result.
Ten automated tests cover regeneration, exact original goal-domain
preservation, initialization and goal updates, generator reproducibility,
pair invariants, host-count validation, and signed-clock handling.

The four rescue directories remain unchanged. The earlier cleanup of
68 redundant ASL tests remains separately verified by the seven matching
before/after output hashes in [asl_cleanup_verification.json](asl_cleanup_verification.json).

## Paper and reproduction

[Updated source](ICAART2027_updated.tex) preserves the original
goal-method section and its listings. [Exact original-line edits](paper_edits.md)
replace the previous instructions about removing goal control.

Run from the repository root, with MCMAS commands in Linux/WSL:

```bash
python3 -B -m unittest discover -s src -p 'test_*.py' -v
python3 -B tools/cage1/validate.py
python3 -B tools/cage1/benchmark.py --repeats 11
python3 -B tools/cage1/benchmark.py --repeats 11 --profile ordered --output docs/cage1_results/ordered
```


Adding --require-reductions makes the benchmark fail if any pair lacks
a strict reduction in states, BDD bytes, or median monotonic elapsed time.
The original goal-control structure is checked before benchmarking.
The current all-example strict check fails; this limitation is explicit.
