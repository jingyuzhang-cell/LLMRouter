"""New final-acceptance gaps; synthetic callbacks only, no transport client."""
import copy
import unittest
import hashlib
import json
from pathlib import Path

import joint_scheduler_v5 as v5
import rule_scheduler_rl as rl
from cache_lineage import Lineage,fingerprint
from v5_executor import V5RecoveryExecutor


def fixture():
    return {'ev':'SYNTHETIC_FINAL', 'children_map':{'a':['join'],'b':['join'],'join':['out']},
            'model_nodes':{'a','b','out'}, 'feedback':{'confirmed':['a']},
            'missing_outputs':['a'], 'cache_model':{'b':'cheap'},
            'pools':{'*':['cheap','fast']},
            'cost_lat':{(n,m):(10,4) if m=='cheap' else (20,1) for n in ['a','b','out','verify_b'] for m in ['cheap','fast']},
            'cash_cost':{(n,m):{'CNY':.01 if m=='cheap' else .02} for n in ['a','b','out','verify_b'] for m in ['cheap','fast']},
            'token_budget_remaining':100,'cash_budget':{'CNY':1},'deadline_remaining_s':30,
            'deterministic_latency':{'join':.1},'resource_limit':1}


def fake_call(s, seen, fail=None):
    def call(n,m,inputs):
        seen.append((n,m,copy.deepcopy(inputs)))
        value=2 if n=='a' else 3 if n=='b' else sum(inputs.values()) if n=='join' else 2*inputs['join']
        tokens,seconds=s['cost_lat'][(n,m)][:2] if m else (0,s['deterministic_latency'].get(n,0))
        return {'contract_ok':n!=fail,'output':value,'tokens':tokens,'wall_s':seconds,
                'cash_cost':s['cash_cost'][(n,m)] if m else {}}
    return call


class FinalAcceptanceTests(unittest.TestCase):
    def test_join_root_invalid_recomputes_join_not_healthy_branches(self):
        for strategy in ('V5','RL'):
            s=fixture();s['feedback']={'confirmed':['join']};s['missing_outputs']=['join']
            s['cache_model']={'a':'cheap','b':'cheap','out':'cheap'}
            seen=[];r=V5RecoveryExecutor(s,{'a':2,'b':3,'join':999,'out':1998},fake_call(s,seen),strategy).run()
            self.assertEqual([n for n,_,_ in seen],['join','out'])
            self.assertEqual(r['selected']['R'],['out']);self.assertEqual(r['outputs']['out'],10)
            self.assertIn('join',r['selected']['tools'])
    def test_join_failed_contract_blocks_terminal(self):
        s=fixture();seen=[]
        r=V5RecoveryExecutor(s,{'b':3,'join':999,'out':1998},fake_call(s,seen,fail='join')).run()
        self.assertEqual(r['status'],'CONTRACT_FAILED');self.assertNotIn('out',[n for n,_,_ in seen])
        self.assertNotIn('out',r['outputs'])
    def test_selected_assignment_is_the_executed_assignment_and_committed(self):
        s=fixture();seen=[];lin=Lineage();s['lineage']=lin
        r=V5RecoveryExecutor(s,{'b':3},fake_call(s,seen)).run()
        for n,m,_ in seen:
            if m is not None:self.assertEqual(m,r['selected']['pi'][n])
        self.assertEqual(r['outputs']['out'],10)
        self.assertEqual(lin.current('out')['inputs_fp'],fingerprint({'join':5}))
        self.assertTrue(lin.valid('out',fingerprint({'join':5})))
    def test_clean_complete_cache_is_none_no_callbacks(self):
        for strategy in ('V5','RL'):
            s=fixture();s['feedback']={};s['missing_outputs']=[]
            s['cache_model']={'a':'cheap','b':'cheap','out':'cheap'};seen=[]
            r=V5RecoveryExecutor(s,{'a':2,'b':3,'join':5,'out':10},fake_call(s,seen),strategy).run()
            self.assertEqual(r['selected']['Z'],'NONE');self.assertEqual(seen,[])
            self.assertEqual(r['outputs']['out'],10)
    def test_insufficient_budget_zero_dispatch_both(self):
        s=fixture();s['token_budget_remaining']=1
        for strategy in ('V5','RL'):
            seen=[];r=V5RecoveryExecutor(s,{'b':3},fake_call(s,seen),strategy).run()
            self.assertEqual(r['status'],'REFUSED');self.assertEqual(seen,[])
    def test_prepared_state_and_common_feedback_match_across_strategies(self):
        s=fixture();s['feedback_records']=[{'node':'b','class':'CONFIRMED-INVALID','kind':'contract_violation'}]
        for strategy in ('V5','RL'):
            seen=[];ex=V5RecoveryExecutor(s,{'b':3},fake_call(s,seen),strategy)
            chooser=v5.choose if strategy=='V5' else rl.choose
            decision,_=chooser(ex.state);r=ex.run()
            self.assertEqual({k:decision[k] for k in ('Z','R','pi')},{k:r['selected'][k] for k in ('Z','R','pi')})
    def test_legacy_is_an_explicit_separate_module(self):
        from legacy.scheduler_v4_20261022.src import joint_scheduler as old
        import joint_scheduler as current
        self.assertNotEqual(old.__file__,current.__file__)
        self.assertIn('legacy',old.__file__)
        self.assertIsNot(old.choose,current.choose)
        self.assertNotIn('from legacy',Path(current.__file__).read_text())
    def test_refused_recovery_does_not_publish_invalid_terminal(self):
        s=fixture();s['token_budget_remaining']=1
        for strategy in ('V5','RL'):
            seen=[]
            r=V5RecoveryExecutor(s,{'a':999,'b':3,'join':1002,'out':2004},fake_call(s,seen),strategy).run()
            self.assertEqual(r['status'],'REFUSED');self.assertEqual(seen,[])
            self.assertNotIn('out',r['outputs']);self.assertEqual(r['outputs']['b'],3)
    def test_14472_proxy_is_not_a_terminal_quality_objective(self):
        from task_quality import TaskQuality,measured_cells
        s={'ev':'kdx','children_map':{},'model_nodes':{'t1','t2'},
           'missing_outputs':['t2'],'feedback':{'confirmed':['t2']},
           'cache_model':{'t1':'glm53'},'pools':{'t2':['deepseek']},
           'cost_lat':{('t2','deepseek'):(10,1)},
           'task_quality':TaskQuality(*measured_cells()),
           'facts_per_call':{('t2','deepseek'):15}}
        for choose in (v5.choose,rl.choose):
            c,_=choose(s)
            self.assertAlmostEqual(c['diagnostic_q_proxy'],14.472)
            self.assertIsNone(c['terminal_q']);self.assertIsNone(c['q_task'])
            self.assertFalse(c['quality_term_used'])
    def test_join_prediction_includes_tool_latency(self):
        s=fixture();s['feedback']={'confirmed':['join']};s['missing_outputs']=['join']
        s['cache_model']={'a':'cheap','b':'cheap','out':'cheap'}
        best,_=v5.choose(s)
        self.assertAlmostEqual(best['path_s'],s['cost_lat'][('out',best['pi']['out'])][1]+.1)


if __name__=='__main__':unittest.main(verbosity=2)
