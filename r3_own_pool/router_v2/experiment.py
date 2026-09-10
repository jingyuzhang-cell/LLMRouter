"""Fit/validation freeze and single-use holdout evaluation are separate stages.

Run from /root/r3_own_pool: python -m router_v2.experiment --help
"""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPClassifier, MLPRegressor
from .core import (GRID, SLOTS, rank_loss, scales_from_train, utility, route, chosen,
                   select_operating_point, evaluate_policy, zero_mixture, constrained_metrics)
from .data import sha, load_cohort, load_outcomes, matrix, verify_gate
from train_router import HybridUtilityRouter

ALPHAS = (0., .25, .5, 1.)


class TieAwareWinner(HybridUtilityRouter):
    """Query-only classifier with uniform probability mass on all quality maxima."""
    def __init__(self, q_dim, seed=42):
        super().__init__(q_dim=q_dim, seed=seed, use_m_emb=False)

    def fit(self, x, y, epochs=60, seed=42):
        self.train()
        rng = np.random.default_rng(seed)
        target = torch.tensor(y, dtype=torch.float32)
        winners = (target == target.max(1, keepdim=True).values).float()
        probabilities = winners / winners.sum(1, keepdim=True)
        for _ in range(epochs):
            order = rng.permutation(len(x))
            for start in range(0, len(x), 64):
                idx = order[start:start+64]
                logits = self.predict_batch(torch.tensor(x[idx], dtype=torch.float32))
                loss = -(probabilities[idx] * torch.log_softmax(logits, dim=1)).sum(1).mean()
                self.opt.zero_grad()
                loss.backward()
                self.opt.step()
        return self

    def predict_all(self, x):
        was_training = self.training
        self.eval()
        try:
            with torch.no_grad():
                logits = self.predict_batch(torch.tensor(x, dtype=torch.float32))
                return torch.softmax(logits, dim=1).numpy()
        finally:
            self.train(was_training)


class Router(HybridUtilityRouter):
    def fit(self, x, y, epochs=60, seed=42):
        self.train()
        rng = np.random.default_rng(seed)
        for _ in range(epochs):
            permutation = rng.permutation(len(x))
            for start in range(0, len(x), 64):
                idx = permutation[start:start+64]
                pred = self.predict_batch(torch.tensor(x[idx], dtype=torch.float32))
                target = torch.tensor(y[idx], dtype=torch.float32)
                loss = self.alpha * rank_loss(pred, target, self.margin)
                if not self.pure_rank:
                    loss = loss + ((pred-target)**2).mean()
                self.opt.zero_grad()
                loss.backward()
                self.opt.step()
        return self


def features(cohort, split, cohort_dir, embeddings, seed):
    ids = sum([split[k] for k in ('train', 'validation', 'test')], [])
    nt = len(split['train'])
    if embeddings:
        with np.load(embeddings, allow_pickle=False) as archive:
            if str(archive['query_sha256'].item()) != sha(Path(cohort_dir)/'queries.jsonl'):
                raise ValueError('Embedding query hash mismatch')
            emb_ids = archive['ids'].tolist()
            if len(set(emb_ids)) != len(emb_ids) or set(emb_ids) != set(ids):
                raise ValueError('Embedding ids do not match cohort')
            vectors = archive['vectors']
            if vectors.ndim != 2 or vectors.shape[0] != len(ids) or not np.isfinite(vectors).all():
                raise ValueError('Invalid embedding matrix')
            index = {qid: i for i, qid in enumerate(emb_ids)}
            x = vectors[[index[q] for q in ids]].astype('float32')
        description = 'Caller-supplied frozen query embeddings; identity/provenance recorded in protocol'
    else:
        # Explicit low-cost development feature route; not the frozen GTE main experiment.
        text = [cohort[q]['query'] for q in ids]
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=12000, sublinear_tf=True)
        train = vectorizer.fit_transform(text[:nt])
        all_x = vectorizer.transform(text)
        dimensions = min(128, nt-1, train.shape[1]-1)
        if dimensions < 1:
            raise ValueError('Insufficient training features')
        reducer = TruncatedSVD(n_components=dimensions, random_state=seed)
        reducer.fit(train)
        x = reducer.transform(all_x).astype('float32')
        description = 'Development TF-IDF/SVD fitted on train requests only; not GTE reproduction'
    nv = len(split['validation'])
    return (x[:nt], x[nt:nt+nv], x[nt+nv:]), description


