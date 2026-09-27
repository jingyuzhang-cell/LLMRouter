"""P0-2 analyzer: six cells {A,B,C'} x {V0,V1}, state strata, paired stats.

Zero model calls. Cells:
  A(V0) exec stored expr on modified facts            (0 calls)
  A(V1) exec post-repair expr on modified facts       (repair cost separate)
  B      exec regenerated expr on modified facts      (1 call)
  C'     exec C'-reasoning on C'-extracted facts      (2 calls, mutated source)
Strata by round-1 stored correctness; P(harm|correct,a), P(recover|wrong,a),
dC_a, dL_a; McNemar exact for Q, paired bootstrap for C/L.
"""
import json
import math
from pathlib import Path

import numpy as np

from .decompose_v1 import exec_calc
from .graph_forest_v2_diagnostic import eval_expr, gold_expression
from .multidag_dynamic import parse_facts_safe
from .tool_aware_v1 import decode

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p02'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def mcnemar_exact(x, y):
    """Paired binary vectors; returns (b, c, p_two_sided)."""
    b = int(sum(1 for i, j in zip(x, y) if i and not j))
    c = int(sum(1 for i, j in zip(x, y) if j and not i))
    n = b + c
    if n == 0:
        return b, c, 1.0
    p = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n * 2
    return b, c, min(1.0, p)


def paired_bootstrap(d, n=10000, seed=0):
    rng = np.random.default_rng(seed)
    d = np.asarray(d, float)
    idx = rng.integers(0, len(d), (n, len(d)))
    means = d[idx].mean(1)
    return dict(mean_diff=float(d.mean()), ci95=[float(np.percentile(means, 2.5)),
                                                 float(np.percentile(means, 97.5))],
                median_diff=float(np.median(d)))


