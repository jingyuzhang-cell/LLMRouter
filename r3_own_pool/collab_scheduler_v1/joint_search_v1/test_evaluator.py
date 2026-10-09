import json
import tempfile
import unittest
from pathlib import Path
from .evaluator import JointEvaluator,MeteredExecutor,SearchSession,space,detected_failure
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun
from collab_scheduler_v1.fault30_protocol import Ledger
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task


class EvaluatorTests(unittest.TestCase):
    def setup_evaluator(self, answers=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        p=Path(tmp.name)
        budget=Budget(p,dict(new_request_attempts=10000,new_total_tokens=81920000,
            request_token_reservation=8192,max_output_tokens=512,wall_seconds=3600,
            logical_calls_per_task_config_state=12))
        def dispatch(model,prompt):
            answer=answers(model,prompt) if answers else '{}'
            return dict(status='delivered',answer=answer,
                usage=dict(prompt_tokens=60,completion_tokens=40,total_tokens=100))
        ex=MeteredExecutor(p,budget,dispatch,lambda model:None,
                           dict(medium='medium',large='large',coder='coder'))
        return JointEvaluator(ex,Ledger(),[make_task()])

    def test_exact_original_48_configs(self):
        original=json.loads(Path('collab_scheduler_v1/joint_search_smoke/proposal_v2/SEARCH_DESIGN.json').read_text())['configs']
        self.assertEqual(space(),original)
        self.assertEqual(len({c['id'] for c in space()}),48)

    def test_all_48_configs_execute_and_reconcile_without_models(self):
        e=self.setup_evaluator()
        for c in space():
            r=e.evaluate(c['id'],'clean',{})
            self.assertGreaterEqual(r['objectives']['C'],400)
            self.assertEqual(r['search_spend']['new_tokens'],100*r['search_spend']['new_requests'])
        self.assertEqual(len(e.completed),48)

    def test_full_is_eight_logical_calls_after_failure(self):
        e=self.setup_evaluator();c=next(c for c in space() if c['Z']=='FULL')
        r=e.evaluate(c['id'],'clean',{})
        self.assertEqual(r['tasks'][0]['logical_calls'],8)
        self.assertEqual(r['objectives']['C'],800)
        replay=[r for r in e.ex.workflow if ':replay:' in r['key']]
        self.assertEqual({r['key'].split(':')[3] for r in replay},{'e1','e2','r','v'})
        self.assertTrue(all(r['model'] != c['X'][r['key'].split(':')[3]] for r in replay))

    def test_cached_evaluation_keeps_deployment_cost(self):
        e=self.setup_evaluator();cid=space()[0]['id']
        first=e.evaluate(cid,'clean',{})
        # New session view, same already populated cache: objective must persist.
        e2=JointEvaluator(e.ex,e.led,e.tasks)
        second=e2.evaluate(cid,'clean',{})
        self.assertEqual(first['objectives'],second['objectives'])
        self.assertEqual(second['search_spend']['new_requests'],0)
        self.assertEqual(second['search_spend']['new_tokens'],0)
        self.assertEqual(second['search_spend']['new_latency_s'],0)
        self.assertEqual(second['objectives']['C'],400)

    def test_fault_has_deployment_cost_and_metered_underlying_source(self):
        e=self.setup_evaluator();cid=space()[0]['id'];uid=e.tasks[0]['uid']
        r=e.evaluate(cid,'fault30',{uid:('e1','{"facts":[]}')})
        self.assertEqual(r['objectives']['C'],400)
        self.assertEqual(r['search_spend']['new_requests'],4)
        self.assertEqual(sum(bool(x['response'].get('injected_fault')) for x in e.ex.workflow),1)
        self.assertFalse(any(x['response'].get('injected_fault') for x in e.ex.events))

    def test_detector_does_not_read_gold_or_ok(self):
        e=self.setup_evaluator();cid=space()[0]['id']
        e.evaluate(cid,'clean',{})
        class NoGold(dict):
            def __getitem__(self,k):
                if k!='keys':raise AssertionError('gold access')
                return super().__getitem__(k)
        self.assertTrue(detected_failure(NoGold(keys=list(e.ex.by_key)),e.ex,e.led))

    def test_joint_interface_budget_and_selection_boundary(self):
        e=self.setup_evaluator();session=SearchSession(e,'random',1)
        def choose(candidates,observations):
            self.assertEqual(observations,[])
            self.assertTrue(all(set(c)=={'id','X','Z'} for c in candidates))
            return candidates[0]['id']
        session.step(choose,[('clean',{})])
        with self.assertRaises(StopRun):session.step(choose,[('clean',{})])

    def test_duplicate_and_unknown_config_rejected_before_dispatch(self):
        e=self.setup_evaluator()
        with self.assertRaises(ValueError):e.evaluate('bad','clean',{})
        cid=space()[0]['id'];e.evaluate(cid,'clean',{});n=e.ex.budget.attempts
        with self.assertRaises(ValueError):e.evaluate(cid,'clean',{})
        self.assertEqual(e.ex.budget.attempts,n)


if __name__=='__main__':unittest.main()
