"""Pre-submission statistical consistency check (zero model calls).

Recomputes every headline comparison from the frozen artifacts with one uniform
method (paired task bootstrap CI, seed 20260918, B=10000; McNemar exact) and
cross-checks the reported accuracies against recomputation:

  1. clean overall: Router/Static/Dynamic pairwise (Table 1)
  2. clean subsets (Easy/Hard): Dynamic vs Static, Dynamic vs Router (Table 1b)
  3. fault 10/20/30: Dynamic vs Router and Dynamic vs Static, overall + Hard
  4. RD vs FG (Table 2), DV vs Dynamic (verifier ablation)
  5. reported-vs-recomputed accuracy audit for every arm/scenario

Writes adaptive_benchmark/STAT_CHECK.md + STAT_CHECK.json. Exit code 1 on any
mismatch between reported and recomputed numbers.
"""
import json
import math
import random
import time

from .multidag_dynamic import OUT
from .multidag_fullgraph import FG
from .benchmark_run import BENCH, RATES
from .verifier_run import DV

SEED = 20260918
B = 10000


def mcnemar_exact(b, c):
    m = b + c
    if m == 0:
        return 1.0
    return min(1.0, sum(math.comb(m, i) for i in range(0, min(b, c) + 1)) / 2 ** m * 2)


