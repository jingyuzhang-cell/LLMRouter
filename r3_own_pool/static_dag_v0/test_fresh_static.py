import unittest
import numpy as np
from .fresh_static_evaluate import dedup_cost,bootstrap_quality
class Tests(unittest.TestCase):
 def test_shared_extraction_cost(self):
  ns=[dict(node_id='a',task_uid='t'),dict(node_id='b',task_uid='t')]
  a=dict(call_key='ex',usage=dict(total_tokens=10),latency_s=2);b=dict(call_key='ex',usage=dict(total_tokens=20),latency_s=3)
  lookup={'medium':{'a':a,'b':a},'large':{'a':b,'b':b}}
  c,l,n=dedup_cost(ns,[0,1],np.array([0,0]),lookup,{'t':0});self.assertEqual((c[0],l[0],n[0]),(10,2,1))
  c,l,n=dedup_cost(ns,[0,1],np.array([0,1]),lookup,{'t':0});self.assertEqual((c[0],l[0],n[0]),(30,5,2))
 def test_cluster_bootstrap_matches_node_estimand(self):
  Q=np.array([[1,0,0],[1,0,0],[0,1,0]],float);p={'Node':np.array([0,0,0])};boot=np.array([[0,1],[0,0],[1,1]])
  s,b=bootstrap_quality(Q,p,np.ones(3,bool),np.array([0,0,1]),boot)
  np.testing.assert_allclose(s['Node'],[2/3,1,0]);np.testing.assert_allclose(b,[2/3,1,1])
if __name__=='__main__':unittest.main()