def component_predictions(qpred, resource_pred):
    return np.concatenate([np.clip(qpred, 0, 1)[:, :, None], resource_pred], axis=2)


def select_alpha(candidates, validation_y, scales, preference):
    scores = [float(utility(chosen(validation_y, route(pred, preference, scales))[:, None, :],
                            preference, scales).mean()) for pred in candidates]
    return int(np.argmax(scores)), scores


def fit(args):
    quality_delta = getattr(args, 'quality_delta', 0.)
    if not np.isfinite(quality_delta) or not 0 <= quality_delta <= 1:
        raise ValueError('quality_delta must be finite and in [0, 1]')
    cohort, split = load_cohort(args.cohort)
    gate = verify_gate(args.gate, args.outcomes, args.cohort)
    if gate.get('role') != 'synthetic_smoke':
        if [len(split[k]) for k in ('train', 'validation', 'test')] != [3500, 750, 750]:
            raise ValueError('Real v2 cohort must use 3500/750/750')
    if args.epochs < 1:
        raise ValueError('epochs must be positive')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), Path(__file__).with_name('core.py'),
                    Path(__file__).with_name('data.py'), Path(__file__).with_name('integrity.py'),
                    Path(__file__).parents[1]/'train_router.py']
    protocol = dict(seed=args.seed, epochs=args.epochs, alphas=ALPHAS, grid=GRID,
        quality_delta=quality_delta, role=gate.get('role', 'development_until_all_preregistered_baselines_complete'),
        encoder=gate.get('embedding_provenance', 'TF-IDF/SVD development'),
        input_sha256={str(Path(p).resolve()): sha(p) for p in
                      [args.outcomes, args.gate, Path(args.cohort)/'queries.jsonl',
                       Path(args.cohort)/'split.json', Path(args.cohort)/'MANIFEST.json'] +
                      ([args.embeddings] if args.embeddings else [])},
        source_sha256={str(p.resolve()):sha(p) for p in source_files},
        scale='Train median positive C/L', fit_labels='train only',
        selection='validation only; per-preference alpha and independent constrained operating point',
        costs=dict(currency=gate['currency'], basis=gate['cost_basis']),
        limitations=['Finite grid, not complete Pareto frontier',
          'Fixed-seed conditional query bootstrap; not training variance or simultaneous intervals',
          'Transformer baseline not yet implemented; no claim of complete main-paper comparison',
          'Current features are fixed-model-pool; no unseen-model or held-out-source claim',
          'Conditional resource means, no latency SLO guarantee; encoder/dispatch overhead excluded'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol, indent=2))
    by = load_outcomes(args.outcomes, cohort)
    train_y = matrix(by, split['train'])
    validation_y = matrix(by, split['validation'])
    # Do not extract, score or select using test outcomes in this stage.
    (xt, xv, xe), feature_description = features(cohort, split, args.cohort, args.embeddings, args.seed)
    scales = scales_from_train(train_y)
    resource_fit = Ridge(alpha=20).fit(xt, (train_y[:, :, 1:]/scales[1:]).reshape(len(xt), -1))
    resource_v = np.maximum(resource_fit.predict(xv).reshape(-1, 4, 2), 0)*scales[1:]
    resource_e = np.maximum(resource_fit.predict(xe).reshape(-1, 4, 2), 0)*scales[1:]
    val, test, timing = {}, {}, {}

    def add(name, model, y, neural=False):
        started = time.perf_counter()
        if neural:
            model.fit(xt, y, epochs=args.epochs, seed=args.seed)
            pv = model.predict_all(xv)
            infer_start = time.perf_counter()
            pe = model.predict_all(xe)
        else:
            model.fit(xt, y)
            pv = model.predict(xv)
            infer_start = time.perf_counter()
            pe = model.predict(xe)
        timing[name] = dict(fit_and_predict_seconds=time.perf_counter()-started,
                           prediction_ms_per_test_query=(time.perf_counter()-infer_start)*1000/len(xe))
        return pv, pe

    for name, model in [('Ridge', Ridge(alpha=20)),
                        ('MLPReward', MLPRegressor(hidden_layer_sizes=(128,64), max_iter=args.epochs,
                          random_state=args.seed, early_stopping=False))]:
        pv, pe = add(name, model, train_y[:, :, 0])
        val[name], test[name] = component_predictions(pv, resource_v), component_predictions(pe, resource_e)
    knn = KNeighborsRegressor(n_neighbors=min(20,len(xt)), metric='cosine', algorithm='brute')
    pv, pe = add('KNN', knn, (train_y/scales).reshape(len(xt), -1))
    for dest, pred in [(val, pv), (test, pe)]:
        dest['KNN'] = pred.reshape(-1,4,3)*scales
        dest['KNN'][:, :, 0] = dest['KNN'][:, :, 0].clip(0,1)
        dest['KNN'][:, :, 1:] = dest['KNN'][:, :, 1:].clip(0)
    winner = MLPClassifier(hidden_layer_sizes=(128,64), max_iter=args.epochs,
                           random_state=args.seed, early_stopping=False)
    win_v, win_e = add('MLPWinner', winner, train_y[:, :, 0].argmax(1))
    tie_model = TieAwareWinner(q_dim=xt.shape[1], seed=args.seed)
    tie_v, tie_e = add('MLPWinnerTieAware', tie_model, train_y[:, :, 0], neural=True)
    ranking = Router(q_dim=xt.shape[1], seed=args.seed, alpha=1., pure_rank=True)
    rank_v, rank_e = add('RankingOnly', ranking, train_y[:, :, 0], neural=True)
    for family, use_m in [('Hybrid', True), ('NoModelEmbedding', False)]:
        for alpha in ALPHAS:
            name = f'{family}_alpha{alpha:g}'
            pv, pe = add(name, Router(q_dim=xt.shape[1], seed=args.seed, alpha=alpha, use_m_emb=use_m),
                         train_y[:, :, 0], neural=True)
            val[name], test[name] = component_predictions(pv, resource_v), component_predictions(pe, resource_e)
        print(f'completed {family} alpha ablation', flush=True)

    selection = dict(features=feature_description, families={}, constrained={}, timing=timing)
    for family in ('Hybrid', 'NoModelEmbedding'):
        names = [f'{family}_alpha{a:g}' for a in ALPHAS]
        selected, validation_scores = [], []
        for pref in GRID:
            index, scores = select_alpha([val[k] for k in names], validation_y, scales, pref)
            selected.append(names[index]); validation_scores.append(scores)
        selection['families'][family] = dict(selected_by_preference=selected, validation_scores=validation_scores)

    # Constrained operating point: enumerate all alphas on validation, never test.
    for family in ('Hybrid', 'NoModelEmbedding', 'Ridge', 'MLPReward', 'KNN'):
        names = [f'{family}_alpha{a:g}' for a in ALPHAS] if family in ('Hybrid','NoModelEmbedding') else [family]
        points = []
        for name in names:
            point = select_operating_point(val[name], validation_y, train_y, scales, delta=quality_delta)
            point['prediction_key'] = name
            decision = (route(val[name], GRID[point['grid_index']], scales) if point['kind']=='grid'
                        else np.full(len(xv), point['baseline_slot']))
            point['validation_cost'] = float(chosen(validation_y, decision)[:,1].mean())
            points.append(point)
        selection['constrained'][family] = min(points, key=lambda p: p['validation_cost'])
    baseline = int(train_y[:, :, 0].mean(0).argmax())
    mixture = zero_mixture(train_y, baseline, scales, delta=quality_delta)
    np.savez_compressed(out/'PREDICTIONS.npz', test_ids=np.array(split['test']),
                        train_y=train_y, scales=scales, zero_mixture=mixture,
                        winner_choices=win_e.astype(int), tie_winner_choices=tie_e.argmax(1), ranking_choices=rank_e.argmax(1),
                        **{'pred_'+k:v for k,v in test.items()})
    np.savez_compressed(out/'VALIDATION_PREDICTIONS.npz', ids=np.array(split['validation']),
                        outcomes=validation_y, tie_winner_choices=tie_v.argmax(1), winner_choices=win_v.astype(int), ranking_choices=rank_v.argmax(1),
                        **{'pred_'+k:v for k,v in val.items()})
    (out/'SELECTION.json').write_text(json.dumps(selection, indent=2))
    sealed = {name:sha(out/name) for name in ('PROTOCOL.json','PREDICTIONS.npz','SELECTION.json','VALIDATION_PREDICTIONS.npz')}
    (out/'FROZEN.json').write_text(json.dumps(sealed, indent=2))
    print(f'Fitted and sealed validation choices: {out}; test outcomes not scored', flush=True)


