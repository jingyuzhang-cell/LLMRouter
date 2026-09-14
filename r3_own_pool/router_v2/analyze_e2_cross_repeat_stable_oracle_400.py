"""E2: cross-repeat stable oracle — how much of the 8.6pp hindsight gap is real?

Leave-one-repeat-out over the 400x4x5 utility panel: for each query and each
held-out repeat r, select the model with the best mean over the OTHER FOUR
repeats, then evaluate that choice only on repeat r. Selection never sees the
repeat it is judged on. The hindsight oracle (max of 5-repeat means, 81.0%)
contains selection bias from generation noise; the stable oracle removes it.

Baselines reuse the frozen fold-local choices (BestSingle, QueryOnlyRidge) —
no retraining. Tie policy: among models tied at the best 4-repeat mean, fall
back to the global best single (reasoning); a fractional variant averaging
over the tied set is reported as sensitivity. Diagnostic only.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC_EXP = ROOT / 'router_v2/experiment_repeat_compatibility_400_fold_local'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
OUT = ROOT / 'router_v2/e2_cross_repeat_stable_oracle_400'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
R = 5
N_BOOT = 10000


def main():
    z = np.load(SRC_EXP / 'PREDICTIONS.npz', allow_pickle=False)
    ids = z['ids'].tolist()
    quality = z['quality']  # (400,4) realized 5-repeat means, integrity-checked in E1
    labels = {r['query_id']: r for r in map(json.loads, LABELS.open())}
    V = np.array([[labels[q]['models'][m]['values'] for m in SLOTS] for q in ids])  # (400,4,5)
    if not np.allclose(V.mean(2), quality, atol=1e-5):
        raise ValueError('Labels/npz quality mismatch')

    hindsight = quality.max(1)
    hindsight_eq = float(hindsight.mean())
    global_best = int(np.bincount(z['choice_BestSingle'], minlength=4).argmax())  # reasoning
    bestsingle_q = quality[np.arange(len(ids)), z['choice_BestSingle']]
    queryonly_q = quality[np.arange(len(ids)), z['choice_QueryOnlyRidge']]
    bestsingle_eq = float(bestsingle_q.mean())
    queryonly_eq = float(queryonly_q.mean())

    stable_q = np.zeros(len(ids))
    fractional_q = np.zeros(len(ids))
    picks = np.zeros((len(ids), R), dtype=int)
    tied_frac = 0.0
    per_query = []
    for i, q in enumerate(ids):
        rotations, frac_rots = [], []
        for r in range(R):
            mask = np.arange(R) != r
            means4 = V[i][:, mask].mean(1)
            best = means4.max()
            cand = np.flatnonzero(means4 >= best - 1e-9)
            tied_frac += len(cand) > 1
            pick = global_best if global_best in cand else int(cand[0])
            picks[i, r] = pick
            rotations.append(V[i, pick, r])
            frac_rots.append(float(V[i, cand, r].mean()))
        stable_q[i] = np.mean(rotations)
        fractional_q[i] = np.mean(frac_rots)
        counts = np.bincount(picks[i], minlength=4)
        per_query.append({'query_id': q, 'rotations': [{'held_out_repeat': r, 'choice': SLOTS[picks[i, r]],
                                                        'holdout_quality': float(V[i, picks[i, r], r])} for r in range(R)],
                          'stable_eq': round(float(stable_q[i]), 4),
                          'hindsight_eq': round(float(hindsight[i]), 4),
                          'winner_consistency': int(counts.max()),
                          'consistent_winner': SLOTS[int(counts.argmax())]})

    stable_eq = float(stable_q.mean())
    fractional_eq = float(fractional_q.mean())
    rng = np.random.default_rng(0)

    def boot_ci(a, b):
        diff = a - b
        idx = rng.integers(0, len(ids), (N_BOOT, len(ids)))
        means = diff[idx].mean(1)
        return [round(float(v) * 100, 2) for v in np.percentile(means, [2.5, 97.5])]

    consistency = [p['winner_consistency'] for p in per_query]
    sel_total = np.bincount(picks.reshape(-1), minlength=4)
    result = {
        'question': 'How much of the hindsight oracle gap is cross-repeat stable per-query model preference?',
        'n': len(ids), 'slots': SLOTS, 'repeats': R, 'bootstrap': N_BOOT,
        'tie_policy': 'fallback to global best single (reasoning); fractional tie-average reported separately',
        'numbers': {
            'best_single_eq': round(bestsingle_eq, 4),
            'query_only_ridge_eq': round(queryonly_eq, 4),
            'hindsight_oracle_eq': round(hindsight_eq, 4),
            'stable_oracle_eq': round(stable_eq, 4),
            'stable_oracle_fractional_eq': round(fractional_eq, 4)},
        'gaps': {
            'hindsight_gap_pp': round((hindsight_eq - bestsingle_eq) * 100, 2),
            'stable_gap_pp': round((stable_eq - bestsingle_eq) * 100, 2),
            'stable_fractional_gap_pp': round((fractional_eq - bestsingle_eq) * 100, 2),
            'stable_over_hindsight_pct': round(100 * (stable_eq - bestsingle_eq) / (hindsight_eq - bestsingle_eq), 1),
            'noise_fraction_pct': round(100 * (1 - (stable_eq - bestsingle_eq) / (hindsight_eq - bestsingle_eq)), 1)},
        'stable_selection_counts_rotations': dict(zip(SLOTS, sel_total.tolist())),
        'tie_incidence_pct': round(100 * tied_frac / (len(ids) * R), 1),
        'winner_consistency': {
            'five_of_five': consistency.count(5), 'four_of_five': consistency.count(4),
            'three_or_less': sum(1 for c in consistency if c <= 3)},
        'paired_bootstrap_ci95_pp': {
            'stable_vs_bestsingle': boot_ci(stable_q, bestsingle_q),
            'stable_vs_queryonly': boot_ci(stable_q, queryonly_q)}}
    result['answers'] = {
        'A_stable_share_of_hindsight_gap': result['gaps']['stable_over_hindsight_pct'],
        'B_dominant_component': 'stable heterogeneity' if result['gaps']['stable_over_hindsight_pct'] >= 50 else 'generation noise',
        'C_worth_finer_representation': bool(result['gaps']['stable_gap_pp'] >= 2.0
                                             and result['paired_bootstrap_ci95_pp']['stable_vs_bestsingle'][0] > 0)}
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'PER_QUERY.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in per_query))
    (OUT / 'RESULTS.json').write_text(json.dumps(result, indent=1) + '\n')
    n = result['numbers']; g = result['gaps']; c = result['paired_bootstrap_ci95_pp']
    lines = ['# E2 cross-repeat stable oracle (utility-400, leave-one-repeat-out, zero generation)', '',
             '| quantity | EQ |', '|---|---|',
             f'| BestSingle | {n["best_single_eq"]:.4f} |',
             f'| QueryOnlyRidge | {n["query_only_ridge_eq"]:.4f} |',
             f'| Hindsight Oracle (5-repeat mean max) | {n["hindsight_oracle_eq"]:.4f} |',
             f'| **CrossRepeatStableOracle** | **{n["stable_oracle_eq"]:.4f}** |',
             f'| StableOracle (fractional ties) | {n["stable_oracle_fractional_eq"]:.4f} |', '',
             f'Hindsight gap {g["hindsight_gap_pp"]:.2f}pp; stable gap {g["stable_gap_pp"]:.2f}pp '
             f'({g["stable_over_hindsight_pct"]:.0f}% of hindsight; {g["noise_fraction_pct"]:.0f}% is generation noise).', '',
             f'Stable vs BestSingle: {100 * (stable_eq - bestsingle_eq):+.2f}pp, CI95 {c["stable_vs_bestsingle"]}',
             f'Stable vs QueryOnlyRidge: {100 * (stable_eq - queryonly_eq):+.2f}pp, CI95 {c["stable_vs_queryonly"]}', '',
             f'Winner consistency: 5/5 on {result["winner_consistency"]["five_of_five"]} queries, '
             f'4/5 on {result["winner_consistency"]["four_of_five"]}, <=3/5 on {result["winner_consistency"]["three_or_less"]}. '
             f'Ties at the top 4-repeat mean occurred in {result["tie_incidence_pct"]:.0f}% of rotations.', '',
             f'Answers: A={result["answers"]["A_stable_share_of_hindsight_gap"]}% stable; '
             f'B={result["answers"]["B_dominant_component"]}; C={result["answers"]["C_worth_finer_representation"]}', '',
             'Selection never sees its judged repeat; bootstrap unit is the query. Development panel; no population claim.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'numbers': result['numbers'], 'gaps': result['gaps'], 'answers': result['answers']}, indent=1))


if __name__ == '__main__':
    main()
