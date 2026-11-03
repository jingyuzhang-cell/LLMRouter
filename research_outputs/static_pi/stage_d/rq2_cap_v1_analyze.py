#!/usr/bin/env python3
"""RQ2_CAP_V1 analysis, FROZEN BEFORE DATA (zero API calls).

Implements RQ2_CAP_V1_PREREGISTRATION.md sec.4-5 criteria exactly:
  C1 node-type advantage: model beats mean(other models) by >=10pp node_Q,
     node-clustered bootstrap 95% CI > 0, stable in >=80% of cross-model
     rep pairings. (verification type: descriptive only, n=1 node.)
  C2 combination headroom: per-node best-model oracle assignment,
     fact-weighted pooled node_Q >= best single model + 5pp, CI > 0
     (bootstrap: resample nodes with replacement, resample reps within).
  C3 deployability screen: oracle assignment accounting cost <= 1.5x
     cheapest single model; latency sum reported alongside.
Answers: who excels where / stable complementarity / combination beating
best homogeneous under cost control. Verdict: proceed to static-allocation
experiment vs no usable complementarity in the pool.
"""
import json, statistics, random, collections, itertools
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / 'rq2_cap_v1_runs' / 'results.jsonl'
LED = HERE / 'rq2_cap_v1_runs' / 'ledger.jsonl'
TYPES = ('extract', 'reason', 'verification', 'report')
RNG = random.Random(20261104)
BOOT = 5000


def load():
    rows = [json.loads(l) for l in open(RES)]
    led = [json.loads(l) for l in open(LED)] if LED.exists() else []
    return rows, led


def agg_type(rows, model, kind):
    xs = [r for r in rows if r['model'] == model and r['kind'] == kind]
    if not xs:
        return None
    return dict(n_nodes=len({(r['task'], r['node']) for r in xs}), n_obs=len(xs),
                node_q=round(statistics.mean(r['node_q'] for r in xs
                                             if r['node_q'] is not None), 4),
                parse_rate=round(statistics.mean(r['parse_ok'] for r in xs), 4))


def type_table(rows):
    models = sorted({r['model'] for r in rows})
    return {t: {m: agg_type(rows, m, t) for m in models} for t in TYPES}


def node_model_q(rows):
    """(task,node) x model -> list of rep node_Q (length = reps run)."""
    d = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        d[(r['task'], r['node'], r['kind'])][r['model']].append(
            r['node_q'] if r['node_q'] is not None else 0.0)
    return d


def fact_weights(rows):
    """assigned gold facts per node (n field is constant per node)."""
    w = {}
    for r in rows:
        w[(r['task'], r['node'])] = r['n']
    return w


def pooled_fact_weighted(nodes, model, weights):
    num = den = 0.0
    for k, per in nodes.items():
        xs = per.get(model)
        if not xs:
            continue
        num += statistics.mean(xs) * weights[(k[0], k[1])]
        den += weights[(k[0], k[1])]
    return num / den if den else None


def oracle_assignment(nodes):
    assign = {}
    for k, per in nodes.items():
        assign[k] = max(per, key=lambda m: statistics.mean(per[m]))
    return assign


def c1_checks(rows, nodes):
    models = sorted({r['model'] for r in rows})
    out = {}
    for kind in TYPES:
        knodes = {k: per for k, per in nodes.items() if k[2] == kind}
        if kind == 'verification' or len(knodes) < 2:
            out[kind] = dict(status='descriptive-only (n_nodes<2)')
            continue
        res = {}
        for m in models:
            others = [o for o in models if o != m]
            # point estimate: m mean vs mean of others, node-level
            diffs, stable_pairs, total_pairs = [], 0, 0
            for k, per in knodes.items():
                if m not in per or not all(o in per for o in others):
                    continue
                mv = statistics.mean(per[m])
                ov = statistics.mean(statistics.mean(per[o]) for o in others)
                diffs.append(mv - ov)
                for rm in per[m]:
                    for o in others:
                        for ro in per[o]:
                            total_pairs += 1
                            stable_pairs += int(rm >= ro)
            if not diffs:
                continue
            point = statistics.mean(diffs) * 100
            boots = []
            keys = [k for k in knodes
                    if m in knodes[k] and all(o in knodes[k] for o in others)]
            for _ in range(BOOT):
                vals = []
                for _ in range(len(keys)):
                    k = RNG.choice(keys)
                    per = knodes[k]
                    mv = RNG.choice(per[m])
                    ov = statistics.mean(RNG.choice(per[o]) for o in others)
                    vals.append(mv - ov)
                boots.append(statistics.mean(vals) * 100)
            boots.sort()
            lo, hi = boots[int(0.025 * BOOT)], boots[int(0.975 * BOOT) - 1]
            stab = stable_pairs / total_pairs if total_pairs else 0
            res[m] = dict(
                advantage_pp=round(point, 2),
                ci95=[round(lo, 2), round(hi, 2)],
                stability=round(stab, 3),
                meets_C1=bool(point >= 10 and lo > 0 and stab >= 0.80))
        out[kind] = res
    return out


