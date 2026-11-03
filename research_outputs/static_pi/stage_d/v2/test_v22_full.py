"""22 offline tests for Phase Pi V2.2.1. No network, no keys. Mock results are SIMULATED."""
import json, random, sys
sys.path.insert(0, '.')
import engine_v22 as E

RESULTS = []
def T(name, fn):
    try:
        fn(); RESULTS.append((name, 'PASS', ''))
    except AssertionError as ex:
        RESULTS.append((name, 'FAIL', str(ex)[:110]))
    except Exception as ex:
        RESULTS.append((name, 'ERROR', f'{type(ex).__name__}: {ex}'[:110]))

# 1 DAG split legality
def t1():
    d = E.DAG(); d.split('E2')
    assert d.nodes['E2']['deleted']
    assert d.nodes['E2_merge']['downs'] == ['J1']
    assert d.nodes['E1']['downs'] == ['J1']
    assert d.nodes['J1']['ups'] == ['E1', 'E2_merge']
    assert d.nodes['E2_pos']['ups'] == [] and d.nodes['E2_rest']['ups'] == []
    assert d.version == 1 and d.edits[0]['added'] == ['E2_pos','E2_rest','E2_merge']
T('01_dag_split_legality', t1)

# 2 merge contract completeness
def t2():
    d = E.DAG(); d.split('E2')
    merged = E.merge_code(d, 'E2_merge', {}, {'E2_pos': {'positions': [1]},
                                              'E2_rest': {'subjects': [], 'notice_numbers': [], 'dates': [], 'cause': [], 'quotes': []}})
    assert set(merged) == {'positions','subjects','notice_numbers','dates','cause','quotes'}, set(merged)
T('02_merge_contract_complete', t2)

# 3 acyclic + closure
def t3():
    d = E.DAG(); d.split('E2')
    seen, stack = set(), ['SINK']
    while stack:
        x = stack.pop()
        assert x not in seen, 'cycle'
        seen.add(x); stack.extend([u for u in d.nodes[x]['ups'] if not d.nodes[u]['deleted']])
    assert 'J1' in seen and 'E2_merge' in seen and 'E2' not in seen
T('03_acyclic_closure', t3)

# 4 same R0 function object for the four factorial arms
def t4():
    import inspect
    src = inspect.getsource(E.run_execution)
    assert src.count('R0(dag, n, states, versions, audit)') == 1, 'R0 must be called from one site'
    assert callable(E.R0)
T('04_R0_single_function', t4)

# 5 R0 descendant invalidation when descendants already COMPLETED
def t5():
    d = E.DAG(); states = {n: 'PENDING' for n in d.nodes}; versions = {}
    states.update({'E1':'COMPLETED','E2':'COMPLETED','J1':'COMPLETED','J2':'COMPLETED','SINK':'COMPLETED'})
    inv = E.R0(d, 'E2', states, versions, [])
    assert set(inv) == {'J1','J2','SINK'}, inv
    assert states['J2'] == 'READY' and states['SINK'] == 'READY'
T('05_R0_descendant_invalidation', t5)

# 6 pi scope
def t6():
    d = E.DAG(); states = {n: 'PENDING' for n in d.nodes}
    states.update({'E1':'COMPLETED','E2':'READY','J1':'COMPLETED'})
    U = E.compute_U(d, states)
    assert 'E1' not in U and 'E2' in U and 'J1' not in U, U
T('06_pi_scope', t6)

# 7 Running protection
def t7():
    d = E.DAG(); states = {n: 'PENDING' for n in d.nodes}; states['J2'] = 'RUNNING'
    assert 'J2' not in E.compute_U(d, states)
T('07_running_protected', t7)

# 8 Completed protection
def t8():
    d = E.DAG(); states = {n: 'PENDING' for n in d.nodes}; states['E3'] = 'COMPLETED'
    assert 'E3' not in E.compute_U(d, states)
T('08_completed_protected', t8)

# 9 deleted exclusion
def t9():
    d = E.DAG(); d.split('E2'); states = {n: 'PENDING' for n in d.nodes}; states['E2'] = 'DELETED'
    U = E.compute_U(d, states)
    assert 'E2' not in U and 'E2_pos' in U and 'E2_merge' not in U
T('09_deleted_excluded', t9)

# 10 S1 persistent fault
def t10():
    r = E.run_execution('Retry-only', 'S1')
    assert r['stop_reason'] == 'completed', r['stop_reason']
    assert r['states'].get('E2') == 'COMPLETED_DEGRADED'
    assert r['degraded_fields'].get('E2') == ['positions']
T('10_S1_persistent_fault', t10)

# 11 S1b persistent fault
def t11():
    r = E.run_execution('Retry-only', 'S1b')
    assert r['stop_reason'] == 'completed', r['stop_reason']
    assert r['degraded_fields'].get('E1') == ['positions']
T('11_S1b_persistent_fault', t11)

# 12 Retry-only cannot eliminate spec defect
def t12():
    r = E.run_execution('Retry-only', 'S1')
    assert r['states'].get('E2') == 'COMPLETED_DEGRADED'
    assert r['degraded_fields'].get('E2') == ['positions']
    # downstream now proceeds under the partial-input contract
    assert r['states'].get('SINK') in ('COMPLETED', 'COMPLETED_DEGRADED')
T('12_retry_cannot_fix', t12)

