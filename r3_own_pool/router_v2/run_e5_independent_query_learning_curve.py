"""E5: independent-query learning curves using the unmodified frozen MA trainer."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import fcntl
import hashlib
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e5_independent_query_learning_curve'
SOURCE = ROOT / 'router_v2/experiment_repeat_compatibility_400_fold_local'
PANEL = ROOT / 'router_v2/mmlu_utility_panel_400'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
E4 = ROOT / 'router_v2/e4_representation_20260914'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
METHODS = ['BestSingle', 'QueryOnlyRidge', 'RepeatPairwiseMA']
REPRESENTATIONS = ['Original', 'Content_secondary']
NS = ['40', '80', '120', 'Full']
SUBSEEDS = list(range(2026091400, 2026091410))
MASEEDS = [42, 43, 44]
TRAINER = Path(__file__).with_name('train_repeat_pairwise_compatibility_115.py')


def write_json(path, row):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write_json(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def stratified_order(development, subjects, seed, fold):
    """Nested proportional allocation; no labels or embeddings are consulted."""
    development = np.asarray(development, dtype=int)
    rng = np.random.default_rng(np.random.SeedSequence([seed, fold, 5]))
    names = sorted(set(subjects[development]))
    queues = {s: rng.permutation(development[subjects[development] == s]).tolist() for s in names}
    counts = {s: len(queues[s]) for s in names}
    used = {s: 0 for s in names}
    order = []
    for step in range(len(development)):
        available = [s for s in names if used[s] < counts[s]]
        # Largest proportional deficit, with deterministic lexical tie-breaking.
        s = max(available, key=lambda s: ((step + 1) * counts[s] / len(development) - used[s], -names.index(s)))
        order.append(queues[s][used[s]])
        used[s] += 1
    return np.asarray(order, dtype=int)


def load_inputs():
    from .diagnose_rank_signal import load_inputs as load_original
    from .train_repeat_pairwise_compatibility_115 import subject
    manifest = json.loads((PANEL / 'MANIFEST.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(PANEL / name) != digest:
            raise ValueError('Frozen panel changed: ' + name)
    for name, digest in manifest['source_files'].items():
        if sha(Path(manifest['source']) / name) != digest:
            raise ValueError('Frozen source changed: ' + name)
    source_protocol = json.loads((SOURCE / 'PROTOCOL.json').read_text())
    if sha(Path(__file__).with_name('train_repeat_compatibility_400_fold_local.py')) != source_protocol['source_sha256']['trainer']:
        raise ValueError('Frozen wrapper changed')
    label_status = json.loads((LABELS.parent / 'STATUS.json').read_text())
    if sha(LABELS) != label_status['labels_sha256'] or sha(LABELS) != source_protocol['source_sha256']['labels']:
        raise ValueError('Corrected labels changed')
    if sha(manifest['groups']) != manifest['groups_sha256']:
        raise ValueError('Groups changed')
    features, original, _ = load_original(manifest['source'])
    z = np.load(SOURCE / 'PREDICTIONS.npz', allow_pickle=False)
    ids = z['ids'].tolist(); index = {q: i for i, q in enumerate(ids)}
    if len(ids) != 400 or len(index) != 400:
        raise ValueError('400 unique queries required')
    labels = {r['query_id']: r for r in map(json.loads, LABELS.open())}
    values = np.array([[labels[q]['models'][s]['values'] for s in SLOTS] for q in ids])
    y = np.array([[labels[q]['models'][s]['mean'] for s in SLOTS] for q in ids], dtype='float32')
    if values.shape != (400, 4, 5) or not np.isin(values, [0, 1]).all():
        raise ValueError('Five complete binary repeats required')
    if not np.allclose(values.mean(2), y) or not np.array_equal(y, z['quality']):
        raise ValueError('Mean-label mismatch')
    orig_index = {q: i for i, q in enumerate(features['ids'])}
    x = original[[orig_index[q] for q in ids]].astype('float32')
    em = json.loads((E4 / 'EMBEDDING_MANIFEST.json').read_text())
    if sha(E4 / 'EMBEDDINGS.npz') != em['sha256']:
        raise ValueError('Secondary embeddings changed')
    content = np.load(E4 / 'EMBEDDINGS.npz', allow_pickle=False)
    if content['ids'].tolist() != ids:
        raise ValueError('Secondary ID mismatch')
    xs = content['Content'].astype('float32')
    panel = {r['query_id']: r for r in map(json.loads, (PANEL / 'PANEL.jsonl').open())}
    subjects = np.array([subject(panel[q]['query']) for q in ids])
    if 'unknown' in subjects:
        raise ValueError('Unparsed subject')
    group_map = json.loads(Path(manifest['groups']).read_text())['groups']
    groups = np.array([group_map[q] for q in ids])
    if len(set(groups)) != 400:
        raise ValueError('Query-level bootstrap requires the expected 400 distinct prompt groups')
    folds = json.loads((SOURCE / 'FOLDS.json').read_text())
    allow = json.loads((PANEL / 'FOLD_SELECTION.json').read_text())
    coverage = np.zeros(400, int)
    for f in folds:
        dev = [index[q] for q in f['development_ids']]
        test = [index[q] for q in f['test_ids']]
        if set(f['development_ids']) != set(allow[str(f['fold'])]) & set(ids):
            raise ValueError('Development allowlist mismatch')
        if set(groups[dev]) & set(groups[test]) or not np.all(z['folds'][test] == f['fold']):
            raise ValueError('Outer fold leakage')
        coverage[test] += 1
    if not np.all(coverage == 1) or not np.isfinite(x).all() or not np.isfinite(xs).all():
        raise ValueError('Invalid feature/coverage')
    return dict(ids=ids, x=x, content=xs, y=y, values=values, subjects=subjects,
                groups=groups, folds=folds, index=index, z=z, manifest=manifest)


def prepare():
    from .train_repeat_pairwise_compatibility_115 import inner_split
    if OUT.exists():
        raise FileExistsError('E5 output already exists')
    data = load_inputs()
    OUT.mkdir()
    ids, index, subjects = data['ids'], data['index'], data['subjects']
    samples = []
    for fold in data['folds']:
        dev = np.array([index[q] for q in fold['development_ids']])
        for seed in SUBSEEDS:
            ordered = stratified_order(dev, subjects, seed, fold['fold'])
            previous = set()
            for n in NS:
                selected = np.sort(ordered[:int(n)] if n != 'Full' else dev)
                if len(selected) != (int(n) if n != 'Full' else len(dev)) or not previous <= set(selected):
                    raise ValueError('Non-nested/incorrect sample')
                previous = set(selected)
                train, validation = inner_split(selected, subjects, fold['fold'])
                if not len(train) or not len(validation) or set(train) & set(validation):
                    raise ValueError('Empty/overlapping inner split')
                if set(train) | set(validation) != set(selected):
                    raise ValueError('Inner split missing query')
                if n == 'Full' and ([ids[i] for i in train] != fold['inner_train_ids'] or [ids[i] for i in validation] != fold['inner_validation_ids']):
                    raise ValueError('Full inner split differs from frozen method')
                sample_key = hashlib.sha256(json.dumps(selected.tolist()).encode()).hexdigest()[:16]
                samples.append(dict(fold=fold['fold'], n=n, actual_n=len(selected), subsampling_seed=seed,
                    development_ids=[ids[i] for i in selected], inner_train_ids=[ids[i] for i in train],
                    inner_validation_ids=[ids[i] for i in validation], test_ids=fold['test_ids'],
                    subject_counts={s: int((subjects[selected] == s).sum()) for s in sorted(set(subjects[dev]))},
                    sample_key=sample_key))
    (OUT / 'SAMPLES.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in samples))
    paths = [Path(__file__), TRAINER, Path(__file__).with_name('summarize_e5_independent_query_learning_curve.py'),
             Path(__file__).with_name('diagnose_rank_signal.py'), Path(__file__).with_name('data.py'),
             Path(__file__).with_name('train_repeat_compatibility_400_fold_local.py'),
             SOURCE / 'PROTOCOL.json', SOURCE / 'FOLDS.json', SOURCE / 'PREDICTIONS.npz',
             PANEL / 'PANEL.jsonl', PANEL / 'MANIFEST.json', PANEL / 'FOLD_SELECTION.json',
             LABELS, E4 / 'EMBEDDINGS.npz', E4 / 'EMBEDDING_MANIFEST.json',
             OUT / 'SAMPLES.jsonl', Path(data['manifest']['groups'])]
    original_protocol = json.loads((Path(data['manifest']['source']) / 'PROTOCOL.json').read_text())
    paths.extend(Path(p) for p in original_protocol['input_sha256'])
    paths.extend(SOURCE.glob('model_fold*_seed*.pt'))
    protocol = dict(
        experiment='E5 Independent-Query Learning Curve', role='existing opportunity-enriched development panel; not independent confirmation',
        methods=METHODS, representations=dict(primary='Original frozen original-prompt GTE', secondary='Content_secondary E4 template-removed GTE; never used for primary verdict'),
        slots=SLOTS, labels='All five corrected repeat means retained for every selected query and model; no repeat splitting/filtering',
        N=NS, actual_full_n_by_fold={str(f['fold']): len(f['development_ids']) for f in data['folds']},
        subsampling_seeds=SUBSEEDS, optimization_seeds=MASEEDS,
        sampling='Nested within-subject permutations, largest proportional deficit allocation, fold-specific RNG; selected global indices sorted before fitting; no labels consulted',
        MA='Import frozen fit() unchanged: model embedding8, shared64-ReLU-1; soft pairwise BCE; AdamW lr.001 weight_decay.01; batch64; inner validation epoch1..100 then refit on all sampled N',
        inner_validation='Unmodified subject-stratified inner_split; minimum1 validation per represented subject, so validation fraction can exceed20% at small N',
        ridge_alpha=1.0, bestsingle='argmax of sampled development five-repeat mean; no test labels',
        ma_aggregation='Mean realized utility over frozen optimization seeds42,43,44, not majority vote or averaged-logit deployment; all per-optimizer metrics retained',
        full_reuse='Identical Full development/inner splits and optimizer seeds across subsampling seeds; compute once per fold/representation and reference it ten times. Full subsampling std is zero, not ten independent fits.',
        metrics=dict(train='Resubstitution EQ on all sampled queries after final refit; pooled across fold training occurrences',
                     test='Query-weighted OOF EQ on the same400 queries for each subsampling seed',
                     std='Sample standard deviation (ddof=1) over10 subsampling-seed outcomes after averaging3 MA optimization seeds',
                     gap_recovery='(method EQ - matched-N BestSingle EQ)/(empirical five-repeat-max Oracle EQ - matched-N BestSingle EQ); paired numerator/denominator resampled',
                     bootstrap='10000 paired query-level resamples, seed20260914; average subsampling/optimization seeds within query before inference; no4000/12000 fictitious independent queries',
                     train_gap='Train EQ minus outer-test EQ; train query occurrence weights retained; descriptive conditional resampling, not independent holdout uncertainty'),
        trend='Adjacent-N marginal EQ and MA-Ridge changes, plus40-to-Full; no extrapolation or outer-test parameter choice',
        classification=dict(data_limited='MA-Ridge40-to-Full CI lower>0 AND MA120-to-Full CI lower>0',
            representation_limited='Ridge40-to-Full CI lower>0 AND MA-Ridge40-to-Full CI upper<0 AND MA40-to-Full CI includes0 or is negative; shorthand for frozen MA representation/objective recipe, not causal attribution to shared GTE',
            overfitting='MA train40-to-Full CI lower>0 AND MA outer40-to-Full CI upper<=0; train-test gaps reported as additional overfitting diagnostics',
            inconclusive='If the above sufficient patterns are absent or conflict; absence of significance is not proof of flatness/saturation'),
        constraints=['No new model answers', 'No architecture/loss/hidden-size/rank/threshold changes',
                     'No outer-test tuning', 'No GitHub push', 'Stop after E5; no automatic next experiment'],
        limits=['Only approximately167-168 independent development queries per fold at Full, not400.',
                'Already-used enriched panel; no representative benchmark or new-query confirmation claim.',
                'Pointwise95% intervals, no multiplicity correction; conditional on fitted models, not a full retraining population interval.',
                'Three-fold train sets overlap; training EQ is resubstitution and not a separate test sample.',
                'No exact equivalence/plateau claim from a CI containing0.'],
        packages={n: importlib.metadata.version(n) for n in ['numpy', 'torch', 'scikit-learn']},
        hashes={str(p): sha(p) for p in paths})
    np.savez_compressed(OUT / 'INPUTS.npz', ids=np.array(ids), Original=data['x'], Content_secondary=data['content'],
                        quality=data['y'], repeats=data['values'], groups=data['groups'], subjects=subjects)
    protocol['hashes'][str(OUT / 'INPUTS.npz')] = sha(OUT / 'INPUTS.npz')
    write_json(OUT / 'PROTOCOL.json', protocol)
    status('PREPARED', samples=len(samples), unique_fit_jobs=186, ma_fits=558)


def verify():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    for path, digest in protocol['hashes'].items():
        if sha(path) != digest:
            raise ValueError('Frozen E5 input/code changed: ' + path)
    return protocol


def job_name(representation, sample):
    return f'{representation}_fold{sample["fold"]}_N{sample["n"]}_{sample["sample_key"]}'


def worker(task):
    representation, sample = task
    import torch
    from sklearn.linear_model import Ridge
    from .train_repeat_pairwise_compatibility_115 import fit, PairwiseMA
    torch.set_num_threads(4)
    name = job_name(representation, sample)
    file = OUT / 'jobs' / f'{name}.npz'
    metadata = OUT / 'jobs' / f'{name}.json'
    if metadata.exists():
        row = json.loads(metadata.read_text())
        if row['npz_sha256'] != sha(file) or row['protocol_sha256'] != sha(OUT / 'PROTOCOL.json'):
            raise ValueError('Cached job integrity mismatch')
        return dict(job=name, reused=True, seconds=row['seconds'])
    start = time.monotonic()
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    ids = z['ids'].tolist(); index = {q: i for i, q in enumerate(ids)}
    dev = np.array([index[q] for q in sample['development_ids']])
    train = np.array([index[q] for q in sample['inner_train_ids']])
    validation = np.array([index[q] for q in sample['inner_validation_ids']])
    test = np.array([index[q] for q in sample['test_ids']])
    if set(dev) & set(test) or set(train) | set(validation) != set(dev):
        raise ValueError('Job split leakage')
    x, y = z[representation], z['quality']
    best = int(y[dev].mean(0).argmax())
    ridge = Ridge(alpha=1.0).fit(x[dev], y[dev])
    ridge_test, ridge_train = ridge.predict(x[test]), ridge.predict(x[dev])
    ma_test, ma_train, details = [], [], []
    for seed in MASEEDS:
        pred, state, detail = fit(x, y, train, validation, dev, test, seed)
        model = PairwiseMA(x.shape[1]); model.load_state_dict(state); model.eval()
        with torch.no_grad():
            train_pred = model.utilities(torch.tensor(x[dev], dtype=torch.float32)).numpy()
        ma_test.append(pred); ma_train.append(train_pred)
        details.append(dict(optimization_seed=seed, **detail))
    if representation == 'Original' and sample['n'] == 'Full':
        old = np.load(SOURCE / 'PREDICTIONS.npz', allow_pickle=False)
        if old['ids'].tolist() != ids or not np.array_equal(ridge_test.argmax(1), old['choice_QueryOnlyRidge'][test]):
            raise ValueError('Frozen Full Ridge decisions not reproduced')
        for seed, scores in zip(MASEEDS, ma_test):
            if not np.array_equal(scores.argmax(1), old[f'choice_RepeatPairwiseMA_seed{seed}'][test]):
                raise ValueError(f'Frozen Full MA decisions not reproduced, fold{sample["fold"]}, seed{seed}')
    # Prediction artifacts store all three optimizers separately; no winner selection.
    with file.with_suffix('.tmp').open('wb') as stream:
        np.savez_compressed(stream, development_indices=dev, test_indices=test,
            bestsingle=np.array(best), ridge_test=ridge_test, ridge_train=ridge_train,
            ma_test=np.stack(ma_test), ma_train=np.stack(ma_train))
    file.with_suffix('.tmp').replace(file)
    row = dict(job=name, representation=representation, fold=sample['fold'], n=sample['n'],
               actual_n=len(dev), sample_key=sample['sample_key'], ma_fit=details,
               seconds=time.monotonic() - start, protocol_sha256=sha(OUT / 'PROTOCOL.json'), npz_sha256=sha(file),
               full_baseline_reproduced=(representation == 'Original' and sample['n'] == 'Full'))
    write_json(metadata, row)
    return dict(job=name, reused=False, seconds=row['seconds'])


def run(workers):
    verify()
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('E5 already complete')
    (OUT / 'jobs').mkdir(exist_ok=True)
    samples = [json.loads(r) for r in (OUT / 'SAMPLES.jsonl').open()]
    tasks = {}; full = []; rest = []
    for representation in REPRESENTATIONS:
        for sample in samples:
            key = job_name(representation, sample)
            tasks[key] = (representation, sample)
    for task in tasks.values():
        (full if task[1]['n'] == 'Full' else rest).append(task)
    with (OUT / 'RUN.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = 0
        status('FITTING', completed=completed, total=len(tasks), workers=workers)
        context = multiprocessing.get_context('spawn')
        # Validate frozen Full reproduction before subsampled jobs; no selection by outcome.
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            for phase_tasks in [full, rest]:
                futures = {executor.submit(worker, task): task for task in phase_tasks}
                for future in as_completed(futures):
                    outcome = future.result()
                    completed += 1
                    status('FITTING', completed=completed, total=len(tasks), last_job=outcome)
        status('FITS_COMPLETE', completed=completed, total=len(tasks))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['prepare', 'run'])
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    if args.stage == 'prepare':
        prepare()
    else:
        if args.workers < 1 or args.workers > 4:
            raise ValueError('Use1..4 workers, each with4 CPU threads')
        run(args.workers)


if __name__ == '__main__':
    main()
