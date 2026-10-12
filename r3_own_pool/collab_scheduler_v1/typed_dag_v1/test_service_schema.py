import copy,json,unittest,hashlib
from pathlib import Path
from .service_schema import to_service_schema,unsupported,full_validate,classify_http
from .producer_plan import producer_schema,compile_producer_plan
from .goal_ir import goal_ir_schema
from .semantic_validation import SemanticErrors
from .test_producer_plan import producers
from .fresh_acceptance import response_format

class TransportTests(unittest.TestCase):
 def test_nested_unique(self):
  s=producer_schema({'extraction','reasoning','transformation','verification'},5);before=copy.deepcopy(s);t,a=to_service_schema(s);self.assertTrue(a['differences']);self.assertFalse(unsupported(t));self.assertEqual(s,before)
 def test_other_features_refuse(self):
  for s in ({'type':'array','contains':{'type':'number'}},{'type':'string','format':'date'},{'type':'number','multipleOf':2},{'type':'object','patternProperties':{}}):
   with self.assertRaises(ValueError):to_service_schema(s)
 def test_normal_schema_no_change(self):
  s=goal_ir_schema();t,a=to_service_schema(s);self.assertEqual(s,t);self.assertEqual(a['full_sha256'],a['service_sha256'])
 def test_duplicate_remains_full_rejected(self):
  p=producers();p['nodes'][1]['input_producers']['facts']=['raw','raw'];s=producer_schema({'extraction','reasoning','transformation','verification'},5)
  with self.assertRaises(SemanticErrors):full_validate(p,s)
  with self.assertRaises(SemanticErrors):compile_producer_plan(p)
 def test_both_schema_program_validation(self):
  full_validate(producers(),producer_schema({'extraction','reasoning','transformation','verification'},5))
  from .test_goal_ir import ir
  full_validate(ir(),goal_ir_schema())
 def test_initial_and_repair_same_transport(self):
  for s,ops in ((producer_schema({'extraction','reasoning','transformation','verification'},5),('plan_typed_dag','repair_semantic_plan')),(goal_ir_schema(),('plan_goal_ir','repair_goal_ir'))):
   self.assertEqual(response_format(dict(operation=ops[0],plan_json_schema=s)),response_format(dict(operation=ops[1],plan_json_schema=s)))
 def test_http_error_classification(self):
  self.assertEqual(classify_http(400,'JSON schema contains features not supported by xgrammar'),'SERVICE_SCHEMA_UNSUPPORTED');self.assertEqual(classify_http(500,'oops'),'HTTP_SERVICE_ERROR')
 def test_full_required_not_dropped(self):
  s=producer_schema({'extraction','reasoning','transformation','verification'},5);t,_=to_service_schema(s)
  self.assertEqual(s['required'],t['required']);self.assertEqual(s['properties']['nodes']['items']['anyOf'][0]['required'],t['properties']['nodes']['items']['anyOf'][0]['required'])
 def test_old_ledger_unknown_unchanged(self):
  p=Path(__file__).parent/'stage3_ab_real_01/A/DISPATCH.jsonl';before=p.read_bytes();rows=[json.loads(l) for l in before.splitlines()];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['tokens'],2496);self.assertEqual(rows[0]['event'],'reserved');self.assertEqual(p.read_bytes(),before)
