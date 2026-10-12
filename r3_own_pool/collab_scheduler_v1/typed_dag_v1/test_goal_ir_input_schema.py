import copy,json,unittest
from pathlib import Path
from .goal_ir import goal_ir_schema,compile_goal_ir
from .service_schema import full_validate
from .semantic_validation import SemanticErrors
from .test_goal_ir import ir,datum
class IRInputSchemaTests(unittest.TestCase):
 def test_three_five_and_reordered_inputs(self):
  for n in (3,5):
   p=ir(n)
   for s in p['steps']:s['inputs'].reverse()
   full_validate(p,goal_ir_schema());compile_goal_ir(p)
 def test_real_run03_missing_facts_rejected_by_schema(self):
  p=json.loads((Path(__file__).parent/'http_schema_diagnostic_v1/run03/execution/B/RAW_CANDIDATE.txt').read_text())
  with self.assertRaises(SemanticErrors):full_validate(p,goal_ir_schema())
 def test_reasoning_cannot_consume_value(self):
  p=ir();p['steps'][1]['inputs'][0]['type']='calculated_value'
  with self.assertRaises(SemanticErrors):full_validate(p,goal_ir_schema())
 def test_duplicate_role_still_rejected_by_compiler(self):
  p=ir();p['steps'][2]['inputs']=[datum('sum_formula','expression'),datum('sum_formula','expression')]
  full_validate(p,goal_ir_schema())
  with self.assertRaises(SemanticErrors) as e:compile_goal_ir(p)
  self.assertEqual(e.exception.feedback['error_code'],'IR_DUPLICATE_INPUT')
