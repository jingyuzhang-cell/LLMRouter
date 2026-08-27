import unittest

from finrome_frar_experiment import DEFAULT_DYNAMIC_LAMBDA, FrozenModels, freeze_decisions, outcome_utility


class TestFRAR(unittest.TestCase):
    def test_soft_penalty_keeps_high_utility_low_enough_risk(self):
        candidates = {"t": [
            {"model": "deepseek-chat", "utility_hat": .85, "risk_hat": .05, "risk_level": "medium"},
            {"model": "glm-5.2", "utility_hat": .20, "risk_hat": .10, "risk_level": "medium"},
            {"model": "qwen-plus", "utility_hat": .95, "risk_hat": .30, "risk_level": "medium"},
            {"model": "qwen-turbo", "utility_hat": .30, "risk_hat": .20, "risk_level": "medium"},
        ]}
        fitted = FrozenModels(None, None, {}, "qwen-plus")
        picks = freeze_decisions(candidates, fitted, DEFAULT_DYNAMIC_LAMBDA, 1)
        self.assertEqual(picks["frar_dynamic"]["t"], "qwen-plus")
        self.assertNotEqual(picks["rank_safety"]["t"], "qwen-plus")

    def test_high_risk_lambda_can_switch_model(self):
        candidates = {"t": [
            {"model": "deepseek-chat", "utility_hat": .85, "risk_hat": .05, "risk_level": "high"},
            {"model": "glm-5.2", "utility_hat": .10, "risk_hat": .10, "risk_level": "high"},
            {"model": "qwen-plus", "utility_hat": .95, "risk_hat": .80, "risk_level": "high"},
            {"model": "qwen-turbo", "utility_hat": .20, "risk_hat": .20, "risk_level": "high"},
        ]}
        fitted = FrozenModels(None, None, {}, "qwen-plus")
        self.assertEqual(freeze_decisions(candidates, fitted, DEFAULT_DYNAMIC_LAMBDA, 1)["frar_dynamic"]["t"], "deepseek-chat")

    def test_outcome_utility_formula(self):
        x = {"quality": 1., "cost": 0., "latency": 0., "reliability": 1.}
        self.assertAlmostEqual(outcome_utility(x), 1.)


if __name__ == "__main__":
    unittest.main()
