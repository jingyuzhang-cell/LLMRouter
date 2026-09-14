"""E1: capability upper-bound router on the frozen utility-400 folds.

Zero generation cost. Question: if the router is given the TRUE MMLU-Pro
subject of each query, plus per-subject model capability estimated on
development folds only, does it beat QueryOnly Ridge / BestSingle on the same
outer folds? If not, subject-level capability cannot explain the remaining gap
and the capability-feature line stops here.

Subjects are recovered from the frozen cohort prompts (the standard MMLU-Pro
template states 'Answer the following <subject> question.'); no external data
is used. Baseline per-query choices are reused from the existing fold-local
experiment without retraining.
"""
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from router_v2.data import load_cohort  # noqa: E402

SRC_EXP = ROOT / 'router_v2/experiment_repeat_compatibility_400_fold_local'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
COHORT = ROOT / 'data/cohort_full_v2'
OUT = ROOT / 'router_v2/e1_capability_upper_bound_400'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
PRIOR_STRENGTH = 3  # shrinkage pseudo-count of global dev mean into small subjects
SUBJECT_RE = re.compile(r"Answer the following ([a-z ]+?) question")


def subjects_of(ids):
    cohort, _ = load_cohort(COHORT)
    out = {}
    for q in ids:
        m = SUBJECT_RE.search(cohort[q]['query'])
        if not m:
            raise ValueError(f'No subject in prompt for {q}')
        out[q] = m.group(1).strip()
    return out


