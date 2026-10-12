import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from .ab_review_diagnostic import cell_specs,run_cell,classify_result,STATES,global_gate,request_wall_gate
from .ab_diagnostic import DiagnosticArm
from . import test_typed_dag as fixtures
from .test_producer_plan import producers
from .test_goal_ir import ir
from .test_goal_ir_roles import grouped
from .test_semantic_ids import CTX

class InterleaveTests(fixtures.ExecutionTests):
 def exercise(self,fail_first=False,small=False):
  rows=[];captures=[];dirs=[]
  class Tokenizer:
   def apply_chat_template(self,*a,**k):return [1]
  with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('HTTP forbidden')):
   for rid in ['T1_A','T1_B','T2_B','T2_A']:
    arm=rid[-1];spec=dict(run_id=rid,arm=arm,mode='semantic' if arm=='A' else 'goal_ir',role='flat' if arm=='A' else 'roles',task=dict(task_id='stub-'+rid[:2],domain='arithmetic',context=CTX,required_outputs={'answer':'number'}),required=None)
    def dispatch(m,p):
     body=json.loads(p);captures.append((rid,body))
     if body['operation']=='review_coverage':return json.dumps(dict(status='PASS',error_code='NONE',node_refs=[],evidence='Stub only',replan=False))
     if fail_first and rid=='T1_A':return '{}'
     return json.dumps(producers(3) if arm=='A' else grouped(ir(3)))
    inner=self.executor(dispatch,caps=dict(new_request_attempts=2,new_total_tokens=100 if small else 10000))
    dirs.append(inner.directory);ex=DiagnosticArm(inner,Tokenizer(),'medium',1);row={};run_cell(ex,spec,row,inner.directory);rows.append(row)
  return rows,captures,dirs
 def test_order_modes_and_isolation(self):
  rows,c,dirs=self.exercise();self.assertEqual([r['run_id'] for r in rows],['T1_A','T1_B','T2_B','T2_A']);self.assertEqual(len(set(dirs)),4)
  self.assertTrue(all(r['state']=='ACCEPTED' and r['ledger_accounting']['attempts']==2 for r in rows))
  self.assertEqual([b['operation'] for _,b in c if b['operation']!='review_coverage'],['plan_typed_dag','plan_goal_ir','plan_goal_ir','plan_typed_dag'])
  for d in dirs:self.assertTrue((d/'DISPATCH.jsonl').exists())
 def test_equal_public_no_gold(self):
  _,c,_=self.exercise();gen=[b for _,b in c if b['operation']!='review_coverage']
  self.assertEqual(gen[0]['public_task'],gen[1]['public_task']);self.assertEqual(gen[2]['public_task'],gen[3]['public_task'])
  for _,b in c:self.assertNotIn('gold',b['public_task']);self.assertNotIn('answer',b['public_task']['context'])
 def test_failure_no_retry_continue(self):
  rows,c,_=self.exercise(True);self.assertNotEqual(rows[0]['state'],'ACCEPTED');self.assertEqual(rows[0]['ledger_accounting']['attempts'],1)
  self.assertTrue(all(r['state']=='ACCEPTED' for r in rows[1:]));self.assertEqual(sum(r['ledger_accounting']['attempts'] for r in rows),7)
 def test_budget_no_dispatch(self):
  rows,c,_=self.exercise(small=True);self.assertEqual(c,[]);self.assertTrue(all(r['state']=='RESOURCE_STOP' for r in rows))
 def test_layer_classification(self):
  for code,state in [('REQUIRED_SOURCE_MISSING','SOURCE_REJECTED'),('IR_TYPE_MISMATCH','CONTRACT_REJECTED'),('SEMANTIC_REVIEW_REJECTED','REVIEW_REJECTED'),('CYCLE','STRUCTURE_REJECTED')]:
   self.assertEqual(classify_result(SimpleNamespace(status='NO_MATCHING_FALLBACK',events=[dict(status='REJECTED',code=code)])),state)
 def test_global_infrastructure_gate(self):
  from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
  with self.assertRaises(StopRun):global_gate(dict(state='INFRASTRUCTURE_ERROR',error='HTTP500'))
  global_gate(dict(state='STRUCTURE_REJECTED'))
 def test_wall_request_cleanup(self):
  from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
  p=dict(wall_seconds=664,request_timeout_s=30,cleanup_reserve_s=30)
  request_wall_gate(604,p)
  with self.assertRaises(StopRun):request_wall_gate(604.01,p)
 def test_states(self):self.assertEqual(len(STATES),9)
for name in vars(fixtures.ExecutionTests):
 if name.startswith('test_'):setattr(InterleaveTests,name,None)
