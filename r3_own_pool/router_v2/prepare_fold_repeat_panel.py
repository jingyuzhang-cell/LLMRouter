"""Select repeat queries separately inside each existing outer training fold."""
import argparse
import json
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedGroupKFold
from .data import load_cohort, sha
from .diagnose_rank_signal import load_inputs

ROOT = Path(__file__).resolve().parents[1]


def select_panel(x, y, datasets, groups, ids, seed=42):
    pred = np.empty_like(y); fallback = np.empty(len(y), dtype=int)
    for tr, va in StratifiedGroupKFold(3, shuffle=True, random_state=seed).split(x, datasets, groups):
        pred[va] = Ridge(alpha=20.).fit(x[tr], y[tr]).predict(x[va]).clip(0, 1)
        by = {d: y[tr][datasets[tr] == d].mean(0).argmax() for d in set(datasets[tr])}
        fallback[va] = [by[d] for d in datasets[va]]
    margin = y[:, 3] - y[:, 2]; pm = np.abs(pred[:, 3] - pred[:, 2])
    regret = y.max(1) - y[np.arange(len(y)), fallback]
    selected = {}
    def add(indices, tag):
        for i in indices: selected.setdefault(str(ids[i]), []).append(tag)
    for sign, tag in ((1, 'reasoning_strict'), (-1, 'large_strict')):
        ix = np.flatnonzero(sign * margin > 0)
        add(ix[np.argsort(pm[ix], kind='stable')][:8], tag)
    add(np.argsort(pm, kind='stable')[:12], 'predicted_near_tie')
    ix = np.flatnonzero((regret > 0) & (y[:, 2:4].max(1) == y.max(1)))
    add(ix[np.lexsort((pm[ix], -regret[ix]))][:12], 'high_regret')
    rng = np.random.default_rng(seed)
    for d in sorted(set(datasets)):
        add(rng.permutation(np.flatnonzero(datasets == d))[:3], 'random_by_dataset')
    return selected


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True); ap.add_argument('--groups', required=True); ap.add_argument('--output', required=True)
    a = ap.parse_args(); source = Path(a.source); out = Path(a.output)
    frozen, x, ds = load_inputs(source)
    cohort, split = load_cohort(ROOT / 'data/cohort_full_v2')
    grouping = json.loads(Path(a.groups).read_text())
    if grouping['queries_sha256'] != sha(ROOT / 'data/cohort_full_v2/queries.jsonl'): raise ValueError('Group source changed')
    ids, folds, y = frozen['ids'], frozen['folds'], frozen['quality']
    groups = np.array([grouping['groups'][q] for q in ids]); selections = {}; union = {}
    for fold in sorted(np.unique(folds)):
        tr = np.flatnonzero(folds != fold); va = np.flatnonzero(folds == fold)
        if set(groups[tr]) & set(groups[va]): raise ValueError('Outer group overlap')
        selected = select_panel(x[tr], y[tr], ds[tr], groups[tr], ids[tr])
        selections[str(fold)] = selected
        for q, tags in selected.items(): union.setdefault(q, set()).update(tags)
        print('fold', int(fold), 'selected', len(selected), flush=True)
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for i, q in enumerate(sorted(union)):
        row = {k: cohort[q][k] for k in ('query_id', 'query', 'dataset', 'task_type')}
        rows.append(dict(**row, panel_index=i, target_slots=['large', 'reasoning'], planned_repeats_per_slot=5,
                         strata=sorted(union[q]), training_folds=[f for f, s in selections.items() if q in s]))
    with (out/'PANEL.jsonl').open('x') as f:
        for row in rows: f.write(json.dumps(row, ensure_ascii=False)+'\n')
    (out/'FOLD_SELECTION.json').write_text(json.dumps(selections, indent=2)+'\n')
    protocol = dict(role='outer_train_only_repeat_selection', n_panel=len(rows), repeats=5, temperature=.7, top_p=1.,
        target='Stochastic-training-label transfer to original temperature-0 outcomes; not a same-distribution noise estimate',
        stable_threshold=.8, source=str(source.resolve()),
        source_files={n:sha(source/n) for n in ['PROTOCOL.json','OOF.npz','RESULTS.json']},
        groups_sha256=sha(a.groups), selector_sha256=sha(__file__),
        selection='Per outer train fold: inner-group OOF Ridge; 8 strict per direction, 12 near ties, 12 high regret, 3 random per dataset; overlaps deduplicated',
        evaluation='Only apply each selection to its corresponding outer training fold; query repeats from the held fold must never be used to train that fold',
        limits=['Original-train development only, no independent test claim', '5x5 comparisons are dependent; empirical .8 is not 80% statistical confidence'],
        files={n:sha(out/n) for n in ['PANEL.jsonl','FOLD_SELECTION.json']})
    (out/'MANIFEST.json').write_text(json.dumps(protocol, indent=2)+'\n')
    print(json.dumps({'n_panel':len(rows), 'by_fold':{f:len(v) for f,v in selections.items()}}, indent=2))

if __name__ == '__main__': main()
