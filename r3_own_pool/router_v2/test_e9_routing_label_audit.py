import unittest
import numpy as np
from scipy.special import roots_legendre
from .run_e9_routing_label_audit import (p_greater, p_gain, p_tie, classify, vectorized_p_greater,
                                         predictive_resolution, CONF)


class E9AuditTests(unittest.TestCase):
    def test_p_greater_symmetric_and_extreme(self):
        self.assertAlmostEqual(p_greater(2.5, 3.5, 2.5, 3.5), 0.5, places=10)
        self.assertGreater(p_greater(5.5, 0.5, 0.5, 5.5), 0.95)
        self.assertLess(p_greater(0.5, 5.5, 5.5, 0.5), 0.05)

    def test_p_gain_margin_monotonic_and_zero(self):
        a1, b1, a2, b2 = 4.5, 1.5, 2.5, 3.5
        self.assertAlmostEqual(p_gain(a1, b1, a2, b2, 0.0), p_greater(a1, b1, a2, b2), places=6)
        self.assertGreater(p_gain(a1, b1, a2, b2, 0.0), p_gain(a1, b1, a2, b2, 0.1))
        self.assertGreater(p_gain(a1, b1, a2, b2, 0.1), p_gain(a1, b1, a2, b2, 0.3))

    def test_p_tie_high_for_equal_low_for_apart(self):
        tie_equal = p_tie(2.5, 3.5, 2.5, 3.5, 0.1)
        tie_apart = p_tie(5.5, 0.5, 0.5, 5.5, 0.1)
        # n=5 posteriors are wide: even equal models land in a ±0.1 band only ~29% of the time
        self.assertGreater(tie_equal, 0.25)
        self.assertLess(tie_apart, 0.05)

    def test_classify_hierarchy(self):
        self.assertEqual(classify(np.array([0.95, 0.2, 0.2]), 0.3, 0.9), 'switch')
        self.assertEqual(classify(np.array([0.5, 0.2, 0.2]), 0.95, 0.9), 'stay')
        self.assertEqual(classify(np.array([0.5, 0.2, 0.2]), 0.5, 0.95), 'tie')
        self.assertEqual(classify(np.array([0.5, 0.5, 0.5]), 0.5, 0.5), 'uncertain')

    def test_vectorized_matches_quadrature(self):
        rng = np.random.default_rng(31)
        nodes, weights = roots_legendre(64)
        a1 = rng.integers(1, 6) + 0.5
        b1 = rng.integers(1, 6) + 0.5
        a2 = rng.integers(1, 6) + 0.5
        b2 = rng.integers(1, 6) + 0.5
        exact = p_greater(a1, b1, a2, b2)
        approx = vectorized_p_greater(np.array([a1]), np.array([b1]),
                                      np.array([a2]), np.array([b2]), nodes, weights)[0]
        self.assertAlmostEqual(exact, approx, places=4)

    def test_predictive_resolution_bounds_and_monotonicity(self):
        rng = np.random.default_rng(32)
        alpha = rng.integers(1, 6, (12, 4)) + 0.5
        beta_ = 5.5 - (alpha - 0.5)          # keep n=5 style posteriors
        base, _, _ = predictive_resolution(alpha, beta_, 0)
        more, _, _ = predictive_resolution(alpha, beta_, 15)
        self.assertAlmostEqual(base['switch'] + base['stay'] + base['unresolved'], 1.0, places=6)
        self.assertLessEqual(more['unresolved'], base['unresolved'] + 0.05)


if __name__ == '__main__':
    unittest.main()