def c2_check(nodes, weights):
    models = sorted({m for per in nodes.values() for m in per})
    single = {m: pooled_fact_weighted(nodes, m, weights) for m in models}
    best_single = max(single, key=lambda m: single[m])
    assign = oracle_assignment(nodes)
    num = den = 0.0
    for k, per in nodes.items():
        m = assign[k]
        num += statistics.mean(per[m]) * weights[(k[0], k[1])]
        den += weights[(k[0], k[1])]
    oracle_q = num / den if den else None
    head = (oracle_q - single[best_single]) * 100

    def sample_pooled(model_of):
        num = den = 0.0
        keys = list(nodes)
        for _ in range(len(keys)):
            k = RNG.choice(keys)
            m = model_of(k)
            if m not in nodes[k]:
                continue
            num += RNG.choice(nodes[k][m]) * weights[(k[0], k[1])]
            den += weights[(k[0], k[1])]
        return num / den if den else 0.0

    boots = []
    for _ in range(BOOT):
        boots.append((sample_pooled(lambda k: assign[k]) -
                      sample_pooled(lambda k: best_single)) * 100)
    boots.sort()
    lo, hi = boots[int(0.025 * BOOT)], boots[int(0.975 * BOOT) - 1]
    return dict(single_model_pooled={m: round(v, 4) for m, v in single.items()},
                best_single=best_single,
                best_single_q=round(single[best_single], 4),
                oracle_assignment={f'{k[0]}|{k[1]}': m for k, m in
                                   sorted(assign.items())},
                oracle_q=round(oracle_q, 4),
                headroom_pp=round(head, 2),
                ci95=[round(lo, 2), round(hi, 2)],
                meets_C2=bool(head >= 5 and lo > 0))


def c3_check(nodes, led):
    yen = collections.defaultdict(list)
    lat = collections.defaultdict(list)
    for r in led:
        yen[r['model']].append(r['yuan'])
        lat[r['model']].append(r['lat'])
    mean_y = {m: statistics.mean(v) for m, v in yen.items()}
    mean_l = {m: statistics.mean(v) for m, v in lat.items()}
    cheapest = min(mean_y, key=mean_y.get)
    assign = oracle_assignment(nodes)
    oracle_y = sum(mean_y.get(assign[k], 0) for k in nodes)
    cheapest_y = mean_y[cheapest] * len(nodes)
    oracle_l = sum(mean_l.get(assign[k], 0) for k in nodes)
    fastest_l = min(mean_l.values()) * len(nodes)
    return dict(mean_yuan_per_call={m: round(v, 4) for m, v in mean_y.items()},
                mean_lat_s={m: round(v, 1) for m, v in mean_l.items()},
                oracle_total_yuan=round(oracle_y, 2),
                cheapest_single_total_yuan=round(cheapest_y, 2),
                ratio_vs_cheapest=round(oracle_y / cheapest_y, 2)
                if cheapest_y else None,
                oracle_total_lat_s=round(oracle_l, 1),
                fastest_single_total_lat_s=round(fastest_l, 1),
                meets_C3=bool(cheapest_y and oracle_y <= 1.5 * cheapest_y))


def delivery_rows(rows):
    out = {}
    for m in sorted({r['model'] for r in rows}):
        xs = [r for r in rows if r['model'] == m]
        out[m] = dict(parse_rate=round(statistics.mean(r['parse_ok'] for r in xs), 4),
                      mean_facts=round(statistics.mean(r['facts'] for r in xs), 1))
    return out


def main():
    rows, led = load()
    nodes = node_model_q(rows)
    weights = fact_weights(rows)
    result = dict(
        n_rows=len(rows),
        models=sorted({r['model'] for r in rows}),
        reps_per_cell={f'{k[0]}|{k[1]}|{m}': len(v)
                       for k, per in nodes.items() for m, v in per.items()},
        type_table=type_table(rows),
        delivery=delivery_rows(rows),
        C1=c1_checks(rows, nodes),
        C2=c2_check(nodes, weights),
        C3=c3_check(nodes, led),
    )
    c2 = result['C2']
    result['verdict'] = (
        'PROCEED to static-allocation experiment'
        if (c2['meets_C2'] and result['C3']['meets_C3'])
        else 'NO usable complementarity in current pool (per prereg rules)')
    json.dump(result, open(HERE / 'RQ2_CAP_V1_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in
                      ('n_rows', 'models', 'type_table', 'C1', 'C2', 'C3',
                       'verdict')}, ensure_ascii=False, indent=1)[:6000])


if __name__ == '__main__':
    main()