def evaluate(args):
    out = Path(args.output)
    sealed = json.loads((out/'FROZEN.json').read_text())
    for name, digest in sealed.items():
        if sha(out/name) != digest:
            raise ValueError('Frozen prediction/selection artifact changed: '+name)
    protocol = json.loads((out/'PROTOCOL.json').read_text())
    for path, digest in {**protocol['input_sha256'], **protocol['source_sha256']}.items():
        if sha(path) != digest:
            raise ValueError('Input or implementation changed since fit: '+path)
    # CLI inputs must be those that passed the gate and were sealed at fit time.
    for path in (args.outcomes, Path(args.cohort)/'queries.jsonl', Path(args.cohort)/'split.json'):
        if str(Path(path).resolve()) not in protocol['input_sha256']:
            raise ValueError('Evaluation input not in fitted protocol')
    cohort, split = load_cohort(args.cohort)
    selection = json.loads((out/'SELECTION.json').read_text())
    with np.load(out/'PREDICTIONS.npz', allow_pickle=False) as saved:
        data = {k:saved[k] for k in saved.files}
    if data['test_ids'].tolist() != split['test']:
        raise ValueError('Test query order mismatch')
    # Atomic, exclusive marker prevents silent reruns/selection after unblinding.
    with (out/'TEST_OPENED.json').open('x') as stream:
        json.dump(dict(time=time.time(), note='Evaluation attempted; no automatic retry or overwrite'), stream)
    y = matrix(load_outcomes(args.outcomes, cohort), split['test'])
    train_y, scales = data['train_y'], data['scales']
    rows = []
    for g, pref in enumerate(GRID):
        base = int(utility(train_y,pref,scales).mean(0).argmax())
        policies = {'RandomExpected':np.full((len(y),4),.25),
                    'BestSingle':np.full(len(y),base),
                    'ZeroMixture':np.tile(data['zero_mixture'],(len(y),1)),
                    'Oracle':utility(y,pref,scales).argmax(1)}
        for name in ('Ridge','MLPReward','KNN','Hybrid_alpha0','NoModelEmbedding_alpha0'):
            policies[name] = route(data['pred_'+name],pref,scales)
        for family in ('Hybrid','NoModelEmbedding'):
            key = selection['families'][family]['selected_by_preference'][g]
            policies[family] = route(data['pred_'+key],pref,scales)
        if g == 0:
            # Ranking logits and winner ids are not calibrated multiobjective utilities.
            policies['MLPWinner'] = data['winner_choices']
            policies['MLPWinnerTieAware'] = data['tie_winner_choices']
            policies['RankingOnly'] = data['ranking_choices']
        for name, decisions in policies.items():
            report = evaluate_policy(y,decisions,train_y,pref,scales)
            actual = chosen(y,decisions)
            report['by_source'] = {}
            datasets = np.array([cohort[q]['dataset'] for q in split['test']])
            for ds in sorted(set(datasets)):
                mask = datasets == ds
                report['by_source'][ds] = dict(n=int(mask.sum()),quality=float(actual[mask,0].mean()),
                    cost=float(actual[mask,1].mean()),latency_ms=float(actual[mask,2].mean()))
            report['routing_fraction'] = (np.bincount(decisions,minlength=4)/len(y)).tolist() if decisions.ndim==1 else decisions.mean(0).tolist()
            rows.append(dict(method=name,lam=pref[0],mu=pref[1],**report))
    constrained = {}
    for name, point in selection['constrained'].items():
        decisions = (route(data['pred_'+point['prediction_key']],GRID[point['grid_index']],scales)
                     if point['kind']=='grid' else np.full(len(y),point['baseline_slot']))
        constrained[name] = dict(frozen_policy=point,
            **constrained_metrics(y,decisions,point['baseline_slot'],point['delta']))
    baseline = int(train_y[:,:,0].mean(0).argmax())
    constrained['ZeroMixture'] = constrained_metrics(y,np.tile(data['zero_mixture'],(len(y),1)),baseline,protocol['quality_delta'])
    # Three-axis nondominance is descriptive only, never a test-selected policy.
    learned = [row for row in rows if row['method']=='Hybrid']
    frontier = []
    for point in learned:
        def dominates(other):
            a,b = np.array([-other['quality'],other['cost'],other['latency_ms']]), np.array([-point['quality'],point['cost'],point['latency_ms']])
            return bool((a<=b).all() and (a<b).any())
        if not any(dominates(other) for other in learned):
            frontier.append(dict(lam=point['lam'],mu=point['mu'],quality=point['quality'],cost=point['cost'],latency_ms=point['latency_ms']))
    result = dict(role=protocol['role'],n_test=len(y),sweep=rows,constrained=constrained,
                  fixed_model_anchors=[dict(slot=s,quality=float(y[:,j,0].mean()),cost=float(y[:,j,1].mean()),latency_ms=float(y[:,j,2].mean())) for j,s in enumerate(SLOTS)],
                  descriptive_three_axis_nondominated_grid=frontier,limitations=protocol['limitations'])
    with (out/'RESULTS.json').open('x') as f:
        json.dump(result,f,indent=2)
    lines = ['# R3 v2 routing evaluation', '', f"Role: {protocol['role']}; n_test={len(y)}.",
             '', '| Method (quality preference) | Quality | Utility gain | GRR |', '|---|---:|---:|---:|']
    for row in rows:
        if row['lam']==row['mu']==0:
            grr = 'null' if row['gap_recovery'] is None else f"{row['gap_recovery']:.4f}"
            lines.append(f"| {row['method']} | {row['quality']:.6f} | {row['utility_gain']:+.6f} | {grr} |")
    lines += ['', 'Constrained policies were selected on validation before test. See RESULTS.json for paired intervals, all preferences, and source strata.',
              '', *[f'- {s}' for s in protocol['limitations']]]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(f'One-time evaluation written to {out}',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='stage',required=True)
    for stage in ('fit','evaluate'):
        p = sub.add_parser(stage)
        p.add_argument('--cohort',required=True)
        p.add_argument('--outcomes',required=True)
        p.add_argument('--output',required=True)
        if stage=='fit':
            p.add_argument('--gate',required=True)
            p.add_argument('--embeddings',default=None)
            p.add_argument('--seed',type=int,default=42)
            p.add_argument('--epochs',type=int,default=60)
            p.add_argument('--quality-delta',type=float,default=0.,
                           help='Predeclared quality noninferiority margin in [0,1]; sealed at fit.')
    args = parser.parse_args()
    (fit if args.stage=='fit' else evaluate)(args)

if __name__=='__main__':
    main()
