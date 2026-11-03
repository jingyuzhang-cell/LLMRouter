"""Regression for the v5 minimal modules (zero-pay). GO-path gate mechanics:
lineage validity, DAG patch safety, task-quality identifiability propagation,
and the state-X action choice BEFORE vs AFTER the (pending) supplement cells.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cache_lineage import Lineage, fingerprint
from dag_patch import PatchedDAG
from task_quality import TaskQuality, measured_cells
import joint_scheduler_v5 as v5

fails = []


def check(c, m):
    print(('  ok   ' if c else '  FAIL ') + m)
    if not c:
        fails.append(m)


print('== lineage ==')
lin = Lineage()
lin.register('t1', 'glm53', 'out', fingerprint({'a': 1}), 'L0_strict', grounding=(15, 22))
check(lin.valid('t1', fingerprint({'a': 1})), 'valid when inputs unchanged')
check(not lin.valid('t1', fingerprint({'a': 2})), 'invalid when upstream changed')
lin.register('t1', 'glm53', 'out2', fingerprint({'a': 2}), None)
check(not lin.valid('t1', fingerprint({'a': 2})), 'invalid after contract failure')
check(lin.health('t1') is None, 'health reflects last (failed) version')

print('== dag_patch ==')
dag = PatchedDAG({'t1': {}, 'm': {}, 't6': {}}, {'t1': [], 'm': ['t1'], 't6': ['m']})
v = dag.add_annotation('verify_t1', 'verify.v1', 't1')
check(v == 1 and dag.version == 1, 'annotation bumps graph_version')
check(dag.dataflow_edges() == {'t1': [], 'm': ['t1'], 't6': ['m']},
      'dataflow unchanged (downstream caches stay valid)')
try:
    dag.add_annotation('t1', 'verify.v1', 't1')
    check(False, 'duplicate id rejected')
except AssertionError:
    check(True, 'duplicate id rejected')

print('== task_quality identifiability propagation ==')
g, s, obs = measured_cells()
tq = TaskQuality(g, s, obs)
# plan A (keep both caches) — fully identified with measured cells
qA, idA, _ = tq.estimate('kdx', {'keep': {'t1': 'glm53', 't2': 'glm53'}, 'reexec': {}})
check(idA and abs(qA - (15 * 0.29 + 10 * 0.29)) < 1e-9, f'plan A identified Q̂={qA:.2f}')
# plan C (reexec t1 on flash) — UNIDENTIFIED (cell missing) -> None
qC, idC, _ = tq.estimate('kdx', {'keep': {'t2': 'glm53'}, 'reexec': {'t1': 'glm53flash'},
                                 'facts_per_call': {('t1', 'glm53flash'): 22}})
check(not idC and qC is None, 'plan C unidentified (flash cell missing) -> None, no guess')
# with supplement cells filled (grounding AND KDX flash chain survival — both
# derivable from the frozen supplement's deliverable-level arms):
_Cell = type(next(iter(g.values())))
tq2 = TaskQuality({**g, ('kdx', 't1', 'glm53flash'): _Cell(0.95, 22, 'supplement')},
                  {**s, ('kdx', 'glm53flash'): _Cell(0.90, 2, 'supplement')}, obs)
qC2, idC2, _ = tq2.estimate('kdx', {'keep': {'t2': 'glm53'}, 'reexec': {'t1': 'glm53flash'},
                                    'facts_per_call': {('t1', 'glm53flash'): 22}})
check(idC2 and qC2 > qA, f'supplement cell flips C to identified and above A ({qC2:.2f} > {qA:.2f})')

print('== v5 chooser on state X (before supplement) ==')
state = {
    'ev': 'kdx',
    'allow_proxy_objective': True,  # TEST-only preservation of the original proxy objective; production disables it
    'fault_node': 't2', 'blocked': {('t1', 'deepseek')},
    'children_map': {'t1': ['m'], 't2': ['m'], 'm': ['t3', 't4'], 't3': ['t5'], 't4': ['t5'], 't5': ['t6']},
    'model_nodes': {'t1', 't2', 't3', 't4', 't5', 't6'},
    'feedback': {'confirmed': ['t2'], 'suspicious': {'t1': (15, 22)}, 'verify_targets': []},
    'pools': {'*': ['glm53', 'glm53flash', 'deepseek', 'qwen'],
              't1': ['glm53flash', 'qwen']},  # DS blocked for t1 by F7
    'cache_model': {'t1': 'glm53', 't2': 'glm53'},
    'task_quality': tq, 'facts_per_call': {('t2', 'deepseek'): 15, ('t2', 'glm53flash'): 15},
    'cost_lat': {(n, m): (5500, 10.0) for n in ('t1', 't2') for m in ('glm53', 'glm53flash', 'deepseek', 'qwen')} |
                {(n, m): (5500, 12.0) for n in ('t3', 't4', 't5', 't6') for m in ('glm53', 'glm53flash', 'deepseek', 'qwen')},
}
best, scored = v5.choose(state)
classes = sorted({a['class'] for a in scored})
check(classes == ['KEEP', 'REEXEC_EXPAND', 'REEXEC_FULL', 'REEXEC_LOCAL'],
      f'action classes generated: {classes} (VERIFY absent for extraction suspicion — dominated)')
check(best['class'] == 'REEXEC_LOCAL' and best['reexec'].get('t2') == 'deepseek',
      f"before supplement: LOCAL(t2->DS) is ALREADY identified from measured cells "
      f"and wins over KEEP (Q̂={best['q_task']}) — expansion part alone stays unidentified")
expand = [a for a in scored if a['class'] == 'REEXEC_EXPAND']
check(len(expand) > 0 and any('t1' in a['extras'] for a in expand),
      'REEXEC_EXPAND generated with detector-flagged t1 beyond closure')

print('== v5 chooser AFTER supplement cells (simulated measurement) ==')
state2 = dict(state)
state2['task_quality'] = tq2
state2['facts_per_call'] = {**state['facts_per_call'], ('t1', 'glm53flash'): 22, ('t1', 'qwen'): 22}
tq3 = TaskQuality({**g, ('kdx', 't1', 'glm53flash'): _Cell(0.95, 22, 'supplement')},
                  {**s, ('kdx', 'glm53flash'): _Cell(0.90, 2, 'supplement')}, obs)
state2['task_quality'] = tq3
best2, scored2 = v5.choose(state2)
check(best2['class'] in ('REEXEC_EXPAND', 'REEXEC_LOCAL'),
      f"identified cells flip the choice to re-execution ({best2['class']}, extras={best2.get('extras')})")

print('(core tests done — propagation tests follow)')

print('== verify.v1 outcome propagation ==')
import feedback_detector as fdl
fb = {'confirmed': [], 'suspicious': {'t1': (15, 22)}, 'verify_targets': []}
fps = {'t1': fingerprint({'ev': 'packA_v1'})}
# branch 1: all grounded -> no change
before_clean_verify = lin.snapshot()
rec = fdl.apply_verify_outcome([{'idx': 0, 'grounded': True}], 't1', fb, lin, fps)
check(not rec['state_changed'] and fb['confirmed'] == [], 'all-grounded verdict changes nothing')
check(lin.snapshot() == before_clean_verify, 'cache validity untouched by clean verdict path')
# branch 2: flagged -> semantic invalidation enters confirmed set
rec2 = fdl.apply_verify_outcome([{'idx': 0, 'grounded': True}, {'idx': 1, 'grounded': False}], 't1', fb, lin, fps)
check(rec2['state_changed'] and fb['confirmed'] == ['t1'], 'flagged verdict moves target to confirmed-invalid')
check('t1' not in fb['suspicious'], 'suspicious entry cleared on confirmation')
# branch 3: propagated SEMANTIC flag -> KEEP stays legal and (pre-supplement,
# t1 cells unidentified) wins conservatively; contract-invalid would forbid KEEP
state3 = dict(state)
state3['feedback'] = fb
state3['cache_model'] = {'t1': 'glm53', 't2': 'deepseek'}
state3['fault_node'] = 't1'
state3['missing_outputs'] = []          # semantic flag: output still usable
best3, _ = v5.choose(state3)
check(best3['class'] == 'KEEP',
      f'semantic flag pre-supplement: KEEP wins conservatively ({best3["class"]})')
state4 = dict(state3)
state4['missing_outputs'] = ['t1']      # contract-invalid: KEEP must be illegal
cands4 = v5.enumerate_actions(state4)
keep4 = [c for c in cands4 if c['class'] == 'KEEP'][0]
check(keep4['legality'] != 'ok', 'contract-invalid forbids KEEP (forced re-exec)')
best4, _ = v5.choose(state4)
check(best4['class'].startswith('REEXEC') and 't1' in best4['reexec'],
      f'contract-invalid drives forced re-execution of t1 ({best4["class"]})')
print()
print('RESULT:', 'ALL PASS' if not fails else f'{len(fails)} FAILURES')
sys.exit(1 if fails else 0)
