"""Reproduce CAGE comparisons serially with identical MCMAS settings (Linux/WSL)."""
import argparse
import csv
import hashlib
import json
import platform
import re
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("Cage1-small", "Cage1-simple", "Cage1-complete")


def block(text, name):
    return re.search(rf"(?ms)^Agent {name}\s*$.*?^end Agent\s*$", text).group(0).strip()


def check_pair(baseline, guided):
    before, after = baseline.read_text(), guided.read_text()
    for name in ("Environment", "Red"):
        if block(before, name) != block(after, name):
            raise ValueError(f"{name} differs between {baseline} and {guided}")
    for name in ("Evaluation", "Groups", "Formulae", "InitStates"):
        pattern = rf"(?ms)^{name}\s*$.*?^end {name}\s*$"
        if re.search(pattern, before).group(0).strip() != re.search(pattern, after).group(0).strip():
            raise ValueError(f"{name} differs between {baseline} and {guided}")


def parse_output(output):
    def value(label):
        match = re.search(re.escape(label) + r"\s*=\s*([\d.eE+]+)", output)
        if not match:
            raise ValueError(f"Missing MCMAS statistic: {label}\n{output}")
        return match.group(1)
    formulae = re.findall(r"Formula number (\d+): (.*), is (TRUE|FALSE) in the model", output)
    if not formulae:
        raise ValueError(f"No checked properties:\n{output}")
    return {
        "reachable_states": int(float(value("number of reachable states"))),
        "mcmas_seconds": float(value("execution time")),
        "bdd_bytes": int(value("BDD memory in use")),
        "formulae": [{"number": int(n), "formula": f, "holds": v == "TRUE"}
                     for n, f, v in formulae],
    }


def run_model(executable, model, timeout, flags=()):
    command = [executable, *flags, str(model.relative_to(ROOT))]
    timer = Path("/usr/bin/time")
    timed = [str(timer), "-v", *command] if timer.exists() else command
    start = time.perf_counter()
    result = subprocess.run(timed, cwd=ROOT, text=True, capture_output=True,
                            timeout=timeout, check=True)
    record = parse_output(result.stdout)
    record.update(command=command, wall_seconds=time.perf_counter() - start,
                  stdout=result.stdout, stderr=result.stderr)
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", result.stderr)
    record["peak_rss_kib"] = int(rss.group(1)) if rss else None
    return record


def summarize(runs):
    first = runs[0]
    for run in runs:
        for key in ("reachable_states", "bdd_bytes", "formulae"):
            if run[key] != first[key]:
                raise ValueError(f"Inconsistent repeated result for {key}")
    return {"reachable_states": first["reachable_states"], "bdd_bytes": first["bdd_bytes"],
            "median_mcmas_seconds": statistics.median(r["mcmas_seconds"] for r in runs),
            "median_wall_seconds": statistics.median(r["wall_seconds"] for r in runs),
            "median_peak_rss_kib": statistics.median(r["peak_rss_kib"] for r in runs)
            if all(r["peak_rss_kib"] is not None for r in runs) else None,
            "formulae": first["formulae"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcmas", default="mcmas")
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/cage1_results")
    parser.add_argument("--require-reductions", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    executable = shutil.which(args.mcmas)
    if not executable:
        parser.error("MCMAS executable not found")
    report = {"platform": platform.platform(), "python": platform.python_version(),
              "measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "mcmas_executable": str(Path(executable).resolve()), "flags": [],
              "repeats": args.repeats, "warmups_per_model": 1,
              "procedure": "Serial runs; alternate baseline/guided order each repeat; no export.",
              "scenarios": {}}
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for scenario in SCENARIOS:
        models = {"baseline": ROOT / f"examples/{scenario}/input/cage1_baseline.ispl",
                  "guided": ROOT / f"examples/{scenario}/generated/cage1_jason_guided.ispl"}
        check_pair(models["baseline"], models["guided"])
        runs = {kind: [] for kind in models}
        warmups = {kind: run_model(executable, model, args.timeout) for kind, model in models.items()}
        for i in range(args.repeats):
            for kind in (("baseline", "guided") if i % 2 == 0 else ("guided", "baseline")):
                runs[kind].append(run_model(executable, models[kind], args.timeout))
        summaries = {kind: summarize(values) for kind, values in runs.items()}
        before, after = summaries["baseline"], summaries["guided"]
        same_properties = before["formulae"] == after["formulae"]
        protected = any("<blue_team>G OTService_running" == f["formula"].strip("()") and f["holds"]
                        for f in after["formulae"])
        if not same_properties or not protected:
            raise ValueError(f"Strategic-property regression in {scenario}: {summaries}")
        reductions = {key: after[key] < before[key]
                      for key in ("reachable_states", "bdd_bytes", "median_mcmas_seconds")}
        report["scenarios"][scenario] = {
            "models": {kind: {"path": str(model.relative_to(ROOT)),
                               "sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
                       for kind, model in models.items()},
            "same_properties": same_properties, "blue_protects_service": protected,
            "strict_reductions": reductions, "summary": summaries, "warmups": warmups, "runs": runs}
        for kind, summary in summaries.items():
            rows.append({"scenario": scenario, "model": kind,
                         **{k: v for k, v in summary.items() if k != "formulae"}})
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(scenario, json.dumps(summaries), "reductions:", reductions, flush=True)
    with (args.output / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if args.require_reductions and not all(all(s["strict_reductions"].values())
                                          for s in report["scenarios"].values()):
        raise SystemExit("One or more strict reductions were not observed; see results.json")


if __name__ == "__main__":
    main()
