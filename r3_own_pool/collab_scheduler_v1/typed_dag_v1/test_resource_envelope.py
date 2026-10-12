import json,tempfile,unittest
from pathlib import Path
from .resource_envelope import ResourceEnvelope,StageBound,STAGES
from .fresh_acceptance import ScopedBudget,CAPS
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

APPROX_CAPS={**CAPS,'new_total_tokens':56000}
class EnvelopeTests(unittest.TestCase):
 def budget(self,caps=None,tasks=('a','b')):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
  b=ScopedBudget(Path(d.name),caps or APPROX_CAPS);b.bind_envelope(ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}),list(tasks));b.select(tasks[0],'generation');return b
 def send(self,b,kind,ninput=100,output=None):
  out=STAGES[kind].output_tokens if output is None else output
  b.check_request(kind,ninput,out);i=b.reserve(kind)
  return i,out
 def settle(self,b,i,out,ninput=100):b.settle(i,dict(status='delivered',usage=dict(prompt_tokens=ninput,completion_tokens=out,total_tokens=ninput+out)))
 def test_totals(self):
  t=ResourceEnvelope().totals();self.assertEqual(t,dict(requests=10,tokens=27392,phase_tokens={'generation':13568,'execution':13824}))
 def test_old_envelope_rejects_before_requests(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d))
   with self.assertRaises(StopRun):b.bind_envelope(ResourceEnvelope(),['a','b'])
   self.assertEqual(b.attempts,0);self.assertFalse((Path(d)/'DISPATCH.jsonl').exists())
 def test_input_growth_never_truncated(self):
  b=self.budget();b.release_unused('generation');b.select('a','execution')
  with self.assertRaisesRegex(StopRun,'Input length'):b.check_request('node',2049,256)
  self.assertEqual(b.attempts,0)
 def test_output_cap(self):
  b=self.budget()
  with self.assertRaisesRegex(StopRun,'Output cap'):b.check_request('plan',100,769)
 def test_unknown_failure_keeps_all_reservation(self):
  b=self.budget();i,out=self.send(b,'plan')
  with self.assertRaises(StopRun):b.settle(i,dict(status='delivered',usage={}))
  self.assertEqual(b.pending[i],100+out);self.assertEqual(b.charged,100+out)
 def test_repair_resource_insufficient(self):
  b=self.budget();b.buckets[('a','generation')]=12000;b.charged=12000
  with self.assertRaisesRegex(StopRun,'phase_future_tokens'):b.check_request('repair',100,768)
 def test_multinode_and_recovery_slots(self):
  b=self.budget();b.release_unused('generation');b.select('a','execution')
  for _ in range(5):
   i,out=self.send(b,'node',2048);self.settle(b,i,out,2048)
  with self.assertRaisesRegex(StopRun,'Stage request cap'):b.check_request('node',1,256)
  i,out=self.send(b,'recovery',2048);self.settle(b,i,out,2048)
  with self.assertRaisesRegex(StopRun,'Stage request cap'):b.check_request('recovery',1,256)
  self.assertEqual(b.charged,13824)
 def test_request_exhaustion_first(self):
  b=self.budget();b.attempts=23
  with self.assertRaisesRegex(StopRun,'global_future_requests'):b.check_request('plan',1,768)
 def test_tokens_exhaustion_first(self):
  b=self.budget();b.charged=56000
  with self.assertRaisesRegex(StopRun,'global_future_tokens'):b.check_request('plan',1,768)
 def test_remaining_wall_refuses(self):
  b=self.budget();b.clock=lambda:b.start+600
  with self.assertRaisesRegex(StopRun,'future_wall_slots'):b.check_request('plan',1,768)
 def test_exact_boundary_accepted(self):
  caps={**CAPS,'new_total_tokens':27392,'new_request_attempts':10}
  b=self.budget(caps,('a',))
  for k in ('plan','review','repair','review'):
   inp=STAGES[k].input_tokens;i,out=self.send(b,k,inp);self.settle(b,i,out,inp)
  b.release_unused('generation');b.select('a','execution')
  for k in ['node']*5+['recovery']:
   inp=STAGES[k].input_tokens;i,out=self.send(b,k,inp);self.settle(b,i,out,inp)
  self.assertEqual(b.attempts,10);self.assertEqual(b.charged,27392);self.assertEqual(b.pending,{})
 def test_unbounded_input_rejected(self):
  bad=dict(STAGES);bad['node']=StageBound('execution',5,None,256)
  with self.assertRaises(ValueError):ResourceEnvelope(bad)
 def test_missing_hidden_stage_rejected(self):
  bad=dict(STAGES);del bad['recovery']
  with self.assertRaises(ValueError):ResourceEnvelope(bad)
 def test_phase_mismatch(self):
  b=self.budget()
  with self.assertRaisesRegex(StopRun,'Stage/task'):b.check_request('node',100,256)
 def test_closed_phase_cannot_call(self):
  b=self.budget();b.release_unused('generation')
  with self.assertRaisesRegex(StopRun,'Stage request cap'):b.check_request('plan',100,768)
 def test_global_future_other_task_protected(self):
  b=self.budget();b.caps['new_total_tokens']=30000
  with self.assertRaisesRegex(StopRun,'global_future_tokens'):b.check_request('plan',2048,768)
 def test_growth_caught_at_reserve_too(self):
  b=self.budget();b.check_request('plan',100,768);b.next_reservation=2049+768
  with self.assertRaisesRegex(StopRun,'Input length'):b.reserve('tampered')
 def test_stage_input_boundary(self):
  b=self.budget();self.assertEqual(b.check_request('plan',2048,768),2816)
 def test_nominal_wall_budget_admission(self):
  with self.assertRaises(StopRun):ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}).admit(['a','b'],{**APPROX_CAPS,'wall_seconds':900})