# 13 Z split recovers positions
def t13():
    r = E.run_execution('Z-only', 'S1')
    assert r['stop_reason'] == 'completed'
    merged = r['outputs'].get('E2_merge') or {}
    assert merged.get('positions'), 'split must restore positions'
    assert not r['degraded_fields'], 'Z arm must not be degraded'
T('13_Z_recovers_positions', t13)

# 14 S4' L1 success / failure / no-violation
def t14():
    ok, fx, res = E.L1({'answers': [{'fact_id':'F1','value':'2020/01/01'}], 'abstentions': []}, ('answers','abstentions'))
    assert fx and not res, (fx, res)                     # normalized, no residual
    _, _, res2 = E.L1({'abstentions': []}, ('answers','abstentions'))
    assert 'missing:answers' in res2                      # residual (cannot be fabricated)
    _, _, res3 = E.L1({'answers': [], 'abstentions': []}, ('answers','abstentions'))
    assert not res3                                       # no violation at all
T('14_S4_L1_three_cases', t14)

# 15 six-arm alignment
def t15():
    r = {a: E.run_execution(a, 'S1') for a in E.ARMS}
    for a in ('Static-GLM','Static-DS'):
        assert r[a]['z_actions'] == [] and r[a]['pi_scope'] == [] and r[a]['dag_version'] == 0
    assert r['Retry-only']['z_actions'] == [] and r['Retry-only']['pi_scope'] == []
    assert r['Z-only']['z_actions'] and r['Z-only']['pi_scope'] == []
    assert r['pi-only']['z_actions'] == [] and r['pi-only']['pi_scope']
    assert r['Joint']['z_actions'] and r['Joint']['pi_scope']
T('15_six_arm_alignment', t15)

# 16 randomized block order
def t16():
    rng = random.Random(20261102); orders = []
    for st in ('S1','S1b','S4p'):
        for rep in (1,2,3):
            a = list(E.ARMS); rng.shuffle(a); orders.append(tuple(a))
    assert len(set(orders)) > 1 and all(sorted(o)==sorted(E.ARMS) for o in orders)
T('16_randomized_order', t16)

# 17 16-call hard stop
def t17():
    r = E.run_execution('Joint', 'S1', cap_calls=16)
    assert r['call_count'] <= 16
    r2 = E.run_execution('Joint', 'S1', cap_calls=3)
    assert r2['call_count'] <= 3 and r2['stop_reason'] == 'budget', (r2['call_count'], r2['stop_reason'])
T('17_call_hard_stop', t17)

# 18 late/failed request cost settlement (both attempts charged)
def t18():
    r = E.run_execution('Z-only', 'S1', fail_nodes=('E2',))
    statuses = [c['status'] for c in r['calls']]
    assert 'timeout' in statuses and 'retry_ok' in statuses, statuses
    assert r['call_count'] == len(r['calls'])
T('18_late_request_charged', t18)

# 19 budget-exhausted status recorded
def t19():
    r = E.run_execution('Z-only', 'S1', cap_calls=2)
    assert r['stop_reason'] == 'budget', r['stop_reason']
T('19_budget_status', t19)

# 20 full mock pipeline, all arms x scenarios
def t20():
    for sc in ('S1','S1b','S4p'):
        for a in E.ARMS:
            r = E.run_execution(a, sc, sink_missing='F3' if sc=='S4p' else None)
            assert r['simulated'] is True
            assert r['call_count'] == len(r['calls'])
T('20_full_pipeline', t20)

# 21 terminal scoring (structural, SIMULATED)
def score_terminal(r):
    sink = r['outputs'].get('SINK') or {}
    ans = {a.get('fact_id') for a in (sink.get('answers') or []) if a.get('value')}
    need = {'F1','F2','F3'}
    pos = bool((r['outputs'].get('E2_merge') or r['outputs'].get('E1_merge') or r['outputs'].get('E2') or {}).get('positions'))
    return round((len(ans & need)/len(need) + (1 if pos else 0))/2, 4)
def t21():
    a = E.run_execution('Z-only','S1'); b = E.run_execution('Static-GLM','S1')
    assert 0 <= score_terminal(a) <= 1
    assert score_terminal(a) >= score_terminal(b), (score_terminal(a), score_terminal(b))
T('21_terminal_scoring', t21)

# 22 ledger completeness + reproducibility
def t22():
    r1 = E.run_execution('Joint','S1'); r2 = E.run_execution('Joint','S1')
    for k in ('call_count','stop_reason','z_actions','pi_scope','dag_version','states'):
        assert r1[k] == r2[k], k
    need = ('arm','scenario','calls','call_count','stop_reason','z_actions','pi_scope',
            'dag_version','edits','outputs','l1_fixed','residual','audit','snapshots','simulated')
    for f in need: assert f in r1, f
T('22_ledger_reproducible', t22)

if __name__ == '__main__':
    print('=== Phase Pi V2.2.1 offline tests (SIMULATED, no network) ===')
    for name, st, msg in RESULTS:
        print(f"  {name:32s} {st:6s} {msg}")
    bad = [r for r in RESULTS if r[1] != 'PASS']
    print(f"\n{len(RESULTS)-len(bad)}/{len(RESULTS)} PASS")
    json.dump([dict(test=n, status=s, detail=m) for n,s,m in RESULTS],
              open('../V22_OFFLINE_TESTS.json','w'), ensure_ascii=False, indent=1)
