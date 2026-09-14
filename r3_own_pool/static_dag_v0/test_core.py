import unittest
from .core import NODES,tasks,truth,topology,prompt,parse,route

class Tests(unittest.TestCase):
 def test_topology(self):
  self.assertEqual(topology(NODES),[['demand','quotes'],['feasibility'],['decision']])
  for nodes in [[{'id':'a','deps':['b']}],[{'id':'a','deps':['b']},{'id':'b','deps':['a']}],[{'id':'a','deps':[]},{'id':'a','deps':[]}]]:
   with self.assertRaises(ValueError):topology(nodes)
 def test_fixtures(self):
  panel=tasks();self.assertEqual(len(panel),20);self.assertEqual(panel,tasks())
  for t in panel:
   expected=truth(t)
   for nid,v in expected.items():
    import json
    self.assertEqual(parse(json.dumps(v),nid),v)
  self.assertGreater(sum(truth(t)['decision']['vendor']=='NONE' for t in panel),0)
  self.assertGreater(sum(truth(t)['decision']['vendor']!='NONE' for t in panel),0)
 def test_no_truth_in_downstream(self):
  p=prompt(tasks()[0],NODES[-1],{'feasibility':{'options':[]}})
  self.assertNotIn('suppliers',p);self.assertNotIn('departments',p);self.assertIn('"options": []',p)
 def test_invalid_bool_integer(self):
  with self.assertRaises(ValueError):parse('{"units":true}','demand')
  with self.assertRaises(ValueError):parse('{"vendor":"A","total_cents":-1}','decision')
 def test_routing_tradeoff(self):
  p={'a':dict(quality=.8,mean_output_tokens=100,mean_latency_s=1,mean_total_tokens=200),'b':dict(quality=.8,mean_output_tokens=1000,mean_latency_s=10,mean_total_tokens=1100)}
  self.assertEqual(route(p,100)[0],'a')
if __name__=='__main__':unittest.main()
