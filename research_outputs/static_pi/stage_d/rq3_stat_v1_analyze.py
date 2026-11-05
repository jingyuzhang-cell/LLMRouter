#!/usr/bin/env python3
"""RQ3_STAT_V1 analysis, FROZEN BEFORE DATA (zero API calls).

Implements RQ3_STAT_V1_PREREGISTRATION.md sec.2-3 exactly:
  quality: task-equal Q_main paired B-A; per-task deltas; reason-slot
           decomposition (merge-node assigned gold slots); E07 null task.
  delivery: gate/parse/truncation rates.
  cost/latency: per-exec calls/tokens/yuan/span; deltas vs HomDS.
  criteria: quality (mean dQ>0 AND >=3/4 tasks B>=A AND reason-slot dQ>0),
           cost (d yuan <= +10%), latency (d span <= +20%); verdict rules.
"""
import json, statistics, itertools, random, collections
from pathlib import Path
import rq2_p2r_v2_analyze as M  # frozen scorer

HERE = Path(__file__).parent
RUNS = HERE / 'rq3_stat_v1_runs'
TASKS = M.TASKS
RNG = random.Random(20261104)
BOOT = 5000

REASON_SLOTS = {}  # task -> set(fact_id) assigned to merge/reason nodes
MAT = json.load(open(HERE / 'rq1_tasks' / 'rq1_tasks_materials.json'))
for t, spec in MAT['tasks'].items():
    s = set()
    for n in spec['nodes']:
        if n['kind'] == 'reason':
            s.update(n.get('fact_ids', []))
    REASON_SLOTS[t] = s


def load():
    cells = collections.defaultdict(dict)
    for cell in ('HomDS', 'HetQR'):
        for p in sorted(RUNS.glob(f'{cell}__*.json')):
            d = json.load(open(p))
            cells[cell][(d['task'], d['rep'])] = d
    return cells


def slot_pass(rec):
    """fact_id -> slot pass (matched & doc-localized & report gate on adopted)."""
    facts = []
    gate = any(x.get('kind') == 'report' and 'chosen' in x and M.chosen_ok(x)
               for x in rec['nodes'])
    for x in rec['nodes']:
        if 'chosen' not in x:
            continue
        for f in x['chosen'].get('facts', []):
            if isinstance(f, dict):
                facts.append(f)
    out = {}
    for g in M.GOLD[rec['task']]:
        ok = gate and any(M.match(g, f) for f in facts)
        out[g['fact_id']] = ok
    return out, gate


def q_main(rec):
    s, _ = slot_pass(rec)
    return statistics.mean(s.values()) if s else None


def cell_summary(cells, cell):
    per_task = collections.defaultdict(list)
    gates = []
    for (t, r), rec in cells[cell].items():
        per_task[t].append(q_main(rec))
        _, g = slot_pass(rec)
        gates.append(g)
    return dict(
        n_execs=len(gates),
        mean_task_q=round(statistics.mean(
            statistics.mean(v) for v in per_task.values()), 4) if per_task else None,
        per_task={t: round(statistics.mean(v), 4) for t, v in per_task.items()},
        gate_rate=round(statistics.mean(gates), 4) if gates else None)


def paired_delta(cells):
    per_task = {}
    reps = {}
    for t in TASKS:
        a = {r: q_main(rec) for (tt, r), rec in cells['HomDS'].items() if tt == t}
        b = {r: q_main(rec) for (tt, r), rec in cells['HetQR'].items() if tt == t}
        common = sorted(set(a) & set(b))
        if not common:
            continue
        per_task[t] = round((statistics.mean(b[r] for r in common) -
                             statistics.mean(a[r] for r in common)) * 100, 2)
        reps[t] = (a, b, common)
    ds = list(per_task.values())
    obs = statistics.mean(ds)
    cnt = tot = 0
    for signs in itertools.product([1, -1], repeat=len(ds)):
        tot += 1
        if abs(statistics.mean([d * s for d, s in zip(ds, signs)])) >= abs(obs) - 1e-12:
            cnt += 1
    boots = []
    keys = list(reps)
    for _ in range(BOOT):
        vals = []
        for _ in range(len(keys)):
            t = RNG.choice(keys)
            a, b, common = reps[t]
            ca = RNG.choices(list(common), k=len(common))
            vals.append((statistics.mean(b[r] for r in ca) -
                         statistics.mean(a[r] for r in ca)) * 100)
        boots.append(statistics.mean(vals))
    boots.sort()
    return dict(per_task=per_task, mean_pp=round(obs, 2),
                sd_pp=round(statistics.stdev(ds), 2) if len(ds) > 1 else None,
                signflip_p=round(cnt / tot, 4),
                signflip_floor='n=4 tasks => min two-sided p=0.125; exploratory',
                cluster_bootstrap_ci95=[round(boots[int(0.025 * BOOT)], 2),
                                        round(boots[int(0.975 * BOOT) - 1], 2)])


