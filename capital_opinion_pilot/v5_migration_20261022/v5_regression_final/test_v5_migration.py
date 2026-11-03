"""Zero-API synthetic mechanism tests; no performance-benefit claims."""
import copy
import unittest
from cache_lineage import Lineage, fingerprint
from task_quality import TaskQuality, Cell, measured_cells
from dag_patch import PatchedDAG
import feedback_detector as fd
import joint_scheduler_v5 as v5
import rule_scheduler_rl as rl
from v5_executor import V5RecoveryExecutor


class TerminalFixture:
    """Deterministic TEST reference, not calibrated real-model data."""
    quality_scope = 'terminal_calibrated'
    required_nodes = ('a', 'b')
    def estimate(self, ev, plan):
        keep, redo = plan['keep'], plan['reexec']
        if set(plan['invalid_cache']) & set(keep):
            return None, False, {'fixture': 'invalid cache'}
        q = .6 if 'b' in keep else .9
        if redo.get('a') == 'fast':
            q += .05
        return q, True, {'source': 'SYNTHETIC_TEST_ONLY', 'complete_plan': plan}


def state():
    return {'ev': 'TEST', 'children_map': {'a': ['join'], 'b': ['join'], 'join': ['out']},
            'model_nodes': {'a', 'b', 'out'},
            'feedback': {'confirmed': ['a'], 'suspicious': {'b': (1, 3)}},
            'missing_outputs': ['a'], 'cache_model': {'b': 'cheap'},
            'pools': {'*': ['cheap', 'fast']},
            'cost_lat': {(n, m): ((10, 4) if m == 'cheap' else (20, 1))
                         for n in ['a', 'b', 'out', 'verify_b'] for m in ['cheap', 'fast']},
            'quality_evaluator': TerminalFixture(), 'token_budget_remaining': 100,
            'deadline_remaining_s': 20, 'resource_limit': 1}


