"""QP4 causal audit (zero calls): task-level effects with uncertainty,
reuse-confounding check, truncation impact, parse-fail sensitivity.

Key discipline: the 9 compliant cells are NOT a random subgroup; we audit
pre-outcome covariates (verified-table coverage) by compliance group before
interpreting the 0.442 vs 0.089 gap.
"""
import json, sys, collections, statistics as st, random, itertools
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp2_chain as CH
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
TASKS = F.TASKS


def load_cells():
    d = json.load(open(f'{QP}/QP4_RESULTS.json'))
    by = collections.defaultdict(dict)
    for r in d['results']:
        ok = r.get('q') is not None
        by[(r['task'], r['cell'])][r['rep']] = dict(
            q=r['q'] if ok else None, val=r.get('value'), reuse=r.get('reuse_rate'),
            parse_fail=not ok)
    return by


def tq(by, t, c):
    vals = [v['q'] for v in by[(t, c)].values() if v.get('q') is not None]
    return st.mean(vals) if vals else None


def signflip_p(deltas):
    """Two-sided sign-flip randomization test on paired task deltas."""
    pos = sum(1 for x in deltas if x > 0)
    n = len(deltas)
    obs = abs(sum(deltas))
    rng = random.Random(20261103)
    hit = 0
    for _ in range(20000):
        s = sum(x if rng.random() < 0.5 else -x for x in deltas)
        if abs(s) >= obs - 1e-12:
            hit += 1
    return round((hit + 1) / 20001, 4), pos, n


def boot_ci(deltas, B=20000):
    rng = random.Random(20261104)
    means = []
    for _ in range(B):
        sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        means.append(st.mean(sample))
    means.sort()
    return round(means[int(0.025 * B)], 4), round(means[int(0.975 * B)], 4)


def truncation_and_coverage():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    d = json.load(open(f'{QP}/QP4_RESULTS.json'))
    cellmeta = {}
    for r in d['results']:
        if r.get('q') is None:
            continue
        t, c, rep = r['task'], r['cell'], f"r{r['rep']}"
        trunc = sum(1 for k, x in led.items()
                    if k[0] == t and k[1] == c and k[2] == rep and x['stop_reason'] == 'max_tokens')
        # verified-table coverage (H1 cells): rebuild from e outputs
        cov = None
        if c in 'BD':
            contract = F.load_contract(t)
            e0 = extract_any(led[(t, c, rep, 'e0')]['text'])
            e1 = extract_any(led[(t, c, rep, 'e1')]['text'])
            table = CH.build_evidence_table({'e0': e0, 'e1': e1})
            ok, _ = CH.verify_evidence(table, contract)
            cov = len(ok) / len(contract['required_facts'])
        cellmeta[(t, c, rep)] = dict(q=r['q'], trunc=trunc, coverage=cov,
                                     reuse=r.get('reuse_rate'))
    return cellmeta


