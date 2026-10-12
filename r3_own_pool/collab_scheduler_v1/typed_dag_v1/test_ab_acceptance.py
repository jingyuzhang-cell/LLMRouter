import unittest,json,tempfile
from pathlib import Path
from .fresh_acceptance import response_format,ScopedBudget
from .heterogeneous_models import prepare_metered_request
from .resource_envelope import ResourceEnvelope,STAGES,StageBound
from .goal_ir import goal_ir_schema
from .ab_acceptance import MODES

class ABWiringTests(unittest.TestCase):
    def test_both_planning_http_schema(self):
        for op in ('plan_typed_dag','repair_semantic_plan','plan_goal_ir','repair_goal_ir'):
            schema=goal_ir_schema();f=response_format(dict(operation=op,plan_json_schema=schema));self.assertEqual(f['type'],'json_schema');self.assertEqual(f['json_schema']['schema'],schema)
    def test_goal_metering_plan_repair_not_node(self):
        class Tokenizer:
            def apply_chat_template(self,*a,**kw):return list(range(50))
        with tempfile.TemporaryDirectory() as td:
            caps=dict(new_request_attempts=12,new_total_tokens=34000,request_token_reservation=8192,max_output_tokens=768,wall_seconds=12000,logical_calls_per_task_config_state=30)
            budget=ScopedBudget(Path(td),caps);budget.bind_envelope(ResourceEnvelope(phase_tokens={'generation':20000,'execution':14000}),['unit']);budget.select('unit','generation')
            pool={'medium':dict(context_limit=8192,served='m',weights_identity_sha256='stub',tokenizer_sha256={})}
            for op,kind in (('plan_goal_ir','plan'),('repair_goal_ir','repair')):
                r=prepare_metered_request('medium',json.dumps(dict(operation=op)), 'typed:generate:test',budget,{'medium':Tokenizer()},pool)
                self.assertEqual(budget.next_kind,kind);self.assertEqual(r['maxout'],768)
    def test_equal_arm_worst_envelope(self):
        stages=dict(STAGES);stages.update(plan=StageBound('generation',1,3072,768),repair=StageBound('generation',1,6144,768),review=StageBound('generation',2,4096,384))
        e=ResourceEnvelope(stages,phase_tokens={'generation':20000,'execution':14000});t=e.totals();self.assertEqual(t['tokens'],33536);self.assertEqual(t['requests'],10)
        e.admit(['a','b','c','d'],dict(new_request_attempts=48,new_total_tokens=136000,wall_seconds=12000))
    def test_two_distinct_modes(self):self.assertEqual(MODES,{'A':'semantic','B':'goal_ir'})
    def test_unknown_failed_usage_kept_independently(self):
        with tempfile.TemporaryDirectory() as td:
            caps=dict(new_request_attempts=12,new_total_tokens=34000,request_token_reservation=8192,max_output_tokens=768,wall_seconds=12000,logical_calls_per_task_config_state=30)
            budgets=[]
            for arm in ('A','B'):
                path=Path(td)/arm;path.mkdir();b=ScopedBudget(path,caps);b.bind_envelope(ResourceEnvelope(phase_tokens={'generation':20000,'execution':14000}),['unit']);b.select('unit','generation');budgets.append(b)
            a,b=budgets;a.check_request('plan',50,768);a.reserve('unknown-failure');self.assertEqual(a.charged,818);self.assertEqual(b.charged,0);self.assertTrue(a.pending);self.assertFalse(b.pending)
