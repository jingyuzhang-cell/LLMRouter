#!/usr/bin/env python3
"""RQ2_P2R_V3 analysis, FROZEN BEFORE DATA (zero API calls).

Implements the statistical plan of RQ2_P2R_V3_PREREGISTRATION_V1_1.md
sections 3-4 exactly: per-task interaction effects (mandatory), task-clustered
bootstrap CI (exploratory), sign-flip exact p (floor 0.125 at n=4), gate-rate
comparisons, Q/C/L deltas, node-level base-vs-reroll pairing, model_resp drift
audit. Base cells reuse frozen V2 records (read-only).

Written and validated on mock data BEFORE any real V3 execution, so the
analysis cannot flex to the observed outcome.
"""
import json, statistics, itertools, random, math, collections
from pathlib import Path
import rq2_p2r_v2_analyze as M  # frozen scorer (V1.5 Gold, adopted-output gate)

HERE = Path(__file__).parent
V2DIR = HERE / 'rq2_p2r_v2_runs'      # HomBase = V2 B, HetBase = V2 C
V3DIR = HERE / 'rq2_p2r_v3_runs'      # HomImp / HetImp
TASKS = M.TASKS
CELL_OF = {('v2', 'B'): 'HomBase', ('v2', 'C'): 'HetBase',
           ('v3', 'HomImp'): 'HomImp', ('v3', 'HetImp'): 'HetImp'}


def load_cells():
    cells = collections.defaultdict(dict)  # cell -> (task,rep) -> record
    for p in sorted(V2DIR.glob('B__*.json')):
        d = json.load(open(p))
        cells['HomBase'][(d['task'], d['rep'])] = d
    for p in sorted(V2DIR.glob('C__*.json')):
        d = json.load(open(p))
        cells['HetBase'][(d['task'], d['rep'])] = d
    for cell in ('HomImp', 'HetImp'):
        for p in sorted(V3DIR.glob(f'{cell}__*.json')):
            d = json.load(open(p))
            cells[cell][(d['task'], d['rep'])] = d
    return cells


def cell_summary(cells, cell, arm=None):
    by_task = collections.defaultdict(dict)
    for (task, rep), rec in cells[cell].items():
        s = M.score(rec)
        by_task[task][rep] = s
    out = {}
    for task, reps in by_task.items():
        qs = [r['q_main'] for r in reps.values()]
        qr = [r['q_main_raw'] for r in reps.values()]
        qf = [r['q_full'] for r in reps.values()
              if r['q_full'] is not None]
        gates = [r['report_ok'] for r in reps.values()]
        out[task] = dict(n_reps=len(reps),
                         q_main=round(statistics.mean(qs), 4),
                         q_raw=round(statistics.mean(qr), 4),
                         q_full=(round(statistics.mean(qf), 4)
                                 if qf else None),
                         gate_rate=round(statistics.mean(gates), 4))
    pooled = dict(
        mean_task_q_main=round(statistics.mean(
            v['q_main'] for v in out.values()), 4) if out else None,
        mean_task_q_raw=round(statistics.mean(
            v['q_raw'] for v in out.values()), 4) if out else None,
        mean_task_gate=round(statistics.mean(
            v['gate_rate'] for v in out.values()), 4) if out else None,
        n_execs=sum(v['n_reps'] for v in out.values()))
    return dict(by_task=out, pooled=pooled)


def delivery_delta(cells, imp, base):
    per_task = {}
    for task in TASKS:
        ri = [M.score(rec)['q_main'] for (t, r), rec in cells[imp].items()
              if t == task]
        rb = [M.score(rec)['q_main'] for (t, r), rec in cells[base].items()
              if t == task]
        if ri and rb:
            per_task[task] = round(statistics.mean(ri) -
                                   statistics.mean(rb), 4)
    return per_task


def interaction(cells):
    het = delivery_delta(cells, 'HetImp', 'HetBase')
    hom = delivery_delta(cells, 'HomImp', 'HomBase')
    per_task = {t: round((het.get(t) - hom.get(t)) * 100, 2)
                for t in TASKS if t in het and t in hom}
    ds = list(per_task.values())
    if not ds:
        return dict(per_task={}, n_tasks=0)
    obs = statistics.mean(ds)
    cnt = tot = 0
    for signs in itertools.product([1, -1], repeat=len(ds)):
        tot += 1
        if abs(statistics.mean([d * s for d, s in zip(ds, signs)])) \
                >= abs(obs) - 1e-12:
            cnt += 1
    rng = random.Random(20261103)
    boots = []
    cell_reps = {}
    for cell in ('HetImp', 'HetBase', 'HomImp', 'HomBase'):
        for task in TASKS:
            xs = [M.score(rec)['q_main'] for (t, r), rec in
                  cells[cell].items() if t == task]
            if xs:
                cell_reps[(cell, task)] = xs
    for _ in range(5000):
        vals = []
        for _ in range(len(ds)):
            t = rng.choice([t for t in per_task])
            def cm(cell):
                xs = cell_reps[(cell, t)]
                return statistics.mean(rng.choices(xs, k=len(xs)))
            vals.append(((cm('HetImp') - cm('HetBase')) -
                         (cm('HomImp') - cm('HomBase'))) * 100)
        boots.append(statistics.mean(vals))
    boots.sort()
    return dict(per_task=per_task, n_tasks=len(ds),
                mean_pp=round(obs, 2),
                sd_pp=round(statistics.stdev(ds), 2) if len(ds) > 1 else None,
                se_pp=round(statistics.stdev(ds) / len(ds) ** 0.5, 2)
                if len(ds) > 1 else None,
                signflip_p=round(cnt / tot, 4),
                signflip_floor_note='n=4 => two-sided min p = 0.125; '
                                    'exploratory only',
                cluster_bootstrap_ci95_exploratory=[
                    round(boots[int(0.025 * len(boots))], 2),
                    round(boots[int(0.975 * len(boots)) - 1], 2)])