def main():
    by = load_cells()

    # ---- A1 task-level effects with uncertainty
    eff = dict(h1=[], h2=[], i=[], d_a=[])
    per_task = {}
    for t in TASKS:
        A, B, C, D = tq(by, t, 'A'), tq(by, t, 'B'), tq(by, t, 'C'), tq(by, t, 'D')
        per_task[t] = dict(A=A, B=B, C=C, D=D,
                           h1=((B - A) + (D - C)) / 2, h2=((C - A) + (D - B)) / 2,
                           inter=(D - C) - (B - A), d_a=D - A)
        eff['h1'].append(per_task[t]['h1']); eff['h2'].append(per_task[t]['h2'])
        eff['i'].append(per_task[t]['inter']); eff['d_a'].append(D - A)
    print('=== task-level paired effects (Q units) ===')
    for t in TASKS:
        p = per_task[t]
        print(f"  {t:9s} A={p['A']:.3f} B={p['B']:.3f} C={p['C']:.3f} D={p['D']:.3f} | "
              f"H1={p['h1']:+.3f} H2={p['h2']:+.3f} inter={p['inter']:+.3f} D-A={p['d_a']:+.3f}")
    for name in ('h1', 'h2', 'i', 'd_a'):
        p, pos, n = signflip_p(eff[name])
        lo, hi = boot_ci(eff[name])
        print(f"  {name:4s}: mean {st.mean(eff[name]):+.4f}  95%CI[{lo:+.4f},{hi:+.4f}]  "
              f"sign-flip p={p}  positive {pos}/{n}")

    # ---- A2 reuse confounding audit
    meta = truncation_and_coverage()
    h1cells = [(k, v) for k, v in meta.items() if k[1] in 'BD']
    comp = [v for k, v in h1cells if v['reuse'] == 1.0]
    nonc = [v for k, v in h1cells if v['reuse'] is not None and v['reuse'] < 1.0]
    print('\n=== reuse-compliance confounding (pre-outcome covariate: verified coverage) ===')
    print(f"  compliant   n={len(comp)}  coverage mean={st.mean([v['coverage'] for v in comp]):.3f}  Q={st.mean([v['q'] for v in comp]):.3f}")
    print(f"  non-compl.  n={len(nonc)} coverage mean={st.mean([v['coverage'] for v in nonc]):.3f}  Q={st.mean([v['q'] for v in nonc]):.3f}")
    # stratified: within-same-coverage-band comparison
    allc = [(v['coverage'], v['q'], v['reuse'] == 1.0) for k, v in h1cells]
    hi_band = [x for x in allc if x[0] >= st.mean([c[0] for c in allc])]
    lo_band = [x for x in allc if x[0] < st.mean([c[0] for c in allc])]
    for nm, band in (('coverage>=mean', hi_band), ('coverage<mean', lo_band)):
        cq = [x[1] for x in band if x[2]]; nq = [x[1] for x in band if not x[2]]
        print(f"  {nm}: compliant Q={st.mean(cq) if cq else float('nan'):.3f}(n={len(cq)}) "
              f"vs non-compliant Q={st.mean(nq) if nq else float('nan'):.3f}(n={len(nq)})")

    # ---- A3 truncation impact
    tr = [v for v in meta.values() if v['trunc'] > 0]
    ntr = [v for v in meta.values() if v['trunc'] == 0]
    print('\n=== truncation ===')
    print(f"  cells with truncation: {len(tr)}, mean Q={st.mean([v['q'] for v in tr]) if tr else float('nan'):.3f}")
    print(f"  cells without:         {len(ntr)}, mean Q={st.mean([v['q'] for v in ntr]):.3f}")

    # ---- A4 parse-fail sensitivity
    gu_d = by[('GUOEN', 'A')]
    reps = list(gu_d.values())
    fail_as_zero = (sum(v['q'] or 0 for v in reps) + 0) / len(reps)
    fail_missing = st.mean([v['q'] for v in reps if v.get('q') is not None])
    macroD_missing = st.mean([tq(by, t, 'D') for t in TASKS])
    print('\n=== parse-fail sensitivity (GUOEN A r2) ===')
    print(f"  GUOEN A: fail-as-zero={fail_as_zero:.4f}  fail-missing={fail_missing:.4f}")
    print(f"  (D macro unaffected: {macroD_missing:.4f}; A macro 0 under both)")

    json.dump(dict(batch='QP4_CAUSAL_AUDIT', model_calls=0,
                   per_task={t: {k: (round(v, 4) if isinstance(v, float) else v)
                                 for k, v in per_task[t].items()} for t in TASKS},
                   effects={k: [round(x, 4) for x in v] for k, v in eff.items()},
                   tests={name: dict(mean=round(st.mean(eff[name]), 4),
                                     ci95=boot_ci(eff[name]),
                                     signflip_p=signflip_p(eff[name])[0])
                          for name in ('h1', 'h2', 'i', 'd_a')},
                   reuse_confounding=dict(
                       compliant=dict(n=len(comp), coverage=round(st.mean([v['coverage'] for v in comp]), 4),
                                      q=round(st.mean([v['q'] for v in comp]), 4)),
                       non_compliant=dict(n=len(nonc), coverage=round(st.mean([v['coverage'] for v in nonc]), 4),
                                          q=round(st.mean([v['q'] for v in nonc]), 4))),
                   truncation=dict(cells_with=len(tr), q_mean=round(st.mean([v['q'] for v in tr]), 4) if tr else None,
                                   cells_without=len(ntr), q_mean_without=round(st.mean([v['q'] for v in ntr]), 4)),
                   parse_fail_sensitivity=dict(fail_as_zero=round(fail_as_zero, 4),
                                               fail_missing=round(fail_missing, 4))),
              open(f'{QP}/QP4_CAUSAL_AUDIT.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