def reason_slot_decomp(cells):
    out = {}
    for t in TASKS:
        rs = REASON_SLOTS.get(t, set())
        a_b = b_b = a_o = b_o = 0
        n_r = n_o = 0
        for (tt, r), rec in cells['HomDS'].items():
            if tt != t:
                continue
            s, _ = slot_pass(rec)
            for fid, ok in s.items():
                if fid in rs:
                    a_b += ok; n_r += 1
                else:
                    a_o += ok; n_o += 1
        for (tt, r), rec in cells['HetQR'].items():
            if tt != t:
                continue
            s, _ = slot_pass(rec)
            for fid, ok in s.items():
                if fid in rs:
                    b_b += ok; n_r += 0
                else:
                    b_o += ok
        out[t] = dict(reason_slots=sorted(rs),
                      A_reason_rate=round(a_b / n_r, 4) if n_r else None,
                      B_reason_rate=round(b_b / n_r, 4) if n_r else None,
                      A_other_rate=round(a_o / n_o, 4) if n_o else None,
                      B_other_rate=round(b_o / n_o, 4) if n_o else None)
    pooled = dict(
        A_reason=round(sum(out[t]['A_reason_rate'] or 0 for t in TASKS) /
                       max(1, sum(1 for t in TASKS if out[t]['A_reason_rate'] is not None)), 4),
        B_reason=round(sum(out[t]['B_reason_rate'] or 0 for t in TASKS) /
                       max(1, sum(1 for t in TASKS if out[t]['B_reason_rate'] is not None)), 4))
    return dict(per_task=out, pooled=pooled)


def delivery(cells):
    out = {}
    for cell in ('HomDS', 'HetQR'):
        parse_fail = nodes = rerolls = adopted = 0
        for rec in cells[cell].values():
            for x in rec['nodes']:
                if 'chosen' not in x or 'base_output' not in x:
                    continue
                nodes += 1
                parse_fail += int(not x['base_output']['ok'])
                if x.get('reroll_output'):
                    rerolls += 1
                    adopted += int(x['adopted'] == 'reroll')
        out[cell] = dict(nodes=nodes, base_parse_fail=parse_fail,
                         rerolls=rerolls, reroll_adopted=adopted)
    return out


def cost_latency(cells):
    led = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]
    ex = collections.defaultdict(list)
    for r in led:
        ex[(r['cell'], r['task'], r['rep'])].append(r)
    agg = {}
    for cell in ('HomDS', 'HetQR'):
        rows = []
        for (c, t, rp), rs in ex.items():
            if c != cell:
                continue
            rows.append(dict(calls=len(rs),
                             tokens=sum(x['tin'] + x['tout'] for x in rs),
                             yuan=round(sum(x['yuan'] for x in rs), 4),
                             span=round(max(x['ts'] + x['lat'] for x in rs) -
                                        min(x['ts'] for x in rs), 1)))
        agg[cell] = dict(n=len(rows),
                         calls=round(statistics.mean(r['calls'] for r in rows), 2),
                         tokens=round(statistics.mean(r['tokens'] for r in rows), 0),
                         yuan=round(statistics.mean(r['yuan'] for r in rows), 4),
                         span=round(statistics.mean(r['span'] for r in rows), 1))
    a, b = agg['HomDS'], agg['HetQR']
    agg['delta_pct'] = dict(
        yuan=round((b['yuan'] / a['yuan'] - 1) * 100, 1) if a['yuan'] else None,
        span=round((b['span'] / a['span'] - 1) * 100, 1) if a['span'] else None,
        calls=round((b['calls'] / a['calls'] - 1) * 100, 1) if a['calls'] else None)
    trunc = collections.Counter()
    tot = collections.Counter()
    for r in led:
        tot[r['model']] += 1
        trunc[r['model']] += int(r['stop'] in ('max_tokens', 'length'))
    agg['truncation_by_model'] = {m: f'{trunc[m]}/{tot[m]}'
                                  for m in tot}
    return agg


def main():
    cells = load()
    delta = paired_delta(cells)
    decomp = reason_slot_decomp(cells)
    cost = cost_latency(cells)
    qual_ok = (delta['mean_pp'] > 0 and
               sum(1 for v in delta['per_task'].values() if v >= 0) >= 3 and
               (decomp['pooled']['B_reason'] or 0) >
               (decomp['pooled']['A_reason'] or 0))
    cost_ok = (cost['delta_pct']['yuan'] is not None and
               cost['delta_pct']['yuan'] <= 10)
    lat_ok = (cost['delta_pct']['span'] is not None and
              cost['delta_pct']['span'] <= 20)
    verdict = ('PROCEED to dynamic joint-scheduling experiment'
               if (qual_ok and cost_ok and lat_ok)
               else ('QUALITY GAIN WITHOUT cost/latency control (operator call)'
                     if qual_ok else
                     'NO terminal gain from node-type allocation (record layer decomposition)'))
    result = dict(
        counts={c: len(cells[c]) for c in ('HomDS', 'HetQR')},
        cells={c: cell_summary(cells, c) for c in ('HomDS', 'HetQR')},
        paired=delta, reason_slots=decomp,
        delivery=delivery(cells), cost_latency=cost,
        criteria=dict(quality=qual_ok, cost=cost_ok, latency=lat_ok),
        verdict=verdict)
    json.dump(result, open(HERE / 'RQ3_STAT_V1_RESULTS.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1)[:5000])


if __name__ == '__main__':
    main()
