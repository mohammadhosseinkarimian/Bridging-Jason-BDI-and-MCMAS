"""Regression contracts for the directed attacker and hierarchical Blue goals."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

import formatting as fmt
import jason_guided as jg


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cage_generator", ROOT / "tools/cage1/generate.py")
cage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cage)
bench_spec = importlib.util.spec_from_file_location("cage_benchmark", ROOT / "tools/cage1/benchmark.py")
bench = importlib.util.module_from_spec(bench_spec)
bench_spec.loader.exec_module(bench)


class CageRegressionTests(unittest.TestCase):
    def test_all_checked_in_guided_models_regenerate(self):
        with tempfile.TemporaryDirectory() as directory:
            for config in sorted((ROOT / "examples").glob("*/input/jason_mapping.json")):
                with self.subTest(example=config.parent.parent.name):
                    mapping = json.loads(config.read_text())
                    expected = config.parent / mapping["files"]["output"]
                    output = Path(directory) / "output.ispl"
                    jg.translate(config, output_override=output)
                    self.assertEqual(output.read_text(), expected.read_text())

    def test_generator_reproduces_shipped_inputs(self):
        mapping = json.loads((ROOT / "tools/cage1/mapping.json").read_text())
        for name, counts in (("Cage1-simple", (1, 1, 1)), ("Cage1-complete", (5, 3, 3))):
            with self.subTest(example=name):
                counts = dict(zip(("user", "enterprise", "operational"), counts))
                folder = ROOT / "examples" / name / "input"
                self.assertEqual(cage.render(mapping, counts), (folder / "cage1_baseline.ispl").read_text())
                generated = cage.render_jason(mapping, counts, "cage1_baseline.ispl",
                                              "../../../agents/blue_agent.asl")
                self.assertEqual(generated, json.loads((folder / "jason_mapping.json").read_text()))

    def test_directed_attacker_and_pair_invariants(self):
        for name, gateway in (("Cage1-simple", "Enterprise0"), ("Cage1-complete", "Enterprise2")):
            with self.subTest(example=name):
                folder = ROOT / "examples" / name
                baseline = (folder / "input/cage1_baseline.ispl").read_text()
                guided = (folder / "generated/cage1_jason_guided.ispl").read_text()
                for agent in ("Environment", "Red"):
                    self.assertEqual(fmt.parse_ispl_block(baseline, agent)[2],
                                     fmt.parse_ispl_block(guided, agent)[2])
                for section in ("Evaluation", "Groups", "Formulae"):
                    pattern = rf"{section}\n.*?end {section}"
                    self.assertEqual(re.search(pattern, baseline, re.S).group(),
                                     re.search(pattern, guided, re.S).group())
                red = fmt.parse_agent_decision(baseline, "Red")[2]
                actions = {action for _, choices in red for action in choices}
                self.assertNotIn("Sleep", actions)
                self.assertNotIn("DiscoverRemoteSystems_User", actions)
                targets = {action.split("_", 1)[1] for action in actions
                           if action.startswith(("ExploitRemoteService_", "PrivilegeEscalate_"))}
                self.assertEqual(targets, {gateway, "Op_Server0"})
                self.assertIn(f"red_{gateway} = service if turn = red_turn and Red.Action = DiscoverRemoteSystems_Operational", baseline)
                self.assertIn("red_Op_Server0 = service if turn = red_turn and Red.Action = Impact_Op_Server0", baseline)

    def test_original_goal_domains_and_progress_are_retained(self):
        expected = {
            "Cage1-small": ["secure_network", "secure_Op_Server0", "done"],
            "Cage1-simple": ["secure_network", "secure_Op_Server0", "secure_Enterprise0", "secure_Op_Host0", "done"],
            "Cage1-complete": ["secure_network", "secure_Op_Server0", "secure_Enterprise0", "secure_Enterprise1", "secure_Enterprise2", "secure_User1", "secure_User2", "secure_User3", "secure_User4", "secure_Op_Host0", "secure_Op_Host1", "secure_Op_Host2", "done"],
        }
        for name, goals in expected.items():
            with self.subTest(example=name):
                folder = ROOT / "examples" / name
                config = json.loads((folder / "input/jason_mapping.json").read_text())
                role = config["jason"]["roles"]["blue"]
                self.assertTrue(role["program"].endswith("/blue_agent.asl"))
                self.assertNotIn("elide_constant_goal", role["plan"])
                guided = (folder / "generated/cage1_jason_guided.ispl").read_text()
                values = re.search(r"blue_goal_level:\s*\{([^}]+)\}", guided).group(1)
                self.assertEqual([x.strip() for x in values.split(",")], goals)
                self.assertIn("Blue.blue_goal_level = secure_network", guided)
                self.assertIn("blue_goal_level = secure_Op_Server0 if blue_goal_level = secure_network", guided)
                self.assertIn("blue_goal_level = secure_network if blue_goal_level = secure_Op_Server0 and Blue.Action = restore_Op_Server0", guided)
                self.assertIn("blue_goal_level = secure_Op_Server0 and Environment.compromised_Op_Server0 = privileged", guided)
                baseline = (folder / "input/cage1_baseline.ispl").read_text()
                original_init = re.search(r"InitStates\n.*?end InitStates", baseline, re.S).group()
                guided_init = re.search(r"InitStates\n.*?end InitStates", guided, re.S).group()
                self.assertEqual(original_init, guided_init.replace("    Blue.blue_goal_level = secure_network and\n", ""))

    def test_generator_rejects_nonpositive_counts(self):
        for count in (0, -1):
            with self.assertRaisesRegex(ValueError, "at least 1"):
                cage.read_count("users", count)

    def test_negative_mcmas_clock_preserves_monotonic_measurement(self):
        output = ("Formula number 1: (<blue_team>G OTService_running), is TRUE in the model\n"
                  "execution time = -2.152\nnumber of reachable states = 14\n"
                  "BDD memory in use = 9217904\n")
        record = bench.parse_output(output)
        record.update(wall_seconds=0.04, peak_rss_kib=14000)
        summary = bench.summarize([record])
        self.assertEqual(summary["median_wall_seconds"], 0.04)
        self.assertEqual(summary["mcmas_clock_anomalies"], 1)
        self.assertIsNone(summary["median_mcmas_seconds"])


if __name__ == "__main__":
    unittest.main()
