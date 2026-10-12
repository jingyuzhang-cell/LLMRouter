import unittest
from .planner_catalogue import catalogue,BINDINGS,GOAL_FIRST
from .protocol import CONTRACTS,digest
class CatalogueTests(unittest.TestCase):
 def test_contracts(self):
  for row in catalogue()['operations']:
   c=CONTRACTS[row['contract_id']]
   self.assertEqual(row['output_ports'],c[2]);self.assertEqual(row['node_type'],c[0])
   self.assertEqual(set(row['required_roles'])|set(row['task_inputs']),set(c[1]))
 def test_subset(self):
  self.assertEqual([x['operation'] for x in catalogue({'facts.v1':CONTRACTS['facts.v1']})['operations']],['extract'])
 def test_hash(self):
  c=catalogue();h=c.pop('sha256');self.assertEqual(h,digest(c))
 def test_calculate(self):
  c=next(x for x in catalogue()['operations'] if x['operation']=='calculate')
  self.assertEqual(set(c['required_roles']),{'facts','expression'})
  self.assertEqual(c['execution'],'deterministic_expression_evaluation')
 def test_no_template(self):
  self.assertIn('variable node counts',GOAL_FIRST);self.assertFalse(catalogue()['semantic_guarantee'])
