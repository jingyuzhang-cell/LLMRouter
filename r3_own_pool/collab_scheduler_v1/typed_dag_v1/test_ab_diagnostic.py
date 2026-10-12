import json,tempfile,unittest
from pathlib import Path
from .ab_diagnostic import DiagnosticArm,request_packet,CONTEXT_LIMIT
from .test_goal_ir import ir
from .goal_ir import goal_ir_schema
from .http_diagnostic import call_key,decode_response
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun
class Tokenizer:
 def apply_chat_template(self,*a,**kw):return list(range(self.n))
 def __init__(self,n):self.n=n
class DiagnosticTests(unittest.TestCase):
 def arm(self,t,n=10,total=8970,dispatch=None):
  b=Budget(Path(t),dict(new_request_attempts=2,new_total_tokens=total,request_token_reservation=0,max_output_tokens=768,wall_seconds=600,logical_calls_per_task_config_state=2))
  def stub(m,p):return decode_response(dict(model='stub',choices=[dict(message=dict(content=json.dumps(ir())),finish_reason='stop')],usage=dict(prompt_tokens=n,completion_tokens=1,total_tokens=n+1)),'stub')
  e=MeteredExecutor(Path(t),b,dispatch or stub,lambda m:None,{'medium':'stub'});e.begin_cell('diag','task')
  return DiagnosticArm(e,Tokenizer(n),'stub',n)
 def prompt(self):return json.dumps(dict(operation='plan_goal_ir',plan_json_schema=goal_ir_schema()))
 def test_future_review_reserved_and_actual_settled(self):
  with tempfile.TemporaryDirectory() as t:
   e=self.arm(t);e.call(call_key('x'),'medium',self.prompt());self.assertEqual(e.budget.actual_tokens,11);self.assertEqual(e.requests[0]['review_future_reserve'],8192)
 def test_insufficient_future_tokens_before_request(self):
  with tempfile.TemporaryDirectory() as t:
   e=self.arm(t,total=8969)
   with self.assertRaises(StopRun):e.call(call_key('x'),'medium',self.prompt())
   self.assertEqual(e.budget.attempts,0)
 def test_context_overflow_before_request(self):
  with tempfile.TemporaryDirectory() as t:
   e=self.arm(t,n=7425,total=20000)
   with self.assertRaises(StopRun):e.call(call_key('x'),'medium',self.prompt())
   self.assertEqual(e.budget.attempts,0)
 def test_unknown_failure_full_reserve(self):
  with tempfile.TemporaryDirectory() as t:
   def fail(*a):raise RuntimeError('stub HTTP failure')
   e=self.arm(t,dispatch=fail)
   with self.assertRaises(RuntimeError):e.call(call_key('x'),'medium',self.prompt())
   self.assertEqual(e.budget.charged,778);self.assertTrue(e.budget.pending)
 def test_no_repair_no_extra_phase(self):
  with self.assertRaises(StopRun):request_packet('stub',json.dumps(dict(operation='repair_goal_ir')))
 def test_review_output_boundary(self):
  phase,p,a=request_packet('stub',json.dumps(dict(operation='review_coverage',review_json_schema={'type':'object'})))
  self.assertEqual(phase,'semantic_review');self.assertEqual(p['max_tokens'],256)

from .test_semantic_ids import LoopTests as Fixture,CTX
from .test_producer_plan import producers
from .test_goal_ir_roles import grouped
from .generation import InitialDAGGenerator
class DiagnosticLoopTests(Fixture):
 def dispatch_diag(self,m,p):
  d=json.loads(p)
  if d['operation'] in ('plan_typed_dag','plan_goal_ir'):return json.dumps(next(self.candidates))
  return self.dispatch(m,p)
 def test_both_modes_two_phases_original_generator(self):
  for mode,role,plan in [('semantic','flat',producers(5)),('goal_ir','roles',grouped(ir(5)))]:
   self.candidates=iter([plan]);inner=self.executor(self.dispatch_diag,caps={'new_total_tokens':8970,'new_request_attempts':2});e=DiagnosticArm(inner,Tokenizer(10),'stub',10)
   r=InitialDAGGenerator(e,'medium',planning_mode=mode,goal_input_mode=role,max_repairs=0,fallbacks={}).generate('bounded-diag-'+mode,'financial_arithmetic',CTX,{'answer':'sum'})
   self.assertEqual(r.status,'GENERATED');self.assertEqual(e.counts,{'generate':1,'semantic_review':1});self.assertEqual(inner.budget.attempts,2)
 def test_source_failure_skips_review_both_modes(self):
  for mode,role,plan in [('semantic','flat',producers()),('goal_ir','roles',grouped(ir()))]:
   self.candidates=iter([plan]);inner=self.executor(self.dispatch_diag,caps={'new_total_tokens':8970,'new_request_attempts':2});e=DiagnosticArm(inner,Tokenizer(10),'stub',10)
   r=InitialDAGGenerator(e,'medium',planning_mode=mode,goal_input_mode=role,max_repairs=0,fallbacks={}).generate('bounded-reject-'+mode,'financial_arithmetic',CTX,{'answer':'sum'},required_source_data=[dict(data_id='needed',source_id='ctx_text',evidence=CTX['ctx_text'])])
   self.assertIsNone(r.graph);self.assertEqual(e.counts,{'generate':1,'semantic_review':0});self.assertEqual(inner.budget.attempts,1)
for name in dir(Fixture):
 if name.startswith('test_') and name not in DiagnosticLoopTests.__dict__:setattr(DiagnosticLoopTests,name,None)
del Fixture
