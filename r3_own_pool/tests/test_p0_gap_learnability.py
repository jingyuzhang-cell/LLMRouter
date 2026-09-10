import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router_v2.p0_gap_learnability import (
    fit_pairwise_scores,
    guarded_pairwise_choice,
    objective_winner_summary,
    task_best_decisions,
    winner_set,
)


class P0GapLearnabilityTests(unittest.TestCase):
    def test_winner_set_keeps_ties(self):
        self.assertEqual(winner_set([1.0, 0.0, 1.0, 0.0]), (0, 2))

    def test_objective_summary_reports_tie_heavy_targets(self):
        y = np.array([[1, 0, 1, 0], [0, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        fixed = np.array([0, 0, 0])
        summary = objective_winner_summary(y, fixed)
        self.assertAlmostEqual(summary["unique_winner_rate"], 1 / 3)
        self.assertAlmostEqual(summary["multi_winner_rate"], 2 / 3)

    def test_task_best_uses_training_group_means_only(self):
        y = np.array(
            [
                [1, 0, 0, 0],
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 1, 0, 0],
            ],
            dtype=float,
        )
        groups = np.array(["a", "a", "b", "b"])
        decisions = task_best_decisions(y, groups, np.array([0, 2]), np.array([1, 3]))
        np.testing.assert_array_equal(decisions, [0, 1])

    def test_pairwise_training_ignores_tied_pairs(self):
        x = np.eye(4)
        y = np.array(
            [
                [1, 1, 0, 0],
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=float,
        )
        scores, probs = fit_pairwise_scores(x, y, x, alpha=1.0)
        self.assertEqual(scores.shape, (4, 4))
        self.assertTrue(np.all((probs["small>medium"] >= 0) & (probs["small>medium"] <= 1)))

    def test_guarded_pairwise_falls_back_on_small_advantage(self):
        scores = np.array([[2.0, 2.01, 0.0, 0.0], [2.0, 2.2, 0.0, 0.0]])
        choice = guarded_pairwise_choice(scores, np.zeros(2, dtype=int), tau=0.05)
        np.testing.assert_array_equal(choice, [0, 1])


if __name__ == "__main__":
    unittest.main()