class EnvelopePipelineTests(unittest.TestCase):
 def test_generator_to_execution_metered_stub(self):
  from .test_producer_plan import producers
  from .test_semantic_ids import CTX
  from .generation import InitialDAGGenerator
  from .execution import TypedExecutor
  from .protocol import Limits
  from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
  with tempfile.TemporaryDirectory() as d:
   directory=Path(d);budget=ScopedBudget(directory,APPROX_CAPS);budget.bind_envelope(ResourceEnvelope(phase_tokens={'generation':14000,'execution':14000}),['stub-only']);budget.select('stub-only','generation')
   def body(prompt):
    try:return json.loads(prompt)
    except ValueError:return json.loads(prompt.split('\n',1)[1])
   def dispatch(model,prompt):
    x=body(prompt);op=x.get('operation')
    if op=='plan_typed_dag':answer=json.dumps(producers(5))
    elif op=='review_coverage':answer=json.dumps(dict(status='PASS',error_code='NONE',node_refs=[],evidence='Stub coverage only.',replan=False))
    elif x['contract']=='facts.v1':answer=json.dumps(dict(facts=[dict(value=int(x['inputs']['context']),evidence=x['inputs']['context'])]))
    elif x['contract']=='expression.v1':answer=json.dumps(dict(expression='+'.join(x['available_fact_variables'])))
    else:answer=json.dumps(dict(value=x['inputs']['value']))
    return dict(status='delivered',answer=answer,usage=dict(prompt_tokens=100,completion_tokens=10,total_tokens=110),finish_reason='stop')
   class StubBounded(MeteredExecutor):
    def call(self,key,model,prompt,uid=None,node=None):
     x=body(prompt);op=x.get('operation');kind={'plan_typed_dag':'plan','repair_semantic_plan':'repair','review_coverage':'review'}.get(op,'node')
     budget.check_request(kind,100,STAGES[kind].output_tokens)
     return super().call(key,model,prompt,uid,node)
   ex=StubBounded(directory,budget,dispatch,lambda m:None,{'medium':'stub-only'})
   g=InitialDAGGenerator(ex,'medium',limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5)).generate('stub-only','financial_arithmetic',CTX,{'answer':'sum'})
   self.assertEqual(g.status,'GENERATED');budget.release_unused('generation');budget.select('stub-only','execution')
   r=TypedExecutor(g.graph,{n.node_id:'medium' for n in g.graph.nodes},ex,CTX).run()
   self.assertEqual(r['status'],'COMPLETE');self.assertEqual(r['final_outputs']['answer'],5)
   self.assertEqual(budget.attempts,6);self.assertEqual(budget.actual_tokens,660)
   self.assertTrue((directory/'ENVELOPE_PREFLIGHT.jsonl').exists());self.assertEqual(len([x for x in (directory/'DISPATCH.jsonl').read_text().splitlines() if json.loads(x)['event']=='reserved']),6)
 def test_replay_read_only(self):
  from .replay_resource_envelope import audit
  for folder,tokens in [('stage3_fresh_acceptance_real_01',5455),('stage3_producer_fresh_real_01',7652)]:
   r=audit(Path(__file__).parent/folder)
   self.assertTrue(r['source_unchanged']);self.assertEqual(r['known_tokens'],tokens);self.assertEqual(r['attempts'],4);self.assertTrue(all(x['reservation_correct'] for x in r['rows']))
 def test_known_service_failure_settles_phase_before_stop(self):
  with tempfile.TemporaryDirectory() as d:
   b=ScopedBudget(Path(d));b.select('a','generation');b.next_reservation=100;i=b.reserve('x')
   with self.assertRaises(StopRun):b.settle(i,dict(status='failed',usage=dict(prompt_tokens=20,completion_tokens=10,total_tokens=30)))
   self.assertEqual(b.charged,30);self.assertEqual(b.buckets[('a','generation')],30);self.assertEqual(b.pending,{})
 def test_absolute_request_timeout(self):
  import time,signal
  from .resource_envelope import request_deadline
  old=signal.getsignal(signal.SIGALRM)
  with self.assertRaisesRegex(StopRun,'Request wall timeout'):
   with request_deadline(.01):time.sleep(.1)
  self.assertEqual(signal.getsignal(signal.SIGALRM),old);self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
 def test_outer_deadline_restored_without_extending(self):
  import signal,time
  from .resource_envelope import request_deadline
  old=signal.getsignal(signal.SIGALRM)
  try:
   signal.setitimer(signal.ITIMER_REAL,10)
   with request_deadline(1):pass
   self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],9);self.assertLessEqual(signal.getitimer(signal.ITIMER_REAL)[0],10)
   self.assertEqual(signal.getsignal(signal.SIGALRM),old)
  finally:signal.setitimer(signal.ITIMER_REAL,0)
