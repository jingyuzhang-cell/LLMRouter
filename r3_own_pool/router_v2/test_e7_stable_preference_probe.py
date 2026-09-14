import unittest
import numpy as np
from .run_e7_stable_preference_probe import (stable_switch_labels, structural_features, parse_prompt,
                                             fit_linear, stage2_apply)

REF = 3


def build(rows):
    """rows: (reasoning, medium, large, coder) binary draw lists -> (n,4,5) repeats."""
    v = np.zeros((len(rows), 4, 5))
    for i, (r1, med, lar, cod) in enumerate(rows):
        v[i, REF] = r1
        v[i, 0], v[i, 1], v[i, 2] = med, lar, cod
    return v


class E7Tests(unittest.TestCase):
    def test_labels_mean_and_consistency_semantics(self):
        rows = [
            ([1] * 5, [1] * 5, [1] * 5, [1] * 5),                       # q0 all ties: mean 0 -> not stable
            ([0, 0, 0, 0, 1], [1] * 5, [0, 0, 0, 0, 1], [0, 0, 0, 0, 1]),  # q1 delta +1,+1,+1,+1,0: stable
            ([1, 0, 1, 0, 1], [0, 1, 1, 1, 0], [1, 0, 1, 0, 1], [1, 0, 1, 0, 1]),  # q2 mean 0 -> not
            ([1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [1, 0, 0, 0, 0], [1, 0, 0, 0, 0]),  # q3 mean 0 -> not
            ([1, 0, 0, 0, 0], [0, 1, 1, 0, 0], [1, 0, 0, 0, 0], [1, 0, 0, 0, 0]),  # q4 mean .2, 1 loss -> stable
            ([1] * 5, [0, 1, 1, 1, 1], [1] * 5, [1] * 5),               # q5 net negative -> not
        ]
        stable, switch, which, mean5, consistency = stable_switch_labels(build(rows))
        self.assertEqual(stable[:, 0].tolist(), [False, True, False, False, True, False])
        self.assertFalse(stable[:, 1:].any())
        self.assertEqual(switch.tolist(), [False, True, False, False, True, False])
        self.assertEqual(which.tolist(), [-1, 0, -1, -1, 0, -1])
        self.assertEqual(consistency[4, 0], 4)
        self.assertAlmostEqual(float(mean5[4, 0]), 0.2)

    def test_which_alternative_prefers_bigger_mean_then_consistency(self):
        rows = [([0] * 5, [1] * 5, [1, 1, 1, 1, 0], [0] * 5)]
        _, switch, which, _, _ = stable_switch_labels(build(rows))
        self.assertTrue(switch[0])
        self.assertEqual(which[0], 0)

    def test_two_contradictions_fail_consistency_even_with_positive_mean(self):
        rows = [([1, 0, 1, 0, 0], [0, 1, 0, 1, 1], [1, 0, 1, 0, 0], [1, 0, 1, 0, 0])]  # mean .2, 2 losses
        stable, switch, _, _, consistency = stable_switch_labels(build(rows))
        self.assertEqual(consistency[0, 0], 3)
        self.assertFalse(stable[0, 0] or switch[0])

    def test_parse_prompt_splits_options_deterministically(self):
        text = 'Solve this.\n\nWhat is 2+3?\n\nA. 5\nB. 6\n\nLet us think.'
        stem, lens = parse_prompt(text)
        self.assertEqual(stem, 'Solve this.\n\nWhat is 2+3?\n\n')
        self.assertEqual(len(lens), 2)
        self.assertEqual(structural_features(text), structural_features(text))
        f = structural_features(text)
        self.assertEqual(len(f), 15)
        self.assertEqual(f[2], 2)      # n_options
        self.assertEqual(f[12], 1.0)   # stem ends with '?'

    def test_parse_prompt_fallback_without_options(self):
        stem, lens = parse_prompt('No options here?')
        self.assertEqual(stem, 'No options here?')
        self.assertEqual(lens, [0])

    def test_stage_fit_ignores_evaluation_rows(self):
        rng = np.random.default_rng(11)
        x = rng.normal(size=(40, 6))
        y = (x[:, 0] > 0).astype(int)
        m1 = fit_linear(x[:30], y[:30])
        p1 = m1['clf'].predict_proba(m1['scaler'].transform(x[30:]))[:, 1]
        x2, y2 = x.copy(), y.copy()
        x2[30:] *= 100
        y2[30:] = 1 - y2[30:]
        m2 = fit_linear(x2[:30], y2[:30])
        p2 = m2['clf'].predict_proba(m2['scaler'].transform(x[30:]))[:, 1]
        np.testing.assert_allclose(p1, p2, atol=1e-12)

    def test_stage2_argmax_over_available_classes(self):
        rng = np.random.default_rng(12)
        x = rng.normal(size=(30, 4))
        y = rng.choice([0, 2], 30)
        out = stage2_apply(fit_linear(x, y), x[:5])
        self.assertTrue(np.isin(out, [0, 2]).all())


if __name__ == '__main__':
    unittest.main()
