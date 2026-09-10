"""Fit all declared seeds before opening any test results; summarize without seed selection."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from .data import sha
from . import experiment


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def validate_batch(root):
    root = Path(root)
    seal = json.loads((root/'BATCH_FROZEN.json').read_text())
    for relative, digest in seal.items():
        if sha(root/relative) != digest:
            raise ValueError('Batch artifact changed: ' + relative)
    batch = json.loads((root/'BATCH_PROTOCOL.json').read_text())
    if sha(__file__) != batch['coordinator_sha256']:
        raise ValueError('Batch coordinator changed')
    common = None
    for seed in batch['seeds']:
        run = root/f'seed_{seed}'
        if (run/'TEST_OPENED.json').exists() or (run/'RESULTS.json').exists():
            raise ValueError('A seed has already opened test results')
        frozen = json.loads((run/'FROZEN.json').read_text())
        for name, digest in frozen.items():
            if sha(run/name) != digest:
                raise ValueError('Seed artifact changed: ' + name)
        protocol = json.loads((run/'PROTOCOL.json').read_text())
        if protocol['seed'] != seed:
            raise ValueError('Seed identity mismatch')
        for path, digest in {**protocol['input_sha256'], **protocol['source_sha256']}.items():
            if sha(path) != digest:
                raise ValueError('Seed input or implementation changed: ' + path)
        signature = {k: v for k, v in protocol.items() if k != 'seed'}
        if common is not None and common != signature:
            raise ValueError('Seeds must share inputs, implementation and protocol')
        common = signature
    return batch


def fit_batch(args):
    if len(args.seeds) < 2 or len(set(args.seeds)) != len(args.seeds):
        raise ValueError('Declare at least two distinct seeds')
    if any(seed < 0 or seed >= 2**32 for seed in args.seeds):
        raise ValueError('Seeds must be in [0, 2**32)')
    if not np.isfinite(args.quality_delta) or not 0 <= args.quality_delta <= 1:
        raise ValueError('quality_delta must be finite and in [0, 1]')
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    batch = dict(seeds=args.seeds, cohort=str(Path(args.cohort).resolve()),
                 outcomes=str(Path(args.outcomes).resolve()), quality_delta=args.quality_delta,
                 coordinator_sha256=sha(__file__),
                 limitation='Batch-local sealing only; does not certify historical holdout exposure or prevent direct single-run CLI use.')
    write_new(root/'BATCH_PROTOCOL.json', batch)
    for seed in args.seeds:
        run_args = argparse.Namespace(**vars(args))
        run_args.seed = seed
        run_args.output = str(root/f'seed_{seed}')
        experiment.fit(run_args)
    files = ['BATCH_PROTOCOL.json'] + [f'seed_{seed}/FROZEN.json' for seed in args.seeds]
    write_new(root/'BATCH_FROZEN.json', {name: sha(root/name) for name in files})
    validate_batch(root)
    print(f'All {len(args.seeds)} seeds sealed; no test evaluation: {root}', flush=True)


def numeric_summary(values):
    if any(v is None for v in values):
        return dict(per_seed=values, mean=None, std_across_seeds=None)
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all():
        raise ValueError('Nonfinite result')
    return dict(per_seed=values, mean=float(a.mean()), std_across_seeds=float(a.std(ddof=1)))


def aggregate(results, seeds):
    if len(results) != len(seeds) or len(results) < 2:
        raise ValueError('Every declared seed must have a result')
    indexed = []
    for result in results:
        rows = {(r['method'], r['lam'], r['mu']): r for r in result['sweep']}
        if len(rows) != len(result['sweep']):
            raise ValueError('Duplicate method/preference')
        indexed.append(rows)
    if any(set(rows) != set(indexed[0]) for rows in indexed[1:]):
        raise ValueError('Missing method/preference in a seed')
    if any((r['role'], r['n_test']) != (results[0]['role'], results[0]['n_test']) for r in results[1:]):
        raise ValueError('Inconsistent evaluation cohort or role')
    sweep = []
    for key in sorted(indexed[0]):
        metrics = {metric: numeric_summary([r[key][metric] for r in indexed])
                   for metric in ('quality', 'cost', 'latency_ms', 'utility_gain', 'gap_recovery')}
        sweep.append(dict(method=key[0], lam=key[1], mu=key[2], metrics=metrics))
    names = set(results[0]['constrained'])
    if any(set(r['constrained']) != names for r in results[1:]):
        raise ValueError('Missing constrained method')
    constrained = {}
    for name in sorted(names):
        rows = [r['constrained'][name] for r in results]
        constrained[name] = dict(
            metrics={m: numeric_summary([r[m] for r in rows]) for m in ('quality_delta', 'cost_saving_fraction')},
            pass_counts={m: sum(bool(r[m]) for r in rows) for m in ('passes_quality', 'passes_cost', 'passes_latency', 'all_three_pass')},
            per_seed=rows)
    return dict(role=results[0]['role'], seeds=seeds, n_test=results[0]['n_test'],
                sweep=sweep, constrained=constrained,
                interpretation='Mean and sample SD over all declared seeds; not a confidence interval. Same test queries reused across seeds, not independent extra samples. Per-seed paired intervals retained; no averaged CI or best-seed selection.')


def evaluate_batch(args):
    root = Path(args.output).resolve()
    if (root/'BATCH_TEST_OPENED.json').exists():
        raise ValueError('Batch evaluation already attempted; inspect retained state, no automatic retry')
    batch = validate_batch(root)  # Validate every seed before opening the first.
    write_new(root/'BATCH_TEST_OPENED.json', dict(time=time.time(), frozen_sha256=sha(root/'BATCH_FROZEN.json')))
    results = []
    for seed in batch['seeds']:
        run = root/f'seed_{seed}'
        experiment.evaluate(argparse.Namespace(cohort=batch['cohort'], outcomes=batch['outcomes'], output=str(run)))
        results.append(json.loads((run/'RESULTS.json').read_text()))
    summary = aggregate(results, batch['seeds'])
    summary['result_sha256'] = {str(seed): sha(root/f'seed_{seed}'/'RESULTS.json') for seed in batch['seeds']}
    write_new(root/'SUMMARY.json', summary)
    print(f'All declared seeds evaluated and summarized: {root}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='stage', required=True)
    fit = sub.add_parser('fit')
    for key in ('cohort', 'outcomes', 'gate', 'output'):
        fit.add_argument('--'+key, required=True)
    fit.add_argument('--embeddings')
    fit.add_argument('--seeds', type=int, nargs='+', default=[42, 43, 44])
    fit.add_argument('--epochs', type=int, default=60)
    fit.add_argument('--quality-delta', type=float, default=0.)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--output', required=True)
    args = parser.parse_args()
    (fit_batch if args.stage == 'fit' else evaluate_batch)(args)


if __name__ == '__main__':
    main()
