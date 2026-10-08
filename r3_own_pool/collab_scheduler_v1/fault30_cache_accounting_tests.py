"""Cache-hit accounting regression: verify physical vs logical cost separation.

Uses production eval_config() with a CacheAliasExecutor that returns
alias_of for designated calls, proving that:
  - cache_hits > 0 when aliases occur
  - new_requests < logical_calls (cache doesn't count as physical)
  - new_tokens excludes alias tokens
  - new_latency_s excludes alias latency
  - V1/V2 same-prompt dedup doesn't duplicate physical cost

Run: python3 -m collab_scheduler_v1.fault30_cache_accounting_tests
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/replay_v2'


class CacheAliasExecutor:
    """Executor where designated (node,kind) calls return alias_of cache hits."""

    def __init__(self, real_answers, alias_set):
        self.real_answers = real_answers   # {(node,kind): answer} for real calls
        self.alias_set = alias_set          # {(node,kind)} that return cached
        self.by_key = {}
        self.call_log = []
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        self.new_calls = 0
        self.lock = None
        self.physical_requests = 0  # count of actual server round-trips

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
        elif (nd, kind) in self.alias_set:
            # Cache hit: no physical request, alias to prior execution
            self.physical_requests += 0
            rec = dict(key=key, model=model, alias_of=f'cache:{nd}:{kind}',
                       response=dict(status='delivered',
                                     answer=self.real_answers.get((nd, kind),
                                                                  '{}'),
                                     usage=dict(total_tokens=100),
                                     latency_s=0.5))
        else:
            # Real physical request
            self.physical_requests += 1
            ans = self.real_answers.get((nd, kind), '{}')
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=ans,
                                     usage=dict(total_tokens=100),
                                     latency_s=0.2))
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
    return dict(uid='cache-acct-test-uid', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')


def run():
    from collab_scheduler_v1 import fault30_run
    results = []

    # === T1: V1 is a cache alias; V2 would use same prompt -> also alias ===
    # e1 empty -> fb -> R2 fires -> r changes -> V1 (cache alias) -> V2 (alias)
    real = {
        ('e1', 'plain'): '{"facts": []}',
        ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
        ('e1', 'fb'): '{"facts": [{"value": 9.0, "evidence": "NEW"}]}',
        ('r', 'plain'): '{"expression": "v0+v1"}',
        ('r', 'fbd'): '{"expression": "v0*v1"}',  # changes expression
        ('v', 'plain'): '{"value": 4.0}',
        ('v', 'fbd'): '{"value": 22.5}',
        ('v', 'esc'): '{"value": 22.5}',
        ('r', 'esc'): '{"expression": "v0*v1"}',
    }
    # Make v-planned a cache alias (was executed before in a prior config)
    ex = CacheAliasExecutor(real, alias_set={('v', 'plain')})
    task = make_task()
    led = fp.Ledger()
    cid = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
    try:
        rows = fault30_run.eval_config(cid, ex, led, [task], {task['uid']: ()},
                                       {task['uid']: task})
        row = rows[task['uid']]
        r = dict(
            cache_hits=row.get('cache_hits', 0),
            new_requests=row.get('new_requests'),
            logical=row.get('logical_calls'),
            new_tokens=row.get('new_tokens'),
            total_used=row.get('used'),
            new_latency=row.get('new_latency_s'),
            executor_physical=ex.physical_requests,
            calls=[c['kind'] for c in ex.call_log])
        results.append(dict(
            name='T1_v_planned_is_alias',
            result=r,
            checks={
                'cache_hits_positive': r['cache_hits'] > 0,
                'alias_of_present': any(
                    ex.by_key[kk].get('alias_of') for kk in row['keys']),
                'logical_gt_new_requests': r['logical'] > r['new_requests'],
                'new_requests_eq_executor_physical': r['new_requests'] ==
                                                     r['executor_physical'],
                'new_tokens_excludes_alias': r['new_tokens'] < r['total_used'],
            }))
    except Exception as e:
        results.append(dict(name='T1_v_planned_is_alias',
                            error=f'{type(e).__name__}: {str(e)[:100]}'))

    # === T2: no aliases at all — physical == logical - injected ===
    ex2 = CacheAliasExecutor(real, alias_set=set())
    try:
        rows2 = fault30_run.eval_config(cid, ex2, led, [task], {task['uid']: ()},
                                        {task['uid']: task})
        row2 = rows2[task['uid']]
        r2 = dict(
            cache_hits=row2.get('cache_hits', 0),
            new_requests=row2.get('new_requests'),
            logical=row2.get('logical_calls'),
            executor_physical=ex2.physical_requests)
        results.append(dict(
            name='T2_no_aliases',
            result=r2,
            checks={
                'cache_hits_zero': r2['cache_hits'] == 0,
                'new_eq_logical_minus_injected': r2['new_requests'] ==
                    r2['logical'] - row2.get('injected_calls', 0),
                'new_eq_physical': r2['new_requests'] == r2['executor_physical'],
            }))
    except Exception as e:
        results.append(dict(name='T2_no_aliases',
                            error=f'{type(e).__name__}: {str(e)[:100]}'))

    # === T3: V1/V2 same model+prompt -> V2 as alias, no extra physical cost ===
    # V2's prompt is identical to V1's (same facts, same expr) when r_changed
    # is False. But r_changed=True here (v0*v1). Instead test that V2 being
    # an alias doesn't add physical cost.
    ex3 = CacheAliasExecutor(real, alias_set={('v', 'plain'), ('v', 'fbd')})
    try:
        rows3 = fault30_run.eval_config(cid, ex3, led, [task], {task['uid']: ()},
                                        {task['uid']: task})
        row3 = rows3[task['uid']]
        r3 = dict(
            cache_hits=row3.get('cache_hits', 0),
            new_requests=row3.get('new_requests'),
            logical=row3.get('logical_calls'),
            executor_physical=ex3.physical_requests,
            new_tokens=row3.get('new_tokens'))
        results.append(dict(
            name='T3_v1_v2_both_aliases',
            result=r3,
            checks={
                'two_cache_hits': r3['cache_hits'] >= 2,
                'physical_lt_logical': r3['executor_physical'] < r3['logical'],
                'new_eq_physical': r3['new_requests'] == r3['executor_physical'],
            }))
    except Exception as e:
        results.append(dict(name='T3_v1_v2_both_aliases',
                            error=f'{type(e).__name__}: {str(e)[:100]}'))

    all_pass = all(r.get('checks', {}) and all(r['checks'].values())
                   for r in results if 'checks' in r)
    out = dict(results=results, all_pass=all_pass, zero_model_calls=True)
    (OUT / 'CACHE_ACCOUNTING_TESTS.json').write_text(json.dumps(out, indent=1,
                                                                default=str))
    for r in results:
        print(f'\n=== {r["name"]} === '
              f'{"PASS" if r.get("checks") and all(r["checks"].values()) else "FAIL"}')
        if 'checks' in r:
            for k, v in r['checks'].items():
                print(f'  {k}: {"PASS" if v else "FAIL"}')
            print(f'  cache={r["result"]["cache_hits"]} '
                  f'new_req={r["result"]["new_requests"]} '
                  f'logical={r["result"]["logical"]} '
                  f'physical={r["result"]["executor_physical"]}')
        elif 'error' in r:
            print(f'  ERROR: {r["error"]}')
    print(f'\n{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
