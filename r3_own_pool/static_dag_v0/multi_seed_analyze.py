"""Multi-seed fault-injection consolidation (zero model calls).

Three seeds (20260923 original, 20260924, 20260925), same procedure/pools/policies.
Reports mean +/- std (population std over seeds) per method and rate, paired dQ
mean +/- std, recovery rates, and the hard-subset view. Writes
adaptive_benchmark/MULTI_SEED_RESULTS.json + MULTI_SEED_REPORT.md.
"""
import json
import re
import time

from .multidag_dynamic import OUT
from .benchmark_run import BENCH, RATES

SEEDS = (20260923, 20260924, 20260925)


def stats(xs):
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, var ** 0.5


def load(seed, rate):
    sub = BENCH / (f'fault_p{int(rate * 100)}' if seed == 20260923 else f'fault_p{int(rate * 100)}_seed{seed}')
    return json.loads((sub / 'FAULT_RESULT.json').read_text())


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]

    def n_ops(d):
        return len(re.findall(r'[+\-*/]', d))

    hard = {t['uid'] for t in tasks if n_ops(t['derivation']) >= 2}
    out = {'seeds': SEEDS, 'rates': RATES, 'per_rate': {}, 'hard': {}}
    for rate in RATES:
        rows = {'router': [], 'static': [], 'dynamic': []}
        dq_ds = []
        dq_dr = []
        rec = []
        rec_static = []
        for seed in SEEDS:
            fr = load(seed, rate)
            fset = set(fr['faulted'].keys())
            for m in rows:
                rows[m].append(sum(1 for u in uids if fr[m][u]['ok']) / len(uids))
            dq_ds.append((sum(1 for u in uids if fr['dynamic'][u]['ok']) - sum(1 for u in uids if fr['static'][u]['ok'])) / len(uids))
            dq_dr.append((sum(1 for u in uids if fr['dynamic'][u]['ok']) - sum(1 for u in uids if fr['router'][u]['ok'])) / len(uids))
            rec.append(sum(1 for u in fset if fr['dynamic'][u]['ok']) / len(fset))
            rec_static.append(sum(1 for u in fset if fr['static'][u]['ok']) / len(fset))
        entry = {m: dict(mean=round(stats(v)[0], 4), std=round(stats(v)[1], 4)) for m, v in rows.items()}
        entry['dQ_dynamic_vs_static'] = dict(mean=round(stats(dq_ds)[0], 4), std=round(stats(dq_ds)[1], 4))
        entry['dQ_dynamic_vs_router'] = dict(mean=round(stats(dq_dr)[0], 4), std=round(stats(dq_dr)[1], 4))
        entry['dynamic_recovery'] = dict(mean=round(stats(rec)[0], 4), std=round(stats(rec)[1], 4))
        entry['static_survival'] = dict(mean=round(stats(rec_static)[0], 4), std=round(stats(rec_static)[1], 4))
        out['per_rate'][rate] = entry
        h = {'router': [], 'static': [], 'dynamic': []}
        for seed in SEEDS:
            fr = load(seed, rate)
            for m in h:
                h[m].append(sum(1 for u in hard if fr[m][u]['ok']) / len(hard))
        out['hard'][rate] = {m: dict(mean=round(stats(v)[0], 4), std=round(stats(v)[1], 4)) for m, v in h.items()}
    (BENCH / 'MULTI_SEED_RESULTS.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    lines = ['# Multi-seed fault injection (3 seeds: 20260923/24/25)', '',
             'Mean +/- std over seeds (population std). Same procedure, pools and policies; '
             'calls reused at temperature 0; only new prompts executed for real.', '',
             '| Fault rate | Single LLM (retry) | Static | Dynamic | dQ(Dyn-Static) | dQ(Dyn-Single) | Dynamic recovery | Static survival |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for rate in RATES:
        e = out['per_rate'][rate]
        lines.append(f"| {int(rate * 100)}% | {e['router']['mean']:.4f}±{e['router']['std']:.4f} | "
                     f"{e['static']['mean']:.4f}±{e['static']['std']:.4f} | "
                     f"{e['dynamic']['mean']:.4f}±{e['dynamic']['std']:.4f} | "
                     f"{e['dQ_dynamic_vs_static']['mean']:+.4f}±{e['dQ_dynamic_vs_static']['std']:.4f} | "
                     f"{e['dQ_dynamic_vs_router']['mean']:+.4f}±{e['dQ_dynamic_vs_router']['std']:.4f} | "
                     f"{e['dynamic_recovery']['mean']:.2f}±{e['dynamic_recovery']['std']:.2f} | "
                     f"{e['static_survival']['mean']:.2f}±{e['static_survival']['std']:.2f} |")
    lines += ['', '## Hard subset (46 tasks)', '',
              '| Fault rate | Single LLM | Static | Dynamic |', '|---:|---:|---:|---:|']
    for rate in RATES:
        e = out['hard'][rate]
        lines.append(f"| {int(rate * 100)}% | {e['router']['mean']:.4f}±{e['router']['std']:.4f} | "
                     f"{e['static']['mean']:.4f}±{e['static']['std']:.4f} | "
                     f"{e['dynamic']['mean']:.4f}±{e['dynamic']['std']:.4f} |")
    (BENCH / 'MULTI_SEED_REPORT.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
