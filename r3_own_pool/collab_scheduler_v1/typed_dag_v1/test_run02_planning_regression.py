"""Saved-response replay; counterfactual edits are diagnostics, never real success."""
import copy,json,unittest
from pathlib import Path
from .goal_ir import compile_goal_ir
from .semantic_validation import SemanticErrors
from .http_diagnostic import assess_plan
from .producer_plan import producer_schema
from .protocol import Limits
ROOT=Path(__file__).parent/'http_schema_diagnostic_v1/run02'
class Run02PlanningRegression(unittest.TestCase):
 def test_original_duplicate_output_rejected_without_mutation(self):
  p=json.loads((ROOT/'execution/B/RAW_CANDIDATE.txt').read_text());before=copy.deepcopy(p)
  with self.assertRaises(SemanticErrors) as e:compile_goal_ir(p)
  self.assertEqual(e.exception.feedback['error_code'],'IR_AMBIGUOUS_PRODUCER');self.assertEqual(p,before)
 def test_counterfactual_unique_symbol_exposes_missing_expression(self):
  p=json.loads((ROOT/'execution/B/RAW_CANDIDATE.txt').read_text())
  p['steps'][-1]['outputs'][0]['symbol']='diagnostic_verified_output'
  with self.assertRaises(SemanticErrors) as e:compile_goal_ir(p)
  self.assertEqual(e.exception.feedback['error_code'],'IR_OPERATION_INPUTS')
 def test_a_structure_does_not_certify_source_coverage(self):
  text=(ROOT/'execution/A/RAW_CANDIDATE.txt').read_text();task=json.loads((ROOT/'PUBLIC_INPUT.json').read_text())
  r,g=assess_plan(text,'stop','semantic',producer_schema({'extraction','reasoning','transformation','verification'},5),task)
  self.assertTrue(r['legal_dag']);self.assertFalse(g.provenance['semantic_guarantee'])
  fields={i.field for n in g.nodes for i in n.inputs if i.source=='task'}
  self.assertNotIn('ctx_table',fields)
