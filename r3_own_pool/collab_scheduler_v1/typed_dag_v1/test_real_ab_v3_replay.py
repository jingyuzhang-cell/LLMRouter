"""Immutable real-response regression; never completes or repairs saved output."""
import json,unittest
from pathlib import Path
from .producer_plan import compile_producer_plan
from .goal_ir_roles import normalize_role_ir
from .goal_ir import compile_goal_ir
from .semantic_validation import SemanticErrors
ROOT=Path(__file__).parent/'planner_contract_acceptance_v3/execution'
class RealReplayTests(unittest.TestCase):
 def response(self,rid):return json.loads((ROOT/rid/'generate_HTTP_RESPONSE.json').read_text())
 def candidate(self,rid):return json.loads(self.response(rid)['choices'][0]['message']['content'])
 def test_scanner_a_type_rejected(self):
  with self.assertRaises(SemanticErrors) as e:compile_producer_plan(self.candidate('T1_A'))
  self.assertIn('PRODUCER_TYPE_MISMATCH',str(e.exception))
 def test_scanner_b_truncated_not_completed(self):
  d=self.response('T1_B');self.assertEqual(d['choices'][0]['finish_reason'],'length')
  self.assertEqual(d['usage']['completion_tokens'],768)
  with self.assertRaises(json.JSONDecodeError):json.loads(d['choices'][0]['message']['content'])
 def test_greenhouse_b_final_symbol_rejected(self):
  p,_=normalize_role_ir(self.candidate('T2_B'),5)
  with self.assertRaises(SemanticErrors) as e:compile_goal_ir(p)
  self.assertIn('IR_GOAL_UNCOVERED',str(e.exception))
 def test_greenhouse_a_reference_rejected(self):
  p=self.candidate('T2_A');refs={x['ref'] for x in p['nodes']}
  self.assertNotIn('n5',refs)
  with self.assertRaises(SemanticErrors):compile_producer_plan(p)
