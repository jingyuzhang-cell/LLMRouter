"""Fixed-budget regression versus regression+ranking on an existing train-only OOF split."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from .data import load_cohort, sha, read_rows
from .integrity import require_valid_quality
from .core import paired_ci
from .experiment import Router


def load_inputs(source):
    source = Path(source)
    result = json.loads((source/'RESULTS.json').read_text())
    for name, digest in result['files'].items():
        if sha(source/name) != digest:
            raise ValueError('Source artifact changed')
    protocol = json.loads((source/'PROTOCOL.json').read_text())
    if protocol['role'] != 'exploratory_train_only_objective_signal':
        raise ValueError('Only original-train objective diagnosis accepted')
    inputs = protocol['input_sha256']
    for path, digest in inputs.items():
        if sha(path) != digest:
            raise ValueError('Source input changed: ' + path)
    cohort_path = next(Path(p).parent for p in inputs if Path(p).name == 'queries.jsonl')
    embedding_path = next(p for p in inputs if p.endswith('.npz'))
    cohort, split = load_cohort(cohort_path)
    with np.load(source/'OOF.npz', allow_pickle=False) as data:
        frozen = {k: data[k] for k in data.files}
    ids = frozen['ids'].tolist()
    if len(ids) != len(set(ids)) or not set(ids) <= set(split['train']):
        raise ValueError('OOF contains non-train or duplicate queries')
    with np.load(embedding_path, allow_pickle=False) as data:
        index = {qid: i for i, qid in enumerate(data['ids'].tolist())}
        x = data['vectors'][[index[qid] for qid in ids]].astype('float32')
    matrix_paths = [p for p in inputs if p.endswith('.jsonl') and Path(p).name != 'queries.jsonl']
    for path in matrix_paths:
        for row in read_rows(path):
            if row['query_id'] in set(ids):
                for response in row['responses']:
                    require_valid_quality(response)
    y = frozen['quality']
    if not np.isfinite(x).all() or y.shape != (len(ids), 4) or not np.isin(y, [0, 1]).all():
        raise ValueError('Invalid features or quality')
    if set(frozen['folds'].tolist()) != {0, 1, 2}:
        raise ValueError('Expected same three OOF folds')
    return frozen, x, np.array([cohort[qid]['dataset'] for qid in ids])


def train_pair(x_train, y_train, x_eval, seed, epochs):
    predictions = {}
    for alpha in (0., .5):
        model = Router(q_dim=x_train.shape[1], seed=seed, alpha=alpha)
        model.fit(x_train, y_train, seed=seed, epochs=epochs)
        predictions[str(alpha)] = model.predict_all(x_eval)
    return predictions


def run(args):
    if args.epochs < 1 or len(args.seeds) != len(set(args.seeds)) or len(args.seeds) < 2:
        raise ValueError('Positive epochs and at least two distinct seeds required')
    torch.set_num_threads(4)
    source, out = Path(args.source).resolve(), Path(args.output).resolve()
    frozen, x, datasets = load_inputs(source)
    y, folds = frozen['quality'], frozen['folds']
    out.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path(__file__).with_name('experiment.py'), Path(__file__).with_name('core.py'), Path(__file__).parents[1]/'train_router.py']
    protocol = dict(role='exploratory_train_only_rank_ablation', source=str(source),
        source_files={name:sha(source/name) for name in ('RESULTS.json', 'PROTOCOL.json', 'OOF.npz')},
        implementation={str(p):sha(p) for p in code}, seeds=args.seeds, epochs=args.epochs,
        alphas=[0., .5], architecture='Same Hybrid model-conditioned network, optimizer, initialization and minibatch order',
        primary_comparison='alpha .5 minus alpha 0; both compared with frozen DatasetBest and Ridge',
        selection='No hyperparameter, seed or epoch selection from OOF outcomes',
        limits=['Training-only development experiment following Ridge diagnosis; not independent confirmation',
                'Objective scored subset; no open-ended quality or cost/latency claims',
                'Same queries and folds across seeds; sample count is not multiplied by seeds',
                'Paired bootstrap conditional on fitted OOF models, not retraining uncertainty',
                'Fixed 60-epoch budget by default, not an optimized architecture comparison'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol, indent=2))
    predictions = {}
    for seed in args.seeds:
        for alpha in (0., .5):
            predictions[f'seed{seed}_alpha{alpha}'] = np.zeros_like(y)
        for fold in (0, 1, 2):
            started = time.monotonic()
            tr, va = folds != fold, folds == fold
            pair = train_pair(x[tr], y[tr], x[va], seed, args.epochs)
            for alpha, pred in pair.items():
                predictions[f'seed{seed}_alpha{alpha}'][va] = pred
            print(f'seed={seed} fold={fold} both objectives complete; seconds={time.monotonic()-started:.1f}', flush=True)
        np.savez_compressed(out/f'SEED_{seed}.npz', **{k:v for k,v in predictions.items() if k.startswith(f'seed{seed}_')})
    # No OOF evaluation until all declared fits finish.
    for path, digest in protocol['implementation'].items():
        if sha(path) != digest:
            raise ValueError('Implementation changed during experiment; retain files for audit')
    index = np.arange(len(y))
    actual = {key:y[index, pred.argmax(1)] for key,pred in predictions.items()}
    baselines = {name:y[index,frozen[name]] for name in ('Ridge', 'BestSingle', 'DatasetBest')}
    scopes = {}
    for scope in ['all'] + sorted(set(datasets)):
        mask = np.ones(len(y), dtype=bool) if scope == 'all' else datasets == scope
        per_seed = {}
        for seed in args.seeds:
            pair = {}
            for alpha in (0., .5):
                values = actual[f'seed{seed}_alpha{alpha}'][mask]
                pair[str(alpha)] = dict(quality=float(values.mean()),
                    vs_baselines={name:dict(gain=float((values-base[mask]).mean()),
                        paired_ci95=paired_ci(values-base[mask])) for name,base in baselines.items()})
            diff = actual[f'seed{seed}_alpha0.5'][mask]-actual[f'seed{seed}_alpha0.0'][mask]
            pair['rank_minus_regression'] = dict(gain=float(diff.mean()), paired_ci95=paired_ci(diff))
            per_seed[str(seed)] = pair
        aggregate = {}
        for alpha in (0., .5):
            values = [per_seed[str(seed)][str(alpha)]['quality'] for seed in args.seeds]
            aggregate[str(alpha)] = dict(mean_quality=float(np.mean(values)), std_across_seeds=float(np.std(values, ddof=1)))
        scopes[scope] = dict(n=int(mask.sum()), baselines={k:float(v[mask].mean()) for k,v in baselines.items()}, per_seed=per_seed, aggregate=aggregate)
    result = dict(role=protocol['role'], results=scopes, test_labels_loaded=False, validation_labels_loaded=False,
                  source_sha256=sha(source/'OOF.npz'), files={p.name:sha(p) for p in out.glob('*.npz')})
    (out/'RESULTS.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(scopes['all'], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[42,43,44])
    parser.add_argument('--epochs', type=int, default=60)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
