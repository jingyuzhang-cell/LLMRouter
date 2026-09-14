"""E5 checks: nested stratification, label-free sampling, and frozen-fit isolation."""
import unittest
import numpy as np
import torch
from .run_e5_independent_query_learning_curve import stratified_order
from .train_repeat_pairwise_compatibility_115 import fit, inner_split


class E5Tests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(4)

    def test_nested_stratified_exact_sizes(self):
        subjects = np.repeat(np.array(['a','b','c','d']), [60,48,40,20])
        dev = np.arange(168)
        order = stratified_order(dev, subjects, 2026091400, 0)
        previous = set()
        for n in [40,80,120,168]:
            selected = order[:n]
            self.assertEqual(len(set(selected)), n)
            self.assertTrue(previous <= set(selected))
            self.assertTrue(set(selected) <= set(dev))
            for s in set(subjects):
                expected = (subjects == s).sum() / 168 * n
                self.assertLessEqual(abs((subjects[selected] == s).sum() - expected), 1.01)
            previous = set(selected)

    def test_reproducible_and_varied_subsamples(self):
        subjects = np.array(['a','b','c'] * 60)
        dev = np.arange(12,180)
        first = stratified_order(dev, subjects, 2026091400, 0)
        again = stratified_order(dev, subjects, 2026091400, 0)
        other = stratified_order(dev, subjects, 2026091401, 0)
        np.testing.assert_array_equal(first, again)
        self.assertNotEqual(set(first[:40]), set(other[:40]))
        self.assertEqual(set(first), set(other))
        self.assertTrue(set(first) <= set(dev))

    def test_inner_split_never_leaves_sample(self):
        subjects = np.array(['a','b','c','d'] * 42)
        sample = np.sort(stratified_order(np.arange(168), subjects, 2026091400, 1)[:40])
        train, val = inner_split(sample, subjects, 1)
        self.assertFalse(set(train) & set(val))
        self.assertEqual(set(train) | set(val), set(sample))

    def test_frozen_ma_does_not_consult_outer_labels(self):
        rng = np.random.default_rng(4)
        x = rng.normal(size=(12,8)).astype('float32')
        y = (rng.integers(0,6,(12,4)) / 5).astype('float32')
        train, val, dev, test = np.arange(6), np.arange(6,8), np.arange(8), np.arange(8,12)
        first, state1, detail1 = fit(x,y,train,val,dev,test,42)
        altered = y.copy(); altered[test] = 1 - altered[test]
        second, state2, detail2 = fit(x,altered,train,val,dev,test,42)
        np.testing.assert_array_equal(first,second)
        self.assertEqual(detail1,detail2)
        for name in state1:
            self.assertTrue(torch.equal(state1[name],state2[name]))


if __name__ == '__main__':
    unittest.main()
