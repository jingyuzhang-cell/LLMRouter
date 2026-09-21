"""Pre-registered Math500 six-arm analysis (zero model calls).

Readouts (frozen in CROSS_DOMAIN_MATH_PROTOCOL.json):
  six-arm table (Q/C/L), finite candidate oracle,
  RQ1 staged assignment vs both single-model baselines (paired CI + McNemar),
  RQ2 type_node_router (and static_dag) vs query_router,
  RQ3 dynamic_real vs static_dag on Q/C/L + Help/Harm + budget violations +
     intervention rate.
"""
import json
import math
import random
import time

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .cross_domain_math import OUT, close, extract_mono_value
from .cross_domain_math_run import parse_math_facts, solve_out, verify_value, cost_of

SEED = 20260918
B = 10000


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def ci(diffs, seed=SEED):
    rng = random.Random(seed)
    n = len(diffs)
    out = []
    for _ in range(B):
        out.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    out.sort()
    return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]


def contrast(rows, a, b):
    d = [r[a] - r[b] for r in rows]
    bb = sum(1 for x in d if x == 1); cc = sum(1 for x in d if x == -1)
    return dict(dQ=round(sum(d) / len(d), 4), ci=ci(d),
                mcnemar=dict(b=bb, c=cc, p_exact=round(mcnemar_exact(bb, cc), 6)))


def run():
    tasks = json.loads((OUT / 'frozen_math_tasks.json').read_text())
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    cache = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); cache[r['key']] = r
    lat = {k: r['response'].get('latency_s') or 0 for k, r in cache.items()}
    pol = json.loads((OUT / 'CROSS_DOMAIN_MATH_PROTOCOL.json').read_text())
    import re
    qr_thresh = int(re.search(r'tok_len > (\d+)', pol['arms']['query_router']).group(1))

    rows = []
    for t in tasks:
        i = t['index']; gold = t['gold']
        rec = dict(index=i)
        for arm, key in (('always_medium', f'M:m:{i}'), ('always_large', f'M:l:{i}'), ('query_router', f'M:q:{i}')):
            rec[arm] = int(close(extract_mono_value(cache[key]['response']['answer']), gold))
        # type_node: pure initial DAG (shared X/S/V keys)
        f, _ = parse_math_facts(cache[f'X:{i}']['response']['answer'])
        val, expr, err = solve_out(cache[f'S:{i}']['response']['answer'], f)
        vv = verify_value(cache[f'V:{i}']['response']['answer'])
        rec['type_node_router'] = int(close(vv, gold))
        for arm in ('static', 'dynamic'):
            st = raw[arm][str(i)]
            keys = st['keys']
            vkey = [k for k in keys if k.startswith('V')][-1]
            rec[arm + '_dag'] = int(st['ok'])
            rec[arm + '_used'] = st['used']
            rec[arm + '_lat'] = sum(lat.get(k, 0) for k in keys)
            rec[arm + '_events'] = len(st['events'])
        rec['oracle'] = int(max(rec['always_medium'], rec['always_large'], rec['query_router'],
                                rec['type_node_router'], rec['static_dag'], rec['dynamic_dag']))
        rows.append(rec)
    n = len(rows)

    def q(a):
        return round(sum(r[a] for r in rows) / n, 4)

    def c(a):
        f = a[:-4] + '_used' if a.endswith('_dag') else a + '_used'
        return round(sum(r[f] for r in rows) / n, 1)

    def L(a):
        f = a[:-4] + '_lat' if a.endswith('_dag') else a + '_lat'
        return round(sum(r[f] for r in rows) / n, 2)

    arms = ['always_medium', 'always_large', 'query_router', 'type_node_router', 'static_dag', 'dynamic_dag']
    table = {a: dict(Q=q(a)) for a in arms}
    for a in ('static_dag', 'dynamic_dag'):
        table[a].update(C=c(a), L=L(a))
    # type_node arm cost = the three shared initial calls
    table['type_node_router']['C'] = round(sum(
        cost_of(cache, f'{nd}:{r["index"]}') for r in rows for nd in ('X', 'S', 'V')) / n, 1)
    table['type_node_router']['L'] = round(sum(
        lat.get(f'{nd}:{r["index"]}', 0) for r in rows for nd in ('X', 'S', 'V')) / n, 2)
    # mono-arm costs from responses
    for arm, key in (('always_medium', 'm'), ('always_large', 'l'), ('query_router', 'q')):
        table[arm]['C'] = round(sum(cost_of(cache, f'M:{key}:{r["index"]}') for r in rows) / n, 1)
        table[arm]['L'] = round(sum(lat.get(f'M:{key}:{r["index"]}', 0) for r in rows) / n, 2)
    help_n = sum(1 for r in rows if r['static_dag'] == 0 and r['dynamic_dag'] == 1)
    harm_n = sum(1 for r in rows if r['static_dag'] == 1 and r['dynamic_dag'] == 0)
    over_budget = sum(1 for r in rows if r['dynamic_used'] > r['static_used'] * 1.2 + 1e-9)
    intervention = sum(1 for r in rows if r['dynamic_events'] > 0) / n
    rep = dict(
        generated_unix=time.time(), n=n,
        arms=table,
        finite_candidate_oracle=q('oracle'),
        RQ1=dict(
            best_staged_vs_always_medium=contrast(rows, 'type_node_router', 'always_medium'),
            best_staged_vs_always_large=contrast(rows, 'type_node_router', 'always_large'),
            static_vs_both=dict(vs_medium=contrast(rows, 'static_dag', 'always_medium'),
                                vs_large=contrast(rows, 'static_dag', 'always_large'))),
        RQ2=dict(type_node_vs_query=contrast(rows, 'type_node_router', 'query_router'),
                 static_vs_query=contrast(rows, 'static_dag', 'query_router')),
        RQ3=dict(dynreal_vs_static=contrast(rows, 'dynamic_dag', 'static_dag'),
                 dC=round((sum(r['dynamic_used'] - r['static_used'] for r in rows) / n), 1),
                 dL=round((sum(r['dynamic_lat'] - r['static_lat'] for r in rows) / n), 2),
                 help=help_n, harm=harm_n,
                 budget_violations=over_budget,
                 dynamic_intervention_rate=round(intervention, 4)),
        notes='type_node_router = pure initial assignment (no recovery); static/dynamic = + deployable-detected recovery')
    (OUT / 'MATH_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:3000])


if __name__ == '__main__':
    run()
