"""Task-3/4 gate (v2): integrated joint executor + strategy contrast, FakeMeter only."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, '/root/capital_opinion_pilot/v5_migration_20261022/v5_regression_final')
from pilot_common import PILOT_DIR, Meter
import joint_executor as JE
import joint_scheduler as JS

TMP = PILOT_DIR / 'joint_test_tmp'
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir()
ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


class FakeMeter(Meter):
    fake = True

    def __init__(self, **kw):
        super().__init__(ledger_path=TMP / kw.pop('ledger_name', 'j.jsonl'), **kw)
        self.n = 0

    def _transport(self, alias, system, user, max_tokens, timeout_s):
        self.n += 1
        return {'usage': {'input_tokens': 600, 'output_tokens': 200}, 'text': '{"ok": true}',
                'latency_s': 1.0, 'stop_reason': 'end_turn'}


NODES = {n: f'subtask-{n}' for n in ('t1', 't2', 't3', 't4')}
ORDER = [['t1'], ['t2', 't3'], ['t4']]
DESC = {'t1': ['t2', 't3', 't4'], 't2': ['t4'], 't3': ['t4']}
STATS = {('t1', 'glm53'): (4000, 8.0, 0.75), ('t1', 'glm53flash'): (2200, 8.0, 0.55),
         ('t2', 'glm53'): (1700, 5.0, 0.65), ('t2', 'glm53flash'): (1200, 9.0, 0.70),
         ('t3', 'glm53'): (1700, 5.0, 0.75), ('t3', 'glm53flash'): (1700, 9.0, 0.60),
         ('t4', 'glm53'): (1300, 7.0, 0.80), ('t4', 'glm53flash'): (1500, 9.0, 0.55)}
PLANNED = {'t1': 'glm53', 't2': 'glm53flash', 't3': 'glm53', 't4': 'glm53'}


_RUN_SEQ = [0]
def run_strategy(strategy, fault_node, budget=30000, deadline=100.0):
    _RUN_SEQ[0] += 1
    meter = FakeMeter(max_calls=15, max_guaranteed_actual=10**9,
                      ledger_name=f"run{_RUN_SEQ[0]}_{strategy}_{fault_node}_{budget}.jsonl")

    def call_fn(node, alias):
        if node == fault_node and alias == PLANNED.get(fault_node) and fault_node is not None:
            return False, None                       # planned model unavailable on fault node
        rec, _ = meter.call(alias, 'sys', f'{node}', max_tokens=64, purpose=f'TEST:{strategy}:{node}')
        return True, {'node': node, 'by': alias}

    ex = JE.RecoveringExecutor(NODES, ORDER, DESC, meter, STATS, PLANNED, budget, deadline, call_fn)
    if strategy == 'S3_fixed_retry':
        ex._recover = lambda u: ex.call_fn(u, PLANNED.get(u, 'glm53'))[1]
    elif strategy == 'S4_fixed_reroute':
        def reroute(u):
            alt = 'glm53flash' if PLANNED.get(u, 'glm53') == 'glm53' else 'glm53'
            return ex.call_fn(u, alt)[1]
        ex._recover = reroute
    elif strategy == 'S5_fixed_local':
        def policy(u):
            pi = dict(PLANNED); pi[u] = 'glm53flash' if PLANNED.get(u) == 'glm53' else 'glm53'
            return pi
        ex._recover = JE.GuardedPolicy(ex, policy)
    r = ex.run(JE.FaultInjector('unavailable', fault_node) if fault_node else JE.FaultInjector('clean', None))
    r.update({'strategy': strategy, 'calls': meter.n, 'tokens': meter.actual_tokens,
              'provenance': 'TEST'})
    return r, ex


# T1 clean
r, _ = run_strategy('S6_joint', None)
check('T1 clean completes (4 real-shaped TEST calls)', r['complete'] and r['calls'] == 4)

# T2 joint recovery correctness
r1, ex1 = run_strategy('S6_joint', 't1')
r3, ex3 = run_strategy('S6_joint', 't3')
check('T2 joint completes both fault positions', r1['complete'] and r3['complete'],
      f"t1={r1['complete']} t3={r3['complete']}")
check('T2 R closure differs (t1->all, t3->{t3,t4})',
      r1['decisions'][-1]['action']['R'] == ['t1', 't2', 't3', 't4']
      and r3['decisions'][-1]['action']['R'] == ['t3', 't4'])
check('T2 pi masks unavailable model at fault node',
      r1['decisions'][-1]['action']['pi']['t1'] == 'glm53flash')

# T3 strategy contrast under identical fault (t2: planned flash unavailable)
res = {s: run_strategy(s, 't2')[0] for s in ('S3_fixed_retry', 'S4_fixed_reroute', 'S5_fixed_local', 'S6_joint')}
check('T3 S3 fixed-retry fails against unavailable model (expected separation)',
      res['S3_fixed_retry']['complete'] is False)
check('T3 S4/S5/S6 complete', all(res[s]['complete'] for s in ('S4_fixed_reroute', 'S5_fixed_local', 'S6_joint')))
print('   contrast (calls,tokens,complete):',
      {s: (res[s]['calls'], res[s]['tokens'], res[s]['complete']) for s in res})
check('T3 contrast measurable (call/token profiles differ)',
      len({(res[s]['tokens']) for s in res}) >= 2)

# T4 jointness across constraints
b, ab = JS.choose('t1', list(NODES), DESC, ('glm53', 'glm53flash'), STATS, 20000, 30000, 0, 100.0,
                  blocked={('t1', 'glm53')})           # remaining 10K: glm53-pi 8700? flash-pi cheaper
d, ad = JS.choose('t3', list(NODES), DESC, ('glm53', 'glm53flash'), STATS, 0, 10**9, 0, 10.0)
w, _ = JS.choose('t3', list(NODES), DESC, ('glm53', 'glm53flash'), STATS, 0, 10**9, 0, 100.0)
tight, _ = JS.choose('t1', list(NODES), DESC, ('glm53', 'glm53flash'), STATS, 28600, 30000, 0, 100.0)
check('T4 mid-budget picks LOCAL with flash at t1 (blocked glm53)', b[0] == 'LOCAL' and b[2].get('t1') == 'glm53flash')
check('T4 tiny-remaining -> NONE honest', tight[0] == 'NONE')
check('T4 tight deadline -> NONE (all generated candidates rejected)', d[0] == 'NONE' and len(ad) > 0 and all(not a['feasible'] for a in ad))
check('T4 wide -> LOCAL', w[0] == 'LOCAL')

# T5 suites green
r2 = subprocess.run(['python3', 'test_budget_guard.py'], capture_output=True, text=True, cwd='/root/capital_opinion_pilot/v5_migration_20261022/v5_regression_final')
r3b = subprocess.run(['python3', 'dry_run_tests.py'], capture_output=True, text=True, cwd='/root/capital_opinion_pilot/v5_migration_20261022/v5_regression_final')
check('T5 guard+isolation suites green', '0 failed' in r2.stdout and '0 failed' in r3b.stdout)

json.dump({'T3': {s: {'calls': res[s]['calls'], 'tokens': res[s]['tokens'],
                      'complete': res[s]['complete']} for s in res},
           'T4': {'mid_budget_Z': b[0], 'mid_budget_pi_t1': b[2].get('t1'),
                  'tiny_remaining_Z': tight[0], 'tight_deadline_Z': d[0], 'wide_Z': w[0]}},
          open(PILOT_DIR / 'joint_executor_test_results.json', 'w'), ensure_ascii=False, indent=1)
# (superseded by final gate below)

# T6 cache legality: t3-fault (transport outage, zero-token) => calls = t1,t2 + recovery{t3,t4} = 4;
# completed t1/t2 are NOT rerun (protected)
r3c, _ = run_strategy('S6_joint', 't3')
check('T6 recovery reruns closure only (cache legality)', r3c['calls'] == 4, f"calls={r3c['calls']}")
# T7 deliberate NONE is surfaced as a documented decision, distinct from silent failure
r_none, ex_none = run_strategy('S6_joint', 't1', budget=21000)   # remaining after spent ~20000? use tiny budget
r_tiny, ex_tiny = run_strategy('S6_joint', 't1', budget=5000)
check('T7 deliberate NONE recorded with rejection reasons',
      r_tiny.get('deliberate_none') is not None
      and r_tiny['deliberate_none']['none_type'] == 'no_feasible_recovery'
      and len(r_tiny['deliberate_none']['rejected']) >= 1)
check('T7 prediction errors captured for executed recovery calls',
      len(r3c.get('prediction_errors', [])) >= 1)

def res_guarded_early_refusal(result):
    return result['calls'] == 0 and any(r.get('reason') == 'budget' for r in result.get('calls_log', []))

# T8 fairness: guarded S5 under tiny budget ABSTAINS (no over-budget execution)
r5t, ex5t = run_strategy('S5_fixed_local', 't2', budget=2000)   # actual meter spend ~800 by fault time
s5_dec = [d for d in ex5t.decisions if isinstance(d, dict) and d.get('action',{}).get('Z')=='ABSTAIN']
check('T8 guarded S5 abstains instead of over-budget', (len(s5_dec)==1 and 'budget' in s5_dec[0]['why'] or
       res_guarded_early_refusal(r5t)) and r5t['tokens'] <= 2000,
      str(s5_dec[:1]))
check('T8 same-condition S6 also refuses (fair symmetry)',
      run_strategy('S6_joint','t2',budget=2000)[0]['deliberate_none'] is not None)
print(f'\nFINAL GATE: {ok} passed, {fail} failed')
import sys as _s
_s.exit(1 if fail else 0)
