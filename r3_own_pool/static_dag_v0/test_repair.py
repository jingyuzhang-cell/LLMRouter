import copy
import json
import unittest
from . import core,repair

class Tests(unittest.TestCase):
 def test_fresh_and_reproducible(self):
  new=repair.panel();self.assertEqual(new,repair.panel());self.assertEqual(len(new),20)
  old=json.loads((core.OUT/'TASKS.json').read_text())
  self.assertFalse({json.dumps(t['input'],sort_keys=True) for t in new}&{json.dumps(t['input'],sort_keys=True) for t in old})
 def test_local_contract_uses_actual_predecessors(self):
  t=repair.panel()[0];pred=core.truth(t);pred['demand']={'units':1}
  expected=repair.local_expected(t,core.NODES[2],pred)
  self.assertNotEqual(expected,core.truth(t)['feasibility'])
  audit=repair.inspect_output(t,core.NODES[2],pred,{'status':'delivered','answer':json.dumps(expected)})
  self.assertTrue(audit['passed'])
 def test_no_label_access(self):
  t=repair.panel()[0];copy_t=copy.deepcopy(t);copy_t['ground_truth']='POISON';copy_t['expected']={'vendor':'POISON'}
  self.assertEqual(repair.local_expected(t,core.NODES[0],{}),repair.local_expected(copy_t,core.NODES[0],{}))
 def test_detect_wrong_arithmetic_without_values_in_feedback(self):
  t=repair.panel()[0];audit=repair.inspect_output(t,core.NODES[0],{}, {'status':'delivered','answer':'{"units": 999}'})
  self.assertEqual(audit['error_fields'],['units']);self.assertFalse(audit['passed'])
  self.assertEqual(set(audit),{'parsed','passed','error_fields','validation_seconds'})
 def test_invalid_json_and_infrastructure(self):
  t=repair.panel()[0]
  a=repair.inspect_output(t,core.NODES[0],{}, {'status':'delivered','answer':'{"units": 1+2}'})
  self.assertIsNone(a['parsed']);self.assertFalse(a['passed'])
  a=repair.inspect_output(t,core.NODES[0],{}, {'status':'infrastructure_failure','answer':None})
  self.assertEqual(a['error_fields'],['infrastructure_failure'])
 def test_boundary_and_tie(self):
  t=repair.panel()[1];pred=core.truth(t);a=next(x for x in pred['feasibility']['options'] if x['vendor']=='A');self.assertTrue(a['eligible'])
  actual={'feasibility':{'options':[{'vendor':'B','eligible':True,'total_cents':50},{'vendor':'A','eligible':True,'total_cents':50},{'vendor':'C','eligible':False,'total_cents':1}]}}
  self.assertEqual(repair.local_expected(t,core.NODES[-1],actual),{'vendor':'A','total_cents':50})
if __name__=='__main__':unittest.main()
