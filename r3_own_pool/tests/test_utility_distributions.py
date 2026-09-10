import unittest
import numpy as np
import torch
from router_v2.utility_distributions import distribution,pair_target,expected_difference
from router_v2.expected_utility_ma import MeanVarianceMA,pair_difference


def rows(values):
 return [dict(quality=q,cost={'tokens_input':100,'tokens_output':200},latency={'total_ms':1000}) for q in values]

class UtilityTests(unittest.TestCase):
 def test_all_success_does_not_imply_zero_mean_uncertainty(self):
  r=distribution(rows([1]*5))
  self.assertEqual(r['empirical_mean'],1)
  self.assertAlmostEqual(r['posterior_mean'],6/7)
  self.assertGreater(r['posterior_mean_variance'],0)
 def test_tie_is_retained_with_uncertainty(self):
  r=distribution(rows([1,1,0,0,0]));t=pair_target(r,r)
  self.assertEqual(t['delta_quality_posterior'],0)
  self.assertGreater(t['delta_quality_mean_variance'],0)
 def test_variance_of_mean_is_not_variance_of_observations(self):
  r=distribution(rows([1,0,1,0,0]))
  self.assertAlmostEqual(r['empirical_mean_variance'],r['empirical_outcome_variance']/5)
 def test_reversing_pair_reverses_difference_but_not_variance(self):
  l=distribution(rows([0]*5));r=distribution(rows([1]*5));a=pair_target(l,r);b=pair_target(r,l)
  self.assertEqual(a['delta_quality_posterior'],-b['delta_quality_posterior'])
  self.assertEqual(a['delta_quality_mean_variance'],b['delta_quality_mean_variance'])
 def test_missing_cost_not_imputed_zero(self):
  t={'target':dict(delta_quality_posterior=.18,delta_total_ktokens=None,delta_latency_seconds=2)}
  self.assertEqual(expected_difference(t),.18)
  with self.assertRaises(ValueError):expected_difference(t,lambda_tokens=.1)
 def test_network_pair_orientation_and_positive_variance(self):
  m=MeanVarianceMA(8,42);mean,var=m(torch.zeros(3,8),torch.zeros(3,4))
  a,v=pair_difference(mean,var,3,2);b,w=pair_difference(mean,var,2,3)
  torch.testing.assert_close(a,-b);torch.testing.assert_close(v,w)
  self.assertTrue(torch.all(var>0));self.assertTrue(torch.isfinite(var).all())

if __name__=='__main__':unittest.main()
