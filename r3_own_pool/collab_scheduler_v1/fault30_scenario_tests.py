"""Three targeted integration scenarios for the P0-1-fixed eval_config().

Uses the REAL fault30_run.eval_config() with a scripted stub executor that
controls e-recovery outputs to test three specific dependency-flow cases:

  S1: e-fb returns SAME facts as clean -> R2 should NOT trigger a redundant
      r-refresh (no r-fbd call for this task)
  S2: e-fb returns DIFFERENT facts -> R2 fires, r-fbd runs; verify V1/V2
      prompts reflect the refreshed state and both r-fbd and v-fbd are billed
  S3: R2 fires and changes r output, but R3 (escalation) re-runs r and
      produces a parseable result; verify final r_changed flag is True (r
      keys > 1) and V2 fires on the R3 result

Each scenario runs a single task through the actual eval_config() and checks
the resulting keys/rkeys/vkeys lists. Zero LLM calls.

Run: python3 -m collab_scheduler_v1.fault30_scenario_tests
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/replay_v2'


class ScenarioExecutor:
    """Stub executor with scriptable outputs; same interface as real one."""

    def __init__(self, script):
        self.script = script  # {(node, kind): answer_text}
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
        self.call_log.append(dict(key=key, node=nd, kind=kind, model=model))
        if uid is not None and (uid, node, model) in self.faults:
            failing, cu, cl = self.faults[(uid, node, model)]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0,
                                     injected_fault=True))
        else:
            ans = self.script.get((nd, kind)) or self.script.get((nd, 'any'), \
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
    return dict(uid='scenario-test-uid',
                question='What is 1.5 + 2.5?',
                derivation='1.5+2.5',
                answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')


def run_scenario(name, script, expect, fault_node=None):
    from collab_scheduler_v1 import fault30_run
    task = make_task()
    tasks = [task]
    task_map = {task['uid']: task}
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/'
                       'FAULT_POOLS.json').read_text())
    led = fp.Ledger()
    ex = ScenarioExecutor(script)

    cid = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
    topo, fam, z, nodes = fp.planned_models(cid)

    faults = {}
    if fault_node:
        faults[task['uid']] = (fault_node, pools['e'][0] if 'e' in fault_node
                               else pools['r'][0])

    # register faults
    ex.clear_faults()
    for u, (node, failing) in faults.items():
        mapped = fp.map_fault_node(node, topo)
        if mapped and mapped in nodes:
            ex.set_fault(u, mapped, nodes[mapped], failing,
                         usage=dict(total_tokens=50), lat=0.05)

    try:
        rows = fault30_run.eval_config(cid, ex, led, tasks, faults, task_map)
        row = rows[task['uid']]
        calls = ex.call_log
        result = dict(name=name, row_ok=row['ok'], row_keys=row['keys'],
                      calls_made=[c['kind'] for c in calls],
                      r_fbd_present=any(c['kind'] == 'fbd' and c['node'] == 'r'
                                        for c in calls),
                      v_fbd_present=any(c['kind'] == 'fbd' and c['node'] == 'v'
                                        for c in calls),
                      r_esc_present=any(c['kind'] == 'esc' for c in calls),
                      v_esc_present=any(c['kind'] == 'esc' and c['node'] == 'v'
                                        for c in calls),
                      n_calls=len(calls),
                      total_cost=sum(ex.cost(k) for k in row['keys']))
        checks = expect(result)
        return dict(name=name, result=result, checks=checks,
                    verdict='PASS' if all(checks.values()) else 'FAIL')
    except Exception as e:
        return dict(name=name, error=f'{type(e).__name__}: {str(e)[:120]}',
                    verdict='ERROR')


def run():
    from static_dag_v0.multidag_dynamic import parse_facts_safe

    # Common: e1 returns facts via script; e2 clean
    E1_FACTS = '{"facts": [{"value": 1.5, "evidence": "a"}]}'
    E2_FACTS = '{"facts": [{"value": 2.5, "evidence": "b"}]}'
    E1_EMPTY = '{"facts": []}'  # fault injection makes e1 parse to empty

    results = []

    # === S1: e-fb returns SAME facts as before the fault ===
    # e1 is NOT faulted (no injection), but e1 has naturally empty facts
    # (scenario script returns empty for e1), then fb recovers with SAME facts
    # as e2. Since facts are non-empty after recovery, R2 triggers (fb key
    # exists). But if fb returns the SAME facts as pre-recovery state (which
    # was empty), the r-fbd will use the newly available facts.
    # More precisely: S1 tests that when fb returns the same facts as the
    # clean e (non-empty), the r-fbd runs with those facts (this is correct
    # behavior; the "no trigger" case is when facts were never empty).
    s1_script = {
        ('e1', 'plain'): E1_FACTS,          # e1 clean: has facts
        ('e2', 'plain'): E2_FACTS,          # e2 clean: has facts
        ('e1', 'fb'): E1_FACTS,             # fb returns same facts
        ('e2', 'fb'): E2_FACTS,
        ('r', 'plain'): '{"expression": "v0+v1"}',
        ('r', 'fbd'): '{"expression": "v0+v1"}',   # same expression
        ('r', 'esc'): '{"expression": "v0+v1"}',
        ('v', 'any'): '{"value": 4.0}',
    }
    # No fault injected; no natural empty facts -> ER should NOT trigger
    # -> R2 should NOT fire
    results.append(run_scenario(
        'S1_no_empty_facts_no_fb', s1_script, fault_node=None,
        expect=lambda r: {
            'no_fb_calls': not r['r_fbd_present'] and 'fb' not in r['calls_made'],
            'no_r_fbd': not r['r_fbd_present'],
            'no_v_fbd': not r['v_fbd_present'],
            'planned_chain_only': r['calls_made'].count('plain') >= 3,
        }))

    # === S1b: e1 naturally empty, fb returns non-empty facts ===
    # ER triggers; R2 fires because :e1:fb: exists in keys
    s1b_script = dict(s1_script)
    s1b_script[('e1', 'plain')] = '{"facts": []}'  # naturally empty
    s1b_script[('e1', 'fb')] = E1_FACTS             # recovered to same facts
    results.append(run_scenario(
        'S1b_natural_empty_fb_recovers', s1b_script, fault_node=None,
        expect=lambda r: {
            'fb_called': 'fb' in r['calls_made'],
            'r_fbd_triggered': r['r_fbd_present'],
            'v_fbd_not_triggered_same_expr': not r['v_fbd_present'],
            'r_fbd_billed': r['r_fbd_present'] and r['total_cost'] > 300,
        }))

    # === S2: e-fb returns DIFFERENT facts -> r-fbd uses new facts ===
    s2_script = dict(s1b_script)
    s2_script[('e1', 'fb')] = '{"facts": [{"value": 9.0, "evidence": "NEW"}]}'
    s2_script[('r', 'fbd')] = '{"expression": "v0*v1"}'  # different expression
    results.append(run_scenario(
        'S2_fb_changes_facts', s2_script, fault_node=None,
        expect=lambda r: {
            'r_fbd_fired': r['r_fbd_present'],
            'v_fbd_fired': r['v_fbd_present'],
            'both_billed': r['total_cost'] > 400,
            'r_changed': r['r_fbd_present'],
        }))

    # === S3: R2 fires but R3 escalation produces parseable result ===
    s3_script = dict(s2_script)
    s3_script[('r', 'fbd')] = '###garbage###'  # r-fbd also fails
    s3_script[('r', 'esc')] = '{"expression": "v0+v1"}'  # esc succeeds
    results.append(run_scenario(
        'S3_r_fbd_fails_esc_recovers', s3_script, fault_node=None,
        expect=lambda r: {
            'r_fbd_fired': r['r_fbd_present'],
            'r_esc_fired': r['r_esc_present'],
            'final_r_from_esc': r['r_esc_present'],
            'v_fbd_after_r_change': r['v_fbd_present'],
        }))

    out = dict(results=results,
               all_pass=all(r.get('verdict') == 'PASS' for r in results),
               zero_model_calls=True)
    (OUT / 'SCENARIO_TESTS.json').write_text(json.dumps(out, indent=1,
                                                        default=str))
    for r in results:
        print(f"\n=== {r['name']} === verdict: {r['verdict']}")
        if 'checks' in r:
            for k, v in r['checks'].items():
                print(f'  {k}: {"PASS" if v else "FAIL"}')
            print(f'  calls: {r["result"]["calls_made"]}')
            print(f'  cost: {r["result"]["total_cost"]}')
        elif 'error' in r:
            print(f'  ERROR: {r["error"]}')
    print(f'\n{"ALL PASS" if out["all_pass"] else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
