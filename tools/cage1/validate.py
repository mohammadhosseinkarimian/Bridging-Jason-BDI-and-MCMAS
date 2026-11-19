"""Model-check every supplied example and check CAGE deadlock freedom."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from benchmark import ROOT, SCENARIOS, check_pair, run_model


def check_goal_control(executable, model, timeout):
    source = model.read_text()
    targets = ["Op_Server0"]
    gateway = "Enterprise0" if "Cage1-simple" in str(model) else "Enterprise2"
    if "Cage1-small" not in str(model):
        targets.append(gateway)
    evaluation = ["    jason_network if Blue.blue_goal_level = secure_network;",
                  "    jason_done if Blue.blue_goal_level = done;"]
    formulae = ["    EF jason_network;", "    AG (!jason_done);"]
    for i, host in enumerate(targets):
        evaluation.append(f"    jason_host_{i} if Blue.blue_goal_level = secure_{host};")
        formulae.append(f"    EF (jason_host_{i} and EF jason_network);")
    probe = source.replace("end Evaluation", "\n".join(evaluation) + "\nend Evaluation")
    probe = probe.replace("end Formulae", "\n".join(formulae) + "\nend Formulae")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        path = Path(directory) / "goal_progress.ispl"
        path.write_text(probe)
        result = run_model(executable, path, timeout)
        checks = result["formulae"][-len(formulae):]
        if not all(item["holds"] for item in checks):
            raise ValueError(f"Goal-control reachability/progress check failed: {checks}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcmas", default="mcmas")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/cage1_results/validation.json")
    args = parser.parse_args()
    executable = shutil.which(args.mcmas)
    if not executable:
        parser.error("MCMAS executable not found")
    results = {}
    for config in sorted((ROOT / "examples").glob("*/input/jason_mapping.json")):
        mapping = json.loads(config.read_text())
        scenario = config.parent.parent.name
        models = {kind: (config.parent / mapping["files"][key]).resolve()
                  for kind, key in (("baseline", "raw"), ("guided", "output"))}
        is_cage = scenario in SCENARIOS
        if is_cage:
            check_pair(models["baseline"], models["guided"])
        results[scenario] = {}
        for kind, model in models.items():
            result = run_model(executable, model, args.timeout, ["-k"] if is_cage else [])
            if is_cage and "There is no deadlock state in the model!" not in result["stdout"]:
                raise ValueError(f"Deadlock check failed for {model}\n{result['stdout']}")
            results[scenario][kind] = result
            print(scenario, kind, result["reachable_states"], result["formulae"], flush=True)
        if is_cage and results[scenario]["baseline"]["formulae"] != results[scenario]["guided"]["formulae"]:
            raise ValueError(f"CAGE property mismatch: {scenario}")
        if is_cage:
            results[scenario]["goal_control"] = check_goal_control(executable, models["guided"], args.timeout)
            print(scenario, "goal-stage reachability and return checks passed", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