def main():
    folds = json.loads((SRC_EXP / 'FOLDS.json').read_text())
    z = np.load(SRC_EXP / 'PREDICTIONS.npz', allow_pickle=False)
    ids = z['ids'].tolist()
    quality = z['quality']  # (400,4) repeat-mean realized quality
    index = {q: i for i, q in enumerate(ids)}
    labels = {r['query_id']: r for r in map(json.loads, LABELS.open())}
    subject = subjects_of(ids)

    def lookup_router(dev_ids, test_ids, shrink):
        """argmax_m C_hat[m, subject(q)] with C from dev only."""
        dev_global = quality[[index[q] for q in dev_ids]].mean(0)
        C = {m: {} for m in SLOTS}
        counts = {}
        for k in {subject[q] for q in test_ids} | {subject[q] for q in dev_ids}:
            sub = [index[q] for q in dev_ids if subject[q] == k]
            counts[k] = len(sub)
            if sub:
                block = quality[sub]
                for j, m in enumerate(SLOTS):
                    C[m][k] = block[:, j].mean()
        choice = []
        for q in test_ids:
            k = subject[q]
            n = counts[k]
            scores = [((C[m].get(k, dev_global[j]) * n + dev_global[j] * PRIOR_STRENGTH) / (n + PRIOR_STRENGTH)
                       if shrink and n else C[m].get(k, dev_global[j]))
                      for j, m in enumerate(SLOTS)]
            choice.append(int(np.argmax(scores)))
        return choice, C, counts, dev_global

    profiles, fold_rows = {}, []
    pooled = {}  # method -> per-query choice over all 400 in fold order
    for f in folds:
        dev_ids, test_ids = f['development_ids'], f['test_ids']
        for name, shrink in (('CapabilityLookupPure', False), ('CapabilityLookupShrunk', True)):
            choice, C, counts, dev_global = lookup_router(dev_ids, test_ids, shrink)
            pooled.setdefault(name, {})[f['fold']] = dict(zip(test_ids, choice))
            if shrink:
                # Full capability profile for downstream E2 use (dev-only).
                stability, winrate = {}, {}
                for k in counts:
                    sub = [q for q in dev_ids if subject[q] == k]
                    if not sub:
                        continue
                    V = np.array([[labels[q]['models'][m]['values'] for m in SLOTS] for q in sub])  # (n,4,5)
                    stability[k] = {m: round(float(V[:, j].var(axis=1).mean()), 4) for j, m in enumerate(SLOTS)}
                    means = {m: np.array([labels[q]['models'][m]['mean'] for q in sub]) for m in SLOTS}
                    winrate[k] = {m: round(float((means[m] > means['reasoning']).mean()), 4) for m in SLOTS}
                profiles[f['fold']] = {
                    'dev_n': len(dev_ids), 'subject_counts': counts,
                    'subject_mean_quality': {k: {m: round(float(C[m].get(k, float('nan'))), 4) for m in SLOTS} for k in counts},
                    'subject_repeat_variance': stability, 'subject_winrate_vs_reasoning': winrate,
                    'global_dev_mean': {m: round(float(dev_global[j]), 4) for j, m in enumerate(SLOTS)}}
        for name in ('BestSingle', 'QueryOnlyRidge', 'PairwiseRidge', 'TwoStageResidualGate',
                     'RepeatPairwiseMA_seed42', 'RepeatPairwiseMA_seed43', 'RepeatPairwiseMA_seed44'):
            pooled.setdefault(name, {})[f['fold']] = dict(zip(test_ids, z[f'choice_{name}'][[index[q] for q in test_ids]].tolist()))

    def evaluate(name):
        if name == 'RepeatPairwiseMA_3seed':
            seed_choices = np.stack([np.array([pooled[s][z['folds'][i]][q] for i, q in enumerate(ids)])
                                     for s in ('RepeatPairwiseMA_seed42', 'RepeatPairwiseMA_seed43', 'RepeatPairwiseMA_seed44')])
            choice = np.array([np.bincount(seed_choices[:, i], minlength=4).argmax() for i in range(len(ids))])
        else:
            choice = np.array([pooled[name][z['folds'][i]][q] for i, q in enumerate(ids)])
        chosen_q = quality[np.arange(len(ids)), choice]
        eq = float(chosen_q.mean())
        per_fold = [float(chosen_q[z['folds'] == f].mean()) for f in range(3)]
        return {'choice': choice, 'expected_quality': eq, 'per_fold_eq': [round(x, 4) for x in per_fold]}

    oracle = quality.max(1)
    oracle_eq = float(oracle.mean())
    methods = ['BestSingle', 'QueryOnlyRidge', 'CapabilityLookupPure', 'CapabilityLookupShrunk',
               'PairwiseRidge', 'TwoStageResidualGate', 'RepeatPairwiseMA_3seed']
    ev = {m: evaluate(m) for m in methods}
    base_eq = ev['BestSingle']['expected_quality']
    rng = np.random.default_rng(0)

    def report(m):
        e = ev[m]
        sel = np.bincount(e['choice'], minlength=4).tolist()
        r = {'expected_quality': round(e['expected_quality'], 4),
             'gap_recovery_pct': round(100 * (e['expected_quality'] - base_eq) / (oracle_eq - base_eq), 2),
             'regret_pp': round((oracle_eq - e['expected_quality']) * 100, 2),
             'per_fold_eq': e['per_fold_eq'], 'selection': dict(zip(SLOTS, sel))}
        if m.startswith('CapabilityLookup'):
            ref = ev['QueryOnlyRidge']['choice']
            diff = quality[np.arange(len(ids)), e['choice']] - quality[np.arange(len(ids)), ref]
            changed = diff[e['choice'] != ref]
            boot = [float(np.random.choice(diff, len(diff), replace=True).mean()) for _ in range(10000)] if len(diff) else [0.0]
            r['vs_queryonly'] = {'mean_diff_pp': round(float(diff.mean()) * 100, 2),
                                 'switched_n': int((e['choice'] != ref).sum()),
                                 'rescued': int((changed > 0).sum()), 'harmed': int((changed < 0).sum()),
                                 'switch_ci95_pp': [round(float(v) * 100, 2) for v in np.percentile(boot, [2.5, 97.5])],
                                 'pooled_diff_ci95_pp': [round(float(v) * 100, 2) for v in np.percentile(
                                     [float((quality[np.arange(len(ids)), e['choice']] - quality[np.arange(len(ids)), ref])[rng.integers(0, len(ids), len(ids))].mean()) for _ in range(10000)], [2.5, 97.5])]}
        return r

    table = {m: report(m) for m in methods}
    shrunk, qor = table['CapabilityLookupShrunk'], table['QueryOnlyRidge']
    verdict = {'beats_queryonly_point': shrunk['expected_quality'] > qor['expected_quality'],
               'beats_queryonly_ci': shrunk['vs_queryonly']['pooled_diff_ci95_pp'][0] > 0,
               'beats_bestsingle_point': shrunk['expected_quality'] > base_eq}
    result = {'question': 'Does true-subject capability lookup beat QueryOnly/BestSingle on frozen utility-400 folds?',
              'folds_source': str(SRC_EXP), 'n': len(ids), 'slots': SLOTS, 'oracle_eq': round(oracle_eq, 4),
              'bestsingle_eq': round(base_eq, 4), 'prior_strength': PRIOR_STRENGTH,
              'verdict': verdict, 'methods': table}
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'CAPABILITY_PROFILES.json').write_text(json.dumps(profiles, indent=1) + '\n')
    (OUT / 'RESULTS.json').write_text(json.dumps(result, indent=1) + '\n')
    lines = ['# E1 capability upper bound (utility-400 frozen folds, zero generation)', '',
             f'Oracle EQ {oracle_eq:.4f}; BestSingle EQ {base_eq:.4f}; gap {100 * (oracle_eq - base_eq):.2f}pp', '',
             '| method | EQ | gap recovery % | regret pp | selection |', '|---|---|---|---|---|']
    for m in methods:
        t = table[m]
        lines.append(f'| {m} | {t["expected_quality"]:.4f} | {t["gap_recovery_pct"]:.1f} | {t["regret_pp"]:.2f} | '
                     + ', '.join(f'{s}:{v}' for s, v in t['selection'].items() if v))
    lines += ['', 'CapabilityLookupShrunk vs QueryOnlyRidge: '
              f'{shrunk["vs_queryonly"]["mean_diff_pp"]:+.2f}pp pooled '
              f'(switched {shrunk["vs_queryonly"]["switched_n"]}, rescued {shrunk["vs_queryonly"]["rescued"]}, '
              f'harmed {shrunk["vs_queryonly"]["harmed"]}, CI95 {shrunk["vs_queryonly"]["pooled_diff_ci95_pp"]})', '',
              f'Verdict: {verdict}', '',
              'Development panel (opportunity-enriched); no population-level MMLU-Pro claim. Subjects from frozen prompts; capability estimated on development folds only.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'verdict': verdict, 'table': {m: {'eq': table[m]['expected_quality'], 'recovery': table[m]['gap_recovery_pct']} for m in methods}}, indent=1))


if __name__ == '__main__':
    main()