def gate_comparison(cells):
    def gates(cell):
        return [M.score(rec)['report_ok']
                for rec in cells[cell].values()]
    out = {}
    for cell in ('HomBase', 'HetBase', 'HomImp', 'HetImp'):
        g = gates(cell)
        out[cell] = dict(passed=sum(g), n=len(g),
                         rate=round(statistics.mean(g), 4) if g else None)
    return out


def costs(cells):
    led_v2 = M.load_ledger(V2DIR)
    led_v3 = M.load_ledger(V3DIR)
    ex = {}
    # ledger rows carry arm B/C; map (batch, arm) -> cell name
    for (a, t, r), v in M.exec_costs(led_v2).items():
        ex[(f"v2:{a}", t, r)] = v
    for (a, t, r), v in M.exec_costs(led_v3).items():
        ex[(f"v3:{a}", t, r)] = v
    mapping = {('v2', 'B'): 'HomBase', ('v2', 'C'): 'HetBase',
               ('v3', 'B'): 'HomImp', ('v3', 'C'): 'HetImp'}
    out = {}
    for cell in ('HomBase', 'HetBase', 'HomImp', 'HetImp'):
        vs = [v for (k, t, r), v in ex.items()
              if mapping.get(tuple(k.split(':'))) == cell]
        out[cell] = _agg(vs)
    return out


def _agg(vs):
    if not vs:
        return dict(n_execs=0)
    return dict(n_execs=len(vs),
                calls=round(statistics.mean(v['calls'] for v in vs), 2),
                tokens=round(statistics.mean(v['tokens'] for v in vs), 0),
                yuan=round(statistics.mean(v['yuan'] for v in vs), 4),
                span_s=round(statistics.mean(v['span_s'] for v in vs), 1))


def node_level_reroll(cells):
    """V3-only: base vs reroll node-level pairing (dual outputs persisted)."""
    out = collections.Counter()
    score_pairs = []
    for cell in ('HomImp', 'HetImp'):
        for rec in cells[cell].values():
            for x in rec['nodes']:
                if 'chosen' not in x or 'base_output' not in x:
                    continue
                out[(cell, 'nodes')] += 1
                rr = x.get('reroll_output')
                if rr is None:
                    continue
                out[(cell, 'rerolls')] += 1
                if x.get('adopted') == 'reroll':
                    out[(cell, 'adopted')] += 1
                score_pairs.append((cell, x['base_output']['score'],
                                    rr['score'],
                                    x.get('adopted') == 'reroll'))
    return dict(counts={f'{k[0]}:{k[1]}': v for k, v in out.items()},
                score_pairs=score_pairs[:500],
                note='reroll improvement question: does reroll score > '
                     'base score, and does adoption track the better output?')


def model_drift_audit():
    led = M.load_ledger(V3DIR)
    per = collections.defaultdict(set)
    for r in led:
        if r.get('model_resp'):
            per[r['model']].add(r['model_resp'])
    return {k: sorted(v) for k, v in per.items()} or \
        {'note': 'no V3 ledger yet (mock run: model_resp None)'}


def main():
    cells = load_cells()
    result = dict(
        status='complete' if all(
            len(cells.get(c, {})) == 12
            for c in ('HomImp', 'HetImp')) else 'partial',
        counts={c: len(cells.get(c, {}))
                for c in ('HomBase', 'HetBase', 'HomImp', 'HetImp')},
        cells={c: cell_summary(cells, c)
               for c in ('HomBase', 'HetBase', 'HomImp', 'HetImp')},
        delivery_effect_het=delivery_delta(cells, 'HetImp', 'HetBase'),
        delivery_effect_hom=delivery_delta(cells, 'HomImp', 'HomBase'),
        interaction=interaction(cells),
        gates=gate_comparison(cells),
        costs=costs(cells),
        node_reroll=node_level_reroll(cells),
        model_drift=model_drift_audit(),
        h3_decomposition=dict(
            base_gap_terminal_vs_raw=None, imp_gap_terminal_vs_raw=None,
            note='filled below'),
    )
    def gap(a, b):
        sa, sb = cell_summary(cells, a), cell_summary(cells, b)
        return [round((sb['pooled']['mean_task_q_' + k] -
                       sa['pooled']['mean_task_q_' + k]) * 100, 2)
                for k in ('main', 'raw')]
    result['h3_decomposition']['base_gap_terminal_vs_raw'] = \
        gap('HomBase', 'HetBase')
    result['h3_decomposition']['imp_gap_terminal_vs_raw'] = \
        gap('HomImp', 'HetImp')
    result['h3_decomposition']['note'] = \
        'H3: under improved delivery the Het-Hom terminal gap should shrink ' \
        'toward the raw gap (delivery explains the difference).'
    json.dump(result, open(HERE / 'RQ2_P2R_V3_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in
                      ('status', 'counts', 'interaction', 'gates')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
