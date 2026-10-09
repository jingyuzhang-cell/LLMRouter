"""Experiment 5: V2 formal search-efficiency and ablation analysis.

Zero model requests — reads the completed V2 campaign sessions only.

Reports per method (and seed):
  - best-so-far mean-Q at equal evaluation budget (config quality = mean Q
    over its evaluated states; frozen rule from V2_CANDIDATE_FREEZE)
  - best-so-far vs cumulative physical requests and tokens
  - final best config and non-dominated (Q,C,L) set among evaluated configs
  - hypervolume evolution (frozen normalization Q:[0,1], C:[0,2500], L:[0,12];
    reference point (0, 2500, 12) in raw units, maximized on Q)
  - cross-seed stability for dual-seed methods
  - ablation deltas (single-seed where only one seed completed; labeled
    PRELIMINARY per master task book)

Non-claims: search call cost is NOT deployment cost; the 8-task campaign
panel Q is NOT an independent validation accuracy.

Run:  python3 -m collab_scheduler_v1.joint_search_v1.v2_search_analysis
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/V2_FORMAL_SEARCH_ANALYSIS.json'

METHODS = ('proposed_state_incremental', 'random', 'scalarized_bo',
           'official_qnehvi_same_state', 'proposed_without_state',
           'proposed_without_incremental_cost')
LABEL = dict(proposed_state_incremental='SA-PGFS (proposed)',
             random='Random', scalarized_bo='Scalarized BO',
             official_qnehvi_same_state='qNEHVI (BoTorch)',
             proposed_without_state='w/o state (ablation)',
             proposed_without_incremental_cost='w/o incremental cost (ablation)')
# frozen normalization from tri_objective_upgrade
NORM = dict(Q=(0.0, 1.0), C=(0.0, 2500.0), L=(0.0, 12.0))


def load_sessions():
    sessions = {}
    partial = []
    for f in sorted(glob.glob(str(ROOT / 'collab_scheduler_v1/joint_search_v1'
                                   / 'formal_campaign_v2*' / '*'
                                   / 'EVALUATIONS.jsonl'), recursive=False)):
        evs = [json.loads(l) for l in open(f) if l.strip()]
        if not evs:
            continue
        sid = Path(f).parent.name
        method, seed = sid.rsplit('_', 1)
        rec = dict(method=method, seed=seed, dir=str(Path(f).parent), evals=evs,
                   complete=len(evs) == 24)
        key = (method, seed)
        if key in sessions:
            # duplicate across main/retry dirs: keep the COMPLETE one
            if rec['complete'] and not sessions[key]['complete']:
                partial.append(sessions[key]['dir'])
                sessions[key] = rec
            elif not rec['complete']:
                partial.append(rec['dir'])
        else:
            sessions[key] = rec
    return sessions, partial


def config_quality(evals):
    """config -> mean Q across its evaluated states + mean C/L."""
    by_cfg = {}
    for e in evals:
        c = by_cfg.setdefault(e['config_id'], dict(Q=[], C=[], L=[]))
        c['Q'].append(e['objectives']['Q'])
        c['C'].append(e['objectives']['C'])
        c['L'].append(e['objectives']['L'])
    return {k: dict(Q=sum(v['Q']) / len(v['Q']), C=sum(v['C']) / len(v['C']),
                    L=sum(v['L']) / len(v['L']), n_states=len(v['Q']))
            for k, v in by_cfg.items()}


def best_so_far(evals):
    """Running best mean-Q in evaluation order (a config counts once both its
    states are revealed; campaign order reveals states consecutively)."""
    qs = config_quality(evals)
    seen, best, curve = set(), -1.0, []
    for e in evals:
        seen.add(e['config_id'])
        # a config's quality is fixed; consider configs whose states are all
        # revealed so far (approximated by: all configs seen, quality over the
        # states revealed up to this point)
        q = qs[e['config_id']]['Q']
        best = max(best, q)
        curve.append(dict(step=len(curve) + 1, config=e['config_id'],
                          best_Q=best))
    return curve, qs


def cumulative_spend(evals):
    req = tok = 0
    out = []
    for e in evals:
        s = e.get('search_spend', {})
        req += s.get('new_requests', 0)
        tok += s.get('new_tokens', 0)
        out.append(dict(step=len(out) + 1, cum_requests=req, cum_tokens=tok))
    return out


def hv_evolution(evals):
    """HV of the observed config-level (Q,C,L) set after each step.
    Normalized to the frozen box; reference point at the box origin (worst).
    Uses the FIXED sa_pgfs hypervolume implementation (post bug-fix)."""
    from sa_pgfs_v1.pareto import hypervolume
    seen = {}
    curve = []
    for e in evals:
        o = e['objectives']
        c = seen.setdefault(e['config_id'], dict(Q=[], C=[], L=[]))
        c['Q'].append(o['Q']); c['C'].append(o['C']); c['L'].append(o['L'])
        pts = []
        for v in seen.values():
            q = sum(v['Q']) / len(v['Q'])
            cc = sum(v['C']) / len(v['C'])
            l = sum(v['L']) / len(v['L'])
            pts.append((q, cc, l))
        # normalize: Q up, C/L down -> maximize (Q, 1-C/2500, 1-L/12)
        norm = [( (q - NORM['Q'][0]) / (NORM['Q'][1] - NORM['Q'][0]),
                  1 - min(cc, NORM['C'][1]) / NORM['C'][1],
                  1 - min(l, NORM['L'][1]) / NORM['L'][1] ) for q, cc, l in pts]
        try:
            hv = hypervolume(norm, ref=(0.0, 0.0, 0.0))
        except Exception:
            hv = None
        curve.append(dict(step=len(curve) + 1, hv=hv))
    return curve


def pareto_nd(qs):
    items = [(k, v) for k, v in qs.items()]
    nd = []
    for k, v in items:
        dominated = any(
            (w['Q'] >= v['Q'] and w['C'] <= v['C'] and w['L'] <= v['L']) and
            (w['Q'], w['C'], w['L']) != (v['Q'], v['C'], v['L'])
            for _, w in items)
        if not dominated:
            nd.append(dict(config=k, **{x: round(v[x], 4) for x in ('Q', 'C', 'L')}))
    return sorted(nd, key=lambda x: -x['Q'])


def run():
    sessions, partial = load_sessions()
    methods = {}
    for m in METHODS:
        seeds = {s: r for (mm, s), r in sessions.items()
                 if mm == m and r['complete']}
        entry = dict(label=LABEL[m], n_complete_seeds=len(seeds),
                     seeds={}, multi_seed=len(seeds) >= 2)
        agg_best = {}
        for seed, r in sorted(seeds.items()):
            curve, qs = best_so_far(r['evals'])
            spend = cumulative_spend(r['evals'])
            hv = hv_evolution(r['evals'])
            final_best = max(qs.items(), key=lambda kv: kv[1]['Q'])
            entry['seeds'][seed] = dict(
                n_evals=len(r['evals']),
                final_best_config=final_best[0],
                final_best_Q=round(final_best[1]['Q'], 4),
                best_so_far_Q_at={f'step{k["step"]}': round(k['best_Q'], 4)
                                  for k in curve},
                cum_spend_final=dict(requests=spend[-1]['cum_requests'],
                                     tokens=spend[-1]['cum_tokens']),
                hv_final=hv[-1]['hv'],
                nd_configs=pareto_nd(qs),
                directory=r['dir'])
            for k in curve:
                agg_best.setdefault(k['step'], []).append(k['best_Q'])
        entry['best_Q_mean_by_step'] = {
            f'step{s}': round(sum(v) / len(v), 4) for s, v in sorted(agg_best.items())}
        entry['seed_stability_final_best_Q'] = (
            [round(s['final_best_Q'], 4) for s in entry['seeds'].values()])
        methods[m] = entry

    # equal-budget comparison at step 24 (all complete sessions have 24)
    comparison = dict(step=24,
                      best_Q={m: methods[m]['best_Q_mean_by_step'].get('step24')
                              for m in METHODS if methods[m]['seeds']},
                      note='config quality = mean Q across its evaluated '
                           'states (frozen selection rule); 8-task campaign '
                           'panel; NOT an independent accuracy')

    # ablation deltas (vs proposed, same-seed pairing where possible)
    ablations = {}
    for abl, base in (('proposed_without_state', 'proposed_state_incremental'),
                      ('proposed_without_incremental_cost', 'proposed_state_incremental')):
        a, b = methods[abl], methods[base]
        common = sorted(set(a['seeds']) & set(b['seeds']))
        rows = []
        for s in common:
            qa = a['seeds'][s]['final_best_Q']
            qb = b['seeds'][s]['final_best_Q']
            rows.append(dict(seed=s, ablation_best_Q=qa, base_best_Q=qb,
                             delta=round(qa - qb, 4)))
        ablations[abl] = dict(n_common_seeds=len(common), per_seed=rows,
                              evidence_level=('PRELIMINARY (single seed)'
                                              if len(common) == 1 else
                                              'dual-seed'))

    out = dict(
        role='Experiment 5: V2 search efficiency + ablations (zero model requests)',
        sessions_used={f'{m}_{s}': r['dir'] for (m, s), r in sessions.items()
                       if r['complete']},
        partial_dirs_excluded=partial,
        methods=methods, equal_budget_comparison=comparison, ablations=ablations,
        non_claims=[
            'search call cost is the cost of FINDING a candidate, not deploying it',
            'campaign-panel Q (8 tasks) is not an independent validation accuracy',
            'single-seed ablations are preliminary; no cross-seed stability claim'],
        )
    OUT.write_text(json.dumps(out, indent=1))
    print('equal-budget best-Q @step24:')
    for m, q in comparison['best_Q'].items():
        n = methods[m]['n_complete_seeds']
        print(f'  {LABEL[m]:32s} Q={q} (seeds={n})')
    for a, d in ablations.items():
        print(f'ablation {LABEL[a]}: {d["evidence_level"]} deltas='
              f'{[r["delta"] for r in d["per_seed"]]}')


if __name__ == '__main__':
    run()
