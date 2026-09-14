"""E8: behavior-probe feasibility — does observed cheap-model behavior beat query-only?

Four fixed arms on the existing 400x4x5 raw repeats, zero new generation. Every
repeat j is identified by its file-order position, the same axis every previous
experiment used for `values`. Rotations: probe repeat p, evaluation repeat r
(p != r), the remaining three repeats define the routing target. Probe features
are inference-observable only (option letter, length, tokens, latency, parse
status, Medium/Large agreement); no ground truth enters any feature.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
from sklearn.linear_model import Ridge

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e8_behavior_probe_feasibility'
E6 = ROOT / 'router_v2/e6_representation_objective_2x2'
RAW = ROOT / 'data/repeat_compatibility_400'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
PROBES = ['medium', 'large']
OPTIONS = 'ABCDEFGHIJ'
ARMS = ['A_query', 'B_medium_probe', 'C_large_probe', 'D_joint_probe']
ALPHA = 1.0
ROTATIONS = [(p, r) for p in range(5) for r in range(5) if p != r]


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def load_raw_aligned(ids):
    """File-order alignment: values[k] <-> k-th raw row of that (query, slot).

    Verified against the rescore extractor (rows collected in file order) and
    against the E6 INPUTS repeat matrix.
    """
    labels = {r['query_id']: r for r in map(json.loads, LABELS.open())}
    rows = {s: {} for s in SLOTS}
    for s in SLOTS:
        for line in (RAW / f'{s}.jsonl').open():
            r = json.loads(line)
            rows[s].setdefault(r['query_id'], []).append(r)
    v = np.zeros((len(ids), 4, 5))
    raw = {s: np.empty(len(ids), dtype=object) for s in SLOTS}
    for i, q in enumerate(ids):
        for j, s in enumerate(SLOTS):
            block = rows[s][q]
            if len(block) != 5:
                raise ValueError(f'Expected 5 repeats: {s}/{q}')
            raw[s][i] = block
            for k in range(5):
                v[i, j, k] = labels[q]['models'][s]['values'][k]
    return v, raw


def probe_features(row):
    """20 frozen inference-observable features for one raw repeat row."""
    answer = row.get('answer') or ''
    parsed = bool(row.get('parse_succeeded'))
    option = str(row.get('extracted_option') or '')
    onehot = [float(parsed and option == letter) for letter in OPTIONS]
    cost = row.get('cost') or {}
    latency = row.get('latency') or {}
    tps = latency.get('tokens_per_second') or 0
    return np.array([float(parsed), float(not parsed), *onehot,
                     np.log1p(len(answer)), np.log1p(cost.get('tokens_output') or 0),
                     np.log1p(latency.get('total_ms') or 0), np.log1p(tps),
                     float(row.get('finish_reason') == 'stop'),
                     float(row.get('status') == 'ok')], dtype=float)


def joint_features(z_medium, z_large):
    """4 frozen joint features: agreement one-hot + output-length gap."""
    parsed_m, parsed_l = z_medium[0] > .5, z_large[0] > .5
    om, ol = z_medium[2:12], z_large[2:12]
    if parsed_m and parsed_l:
        agree, disagree = float(om @ ol > .5), float(om @ ol <= .5)
    else:
        agree = disagree = 0.0
    either_unparsed = float(not (parsed_m and parsed_l))
    return np.array([agree, disagree, either_unparsed, abs(z_medium[13] - z_large[13])])


def arm_probe_features(raw, n, slot, probe_repeat):
    return np.array([probe_features(raw[slot][i][probe_repeat]) for i in range(n)])


def build_arm_features(e, raw, probe_repeat):
    zm = arm_probe_features(raw, len(e), 'medium', probe_repeat)
    zl = arm_probe_features(raw, len(e), 'large', probe_repeat)
    joint = np.array([joint_features(zm[i], zl[i]) for i in range(len(e))])
    return {'A_query': e,
            'B_medium_probe': np.hstack([e, zm]),
            'C_large_probe': np.hstack([e, zl]),
            'D_joint_probe': np.hstack([e, zm, zl, joint])}


def rotation_targets(v, p, r):
    keep = [t for t in range(5) if t not in (p, r)]
    return v[:, :3, keep].mean(2) - v[:, 3, keep].mean(1)[:, None]


def fit_arm(x_dev, target_dev):
    return Ridge(alpha=ALPHA).fit(x_dev, target_dev)


def choose(pred_delta):
    """argmax over [medium, large, coder, R1=0]; first-max tie order as in E6."""
    return np.argmax(np.column_stack([pred_delta, np.zeros(len(pred_delta))]), axis=1)


def prepare():
    if OUT.exists():
        raise FileExistsError('E8 output directory already exists')
    e6_protocol = json.loads((E6 / 'PROTOCOL.json').read_text())
    frozen = json.loads((E6 / 'PREDICTIONS_FROZEN.json').read_text())
    if sha(E6 / 'INPUTS.npz') != e6_protocol['hashes'][str(E6 / 'INPUTS.npz')]:
        raise ValueError('E6 inputs changed')
    if sha(E6 / 'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('E6 protocol changed')
    if sha(LABELS) != json.loads((LABELS.parent / 'STATUS.json').read_text())['labels_sha256']:
        raise ValueError('Labels changed')
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    ids = z['ids'].tolist()
    v, raw = load_raw_aligned(ids)
    if not np.array_equal(v, z['repeats']):
        raise ValueError('File-order alignment does not reproduce the E6 repeat matrix')
    OUT.mkdir()
    write(OUT / 'FOLDS.json', json.loads((E6 / 'FOLDS.json').read_text()))
    np.savez_compressed(OUT / 'INPUTS.npz', ids=z['ids'], x=z['x'], repeats=v, quality=z['quality'],
                        groups=z['groups'], outer_fold=z['outer_fold'])
    cost_stats = {}
    for s in SLOTS:
        lengths = np.array([len(r.get('answer') or '') for block in raw[s] for r in block], dtype=float)
        tokens = np.array([(r.get('cost') or {}).get('tokens_output') or 0 for block in raw[s] for r in block], dtype=float)
        latency = np.array([(r.get('latency') or {}).get('total_ms') or 0 for block in raw[s] for r in block], dtype=float)
        cost_stats[s] = dict(model=raw[s][0][0].get('model'),
                             tokens_output_p50=float(np.median(tokens)), latency_ms_p50=float(np.median(latency)),
                             answer_chars_p50=float(np.median(lengths)))
    paths = [Path(__file__), Path(__file__).with_name('summarize_e8_behavior_probe_feasibility.py'),
             Path(__file__).with_name('test_e8_behavior_probe_feasibility.py'),
             E6 / 'INPUTS.npz', E6 / 'FOLDS.json', E6 / 'PROTOCOL.json', E6 / 'PREDICTIONS_FROZEN.json',
             E6 / 'PREDICTIONS.npz', LABELS, *[RAW / f'{s}.jsonl' for s in SLOTS], OUT / 'INPUTS.npz', OUT / 'FOLDS.json']
    protocol = dict(
        experiment='E8 Behavior-Probe Feasibility', arms=ARMS,
        question='Does observing a cheap model actually run on the query (probe behavior) beat query-only routing?',
        alignment='Repeat identity = file-order position in raw jsonl, the same axis as labels values; verified by exact reproduction of the E6 repeat matrix',
        rotations=dict(pairs=[list(pair) for pair in ROTATIONS], rule='probe repeat p, evaluation repeat r, p!=r; remaining 3 repeats define the target',
                       statistics='Bootstrap unit is the query; rotations are averaged within query before any inference'),
        target='mean over the 3 target repeats of V(q,m)-V(q,R1), m in {medium,large,coder}; Ridge alpha=1 per delta head, R1 score fixed 0, first-max tie order medium<large<coder<reasoning',
        probe_features=dict(source='raw repeat row of the probe model at repeat p only; never r, never target repeats, no ground truth',
                            per_probe='parse flags(2) + option one-hot A-J(10) + log answer chars + log tokens_output + log latency_ms + log tokens_per_second + finish=stop + status=ok (18 dims)',
                            joint='agreement one-hot(agree/disagree/either-unparsed) + |log-token gap| (4 dims)',
                            arms=dict(A_query='GTE query embedding only',
                                      B_medium_probe='query + medium@p',
                                      C_large_probe='query + large@p',
                                      D_joint_probe='query + medium@p + large@p + joint')),
        evaluation='V(q, choice(q,p), r) averaged over the 20 rotations within each query; A_anchor = frozen E6 QueryOnly choices evaluated on identical rotations (rotation-mean equals its 73.50% mean5 EQ by construction)',
        cost_report='median tokens_output and latency per slot from the raw runs (probe cost is paid on every query; routed model cost reported per selection)',
        bootstrap=dict(resamples=10000, seed=20260914, unit='400 unique queries',
                       bonferroni='98.33% intervals for B/C/D vs A reported as context'),
        success='EQ>73.50% (anchor) AND paired query bootstrap CI95 lower>0 vs in-protocol A; switch precision/recall and helped/harmed are diagnostics',
        inference_limits=['Historical latency/tokens are infra-specific proxies for probe cost, not re-measured.',
                          'Probe repeats were generated at temperature 0.7 like all repeats; a deployed probe sees one fresh draw.',
                          'Bootstrap conditions on fitted models; no full retraining uncertainty.',
                          'AUC-style classification metrics are not success criteria.'],
        constraints=['Zero new generation', 'No ground truth in any probe feature', 'No threshold/hyperparameter search',
                     'No partial-CoT or complex probes in this version', 'No additional queries', 'No outer-test selection'],
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scikit-learn']},
        slot_cost=cost_stats,
        hashes={str(p): sha(p) for p in paths})
    write(OUT / 'PROTOCOL.json', protocol)
    status('PREPARED', arms=len(ARMS), rotations=len(ROTATIONS))


def run():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    for file, digest in protocol['hashes'].items():
        if sha(file) != digest:
            raise ValueError('Frozen input/code changed: ' + file)
    if (OUT / 'EVAL_STARTED.json').exists():
        raise FileExistsError('Evaluation already started')
    write(OUT / 'EVAL_STARTED.json', dict(unix_time=time.time(), protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    ids = z['ids'].tolist()
    index = {q: i for i, q in enumerate(ids)}
    v = z['repeats']
    e = z['x'].astype(np.float64)
    _, raw = load_raw_aligned(ids)
    e6 = np.load(E6 / 'PREDICTIONS.npz', allow_pickle=False)
    anchor_choice = e6['A_QueryOnly_choice']
    if e6['ids'].tolist() != ids:
        raise ValueError('E6 anchor id mismatch')
    n = len(ids)
    eq = {a: np.zeros((n, len(ROTATIONS))) for a in ARMS}
    anchor_eq = np.zeros((n, len(ROTATIONS)))
    choices = {a: np.zeros((n, len(ROTATIONS)), dtype=int) for a in ARMS}
    for k, (p, r) in enumerate(ROTATIONS):
        status('EVALUATING', probe_repeat=p, eval_repeat=r, step=k + 1, total=len(ROTATIONS))
        targets = rotation_targets(v, p, r)
        arms_x = build_arm_features(e, raw, p)
        for fold in json.loads((OUT / 'FOLDS.json').read_text()):
            d = np.array([index[q] for q in fold['development_ids']])
            t = np.array([index[q] for q in fold['test_ids']])
            for arm in ARMS:
                model = fit_arm(arms_x[arm][d], targets[d])
                pick = choose(model.predict(arms_x[arm][t]))
                choices[arm][t, k] = pick
                eq[arm][t, k] = v[t, pick, r]
            anchor_eq[t, k] = v[t, anchor_choice[t], r]
    per_query_anchor = anchor_eq.mean(1)
    if not np.allclose(per_query_anchor, z['quality'][np.arange(n), anchor_choice], atol=1e-12):
        raise ValueError('Anchor rotation-mean does not equal its mean5 EQ')
    np.savez_compressed(OUT / 'PREDICTIONS.npz', ids=z['ids'], quality=z['quality'],
                        anchor_choice=anchor_choice, anchor_eq=per_query_anchor,
                        **{f'{a}__eq': eq[a].mean(1) for a in ARMS},
                        **{f'{a}__eq_matrix': eq[a] for a in ARMS},
                        **{f'{a}__choice': choices[a] for a in ARMS},
                        rotations=np.array(ROTATIONS))
    write(OUT / 'PREDICTIONS_FROZEN.json', dict(predictions_sha256=sha(OUT / 'PREDICTIONS.npz'),
                                                protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    status('EVAL_COMPLETE', arms=len(ARMS), rotations=len(ROTATIONS))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['prepare', 'run'])
    args = ap.parse_args()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
