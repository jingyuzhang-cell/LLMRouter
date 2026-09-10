import unittest

import numpy as np

from router_v2.oracle_gap_analysis import summarize_block


class OracleGapAnalysisTests(unittest.TestCase):
    def test_gap_and_fractional_winners_do_not_argmax_ties(self):
        records = [
            {"query_id": "a", "quality": np.array([1.0, 1.0, 0.0, 0.0])},
            {"query_id": "b", "quality": np.array([0.0, 0.0, 1.0, 0.0])},
            {"query_id": "c", "quality": np.array([0.0, 0.0, 0.0, 1.0])},
        ]
        row = summarize_block(records, global_best=3)
        self.assertEqual(row["best_single_slot"], "reasoning")
        self.assertAlmostEqual(row["gap"]["mean"], 2 / 3)
        self.assertEqual(row["gap"]["median"], 1.0)
        self.assertEqual(row["winner_distribution"]["strict_counts"]["small"], 0)
        self.assertEqual(row["winner_distribution"]["strict_counts"]["medium"], 0)
        self.assertAlmostEqual(row["winner_distribution"]["fractional_rate"]["small"], 1 / 6)
        self.assertAlmostEqual(row["winner_distribution"]["fractional_rate"]["medium"], 1 / 6)


if __name__ == "__main__":
    unittest.main()
