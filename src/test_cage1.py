"""Regression contracts for the directed attacker and reactive Blue mapping."""
import copy
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
                                              "../../../agents/blue_agent_reactive.asl")
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
                for section in ("InitStates", "Evaluation", "Groups", "Formulae"):
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

    def test_constant_goal_elision_rejects_real_task_progress(self):
        plan = fmt.Plan("respond", "true", "restore", [fmt.parse_term("restore")], 0)
        control = fmt.GoalControl("respond", ["respond", "done"], [], ["respond"])
        spec = fmt.AgentSpec("blue", [plan], control, {}, "", [])
        role = {"ispl_agent": "Blue", "goal_var": "goal",
                "plan": {"elide_constant_goal": True}}
        mapping = {"jason": {"roles": {"blue": role}}}
        raw = (ROOT / "examples/Cage1-small/input/cage1_baseline.ispl").read_text()
        with self.assertRaisesRegex(ValueError, "no control transitions"):
            fmt.build_plain_agent_block(spec, mapping, raw, [], ["goal = done if goal = respond;"])
        other = copy.deepcopy(spec)
        other.control.values.insert(1, "repair")
        with self.assertRaisesRegex(ValueError, "single active goal"):
            fmt.build_plain_agent_block(other, mapping, raw, [], [])

    def test_generator_rejects_nonpositive_counts(self):
        for count in (0, -1):
            with self.assertRaisesRegex(ValueError, "at least 1"):
                cage.read_count("users", count)


if __name__ == "__main__":
    unittest.main()
