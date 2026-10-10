"""Formal campaign final evidence package (zero model calls).

Common-budget curves, deployment Q/C/L, and ablation paired differences for
the 18/18 COMPLETE six-method campaign. Discipline (per review):
- credit separation: the per-seed initial design is IDENTICAL across methods
  (verified); curves count EXTRA requests beyond the shared prefix, and
  targets already reached at init are reported as 0-extra for every method;
- primary endpoint: extra requests to first reach fault30 best-Q (the panel's
  ceiling 0.5); clean-state reported alongside;
- no superiority claim from totals (wo_state total 663 < proposed 695 — the
  reviewer's correction is carried in the report);
- n=3 seeds: paired differences reported per-seed with sign consistency, no
  parametric CI overreach;
- two scoring segments (cells 1-11 legacy-close, 12-18 v2.1-integrated) —
  v2.1 re-score flips = 0 on all cells (verified in reconciliation), so
  recorded Q is used;
- failed/retry trajectories: original INCOMPLETE base cells are EXCLUDED from
  curves (their retry completions are the counted trajectories); their ledger
  spend is already included in the campaign totals.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'
HERE = Path(__file__).resolve().parent
TARGET_Q = 0.5

METHODS = ['proposed_state_incremental', 'proposed_without_state',
           'proposed_without_incremental_cost', 'official_qnehvi_same_state',
           'scalarized_bo', 'random']
LABELS = {
    'proposed_state_incremental': 'Proposed (state+incr-cost)',
    'proposed_without_state': 'w/o state',
    'proposed_without_incremental_cost': 'w/o incr-cost',
    'official_qnehvi_same_state': 'qNEHVI (official)',
    'scalarized_bo': 'Scalarized BO',
    'random': 'Random',
}


def load_sessions():
    sessions = {}
    for root in sorted(JS.glob('formal_campaign_v2*')):
        if not root.is_dir():
            continue
        for d in sorted(root.glob('*_2026*')):
            stf = d / 'STATUS.jsonl'
            if not (stf.exists() and
                    json.loads(stf.read_text().splitlines()[-1])['status'] == 'COMPLETE'):
                continue  # original failed cells: excluded from curves (retry counted)
            evs = [json.loads(l) for l in (d / 'EVALUATIONS.jsonl').read_text().splitlines()]
            method, seed = d.name.rsplit('_', 1)
            sessions[(method, int(seed))] = dict(
                dir=str(d), evals=evs,
                requests=sum(e['search_spend']['new_requests'] for e in evs),
                tokens=sum(e['search_spend']['new_tokens'] for e in evs),
                wall=None)
            st = json.loads(stf.read_text().splitlines()[-1])
            sessions[(method, int(seed))]['wall'] = st.get('observed_wall_s')
    return sessions


def session_curve(evs):
    """(extra_req grid points, running best Q per state beyond shared init)."""
    init_evals, search = evs[:4], evs[4:]
    best = {'clean': -1.0, 'fault30': -1.0}
    for e in init_evals:
        best[e['state']] = max(best[e['state']], e['objectives']['Q'])
    init_req = sum(e['search_spend']['new_requests'] for e in init_evals)
    pts = []
    cum = 0
    cur = dict(best)
    pts.append(dict(extra=0, clean=cur['clean'], fault30=cur['fault30']))
    first_hit = {'clean': (0 if cur['clean'] >= TARGET_Q - 1e-9 else None),
                 'fault30': (0 if cur['fault30'] >= TARGET_Q - 1e-9 else None)}
    for e in search:
        cum += e['search_spend']['new_requests']
        cur[e['state']] = max(cur[e['state']], e['objectives']['Q'])
        for st in ('clean', 'fault30'):
            if first_hit[st] is None and cur[st] >= TARGET_Q - 1e-9:
                first_hit[st] = cum
        pts.append(dict(extra=cum, clean=cur['clean'], fault30=cur['fault30']))
    # deployment choice: among evaluated (config,state) units, best fault30 config
    dep = None
    for e in evs:
        if e['state'] == 'fault30' and e['objectives']['Q'] >= TARGET_Q - 1e-9:
            if dep is None or e['objectives']['C'] < dep['C']:
                dep = dict(cid=e['config_id'], C=e['objectives']['C'],
                           L=e['objectives']['L'], Q=e['objectives']['Q'])
    clean_dep = None
    for e in evs:
        if e['state'] == 'clean' and e['objectives']['Q'] >= TARGET_Q - 1e-9:
            if clean_dep is None or e['objectives']['C'] < clean_dep['C']:
                clean_dep = dict(cid=e['config_id'], C=e['objectives']['C'],
                                 L=e['objectives']['L'], Q=e['objectives']['Q'])
    return dict(points=pts, first_hit=first_hit, init_req=init_req,
                deployment_fault30=dep, deployment_clean=clean_dep)


def interp(pts, grid, key):
    xs = [p['extra'] for p in pts]
    ys = [p[key] for p in pts]
    return np.interp(grid, xs, ys, left=ys[0], right=ys[-1])


def main():
    sessions = load_sessions()
    seeds = sorted({s for (_, s) in sessions})
    curves = {k: session_curve(v['evals']) for k, v in sessions.items()}

    # ---- totals table (reviewer's correction carried) ----
    totals = {}
    for m in METHODS:
        rs = [sessions[(m, s)]['requests'] for s in seeds]
        totals[m] = dict(per_seed=rs, total=sum(rs))
    grand = sum(t['total'] for t in totals.values())

    # ---- Q1: common-budget curves (extra requests beyond shared init) ----
    grid = np.arange(0, 301, 5)
    mean_curves = {}
    for m in METHODS:
        f30 = np.mean([interp(curves[(m, s)]['points'], grid, 'fault30') for s in seeds], axis=0)
        mean_curves[m] = f30

    # first-hit extra requests (primary endpoint)
    first_hit = {m: [curves[(m, s)]['first_hit']['fault30'] for s in seeds] for m in METHODS}
    first_hit_clean = {m: [curves[(m, s)]['first_hit']['clean'] for s in seeds] for m in METHODS}

    # ---- Q2: stability (seed dispersion of first-hit and curve AUC) ----
    stability = {}
    for m in METHODS:
        fh = [x for x in first_hit[m] if x is not None]
        aucs = [float(np.trapz(interp(curves[(m, s)]['points'], grid, 'fault30'), grid))
                for s in seeds]
        stability[m] = dict(first_hit_mean=(np.mean(fh) if fh else None),
                            first_hit_range=(max(fh) - min(fh)) if fh else None,
                            auc_mean=float(np.mean(aucs)), auc_seed_range=float(max(aucs) - min(aucs)),
                            requests_range=max(totals[m]['per_seed']) - min(totals[m]['per_seed']))

    # ---- Q3: deployment Q/C/L of selected best configs ----
    deployment = {}
    for m in METHODS:
        rows = []
        for s in seeds:
            c = curves[(m, s)]
            rows.append(dict(
                seed=s,
                f30_cid=(c['deployment_fault30'] or {}).get('cid'),
                f30_C=(c['deployment_fault30'] or {}).get('C'),
                f30_L=round((c['deployment_fault30'] or {}).get('L', 0), 2),
                clean_cid=(c['deployment_clean'] or {}).get('cid'),
                clean_C=(c['deployment_clean'] or {}).get('C'),
                clean_L=round((c['deployment_clean'] or {}).get('L', 0), 2)))
        deployment[m] = rows

    # ---- ablations & baselines: paired first-hit differences (by seed) ----
    def paired(m_a, m_b):
        diffs, signs = [], []
        for s in seeds:
            a, b = first_hit[m_a][seeds.index(s)], first_hit[m_b][seeds.index(s)]
            if a is not None and b is not None:
                diffs.append(a - b)  # negative => m_a reaches target sooner
                signs.append(1 if a < b else (-1 if a > b else 0))
        return dict(per_seed=diffs, mean=float(np.mean(diffs)) if diffs else None,
                    signs=signs, wins=sum(1 for d in diffs if d < 0),
                    losses=sum(1 for d in diffs if d > 0), ties=sum(1 for d in diffs if d == 0))

    comparisons = {
        'ablation_state': paired('proposed_state_incremental', 'proposed_without_state'),
        'ablation_incr_cost': paired('proposed_state_incremental', 'proposed_without_incremental_cost'),
        'vs_qnehvi': paired('proposed_state_incremental', 'official_qnehvi_same_state'),
        'vs_scalarized': paired('proposed_state_incremental', 'scalarized_bo'),
        'vs_random': paired('proposed_state_incremental', 'random'),
    }

    out = dict(
        status='FINAL EVIDENCE — descriptive; advantage claims bounded per report',
        seeds=seeds, target_Q=TARGET_Q,
        credit_separation='per-seed initial design identical across methods (verified); '
                          'curves use EXTRA requests beyond the shared init prefix; '
                          'targets reached at init count as 0-extra for every method',
        totals=dict(per_method={LABELS[m]: totals[m] for m in METHODS},
                    grand_total_requests=grand),
        reviewer_correction='wo_state total (663) < proposed (695): proposed is NOT the '
                            'minimal-total method; totals alone support no ranking',
        first_hit_extra_requests_fault30={LABELS[m]: first_hit[m] for m in METHODS},
        first_hit_extra_requests_clean={LABELS[m]: first_hit_clean[m] for m in METHODS},
        stability={LABELS[m]: stability[m] for m in METHODS},
        deployment_selection={LABELS[m]: deployment[m] for m in METHODS},
        paired_comparisons={k: v for k, v in comparisons.items()},
        limitations=[
            'n=3 seeds: paired diffs reported per-seed with sign counts; no parametric CI',
            'panel quality ceiling: best Q = 0.5 for every method — quality differences '
            'cannot be claimed; efficiency only',
            'two scoring segments (legacy-close vs v2.1) with zero re-score flips',
            'random baseline consumes more per session partly because random selection '
            'yields worse cache reuse — a real cost, reported as measured',
            'original INCOMPLETE base cells excluded from curves; their spend is in totals '
            'and their retries are the counted trajectories'])
    (HERE / 'FORMAL_FINAL_EVIDENCE.json').write_text(json.dumps(out, indent=1, default=str))

    # figures
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    for m in METHODS:
        ax.plot(grid, mean_curves[m], label=LABELS[m],
                lw=2 if m == 'proposed_state_incremental' else 1.2)
    ax.axhline(TARGET_Q, color='gray', ls=':', lw=1)
    ax.set_xlabel('extra physical requests beyond shared initial design (seed-mean)')
    ax.set_ylabel('best fault30 Q (running)')
    ax.set_title('Common-budget quality curves (fault30), seed means; all methods '
                 'reach the 0.5 ceiling', fontsize=9)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / 'fig_budget_curves.png', dpi=150)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    ms = [LABELS[m] for m in METHODS]
    means = [np.mean([x for x in first_hit[m] if x is not None]) for m in METHODS]
    rngs = [(max([x for x in first_hit[m] if x is not None]) - min([x for x in first_hit[m] if x is not None]))
            for m in METHODS]
    axes[0].barh(ms, means, xerr=rngs, color='#69c')
    axes[0].set_xlabel('extra requests to first reach fault30 Q=0.5 (mean ± seed range)')
    cs = []
    for m in METHODS:
        vals = [r['f30_C'] for r in deployment[m] if r['f30_C'] is not None]
        cs.append(np.mean(vals) if vals else 0)
    axes[1].barh(ms, cs, color='#c9a')
    axes[1].set_xlabel('deployment C of selected fault30-best config (seed mean, tokens)')
    for ax in axes:
        ax.tick_params(labelsize=8)
    fig.suptitle('Efficiency endpoint and deployment cost of final selections', fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / 'fig_efficiency_deployment.png', dpi=150)

    print(json.dumps(dict(grand=grand,
                          first_hit={LABELS[m]: first_hit[m] for m in METHODS},
                          comparisons={k: v['per_seed'] for k, v in comparisons.items()}),
                     indent=1))


if __name__ == '__main__':
    main()