def run():
    dry = json.loads((OUT / 'DRYRUN.json').read_text())
    rows = sorted([r for r in dry['fresh_rows'] if r['ok']], key=lambda r: r['uid'])
    nodes = json.loads((SRC / 'NODES.json').read_text())
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    tmap = {t['uid']: t for t in tasks}
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    resp = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        rec = json.loads(l)
        resp[rec['key']] = rec['response']
    keys = json.loads((OUT / 'RAW_KEYS.json').read_text())

    def tok(k):
        return float(resp[k].get('usage', {}).get('total_tokens', 0)) if k in resp else 0.0

    def lat(k):
        return float(resp[k].get('latency_s', 0)) if k in resp else 0.0

    per = []
    for r in rows:
        uid = r['uid']
        node = rs[uid]
        gold = tmap[uid]['answer']
        gexpr = gold_expression(node)
        facts_m = json.loads(json.dumps(node['gold_facts']))
        facts_m['facts'][0]['value'] = r['facts0'] * 1.10
        target = float(eval_expr(gexpr, facts_m)) if gexpr else None

        def arm_value(expr, facts):
            try:
                return exec_calc(expr, facts)
            except Exception:
                return None

        # arm A V0
        a0 = arm_value(r['expr'], facts_m)
        # arm A V1: post-repair expression
        v1_expr = r['expr']
        rep_tok = rep_lat = 0.0
        if f'p02:repair:{uid}' in keys['keys']['repairs']:
            try:
                cand = decode(resp[f'p02:repair:{uid}']['answer'])['expression']
                exec_calc(cand, node['gold_facts'])
                v1_expr = cand
            except Exception:
                pass
            rep_tok, rep_lat = tok(f'p02:repair:{uid}'), lat(f'p02:repair:{uid}')
        a1 = arm_value(v1_expr, facts_m)
        # arm B
        try:
            b_expr = decode(resp[f'p02:B:{uid}']['answer'])['expression']
            b_val = arm_value(b_expr, facts_m)
        except Exception:
            b_expr, b_val = None, None
        # arm C'
        cfacts, _ = parse_facts_safe(resp[f'p02:C_e:{uid}']['answer'])
        try:
            c_expr = decode(resp[f'p02:C_r:{uid}']['answer'])['expression']
            c_val = arm_value(c_expr, cfacts)
        except Exception:
            c_expr, c_val = None, None
        prop = any(close(f['value'], r['facts0'] * 1.10) for f in cfacts['facts'])
        per.append(dict(uid=uid, round1_correct=r['round1_correct'],
                        target=target,
                        A0=a0, A1=a1, B=b_val, Cp=c_val,
                        cp_propagated=prop,
                        cB_tok=tok(f'p02:B:{uid}'), cB_lat=lat(f'p02:B:{uid}'),
                        cC_tok=tok(f'p02:C_e:{uid}') + tok(f'p02:C_r:{uid}'),
                        cC_lat=lat(f'p02:C_e:{uid}') + lat(f'p02:C_r:{uid}'),
                        v1_repair_tok=rep_tok, v1_repair_lat=rep_lat))

    def okv(x):
        return bool(close(x, per[0]['target'])) if False else None

    T = [p['target'] for p in per]
    ok = lambda p, k: int(close(p[k], p['target']))

    def cell(k):
        return dict(Q=float(np.mean([ok(p, k) for p in per])),
                    C=float(np.mean([p['cB_tok'] if k == 'B' else
                                     p['cC_tok'] if k == 'Cp' else
                                     (p['v1_repair_tok'] if k == 'A1' else 0.0) for p in per])),
                    L=float(np.mean([p['cB_lat'] if k == 'B' else
                                     p['cC_lat'] if k == 'Cp' else
                                     (p['v1_repair_lat'] if k == 'A1' else 0.0) for p in per])))

    cells = {k: cell(k) for k in ('A0', 'A1', 'B', 'Cp')}
    cells['A1']['C_amortized_N1'] = cells['A1']['C']  # write-validation amortized at N=1
    # strata
    strata = {}
    for name, sel in [('stored_correct', lambda p: p['round1_correct']),
                      ('stored_wrong', lambda p: not p['round1_correct'])]:
        sub = [p for p in per if sel(p)]
        strata[name] = dict(n=len(sub),
                            Q={k: float(np.mean([ok(p, k) for p in sub]))
                               for k in ('A0', 'A1', 'B', 'Cp')},
                            P_harm_given_correct={k: float(np.mean(
                                [not ok(p, k) for p in sub if p['round1_correct']])) if name == 'stored_correct' else None
                                for k in ('A0', 'A1', 'B', 'Cp')},
                            P_recover_given_wrong={k: float(np.mean(
                                [ok(p, k) for p in sub if not p['round1_correct']])) if name == 'stored_wrong' else None
                                for k in ('A0', 'A1', 'B', 'Cp')})
    # paired stats
    stats = {}
    for x, y in [('A0', 'B'), ('A0', 'Cp'), ('B', 'Cp'), ('A0', 'A1')]:
        b, c, p = mcnemar_exact([ok(pp, x) for pp in per], [ok(pp, y) for pp in per])
        stats[f'Q_{x}-{y}'] = dict(dQ=cells[x]['Q'] - cells[y]['Q'], mcnemar_b=b,
                                   mcnemar_c=c, p_exact=p)
    for cost in ['cB_tok', 'cC_tok', 'cB_lat', 'cC_lat']:
        stats[f'boot_{cost}'] = paired_bootstrap([p[cost] for p in per])
    out = dict(n=len(per), cells=cells, strata=strata, paired_stats=stats,
               cp_source_mutation_propagation=float(np.mean([p['cp_propagated'] for p in per])),
               per_task=per)
    (OUT / 'RESULTS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(cells={k: {m: round(vv, 4) for m, vv in c.items()}
                                 for k, c in cells.items()},
                          propagation=out['cp_source_mutation_propagation'],
                          strata={s: dict(n=d['n'], Q=d['Q']) for s, d in strata.items()},
                          paired={k: (round(v['dQ'], 4), round(v['p_exact'], 4))
                                  for k, v in stats.items() if k.startswith('Q_')}), indent=1))


if __name__ == '__main__':
    run()
