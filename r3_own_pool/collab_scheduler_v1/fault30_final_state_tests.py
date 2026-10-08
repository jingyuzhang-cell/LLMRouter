"""Final-state + V2 dedup + seven-layer accounting regression tests (zero calls).

Uses production eval_config() with deterministic stubs to verify:

  F1  A→B→A (R2 changes r, R3 restores original) -> r_changed_final=False,
      V2 does NOT fire
  F2  A→B→C (R2 changes r, R3 produces different) -> r_changed_final=True,
      V2 fires
  F3  A→garbage→garbage (unparseable throughout) -> r_changed_final=True
      (recovery failed; must NOT be marked as successfully restored)
  F4  Seven-layer accounting fields present and internally consistent
  F5  No-pathological-change scenario: no ER/R2/V2 at all

Run: python3 -m collab_scheduler_v1.fault30_final_state_tests
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/replay_v2'


class StubExecutor:
    def __init__(self, script):
        self.script = script
        self.by_key = {}
        self.faults = {}
        self.call_log = []
        self.proc = self.log = None
        self.current = None
        self.new_calls = 0
        self.lock = None

    def set_fault(self, uid, node, model, failing, usage=None, lat=None):
        self.faults[(uid, node, model)] = (failing, usage, lat)

    def clear_faults(self):
        self.faults = {}

    def call(self, key, model, prompt, uid=None, node=None):
        parts = key.split(':')
        nd = parts[3]
        kind = parts[4] if len(parts) > 5 else 'plain'
        self.call_log.append(dict(key=key, node=nd, kind=kind, model=model,
                                  prompt=prompt))
        if uid is not None and (uid, node, model) in self.faults:
            failing, cu, cl = self.faults[(uid, node, model)]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0,
                                     injected_fault=True))
        else:
            ans = self.script.get((nd, kind)) or \
                self.script.get((nd, 'any'),
                                '{"facts": [{"value": 1.0, "evidence": "x"}]}')
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=100),
                                     latency_s=0.1))
        self.by_key[key] = rec
        return rec

    def answer(self, key):
        return self.by_key[key]['response']['answer']

    def cost(self, key):
        return float(self.by_key[key]['response'].get('usage', {})
                     .get('total_tokens') or 0)

    def lat(self, key):
        return float(self.by_key[key]['response'].get('latency_s') or 0)

    def run_stage(self, jobs):
        for model in sorted({j['model'] for j in jobs}):
            for j in jobs:
                if j['model'] == model:
                    j['go']()

    def acquire_gpu(self):
        pass

    def release(self):
        pass


def make_task():
    return dict(uid='final-state-test-uid', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')


BASE = {
    ('e1', 'plain'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
    ('e1', 'fb'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('r', 'plain'): '{"expression": "v0+v1"}',
    ('v', 'any'): '{"value": 4.0}',
}


def run_case(name, script_overrides, expect):
    from collab_scheduler_v1 import fault30_run
    script = dict(BASE)
    script.update(script_overrides)
    task = make_task()
    tasks = [task]
    task_map = {task['uid']: task}
    led = fp.Ledger()
    ex = StubExecutor(script)
    cid = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
    faults = {}
    try:
        rows = fault30_run.eval_config(cid, ex, led, tasks, faults, task_map)
        row = rows[task['uid']]
        result = dict(
            r_changed_final=row.get('r_changed_final'),
            r_process_changed=row.get('r_process_changed'),
            v_fbd_fired=any(c['kind'] == 'fbd' and c['node'] == 'v'
                            for c in ex.call_log),
            r_fbd_fired=any(c['kind'] == 'fbd' and c['node'] == 'r'
                            for c in ex.call_log),
            r_esc_fired=any(c['kind'] == 'esc' for c in ex.call_log),
            n_logical=row.get('logical_calls'),
            n_injected=row.get('injected_calls'),
            n_real=row.get('real_calls'),
            n_cache=row.get('cache_hits'),
            real_tokens=row.get('real_tokens'),
            total_used=row.get('used'),
            ok=row.get('ok'),
            calls=[c['kind'] for c in ex.call_log])
        checks = expect(result)
        return dict(name=name, result=result, checks=checks,
                    verdict='PASS' if all(checks.values()) else 'FAIL')
    except Exception as e:
        return dict(name=name, error=f'{type(e).__name__}: {str(e)[:120]}',
                    verdict='ERROR')


def run():
    results = []

    # F1: e1 empty -> fb recovers -> R2 produces B -> R3 restores A
    # final r == original r -> r_changed_final=False, V2 should NOT fire
    results.append(run_case(
        'F1_ABA_final_unchanged',
        {('e1', 'plain'): '{"facts": []}',
         ('r', 'fbd'): '###garbage###',      # R2 produces garbage (change)
         ('r', 'esc'): '{"expression": "v0+v1"}'},  # R3 restores original
        expect=lambda r: {
            'r_changed_final_is_False': r['r_changed_final'] is False,
            'r_process_changed_is_True': r['r_process_changed'] is True,
            'v_fbd_not_fired': not r['v_fbd_fired'],
            'r_fbd_and_esc_fired': r['r_fbd_fired'] and r['r_esc_fired'],
        }))

    # F2: e1 empty -> fb changes facts -> R2 produces C (different from A)
    # -> r_changed_final=True, V2 SHOULD fire
    results.append(run_case(
        'F2_ABC_final_changed',
        {('e1', 'plain'): '{"facts": []}',
         ('e1', 'fb'): '{"facts": [{"value": 9.0, "evidence": "NEW"}]}',
         ('r', 'fbd'): '{"expression": "v0*v1"}'},
        expect=lambda r: {
            'r_changed_final_is_True': r['r_changed_final'] is True,
            'v_fbd_fired': r['v_fbd_fired'],
            'r_fbd_fired': r['r_fbd_fired'],
        }))

    # F3: r always unparseable (recovery fails) -> r_changed_final must be True
    # (must NOT be marked as successfully restored)
    results.append(run_case(
        'F3_recovery_fails',
        {('e1', 'plain'): '{"facts": []}',
         ('r', 'fbd'): '###garbage###',
         ('r', 'esc'): '###garbage###'},
        expect=lambda r: {
            'r_changed_final_True_on_failure': r['r_changed_final'] is True,
            'not_falsely_restored': r['r_changed_final'] is not False,
        }))

    # F4: seven-layer accounting consistency (use F2 which has all layers)
    results.append(run_case(
        'F4_accounting',
        {('e1', 'plain'): '{"facts": []}',
         ('e1', 'fb'): '{"facts": [{"value": 9.0, "evidence": "NEW"}]}',
         ('r', 'fbd'): '{"expression": "v0*v1"}'},
        expect=lambda r: {
            'logical_ge_real': r['n_logical'] >= r['n_real'],
            'logical_eq_real_plus_inj': r['n_logical'] ==
                                        (r['n_real'] or 0) + (r['n_injected'] or 0),
            'real_tokens_positive': (r['real_tokens'] or 0) > 0,
            'tokens_le_used': (r['real_tokens'] or 0) <= (r['total_used'] or 0),
        }))

    # F5: no e-recovery at all -> no fb/fbd/esc calls
    results.append(run_case(
        'F5_no_pathology',
        {},
        expect=lambda r: {
            'no_fb': 'fb' not in r['calls'],
            'no_fbd': 'fbd' not in r['calls'],
            'no_esc': 'esc' not in r['calls'],
            'r_changed_final_False': r['r_changed_final'] is False,
        }))

    out = dict(results=results, zero_model_calls=True,
               all_pass=all(r.get('verdict') == 'PASS' for r in results))
    (OUT / 'FINAL_STATE_TESTS.json').write_text(json.dumps(out, indent=1,
                                                           default=str))
    for r in results:
        print(f'\n=== {r["name"]} === {r["verdict"]}')
        if 'checks' in r:
            for k, v in r['checks'].items():
                print(f'  {k}: {"PASS" if v else "FAIL"}')
            print(f'  r_changed_final={r["result"]["r_changed_final"]}, '
                  f'r_process={r["result"]["r_process_changed"]}, '
                  f'v_fbd={r["result"]["v_fbd_fired"]}')
            print(f'  calls: {r["result"]["calls"]}')
        elif 'error' in r:
            print(f'  ERROR: {r["error"]}')
    print(f'\n{"ALL PASS" if out["all_pass"] else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
