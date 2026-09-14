import unittest
import numpy as np
from .run_e8_behavior_probe_feasibility import (probe_features, joint_features, rotation_targets, choose,
                                                ROTATIONS)


def row(option='C', parsed=True, chars=100, tokens=50, latency=5000.0, tps=60.0,
        finish='stop', status='ok'):
    return dict(answer='x' * chars, parse_succeeded=parsed, extracted_option=option if parsed else None,
                cost=dict(tokens_output=tokens), latency=dict(total_ms=latency, tokens_per_second=tps),
                finish_reason=finish, status=status)


class E8Tests(unittest.TestCase):
    def test_rotations_are_all_ordered_distinct_pairs(self):
        self.assertEqual(len(ROTATIONS), 20)
        self.assertTrue(all(p != r for p, r in ROTATIONS))
        self.assertEqual(len(set(map(tuple, ROTATIONS))), 20)

    def test_targets_exclude_probe_and_eval_repeats(self):
        v = np.arange(2 * 4 * 5).reshape(2, 4, 5).astype(float)
        for p, r in [(0, 1), (2, 4)]:
            keep = [t for t in range(5) if t not in (p, r)]
            expected = v[:, :3, keep].mean(2) - v[:, 3, keep].mean(1)[:, None]
            np.testing.assert_allclose(rotation_targets(v, p, r), expected)

    def test_probe_features_layout_and_flags(self):
        z = probe_features(row())
        self.assertEqual(len(z), 18)
        self.assertEqual(z[0], 1.0)            # parsed
        self.assertEqual(z[1], 0.0)            # not unparsed
        self.assertEqual(z[2:12].tolist(), [0, 0, 1, 0, 0, 0, 0, 0, 0, 0])  # option C
        self.assertAlmostEqual(z[12], np.log1p(100))
        self.assertAlmostEqual(z[13], np.log1p(50))
        z0 = probe_features(row(parsed=False, option=None))
        self.assertEqual(z0[0], 0.0)
        self.assertEqual(sum(z0[2:12]), 0.0)   # no option one-hot when unparseable

    def test_joint_agreement_cases(self):
        a = probe_features(row(option='B'))
        same = probe_features(row(option='B'))
        diff = probe_features(row(option='C'))
        unparseable = probe_features(row(parsed=False, option=None))
        self.assertEqual(joint_features(a, same)[0], 1.0)     # agree
        self.assertEqual(joint_features(a, diff)[1], 1.0)     # disagree
        self.assertEqual(joint_features(a, unparseable)[2], 1.0)  # either unparsed

    def test_choose_tie_order_matches_e6(self):
        pred = np.zeros((3, 3))                 # all heads tie with R1 at 0
        np.testing.assert_array_equal(choose(pred), [0, 0, 0])  # medium wins ties (first max)
        pred2 = np.array([[0., 0., 0.], [-1., 0.2, 0.1]])
        np.testing.assert_array_equal(choose(pred2), [0, 1])

    def test_no_target_or_eval_leakage_through_inputs(self):
        # rotation_targets depends only on the three target repeats
        v = np.random.default_rng(3).integers(0, 2, (6, 4, 5)).astype(float)
        for p, r in [(1, 3)]:
            base = rotation_targets(v, p, r)
            mutated = v.copy()
            mutated[:, :, r] = 1 - mutated[:, :, r]        # eval repeat changed
            np.testing.assert_array_equal(base, rotation_targets(mutated, p, r))


if __name__ == '__main__':
    unittest.main()
