"""Exploratory original-train-only objective quality diagnosis; never formal evaluation."""
import argparse
import json
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedKFold
from .data import load_cohort, read_rows, sha
from .core import SLOTS, paired_ci


def run(args):
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    cohort, split = load_cohort(args.cohort)
    records = read_rows(args.matrix)
    ids = [r['query_id'] for r in records]
    if len(ids) != len(set(ids)) or set(ids) != set(split['train']):
        raise ValueError('Input must contain exactly original train IDs')
    selected, excluded = [], {}
    for row in records:
        qid = row['query_id']
        if row['query'] != cohort[qid]['query'] or row['dataset'] != cohort[qid]['dataset']:
            raise ValueError('Source mismatch')
        if row['dataset'] not in {'gsm8k', 'mmlupro', 'humaneval', 'mbpp'}:
            excluded[row['dataset']] = excluded.get(row['dataset'], 0) + 1
            continue
        slots = {r['slot']: r for r in row['responses']}
        if len(row['responses']) != 4 or set(slots) != set(SLOTS):
            raise ValueError('Incomplete slots')
        labels = [slots[s]['quality']['final'] for s in SLOTS]
        if any(v not in (0, 1) for v in labels):
            raise ValueError('Objective labels must be complete binary outcomes')
        if any(slots[s]['quality'].get('quality_source') not in ('auto', 'code_stdlib', 'code_numpy') for s in SLOTS):
            raise ValueError('Unexpected objective scorer source')
        selected.append((qid, row['dataset'], labels))
    with np.load(args.embeddings, allow_pickle=False) as saved:
        if saved['query_sha256'].item() != sha(Path(args.cohort)/'queries.jsonl'):
            raise ValueError('Embedding query hash mismatch')
        all_ids = saved['ids'].tolist()
        if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(cohort):
            raise ValueError('Embedding IDs mismatch')
        index = {qid: i for i, qid in enumerate(all_ids)}
        x = saved['vectors'][[index[r[0]] for r in selected]].astype('float32')
        if not np.isfinite(x).all():
            raise ValueError('Invalid embeddings')
    y = np.array([r[2] for r in selected], dtype=float)
    datasets = np.array([r[1] for r in selected])
    protocol = dict(role='exploratory_train_only_objective_signal', seed=42, folds=3,
        ridge_alpha=20., selection='No hyperparameter search; fold-training means only for baselines',
        input_sha256={str(Path(p).resolve()): sha(p) for p in (args.matrix, args.embeddings,
            Path(args.cohort)/'queries.jsonl', Path(args.cohort)/'split.json')},
        source_sha256=sha(__file__), excluded=excluded,
        limits=['Original train only; not independent confirmation',
                'Binary scored subset excludes open-ended tasks; not full-cohort performance',
                'Dataset ID baseline uses privileged source metadata and is diagnostic only',
                'Query bootstrap conditions on OOF fits; not retraining uncertainty',
                'No cost/latency claims or certification of labels',
                'Single fixed split seed; no formal gate was certified'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'PROTOCOL.json').write_text(json.dumps(protocol, indent=2))
    decisions = {name: np.zeros(len(y), dtype=int) for name in ('Ridge', 'BestSingle', 'DatasetBest')}
    predictions = np.zeros_like(y)
    folds = np.zeros(len(y), dtype=int)
    for fold, (tr, va) in enumerate(StratifiedKFold(3, shuffle=True, random_state=42).split(x, datasets)):
        model = Ridge(alpha=20.).fit(x[tr], y[tr])
        predictions[va] = model.predict(x[va]).clip(0, 1)
        decisions['Ridge'][va] = predictions[va].argmax(1)
        decisions['BestSingle'][va] = y[tr].mean(0).argmax()
        for dataset in set(datasets):
            local_train = tr[datasets[tr] == dataset]
            local_val = va[datasets[va] == dataset]
            decisions['DatasetBest'][local_val] = y[local_train].mean(0).argmax()
        folds[va] = fold
    actual = {name: y[np.arange(len(y)), choice] for name, choice in decisions.items()}
    oracle = y.max(1)
    reports = {}
    for scope in ['all'] + sorted(set(datasets)):
        mask = np.ones(len(y), dtype=bool) if scope == 'all' else datasets == scope
        baseline = actual['BestSingle'][mask]
        gap = float((oracle[mask] - baseline).mean())
        methods = {}
        for name, values in actual.items():
            gain = values[mask] - baseline
            methods[name] = dict(quality=float(values[mask].mean()), gain_vs_fixed=float(gain.mean()),
                paired_ci95=paired_ci(gain), gap_recovery=float(gain.mean()/gap) if gap > 1e-12 else None,
                routing_fraction=(np.bincount(decisions[name][mask], minlength=4)/mask.sum()).tolist())
        diff = actual['Ridge'][mask] - actual['DatasetBest'][mask]
        reports[scope] = dict(n=int(mask.sum()), empirical_oracle=float(oracle[mask].mean()),
            empirical_oracle_gap=gap, methods=methods,
            ridge_minus_dataset_best=dict(mean=float(diff.mean()), paired_ci95=paired_ci(diff)))
    np.savez_compressed(output/'OOF.npz', ids=np.array([r[0] for r in selected]), folds=folds,
                        quality=y, predicted_quality=predictions, **decisions)
    result = dict(role=protocol['role'], results=reports, test_labels_loaded=False,
        validation_labels_loaded=False, formal_training_ready=False, excluded=excluded,
        fixed_model_means=dict(zip(SLOTS, y.mean(0).tolist())),
        files={name: sha(output/name) for name in ('PROTOCOL.json', 'OOF.npz')})
    (output/'RESULTS.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(reports, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('matrix', 'cohort', 'embeddings', 'output'):
        parser.add_argument('--'+name, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
