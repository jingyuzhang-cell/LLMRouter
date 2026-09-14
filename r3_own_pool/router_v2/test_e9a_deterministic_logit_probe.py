import unittest
import numpy as np
from .run_e9a_deterministic_logit_probe import (logit_statistics, sampled_majority_options,
                                                build_features, choose, ARMS)


class E9aTests(unittest.TestCase):
    def test_logit_statistics_layout(self):
        probs = np.array([[0.5, 0.3, 0.2, 0, 0, 0, 0, 0, 0, 0],
                          [0.1] * 10])
        stats, top1 = logit_statistics(probs)
        self.assertEqual(stats.shape, (2, 14))
        self.assertEqual(top1.tolist(), [0, 0])
        self.assertAlmostEqual(stats[0, 10], 0.5)                       # top-1 prob
        self.assertAlmostEqual(stats[0, 11], 0.2)                       # margin
        self.assertAlmostEqual(stats[0, 12], -(0.5 * np.log(0.5) + 0.3 * np.log(0.3) + 0.2 * np.log(0.2)))
        self.assertAlmostEqual(stats[1, 10], 0.1)
        self.assertAlmostEqual(stats[1, 11], 0.0)                       # uniform margin
        self.assertGreater(stats[1, 12], stats[0, 12])                  # uniform entropy higher

    def test_build_features_dimensions_and_no_quality_leakage(self):
        import tempfile
        from pathlib import Path
        rng = np.random.default_rng(21)
        e = rng.normal(size=(6, 5))
        probs = rng.dirichlet(np.ones(10), size=6)
        ids = [f'q{i}' for i in range(6)]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'medium.jsonl').write_text('')
            original = sampled_majority_options.__globals__['RAW']
            sampled_majority_options.__globals__['RAW'] = Path(tmp)
            try:
                arms, detail = build_features(e, probs, ids)
                arms2, detail2 = build_features(e, probs, ids)
            finally:
                sampled_majority_options.__globals__['RAW'] = original
        self.assertEqual(arms[ARMS[0]].shape, (6, 5))
        self.assertEqual(arms[ARMS[1]].shape, (6, 5 + 16))
        self.assertEqual(arms[ARMS[2]].shape, (6, 5 + 10))
        for a in ARMS:
            np.testing.assert_array_equal(arms[a], arms2[a])

    def test_majority_options_require_unique_mode(self):
        import json as _json
        from pathlib import Path
        import tempfile
        rows = [
            dict(query_id='q0', parse_succeeded=True, extracted_option='A'),
            dict(query_id='q0', parse_succeeded=True, extracted_option='A'),
            dict(query_id='q0', parse_succeeded=True, extracted_option='B'),
            dict(query_id='q0', parse_succeeded=False, extracted_option=None),
            dict(query_id='q0', parse_succeeded=True, extracted_option='C'),
            dict(query_id='q1', parse_succeeded=True, extracted_option='A'),
            dict(query_id='q1', parse_succeeded=True, extracted_option='B'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'medium.jsonl'
            path.write_text(''.join(_json.dumps(r) + '\n' for r in rows))
            original = sampled_majority_options.__globals__['RAW']
            sampled_majority_options.__globals__['RAW'] = Path(tmp)
            try:
                letters, exists = sampled_majority_options(['q0', 'q1', 'q2'])
            finally:
                sampled_majority_options.__globals__['RAW'] = original
        self.assertEqual(letters[0], 0)                 # majority A
        self.assertEqual(exists[0], 1.0)
        self.assertEqual(exists[1], 0.0)                # tie -> no majority
        self.assertEqual(letters[2], -1)                # no repeats at all
        self.assertEqual(exists[2], 0.0)

    def test_choose_tie_order(self):
        pred = np.zeros((2, 3))
        np.testing.assert_array_equal(choose(pred), [0, 0])
        pred[1] = [-1, 0.5, 0.5]
        self.assertEqual(choose(pred)[1], 1)            # first max among alts


if __name__ == '__main__':
    unittest.main()
