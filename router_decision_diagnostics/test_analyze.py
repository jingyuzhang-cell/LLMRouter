import unittest
import numpy as np
from scipy.optimize import linprog
from analyze import envelope,aiq,iso_cost,pareto3

class FrontierTests(unittest.TestCase):
    def test_upper_boundary_against_independent_linear_program(self):
        rng=np.random.default_rng(19)
        for _ in range(10):
            pts=np.column_stack([rng.uniform(.1,3,8),rng.uniform(0,1,8)])
            hull=envelope(pts)
            for budget in np.linspace(0,4,15):
                lp=linprog(-pts[:,1],A_ub=np.vstack([pts[:,0],np.ones(8)]),b_ub=[budget,1],bounds=(0,None),method='highs')
                self.assertTrue(lp.success)
                self.assertAlmostEqual(np.interp(budget,hull[:,0],hull[:,1]),-lp.fun,places=9)
    def test_duplicates_and_dominated_points(self):
        np.testing.assert_allclose(envelope([[1,.5],[1,.8],[2,.7],[3,1]]),[[0,0],[1,.8],[3,1]])
    def test_linear_area_and_extension(self):
        self.assertAlmostEqual(aiq([[1,1]],0,2),.75)
        self.assertAlmostEqual(iso_cost([[1,1]],.5),.5)
        self.assertIsNone(iso_cost([[1,.5]],.6))
    def test_zero_cost_and_flat_quality(self):
        self.assertAlmostEqual(aiq([[0,.7],[1,.5]],0,2),.7)
        self.assertEqual(iso_cost([[0,.7]],.7),0)
        self.assertEqual(aiq([[1,0]],0,2),0)
    def test_common_domain_required(self):
        with self.assertRaises(ValueError):aiq([[1,.5]],1,1)
    def test_three_axis_tradeoff(self):
        self.assertEqual(pareto3([[.8,1,2],[.8,2,3],[.9,2,2],[.7,.5,1]]),[0,2,3])
if __name__=='__main__':unittest.main()
