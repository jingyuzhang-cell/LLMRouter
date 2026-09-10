import unittest
import numpy as np
from router_v2.report_gap_recovery import gap_summary

class GapRecoveryTests(unittest.TestCase):
    def test_two_points_out_of_six_is_one_third(self):
        r=gap_summary(np.full(100,.02),np.full(100,.06),np.arange(100),repeats=100)
        self.assertAlmostEqual(r['gap_recovery'],1/3)
        np.testing.assert_allclose(r['gap_recovery_ci95'],[1/3,1/3])
    def test_losses_outside_opportunity_are_counted(self):
        r=gap_summary([1,-1,-1,0],[1,0,0,0],np.arange(4),repeats=100)
        self.assertEqual(r['gap_recovery'],-1.)
        self.assertEqual(r['mean_seed_wins'],1);self.assertEqual(r['mean_seed_losses'],2)
    def test_no_oracle_gap_is_undefined(self):
        r=gap_summary([0,0],[0,0],['a','b'],repeats=10)
        self.assertIsNone(r['gap_recovery']);self.assertIsNone(r['gap_recovery_ci95'])
    def test_seeds_do_not_multiply_query_groups(self):
        r=gap_summary([[1,0],[0,1]],[1,1],['a','b'],repeats=10)
        self.assertEqual(r['groups'],2);self.assertEqual(r['seed_count'],2)
        self.assertEqual(r['gap_recovery'],.5)

if __name__=='__main__':unittest.main()