class V5MigrationTests(unittest.TestCase):
    def test_closure_crosses_deterministic_join(self):
        s=state(); self.assertEqual(v5.invalidation_closure('a',s['children_map'],s['model_nodes']), {'a','out'})
    def test_multiple_roots_union(self):
        s=state(); s['missing_outputs']=['a','b']; s['feedback']['confirmed']=['a','b']
        self.assertTrue(all(set(c['R'])=={'a','b','out'} for c in v5.enumerate_actions(s) if c['Z']=='LOCAL'))
    def test_supported_extra_and_full(self):
        s=state(); cs=v5.enumerate_actions(s)
        self.assertTrue(any(c['Z']=='LOCAL' and c['R']==['a','out'] for c in cs))
        self.assertTrue(any(c['Z']=='EXPAND' and c['R']==['a','b','out'] for c in cs))
        self.assertTrue(any(c['Z']=='FULL' and c['legality']=='ok' for c in cs))
    def test_unsupported_full_rejected(self):
        s=state(); s['feedback']['suspicious']={}
        _,audit=v5.choose(s)
        self.assertTrue(all(not c['feasible'] for c in audit if c['Z']=='FULL'))
    def test_cache_health_changes_scope(self):
        s=state(); best,_=v5.choose(s); self.assertIn('b',best['R'])
        s['feedback']['suspicious']={}; best,_=v5.choose(s); self.assertNotIn('b',best['R'])
    def test_fingerprint_requires_repair(self):
        s=state(); s['feedback']={'confirmed':[]}; s['missing_outputs']=[]
        lin=Lineage(); lin.register('b','cheap',{},'old','strict')
        s.update(lineage=lin,current_fps={'b':'new'})
        best,_=v5.choose(s); self.assertIn('b',best['R'])
        self.assertNotEqual(best['Z'],'NONE')
    def test_unavailable_and_contract_mask(self):
        s=state(); s['availability']={'fast':False}; best,_=v5.choose(s)
        self.assertEqual(set(best['pi'].values()),{'cheap'})
        s['contract_compatible']={(n,'cheap'):False for n in s['model_nodes']}
        self.assertIsNone(v5.choose(s)[0])
    def test_budget_changes_assignment_or_refuses(self):
        s=state(); s['feedback']['suspicious']={}; s['token_budget_remaining']=20
        best,_=v5.choose(s); self.assertEqual(set(best['pi'].values()),{'cheap'})
        s['token_budget_remaining']=19; self.assertIsNone(v5.choose(s)[0])
    def test_deadline_changes_assignment(self):
        s=state(); s['feedback']['suspicious']={}; s['deadline_remaining_s']=2
        best,_=v5.choose(s); self.assertEqual(set(best['pi'].values()),{'fast'})
        s['deadline_remaining_s']=1; self.assertIsNone(v5.choose(s)[0])
    def test_cash_currencies_not_added(self):
        s=state(); s['cash_budget']={'CNY':.5,'USD':.1}
        s['cash_cost']={(n,m):{'CNY':1} if m=='fast' else {'USD':.02} for n,m in s['cost_lat']}
        best,_=v5.choose(s); self.assertEqual(set(best['pi'].values()),{'cheap'})
        del s['cash_cost']; self.assertIsNone(v5.choose(s)[0])
    def test_unknown_quality_not_zero(self):
        s=state(); del s['quality_evaluator']; best,cs=v5.choose(s)
        self.assertIsNone(best['q_task']); self.assertFalse(best['q_identified'])
        self.assertTrue(all(c['q_task'] is None for c in cs))
        s['terminal_q_min']=.5; self.assertIsNone(v5.choose(s)[0])
    def test_missing_cost_not_zero(self):
        s=state(); s['cost_lat']={}; self.assertIsNone(v5.choose(s)[0])
    def test_verify_requires_conflict(self):
        s=state(); self.assertFalse(any(c['Z']=='VERIFY' for c in v5.enumerate_actions(s)))
        s['feedback']={'verify_targets':['b'], 'verify_conflicts':{'b':{'evidence_ref':'TEST:conflict1'}}}; s['missing_outputs']=[]
        cs=v5.enumerate_actions(s); self.assertTrue(any(c['Z']=='VERIFY' and c['annotations']==['b'] for c in cs))
        s['missing_outputs']=['a']; self.assertTrue(all(not c['feasible'] for c in v5.score_actions(v5.enumerate_actions(s),s) if c['Z']=='VERIFY'))
    def test_clean_verify_does_not_invalidate(self):
        lin=Lineage(); lin.register('b','cheap','value','same','strict')
        fb={'confirmed':[],'suspicious':{'b':(1,1)}}; before=copy.deepcopy(lin.snapshot())
        result=fd.apply_verify_outcome([{'grounded':True}], 'b',fb,lin,{'b':'same'})
        self.assertFalse(result['state_changed']); self.assertEqual(before,lin.snapshot()); self.assertTrue(lin.valid('b','same'))
    def test_malformed_verify_unknown(self):
        lin=Lineage(); fb={'confirmed':[],'suspicious':{}}
        r=fd.apply_verify_outcome([{}],'a',fb,lin,{})
        self.assertEqual(r['status'],'UNKNOWN');self.assertFalse(r['state_changed'])
    def test_quality_formula_and_provenance(self):
        g,s,obs=measured_cells(); tq=TaskQuality(g,s,obs)
        q,ok,p=tq.estimate('kdx',{'keep':{'t1':'glm53'},'reexec':{'t2':'deepseek'},'facts_per_call':{('t2','deepseek'):15}})
        self.assertTrue(ok); self.assertAlmostEqual(p['t2']['contribution'],10.122)
        self.assertAlmostEqual(p['t1']['contribution'],4.35); self.assertAlmostEqual(q,14.472)
        self.assertIsNone(p['_summary']['terminal_accuracy'])
    def test_omitted_quality_node_unknown(self):
        tq=TaskQuality(*measured_cells()); q,ok,p=tq.estimate('kdx',{'keep':{'t1':'glm53'}})
        self.assertFalse(ok); self.assertIsNone(q)
    def test_cycle_rejected(self):
        s=state(); s['children_map']['out']=['a']
        with self.assertRaises(ValueError):v5.choose(s)
        with self.assertRaises(ValueError):PatchedDAG({'a':{},'b':{}},{'a':['b'],'b':['a']})
    def test_deterministic(self):
        self.assertEqual(v5.choose(state()),v5.choose(state()))
        self.assertEqual(rl.choose(state()),rl.choose(state()))
    def test_pareto_and_rejections_recorded(self):
        s=state(); best,cs=v5.choose(s)
        self.assertTrue(best['pareto']);self.assertTrue(any(c['rejection_reasons'] for c in cs))
        self.assertTrue(all('actual_execution' in c for c in cs))
    def test_healthy_or_unproven_cache_not_expandable(self):
        s=state();s['feedback']['suspicious']={'b':(3,3)}
        self.assertFalse(any(c['Z']=='EXPAND' for c in v5.enumerate_actions(s)))
        s['feedback']['suspicious']={'b':None}
        self.assertFalse(any(c['Z']=='EXPAND' for c in v5.enumerate_actions(s)))
    def test_verify_without_evidence_ref_rejected(self):
        s=state();s['missing_outputs']=[];s['feedback']={'verify_targets':['b']}
        cs=v5.score_actions(v5.enumerate_actions(s),s)
        self.assertTrue(all(not c['feasible'] for c in cs if c['Z']=='VERIFY'))
    def test_feedback_adapter_same_for_rl(self):
        s=state();s['feedback_records']=[{'node':'b','class':'CONFIRMED-INVALID','kind':'contract_violation'}]
        self.assertIn('b',v5.choose(s)[0]['R']);self.assertIn('b',rl.choose(s)[0]['R'])
    def test_task_proxy_cannot_satisfy_terminal_constraint(self):
        s=state();s.pop('quality_evaluator');s.update(task_quality=TaskQuality(*measured_cells()),terminal_q_min=.5)
        best,cs=v5.choose(s);self.assertIsNone(best)
        self.assertTrue(all('terminal_quality_unidentified' in c['rejection_reasons'] for c in cs))
    def test_pending_work_reserved(self):
        s=state(); s['pending_assignment']={'b':'cheap'};s['feedback']['suspicious']={};s['token_budget_remaining']=29
        self.assertIsNone(v5.choose(s)[0])
    def test_executor_respects_join_and_reuse(self):
        s=state();s['feedback']['suspicious']={};seen=[]
        def call(n,m,inputs):
            seen.append(n)
            return {'contract_ok':True,'output':n,'tokens':0 if m is None else 1,'wall_s':.01,'cash_cost':{}}
        r=V5RecoveryExecutor(s,{'b':'cached','join':'stale','out':'stale'},call).run()
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(seen,['a','join','out']);self.assertEqual(r['outputs']['b'],'cached')
        self.assertTrue(r['selected']['actual_execution'])
    def test_executor_failure_blocks_downstream(self):
        s=state();s['feedback']['suspicious']={};seen=[]
        def call(n,m,inputs):
            seen.append(n); return {'contract_ok':False}
        r=V5RecoveryExecutor(s,{'b':'cached','out':'stale'},call).run()
        self.assertEqual(r['status'],'CONTRACT_FAILED');self.assertEqual(seen,['a']);self.assertNotIn('out',r['outputs'])
    def test_rl_same_hard_constraints(self):
        s=state(); s['token_budget_remaining']=1
        self.assertIsNone(v5.choose(s)[0]);self.assertIsNone(rl.choose(s)[0])
    def test_verify_execution_preserves_healthy_cache(self):
        s=state();s['missing_outputs']=[]
        s['feedback']={'verify_targets':['b'],'verify_conflicts':{'b':{'evidence_ref':'TEST:e1'}}}
        s['verification_required']=['b'];before={'b':'cached'}
        def call(n,m,inputs):
            return {'contract_ok':True,'output':{'grounded':True},'tokens':1,'wall_s':.1,'cash_cost':{}}
        r=V5RecoveryExecutor(s,before,call).run()
        self.assertEqual(r['status'],'VERIFIED_ANNOTATION');self.assertEqual(r['outputs'],before)
        self.assertEqual(r['selected']['Z'],'VERIFY');self.assertEqual(r['actual_tokens'],1)
    def test_actual_overrun_stops_without_commit(self):
        s=state();s['feedback']['suspicious']={};seen=[]
        def call(n,m,inputs):
            seen.append(n);return {'contract_ok':True,'output':'bad-to-commit','tokens':101,'wall_s':.1,'cash_cost':{}}
        r=V5RecoveryExecutor(s,{'b':'cached'},call).run()
        self.assertEqual(r['status'],'POST_SETTLEMENT_OVERRUN');self.assertEqual(seen,['a']);self.assertNotIn('a',r['outputs'])
    def test_critical_path_not_layer_max(self):
        from scheduler_common import estimates
        s={'children_map':{'a':['b'],'x':['y']},'model_nodes':{'a','b','x','y'},'cost_lat':{('a','m'):(1,10),('b','m'):(1,1),('x','m'):(1,1),('y','m'):(1,10)}}
        self.assertEqual(estimates(set(s['model_nodes']),dict.fromkeys(s['model_nodes'],'m'),s)[1],11)


if __name__=='__main__': unittest.main(verbosity=2)
