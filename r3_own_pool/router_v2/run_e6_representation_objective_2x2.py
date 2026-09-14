"""E6: exactly four fixed representation/objective cells, no new responses."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from sklearn.cluster import KMeans
from sklearn.linear_model import Ridge

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e6_representation_objective_2x2'
E5 = ROOT / 'router_v2/e5_independent_query_learning_curve'
SOURCE = ROOT / 'router_v2/experiment_repeat_compatibility_400_fold_local'
PANEL = ROOT / 'router_v2/mmlu_utility_panel_400'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
ARMS = ['A_QueryOnly', 'B_Capability', 'C_Stability', 'D_Capability_Stability']
K = 8
KMEANS_SEED = 42
PRIOR_COUNT = 5.0
WEIGHT_FLOOR = 0.05
ALPHA = 1.0


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def objective_weights(repeats):
    """Alternative-specific empirical stability; independent-slot variances."""
    repeats = np.asarray(repeats, dtype=float)
    if repeats.ndim != 3 or repeats.shape[1:] != (4, 5) or not np.isin(repeats, [0, 1]).all():
        raise ValueError('Expected complete binary n×4×5 training repeats')
    means = repeats.mean(2)
    delta = means[:, :3] - means[:, [3]]
    variance = repeats.var(2, ddof=0)
    stability = np.clip(1 - 2 * (variance[:, :3] + variance[:, [3]]), 0, 1)
    raw = WEIGHT_FLOOR + (1 - WEIGHT_FLOOR) * np.abs(delta) * stability
    weights = raw / raw.mean(0, keepdims=True)
    return delta, weights, stability, raw


def capability_kernel(x_train, repeats):
    """KMeans and supervised regional means use training data only."""
    x_train = np.asarray(x_train, dtype=float)
    means = np.asarray(repeats, dtype=float).mean(2)
    if len(x_train) < K or len(means) != len(x_train):
        raise ValueError('Insufficient/misaligned training data')
    clustering = KMeans(n_clusters=K, random_state=KMEANS_SEED, n_init=10, algorithm='lloyd').fit(x_train)
    regions = clustering.labels_
    counts = np.bincount(regions, minlength=K)
    if (counts == 0).any():
        raise ValueError('Empty latent region; frozen K is not changed')
    global_mean = means.mean(0)
    sums = np.array([means[regions == k].sum(0) for k in range(K)])
    raw_profiles = (sums / counts[:, None]).T
    profiles = ((sums + PRIOR_COUNT * global_mean[None, :]) / (counts[:, None] + PRIOR_COUNT)).T
    differences = profiles[:3] - profiles[[3]]
    trace = float(np.square(differences).sum())
    scale = np.sqrt(3.0 / trace) if trace > 1e-24 else 0.0
    model_features = differences * scale
    kernel = model_features @ model_features.T
    # A's three independent output coordinates have identity kernel/trace3.
    # Scale only globally; do not whiten away the learned capability geometry.
    detail = dict(k=K, seed=KMEANS_SEED, n_init=10, prior_count=PRIOR_COUNT,
                  region_counts=counts.tolist(), global_model_means=global_mean.tolist(),
                  raw_profiles=raw_profiles.tolist(), shrunk_profiles=profiles.tolist(),
                  normalized_delta_profiles=model_features.tolist(), normalization_scale=float(scale),
                  kernel=kernel.tolist(), eigenvalues=np.linalg.eigvalsh(kernel).tolist())
    return kernel, detail, regions, clustering.cluster_centers_


def fit_delta_kernel(x_train, delta, model_kernel, weights):
    """Convex linear query×model Ridge with unpenalized model-span intercept.

    Solve the weighted kernel Ridge normal equations with explicit intercepts.
    Identity model kernel is exactly three independent (weighted) Ridge heads.
    Capability model kernel is the bilinear feature map e(q) tensor (c_m-c_R1).
    """
    x = np.asarray(x_train, dtype=float)
    target = np.asarray(delta, dtype=float)
    w = np.asarray(weights, dtype=float)
    model_kernel = np.asarray(model_kernel, dtype=float)
    if target.shape != (len(x), 3) or w.shape != target.shape or not np.isfinite(w).all() or (w <= 0).any():
        raise ValueError('Invalid target/weight shape or nonpositive weight')
    eigenvalues, basis = np.linalg.eigh(model_kernel)
    if eigenvalues.min() < -1e-10:
        raise ValueError('Model kernel is not PSD')
    keep = eigenvalues > max(1e-12, float(eigenvalues.max()) * 1e-12)
    basis = basis[:, keep]
    kernel = np.kron(x @ x.T, model_kernel)
    intercept = np.tile(basis, (len(x), 1))
    system = kernel + np.diag(ALPHA / w.ravel())
    factor = cho_factor(system, lower=True, check_finite=True)
    rhs = np.column_stack([target.ravel(), intercept])
    solved = cho_solve(factor, rhs)
    if intercept.shape[1]:
        bias = np.linalg.solve(intercept.T @ solved[:, 1:], intercept.T @ solved[:, 0])
        dual = solved[:, 0] - solved[:, 1:] @ bias
    else:
        bias = np.empty(0)
        dual = solved[:, 0]
    residual = system @ dual + intercept @ bias - target.ravel()
    if np.max(np.abs(residual)) > 1e-7 or (intercept.shape[1] and np.max(np.abs(intercept.T @ dual)) > 1e-7):
        raise ValueError('Weighted Ridge optimality residual too large')
    return dict(x=x, model_kernel=model_kernel, basis=basis, bias=bias, dual=dual,
                max_normal_equation_residual=float(np.max(np.abs(residual))))


def predict_delta(fitted, x_eval):
    x_eval = np.asarray(x_eval, dtype=float)
    cross = np.kron(x_eval @ fitted['x'].T, fitted['model_kernel'])
    intercept = np.tile(fitted['basis'], (len(x_eval), 1))
    return (cross @ fitted['dual'] + intercept @ fitted['bias']).reshape(len(x_eval), 3)


def fit_four(x_train, repeats_train, x_eval):
    delta, weights, stability, raw = objective_weights(repeats_train)
    model_kernel, profiles, regions, centers = capability_kernel(x_train, repeats_train)
    identity = np.eye(3)
    scores, fits = {}, {}
    for arm in ARMS:
        k = model_kernel if arm in [ARMS[1], ARMS[3]] else identity
        w = weights if arm in [ARMS[2], ARMS[3]] else np.ones_like(weights)
        fitted = fit_delta_kernel(x_train, delta, k, w)
        # The R1 reference score is exactly0; preserve existing slot-order argmax ties.
        scores[arm] = np.column_stack([predict_delta(fitted, x_eval), np.zeros(len(x_eval))])
        fits[arm] = fitted
    return scores, fits, dict(profiles=profiles, regions=regions, centers=centers,
                             delta=delta, weights=weights, stability=stability, raw_weights=raw)


def prepare():
    if OUT.exists():
        raise FileExistsError('E6 output directory already exists')
    e5_protocol = json.loads((E5 / 'PROTOCOL.json').read_text())
    input_path = E5 / 'INPUTS.npz'
    if sha(input_path) != e5_protocol['hashes'][str(input_path)]:
        raise ValueError('Validated input snapshot changed')
    if not json.loads((E5 / 'INDEPENDENT_VALIDATION.json').read_text())['passed']:
        raise ValueError('E5 input provenance not verified')
    manifest = json.loads((PANEL / 'MANIFEST.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(PANEL / name) != digest:
            raise ValueError('Panel/allowlists changed')
    status_labels = json.loads((LABELS.parent / 'STATUS.json').read_text())
    if sha(LABELS) != status_labels['labels_sha256']:
        raise ValueError('Corrected repeat labels changed')
    if sha(manifest['groups']) != manifest['groups_sha256']:
        raise ValueError('Groups changed')
    z = np.load(input_path, allow_pickle=False)
    old = np.load(SOURCE / 'PREDICTIONS.npz', allow_pickle=False)
    ids = z['ids'].tolist(); index = {q: i for i, q in enumerate(ids)}
    labels = {r['query_id']: r for r in map(json.loads, LABELS.open())}
    repeats = np.array([[labels[q]['models'][s]['values'] for s in SLOTS] for q in ids], dtype=float)
    if len(ids) != 400 or len(index) != 400 or repeats.shape != (400, 4, 5) or not np.isin(repeats, [0, 1]).all():
        raise ValueError('Expected400 distinct complete4×5 repeat records')
    if not np.array_equal(repeats, z['repeats']) or not np.allclose(repeats.mean(2), old['quality']):
        raise ValueError('Corrected means mismatch')
    if old['ids'].tolist() != ids or len(set(z['groups'])) != 400:
        raise ValueError('ID/group mismatch')
    folds = json.loads((SOURCE / 'FOLDS.json').read_text())
    allow = json.loads((PANEL / 'FOLD_SELECTION.json').read_text())
    coverage = np.zeros(400, dtype=int)
    for fold in folds:
        d = np.array([index[q] for q in fold['development_ids']])
        t = np.array([index[q] for q in fold['test_ids']])
        if set(fold['development_ids']) != (set(allow[str(fold['fold'])]) & set(ids)):
            raise ValueError('Not the frozen development allowlist')
        if set(z['groups'][d]) & set(z['groups'][t]) or not np.all(old['folds'][t] == fold['fold']):
            raise ValueError('Outer fold/group leakage')
        coverage[t] += 1
    if not np.all(coverage == 1):
        raise ValueError('Outer coverage error')
    OUT.mkdir()
    write(OUT / 'FOLDS.json', folds)
    np.savez_compressed(OUT / 'INPUTS.npz', ids=z['ids'], x=z['Original'], repeats=repeats, quality=repeats.mean(2),
                        groups=z['groups'], outer_fold=old['folds'])
    paths = [Path(__file__), Path(__file__).with_name('summarize_e6_representation_objective_2x2.py'),
             Path(__file__).with_name('data.py'), input_path, E5 / 'PROTOCOL.json', E5 / 'INDEPENDENT_VALIDATION.json',
             SOURCE / 'FOLDS.json', SOURCE / 'PREDICTIONS.npz', SOURCE / 'PROTOCOL.json',
             PANEL / 'MANIFEST.json', PANEL / 'PANEL.jsonl', PANEL / 'FOLD_SELECTION.json', LABELS,
             Path(manifest['groups']), OUT / 'INPUTS.npz', OUT / 'FOLDS.json']
    protocol = dict(
        experiment='E6 Representation × Objective 2×2', arms=ARMS,
        A='Identity-output model kernel + unweighted delta Ridge; algebraically same routing as frozen QueryOnly quality Ridge; verify all400 decisions',
        B='Capability-difference model kernel + same unweighted delta objective',
        C='Same identity-output kernel as A + stability-weighted delta objective',
        D='Same capability kernel as B + exactly the weights of C',
        target='mean5(q,m)-mean5(q,R1), m=medium,large,coder; R1 prediction fixed0',
        baseline_equivalence='For identical X/alpha/intercepts, Ridge(Y_m-Y_R1)=Ridge(Y_m)-Ridge(Y_R1). Uniform delta regression preserves original A choices. Thus objective factor isolates weighting.',
        capability=dict(k=K, kmeans_seed=KMEANS_SEED, n_init=10, algorithm='lloyd', features='frozen original-prompt GTE; KMeans fit only development X',
                        profile='c_m[k]=(sum_dev_region mean5(q,m)+5*global_dev_mean(m))/(n_region+5)',
                        prior_count=PRIOR_COUNT, relative_profile='d_m=c_m-c_R1', normalization='One global multiplier sqrt(3/sum_m ||d_m||²); model-kernel trace3 matches identity. No whitening or held-out statistics.'),
        stability=dict(empirical_variance_ddof=0, definition='S(q,m)=clip(1-2*(Var5(q,m)+Var5(q,R1)),0,1)',
                       raw_weight='0.05+0.95*abs(delta)*S', floor=WEIGHT_FLOOR,
                       normalization='Divide by development mean separately for each alternative; every output has total weight N, keeping alpha scale fixed.',
                       ties='Every tie retained with strictly positive raw weight0.05; no filtering',
                       limitation='Five-draw empirical consistency heuristic, not true stability probability or a proven noise fraction. No assumed pairing of independent model repeat draws.'),
        predictor=dict(family='linear bilinear query×model kernel Ridge; no MLP',
                       kernel='K((q,m),(q2,m2))=<e_q,e_q2>*<d_m,d_m2>',
                       alpha=ALPHA, intercept='unpenalized in model-feature span, same solver in all four cells',
                       capacity='With3 independent alternative profiles, model-kernel rank3 spans the same linear heads as A; behavior profiles change sharing/regularization geometry, not the available query information.',
                       no_additive_shortcut='A purely additive linear f(e,c) has q-independent model ranking; explicit bilinear interaction is required.'),
        folds='Exact frozen experiment_repeat_compatibility_400_fold_local full development/test IDs; no new inner search',
        fit='12 fixed fits (4 arms×3 folds); all protocol parameters frozen before fitting. No seed/K/alpha/floor search.',
        tie_policy='Original slot-order np.argmax: medium,large,coder,reasoning; no threshold tuning',
        metrics=['outer-test EQ', 'GapRecovery relative train-selected BestSingle and empirical mean5 Oracle', 'method-A gain', 'paired query bootstrap CI', 'factorial interaction D-B-C+A', 'selection distribution'],
        bootstrap=dict(resamples=10000, seed=20260914, unit='400 unique queries, paired across methods; numerator and denominator jointly recomputed for GapRecovery'),
        success='For each B/C/D: EQ>EQ_A AND pointwise paired bootstrap CI95 lower>0. Otherwise do not expand that scheme.',
        decisions='B succeeds alone: supports capability intervention; C succeeds alone: supports weighting intervention; only D succeeds: joint scheme candidate, interaction separately tested; none succeeds: no scheme passes, not proof of equivalence.',
        inference_limits=['Development panel previously enriched and repeatedly used, not independent confirmation.',
                          'Pointwise95% CI is user-frozen success rule; report98.333% Bonferroni intervals as context, without changing rule.',
                          'No-significance is not equivalence; this2×2 cannot uniquely identify the causal failure of the former nonlinear learned-ID MA.',
                          'A is the requested QueryOnly anchor, not the old MA; B tests one behavior-prior representation and C one fixed weighting definition.',
                          'Profiles are learned from development outcomes as supervised representation learning; no outer labels contribute.',
                          'Bootstrap conditional on fitted models/regions, not full retraining uncertainty.'],
        constraints=['Exactly A/B/C/D', 'No new model answers or embeddings', 'No additionalqueries', 'No MA/network/loss/rank/gate search',
                     'No outer-test selection', 'No GitHub push', 'No automatic expansion or next experiment'],
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scipy', 'scikit-learn']},
        hashes={str(p): sha(p) for p in paths})
    write(OUT / 'PROTOCOL.json', protocol)
    status('PREPARED', queries=400, arms=4, planned_fits=12)


def verify():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    for file, digest in protocol['hashes'].items():
        if sha(file) != digest:
            raise ValueError('Frozen input/code changed: ' + file)
    return protocol


def run():
    verify()
    if (OUT / 'FIT_STARTED.json').exists():
        raise FileExistsError('A fit was already started; inspect rather than silently rerun')
    write(OUT / 'FIT_STARTED.json', dict(unix_time=time.time(), protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    ids=z['ids'].tolist(); index={q:i for i,q in enumerate(ids)}
    x=z['x'].astype(float); repeats=z['repeats']; y=z['quality']
    original=np.load(SOURCE/'PREDICTIONS.npz',allow_pickle=False)
    predictions={a:np.zeros((400,4)) for a in ARMS}; baseline=np.empty(400,int)
    records=[]; fold_hashes={}
    for fold in json.loads((OUT/'FOLDS.json').read_text()):
        d=np.array([index[q] for q in fold['development_ids']]); t=np.array([index[q] for q in fold['test_ids']])
        status('FITTING',fold=fold['fold'])
        scores,fits,detail=fit_four(x[d],repeats[d],x[t])
        # Independently reproduce both the original float32 route and algebraic delta equivalence.
        direct=Ridge(alpha=1.).fit(z['x'][d],original['quality'][d]).predict(z['x'][t])
        expected_choice=original['choice_QueryOnlyRidge'][t]
        if not np.array_equal(direct.argmax(1),expected_choice) or not np.array_equal(scores[ARMS[0]].argmax(1),expected_choice):
            raise ValueError('A did not exactly reproduce frozen QueryOnly decisions')
        exact=Ridge(alpha=1.).fit(x[d],y[d]).predict(x[t])
        if not np.allclose(scores[ARMS[0]][:,:3],exact[:,:3]-exact[:,[3]],atol=1e-8,rtol=1e-7):
            raise ValueError('A delta/quality equivalence failed')
        best=int(original['quality'][d].mean(0).argmax());baseline[t]=best
        for arm in ARMS:predictions[arm][t]=scores[arm]
        fdir=OUT/f'fold{fold["fold"]}';fdir.mkdir()
        saved=dict(development_indices=d,test_indices=t,regions=detail['regions'],centers=detail['centers'],
                   delta=detail['delta'],weights=detail['weights'],raw_weights=detail['raw_weights'],stability=detail['stability'])
        for arm in ARMS:
            saved[arm+'_dual']=fits[arm]['dual'];saved[arm+'_bias']=fits[arm]['bias'];saved[arm+'_basis']=fits[arm]['basis']
            saved[arm+'_model_kernel']=fits[arm]['model_kernel'];saved[arm+'_scores']=scores[arm]
        np.savez_compressed(fdir/'FIT.npz',**saved)
        write(fdir/'CAPABILITY_PROFILES.json',detail['profiles'])
        ties=detail['delta']==0;weights=detail['weights']
        record=dict(fold=fold['fold'],development_ids=fold['development_ids'],test_ids=fold['test_ids'],
                    train_n=len(d),test_n=len(t),region_counts=detail['profiles']['region_counts'],
                    model_kernel_eigenvalues=detail['profiles']['eigenvalues'],
                    A_exact_choice_reproduction=True,A_vs_direct_delta_max_abs=float(np.abs(scores[ARMS[0]][:,:3]-(exact[:,:3]-exact[:,[3]])).max()),
                    weighting=dict(tie_pairs=int(ties.sum()),total_pairs=int(ties.size),all_pairs_retained=True,
                                   positive_weight_min=float(weights.min()),max=float(weights.max()),
                                   effective_sample_size_by_alternative=((weights.sum(0)**2)/(weights**2).sum(0)).tolist(),
                                   mean_weight_ties=float(weights[ties].mean()) if ties.any() else None),
                    normal_equation_residuals={a:fits[a]['max_normal_equation_residual'] for a in ARMS})
        records.append(record);fold_hashes[str(fold['fold'])]={p.name:sha(p) for p in fdir.iterdir()}
    np.savez_compressed(OUT/'PREDICTIONS.npz',ids=z['ids'],quality=y,bestsingle_choice=baseline,
                       **{a+'_scores':predictions[a] for a in ARMS},**{a+'_choice':predictions[a].argmax(1) for a in ARMS})
    write(OUT/'FIT_AUDIT.json',records)
    write(OUT/'PREDICTIONS_FROZEN.json',dict(predictions_sha256=sha(OUT/'PREDICTIONS.npz'),protocol_sha256=sha(OUT/'PROTOCOL.json'),
                                          fold_hashes=fold_hashes,fit_audit_sha256=sha(OUT/'FIT_AUDIT.json')))
    status('FITS_COMPLETE',fits=12,baseline_reproduced=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=['prepare','run']);args=ap.parse_args()
    globals()[args.stage]()


if __name__=='__main__':main()