def paired(a, b, seed=SEED):
    """a, b: lists of 0/1. Returns dQ (a-b), bootstrap CI, help/harm, McNemar p."""
    n = len(a)
    dQ = (sum(a) - sum(b)) / n
    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(seed)
    out = []
    for _ in range(B):
        out.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    out.sort()
    ci = [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]
    bc = sum(1 for x, y in zip(a, b) if y == 0 and x == 1)
    cc = sum(1 for x, y in zip(a, b) if y == 1 and x == 0)
    return dict(dQ=round(dQ, 4), ci=ci, help=bc, harm=cc,
                mcnemar_p=round(mcnemar_exact(bc, cc), 6))


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    import re

    def n_ops(d):
        return len(re.findall(r'[+\-*/]', d))

    hard = {t['uid'] for t in tasks if n_ops(t['derivation']) >= 2}
    easy = set(uids) - hard
    clean = json.loads((BENCH / 'CLEAN_RESULTS.json').read_text())
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())
    dv = json.loads((DV / 'DV_RESULT.json').read_text())['dv']
    fault = {p: json.loads((BENCH / f'fault_p{p}' / 'FAULT_RESULT.json').read_text()) for p in (10, 20, 30)}

    def vec(rows, subset=None):
        sel = sorted(subset if subset else uids)
        return [int(rows[u]['ok']) for u in sel]

    checks = []
    problems = []

    def add(name, a_rows, b_rows, subset, reported_dq=None):
        r = paired(vec(a_rows, subset), vec(b_rows, subset))
        r.update(name=name, n=len(subset) if subset else len(uids))
        if reported_dq is not None and abs(r['dQ'] - reported_dq) > 5e-4:
            problems.append(dict(name=name, reported=reported_dq, recomputed=r['dQ']))
        checks.append(r)
        return r

    # 1. clean overall
    add('clean: router vs static', clean['router'], clean['static'], None)
    add('clean: router vs dynamic', clean['router'], clean['dynamic'], None)
    add('clean: dynamic vs static', clean['dynamic'], clean['static'], None)
    # 2. clean subsets
    add('clean easy: dynamic vs static', clean['dynamic'], clean['static'], easy)
    add('clean hard: dynamic vs static', clean['dynamic'], clean['static'], hard)
    add('clean hard: dynamic vs router', clean['dynamic'], clean['router'], hard)
    # 3. fault scenarios
    for p in (10, 20, 30):
        add(f'fault{p}: dynamic vs router', fault[p]['dynamic'], fault[p]['router'], None)
        add(f'fault{p}: dynamic vs static', fault[p]['dynamic'], fault[p]['static'], None)
        add(f'fault{p} hard: dynamic vs router', fault[p]['dynamic'], fault[p]['router'], hard)
    # 4. RD vs FG, DV vs RD (corrected arms)
    add('RD vs FG (local vs full-graph)', corrected['arms']['fg'], corrected['arms']['rd'], None,
        reported_dq=-0.025)
    add('DV vs Dynamic', dv, clean['dynamic'], None, reported_dq=0.0)

    # 5. reported-vs-recomputed accuracy audit
    audit = []

    def q(rows):
        return round(sum(1 for u in uids if rows[u]['ok']) / len(uids), 4)

    expected = {
        ('clean', 'router'): 0.5500, ('clean', 'static'): 0.3500, ('clean', 'dynamic'): 0.4000,
        ('fault10', 'router'): 0.4833, ('fault10', 'static'): 0.3167, ('fault10', 'dynamic'): 0.4083,
        ('fault20', 'router'): 0.4250, ('fault20', 'static'): 0.2917, ('fault20', 'dynamic'): 0.4083,
        ('fault30', 'router'): 0.3500, ('fault30', 'static'): 0.2667, ('fault30', 'dynamic'): 0.4083,
        ('corrected', 'static'): 0.3917, ('corrected', 'dynamic'): 0.4250,
        ('corrected', 'sm'): 0.4167, ('corrected', 'rd'): 0.4000, ('corrected', 'fg'): 0.3750,
        ('dv', 'dv'): 0.4000,
    }
    actual = {
        ('clean', 'router'): q(clean['router']), ('clean', 'static'): q(clean['static']),
        ('clean', 'dynamic'): q(clean['dynamic']),
        ('fault10', 'router'): q(fault[10]['router']), ('fault10', 'static'): q(fault[10]['static']),
        ('fault10', 'dynamic'): q(fault[10]['dynamic']),
        ('fault20', 'router'): q(fault[20]['router']), ('fault20', 'static'): q(fault[20]['static']),
        ('fault20', 'dynamic'): q(fault[20]['dynamic']),
        ('fault30', 'router'): q(fault[30]['router']), ('fault30', 'static'): q(fault[30]['static']),
        ('fault30', 'dynamic'): q(fault[30]['dynamic']),
        ('corrected', 'static'): q(corrected['arms']['static']),
        ('corrected', 'dynamic'): q(corrected['arms']['dynamic']),
        ('corrected', 'sm'): q(corrected['arms']['sm']),
        ('corrected', 'rd'): q(corrected['arms']['rd']),
        ('corrected', 'fg'): q(corrected['arms']['fg']),
        ('dv', 'dv'): q(dv),
    }
    for k in expected:
        okflag = abs(expected[k] - actual[k]) <= 5e-4
        audit.append(dict(scenario=k[0], arm=k[1], reported=expected[k], recomputed=actual[k], match=okflag))
        if not okflag:
            problems.append(dict(name=f'accuracy {k}', reported=expected[k], recomputed=actual[k]))

    lines = ['# Pre-submission statistical check', '',
             'Method: paired task bootstrap CI (seed 20260918, B=10000) + McNemar exact, recomputed from frozen artifacts.', '',
             '## Headline comparisons', '',
             '| Comparison | n | dQ | CI | help/harm | McNemar p |',
             '|---|---:|---:|---|---:|---:|']
    for c in checks:
        lines.append(f"| {c['name']} | {c['n']} | {c['dQ']:+.4f} | [{c['ci'][0]:+.4f}, {c['ci'][1]:+.4f}] | "
                     f"{c['help']}/{c['harm']} | {c['mcnemar_p']} |")
    lines += ['', '## Accuracy audit (reported vs recomputed)', '',
              '| Scenario | Arm | reported | recomputed | match |', '|---|---|---:|---:|---|']
    for a in audit:
        lines.append(f"| {a['scenario']} | {a['arm']} | {a['reported']} | {a['recomputed']} | {'OK' if a['match'] else 'MISMATCH'} |")
    lines += ['', f'Problems: {len(problems)}', json.dumps(problems, ensure_ascii=False), '']
    (BENCH / 'STAT_CHECK.md').write_text('\n'.join(lines))
    (BENCH / 'STAT_CHECK.json').write_text(json.dumps(
        dict(generated_unix=time.time(), checks=checks, audit=audit, problems=problems),
        ensure_ascii=False, indent=2))
    print('\n'.join(lines))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(run())
