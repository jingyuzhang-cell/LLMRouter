import json,tempfile,unittest
from pathlib import Path
from .http_diagnostic import call_key,build_request,decode_response,assess_plan
from .producer_plan import producer_schema
from .goal_ir import goal_ir_schema
from .test_producer_plan import producers
from .test_goal_ir import ir
from .test_semantic_ids import CTX
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget

class HTTPDiagnosticTests(unittest.TestCase):
 def executor(self,path,dispatch):
  b=Budget(path,dict(new_request_attempts=1,new_total_tokens=5000,request_token_reservation=100,max_output_tokens=768,wall_seconds=60,logical_calls_per_task_config_state=1));e=MeteredExecutor(path,b,dispatch,lambda m:None,{'medium':'stub-served'});e.begin_cell('diagnostic','unit');return e,b
 def test_original_short_key_before_reserve(self):
  with tempfile.TemporaryDirectory() as t:
   seen=[];e,b=self.executor(Path(t),lambda *a:seen.append(a))
   with self.assertRaises(IndexError):e.call('plan-only-A','medium','{}')
   self.assertEqual(b.attempts,0);self.assertEqual(b.pending,{});self.assertEqual(seen,[])
 def test_corrected_key_reserve_decode_both_modes(self):
  for mode,schema,plan in (('semantic',producer_schema({'extraction','reasoning','transformation','verification'},5),producers()),('goal_ir',goal_ir_schema(),ir())):
   with tempfile.TemporaryDirectory() as t:
    seen=[]
    def stub(model,prompt):
     payload,audit=build_request('stub-served',prompt,schema);seen.append(payload)
     return decode_response(dict(model='stub-served',choices=[dict(message=dict(content=json.dumps(plan)),finish_reason='stop')],usage=dict(prompt_tokens=5,completion_tokens=2,total_tokens=7)),'stub-served')
    e,b=self.executor(Path(t),stub);rec=e.call(call_key('generic-http-stub'),'medium','{}');r,g=assess_plan(rec['response']['answer'],rec['response']['finish_reason'],mode,schema,dict(task_id='generic-http-stub',context=CTX,required_outputs={'answer':'sum'}))
    self.assertTrue(r['legal_dag']);self.assertEqual(b.attempts,1);self.assertEqual(b.actual_tokens,7);self.assertEqual(b.pending,{});self.assertEqual(seen[0]['max_tokens'],768)
 def test_bad_key_input_rejected(self):
  for uid in ('',None,'x:y'):
   with self.assertRaises(ValueError):call_key(uid)
 def test_provider_mismatch(self):
  with self.assertRaises(ValueError):decode_response({'model':'other'},'medium')
 def test_truncated_json_classification(self):
  t=dict(task_id='stub',context=CTX,required_outputs={'answer':'sum'});r,_=assess_plan('{','length','goal_ir',goal_ir_schema(),t);self.assertEqual(r['error']['error_code'],'RESPONSE_JSON_INVALID')
  r,_=assess_plan(json.dumps(ir()),'length','goal_ir',goal_ir_schema(),t);self.assertEqual(r['error']['error_code'],'GENERATION_TRUNCATED')
 def test_unknown_dispatch_usage_retained(self):
  with tempfile.TemporaryDirectory() as t:
   def bad(*a):raise RuntimeError('mock transport failure')
   e,b=self.executor(Path(t),bad)
   with self.assertRaises(RuntimeError):e.call(call_key('generic-failure'),'medium','{}')
   self.assertEqual(b.attempts,1);self.assertEqual(b.charged,100);self.assertTrue(b.pending)
