"""Model-check every supplied example and check CAGE deadlock freedom."""
import argparse
import json
import shutil
from pathlib import Path

from benchmark import ROOT, SCENARIOS, check_pair, run_model


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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
