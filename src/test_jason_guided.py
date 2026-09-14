import unittest

import jason_guided as jg


def term(op, name):
    return jg.Term(op=op, name=name, args=[], raw=f"{op}{name}")


def plan(goal, context, terms, index):
    return jg.Plan(
        goal=goal,
        context=context,
        body="; ".join(t.raw for t in terms),
        terms=terms,
        index=index,
    )


class JasonGuidedTests(unittest.TestCase):
    def test_build_goal_control(self):
        plans = [
            plan("saved", "buried & at_area_2", [term("!", "rescued"), term("!", "notified")], 0),
            plan("saved", "not at_area_2", [term("", "move"), term("?", "saved")], 1),
            plan("rescued", "buried & at_area_2", [term("", "rescue"), term("?", "rescued")], 2),
            plan("notified", "not buried", [term("", "notify"), term("?", "notified")], 3),
        ]
        role = {
            "plan": {
                "actions": {
                    "move": "move",
                    "rescue": "rescue",
                    "notify": "notify",
                }
            }
        }

        control = jg.BuildGoalControl(plans, "saved", role, {})

        self.assertEqual(control.top, "saved")
        self.assertEqual(control.reachable, ["saved", "rescued", "notified"])
        self.assertEqual(control.values, ["saved", "rescued", "notified", "done"])
        self.assertEqual(
            [(c.parent, c.child, c.plan_index) for c in control.calls],
            [
                ("saved", "rescued", 0),
                ("saved", "notified", 0),
            ],
        )

    def test_generate_protocol(self):
        rescue_plan = plan(
            "rescued",
            "buried & at_area_2",
            [term("", "rescue"), term("?", "rescued")],
            0,
        )
        control = jg.GoalControl(
            top="rescued",
            values=["rescued", "done"],
            calls=[],
            reachable=["rescued"],
        )
        spec = jg.AgentSpec(
            role_key="rescuer",
            plans=[rescue_plan],
            control=control,
            stages={},
            ranking_goal="",
            ranking_order=[],
        )
        role = {
            "ispl_agent": "Rescuer",
            "goal_var": "goal",
            "plan": {
                "actions": {"rescue": "rescue"},
                "predicates": {
                    "buried": {"eq": [{"env": "buried"}, True]},
                    "at_area_2": {"eq": [{"env": "area"}, "area_2"]},
                },
            },
        }
        mapping = {"jason": {"roles": {"rescuer": role}}}
        baseline = [("true", ["move", "rescue", "rest"])]

        generated = jg.GenerateProtocol(
            spec,
            mapping,
            baseline_protocol=baseline,
            environment_name="Environment",
        )

        self.assertEqual(
            generated,
            [
                (
                    "goal = rescued and Environment.buried = true and Environment.area = area_2",
                    ["rescue"],
                )
            ],
        )

    def test_generate_evolution_rules(self):
        plans = [
            plan("saved", "buried & at_area_2", [term("!", "rescued"), term("!", "notified")], 0),
            plan("rescued", "buried & at_area_2", [term("", "rescue"), term("?", "rescued")], 1),
            plan("notified", "not buried", [term("", "notify"), term("?", "notified")], 2),
        ]
        control = jg.GoalControl(
            top="saved",
            values=["saved", "rescued", "notified", "done"],
            calls=[],
            reachable=["saved", "rescued", "notified"],
        )
        spec = jg.AgentSpec(
            role_key="rescuer",
            plans=plans,
            control=control,
            stages={},
            ranking_goal="",
            ranking_order=[],
        )
        role = {
            "ispl_agent": "Rescuer",
            "goal_var": "goal",
            "plan": {
                "actions": {
                    "rescue": "rescue",
                    "notify": "notify",
                },
                "predicates": {
                    "buried": {"eq": [{"env": "buried"}, True]},
                    "at_area_2": {"eq": [{"env": "area"}, "area_2"]},
                },
                "transitions": [
                    {"from": "rescued", "to": "notified", "action": "rescue"},
                    {"from": "notified", "to": "done", "action": "notify"},
                ],
            },
        }
        mapping = {"jason": {"roles": {"rescuer": role}}}

        generated = jg.GenerateEvolutionRules(
            spec,
            mapping,
            environment_name="Environment",
        )

        self.assertEqual(
            generated,
            [
                "        goal = rescued if goal = saved and Environment.buried = true and Environment.area = area_2;",
                "        goal = notified if goal = rescued and Rescuer.Action = rescue;",
                "        goal = done if goal = notified and Rescuer.Action = notify;",
            ],
        )

    def test_replace_agent_decision_model(self):
        raw = """Agent Rescuer
    Vars:
        buried: boolean;
    end Vars
    Actions = {move};
    Protocol:
        Other: {move};
    end Protocol
    Evolution:
        buried = buried if Action = move;
    end Evolution
end Agent
Agent Observer
    Actions = {wait};
    Protocol:
        Other: {wait};
    end Protocol
end Agent
"""

        replacement = """Agent Rescuer
    Vars:
        buried: boolean;
        goal: {saved, rescued, notified, done};
    end Vars
    Actions = {move, rescue, notify, rest};
    Protocol:
        goal = rescued and buried: {rescue};
        Other: {rest};
    end Protocol
    Evolution:
        goal = notified if goal = rescued and Action = rescue;
    end Evolution
end Agent"""

        expected = """Agent Rescuer
    Vars:
        buried: boolean;
        goal: {saved, rescued, notified, done};
    end Vars
    Actions = {move, rescue, notify, rest};
    Protocol:
        goal = rescued and buried: {rescue};
        Other: {rest};
    end Protocol
    Evolution:
        goal = notified if goal = rescued and Action = rescue;
    end Evolution
end Agent

Agent Observer
    Actions = {wait};
    Protocol:
        Other: {wait};
    end Protocol
end Agent
"""

        generated = jg.ReplaceAgentDecisionModel(
            raw,
            {"Rescuer": replacement},
        )

        self.assertEqual(generated, expected)


if __name__ == "__main__":
    unittest.main()
