"""E7: stable-preference representation probe — is the switch signal in the query?

Two frozen supervised tasks from the corrected 5-repeat panel, no router training:
ShouldSwitch(q) (a stable cross-repeat advantage over reasoning exists) and, on
those queries only, WhichAlternative(q) in {medium, large, coder}. Four fixed
representations, dev-fold-fitted scaler + L2 logistic, frozen outer folds.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e7_stable_preference_probe'
E6 = ROOT / 'router_v2/e6_representation_objective_2x2'
PANEL = ROOT / 'router_v2/mmlu_utility_panel_400'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
QWEN = Path('/root/autodl-tmp/models/Qwen2.5-7B-Instruct')
SLOTS = ['medium', 'large', 'coder', 'reasoning']
REF = 3
REPS = ['R0_gte', 'R1_gte_struct', 'R2_qwen', 'R3_all']
CONSISTENCY_MIN = 4
LOGISTIC = dict(C=1.0, penalty='l2', solver='lbfgs', max_iter=5000, random_state=20260914)
SWITCH_THRESHOLD = 0.5
BOOT_N = 10000
BOOT_SEED = 20260914
MATH_CHARS = set('+-*/=^%<>≤≥±×÷√π∑∫−')
CODE_CHARS = set('_{}[];#')
WH_START = re.compile(r'(?i)^\s*(which|what|who|whom|whose|where|when|why|how)\b')
OPTION_LINE = re.compile(r'(?m)^([A-J])\.\s')
MAX_LEN = 2048
BATCH = 8


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def stable_switch_labels(repeats):
    """Frozen: mean5(m-R1)>0 and m>=R1 in >=4/5 repeats; WhichAlt lexicographic."""
    v = np.asarray(repeats, dtype=float)
    if v.ndim != 3 or v.shape[1:] != (4, 5) or not np.isin(v, [0, 1]).all():
        raise ValueError('Expected complete binary n×4×5 repeats')
    delta = v[:, :3, :] - v[:, [REF], :]
    mean5 = delta.mean(2)
    consistency = (delta >= 0).sum(2)
    stable = (mean5 > 0) & (consistency >= CONSISTENCY_MIN)
    switch = stable.any(1)
    rank = mean5 + 1e-9 * consistency
    which = np.where(switch, np.where(stable, rank, -np.inf).argmax(1), -1)
    return stable, switch, which, mean5, consistency


def parse_prompt(text):
    """Deterministic stem/options split on the panel's 'A. ' option lines."""
    matches = list(OPTION_LINE.finditer(text))
    if len(matches) >= 2:
        stem = text[:matches[0].start()]
        lens = [matches[i + 1].start() - matches[i].start() if i + 1 < len(matches) else len(text) - matches[i].start()
                for i in range(len(matches))]
        return stem, lens
    return text, [0]


def structural_features(text):
    stem, option_lens = parse_prompt(text)
    n = max(1, len(stem))
    math_n = sum(ch in MATH_CHARS for ch in stem)
    digits = sum(ch.isdigit() for ch in stem)
    return [np.log1p(len(stem)), np.log1p(len(text)), len(option_lens),
            np.log1p(digits), digits / n, np.log1p(math_n), math_n / n,
            np.log1p(stem.count('$')), np.log1p(sum(ch in CODE_CHARS for ch in text)),
            np.log1p(text.count('\n')), np.log1p(np.mean(option_lens)), np.log1p(max(option_lens)),
            float(stem.rstrip().endswith('?')), float(bool(WH_START.match(stem))),
            np.log1p(len(stem.split()))]


def load_subjects(ids):
    """Subjects live in the E5 snapshot; E6 INPUTS omits them."""
    e5 = np.load(E6 / '../e5_independent_query_learning_curve/INPUTS.npz', allow_pickle=False)
    if e5['ids'].tolist() != ids or 'subjects' not in e5:
        raise ValueError('E5 subject source mismatch')
    return e5['subjects']


def build_representations(subjects):
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    panel = {r['query_id']: r['query'] for r in map(json.loads, (PANEL / 'PANEL.jsonl').open())}
    ids = z['ids'].tolist()
    if set(ids) != set(panel):
        raise ValueError('Panel/id mismatch')
    gte = z['x'].astype(np.float64)
    struct = np.array([structural_features(panel[q]) for q in ids], dtype=float)
    subs, subj_onehot = np.unique(subjects, return_inverse=True)
    onehot = np.eye(len(subs))[subj_onehot]
    qwen = np.load(OUT / 'EMBEDDINGS_QWEN.npz', allow_pickle=False)['qwen'].astype(np.float64)
    if qwen.shape != (len(ids), gte.shape[1]):
        raise ValueError('Qwen embedding shape mismatch')
    blocks = dict(gte=gte, struct=struct, subj=onehot, qwen=qwen)
    return {REPS[0]: gte, REPS[1]: np.hstack([blocks[k] for k in ('gte', 'struct', 'subj')]),
            REPS[2]: qwen, REPS[3]: np.hstack([blocks[k] for k in ('gte', 'struct', 'subj', 'qwen')])}, blocks


def encode():
    import torch
    from transformers import AutoModel, AutoTokenizer
    if OUT.exists():
        raise FileExistsError('E7 output directory already exists')
    OUT.mkdir()
    ids = np.load(E6 / 'INPUTS.npz', allow_pickle=False)['ids'].tolist()
    texts = {r['query_id']: r['query'] for r in map(json.loads, (PANEL / 'PANEL.jsonl').open())}
    if set(ids) != set(texts):
        raise ValueError('Panel/id mismatch')
    ordered = [texts[q] for q in ids]
    tokenizer = AutoTokenizer.from_pretrained(QWEN)
    model = AutoModel.from_pretrained(QWEN, dtype=torch.bfloat16).to('cuda').eval()
    pooled = []
    with torch.inference_mode():
        for i in range(0, len(ordered), BATCH):
            batch = tokenizer(ordered[i:i + BATCH], padding=True, truncation=True,
                              max_length=MAX_LEN, return_tensors='pt').to('cuda')
            hidden = model(**batch).last_hidden_state.float()
            mask = batch['attention_mask'].unsqueeze(-1).float()
            pooled.append(((hidden * mask).sum(1) / mask.sum(1)).cpu().numpy())
    qwen = np.concatenate(pooled).astype(np.float32)
    np.savez_compressed(OUT / 'EMBEDDINGS_QWEN.npz', ids=np.array(ids), qwen=qwen)
    write(OUT / 'ENCODER_PROVENANCE.json', dict(
        model=str(QWEN), dtype='bfloat16', device='cuda', pooling='final-layer attention-masked mean',
        chat_template='none (raw panel query text verbatim)', max_length=MAX_LEN, batch=BATCH,
        shape=list(qwen.shape),
        versions=dict(torch=torch.__version__, transformers=importlib.metadata.version('transformers')),
        hashes=dict(config=sha(QWEN / 'config.json'), tokenizer=sha(QWEN / 'tokenizer_config.json'))))
    status('ENCODED', queries=len(ids), dim=int(qwen.shape[1]))


def fit_linear(x_dev, y_dev):
    scaler = StandardScaler().fit(x_dev)
    clf = LogisticRegression(**LOGISTIC).fit(scaler.transform(x_dev), y_dev)
    return dict(scaler=scaler, clf=clf)


def stage2_apply(model, x):
    proba = model['clf'].predict_proba(model['scaler'].transform(x))
    return model['clf'].classes_[proba.argmax(1)]


def prepare():
    if not (OUT / 'EMBEDDINGS_QWEN.npz').exists():
        raise FileNotFoundError('Run encode first')
    e6_protocol = json.loads((E6 / 'PROTOCOL.json').read_text())
    frozen = json.loads((E6 / 'PREDICTIONS_FROZEN.json').read_text())
    if sha(E6 / 'INPUTS.npz') != e6_protocol['hashes'][str(E6 / 'INPUTS.npz')]:
        raise ValueError('E6 inputs changed')
    if sha(E6 / 'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('E6 protocol changed')
    manifest = json.loads((PANEL / 'MANIFEST.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(PANEL / name) != digest:
            raise ValueError('Panel changed')
    if sha(LABELS) != json.loads((LABELS.parent / 'STATUS.json').read_text())['labels_sha256']:
        raise ValueError('Labels changed')
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    folds = json.loads((E6 / 'FOLDS.json').read_text())
    subjects = load_subjects(z['ids'].tolist())
    stable, switch, which, mean5, consistency = stable_switch_labels(z['repeats'])
    reps, blocks = build_representations(subjects)
    write(OUT / 'FOLDS.json', folds)
    np.savez_compressed(OUT / 'INPUTS.npz', ids=z['ids'], repeats=z['repeats'], quality=z['quality'],
                        groups=z['groups'], subjects=subjects, outer_fold=z['outer_fold'],
                        stable=stable, switch=switch, which=which, delta_mean5=mean5, consistency=consistency)
    subs = np.unique(subjects)
    np.savez_compressed(OUT / 'FEATURE_BLOCKS.npz', ids=z['ids'], subjects=subs, **blocks)
    paths = [Path(__file__), Path(__file__).with_name('summarize_e7_stable_preference_probe.py'),
             Path(__file__).with_name('test_e7_stable_preference_probe.py'),
             E6 / 'INPUTS.npz', E6 / 'FOLDS.json', E6 / 'PROTOCOL.json', E6 / 'PREDICTIONS_FROZEN.json',
             PANEL / 'MANIFEST.json', PANEL / 'PANEL.jsonl', LABELS, OUT / 'EMBEDDINGS_QWEN.npz',
             OUT / 'ENCODER_PROVENANCE.json', OUT / 'INPUTS.npz', OUT / 'FOLDS.json']
    protocol = dict(
        experiment='E7 Stable Preference Representation Probe', representations=REPS,
        question='Does the query representation carry enough signal to decide when to leave R1 (reasoning), and for whom?',
        labels=dict(source='corrected 5-repeat utility panel (E6-verified)',
                    stable_advantage='mean5(m)>mean5(reasoning) AND #{r: V(q,m,r)>=V(q,reasoning,r)} >= 4/5',
                    should_switch='any stable advantage among medium/large/coder',
                    which_alternative='argmax over stable m by (mean5 delta, consistency, slot order)',
                    counts=dict(switch_queries=int(switch.sum()), stable_pairs=int(stable.sum()),
                                which_distribution={SLOTS[m]: int((which == m).sum()) for m in range(3)}),
                    decomposed_oracle_eq=float(np.where(switch, np.max(np.where(stable, z['quality'][:, :3], -9), 1),
                                                         z['quality'][:, REF]).mean()),
                    note='Decomposed oracle equals the 81.00% hindsight oracle: the two-stage split is lossless.'),
        representations_detail=dict(
            R0_gte='frozen Original GTE-Qwen2-7B-instruct embedding (same features as A in E6)',
            R1_gte_struct='R0 + 15 deterministic structural features + 14 subject one-hot (control)',
            R2_qwen='Qwen2.5-7B-Instruct final-layer hidden state, raw panel text, masked mean pool, no generation',
            R3_all='concatenation of R1 blocks and R2',
            structural='log stem/total chars, n options, digit & math-symbol counts+densities, $ count, code-hint count, newlines, option length mean/max, ends-?, Wh-start, stem words; frozen char sets in code'),
        classifier=dict(stage1='StandardScaler(dev) + L2 logistic C=1.0 lbfgs, threshold 0.5 frozen',
                        stage2='same estimator on dev stable-switch queries only; argmax over available classes',
                        no_pca='PCA not used; identical pipeline across representations',
                        fit='scaler/logistic/threshold fitted or fixed on development fold only',
                        sensitivity='threshold=development switch base rate reported as non-decisional sensitivity'),
        folds='E6 frozen 3 outer folds verbatim', success='EQ>73.50% (E6 A_QueryOnly) AND paired query bootstrap CI95 lower>0 vs A; sole criterion, AUC/F1 are diagnostics only',
        bootstrap=dict(resamples=BOOT_N, seed=BOOT_SEED, unit='400 unique queries',
                       bonferroni='98.75% intervals for 4 representations vs A reported as context'),
        branches=dict(on_pass='integrate the winning representation back into the MA router',
                      on_fail='stop pure query-only static routing; move to query -> cheap model probe/partial response -> routing'),
        constraints=['No new model answers except local Qwen forward passes', 'No threshold/hyperparameter search',
                     'No PCA/MLP/deeper networks', 'No additional queries', 'No outer-test selection'],
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scikit-learn']},
        hashes={str(p): sha(p) for p in paths})
    write(OUT / 'PROTOCOL.json', protocol)
    status('PREPARED', switch_queries=int(switch.sum()), representations=len(REPS))


def run():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    for file, digest in protocol['hashes'].items():
        if sha(file) != digest:
            raise ValueError('Frozen input/code changed: ' + file)
    if (OUT / 'EVAL_STARTED.json').exists():
        raise FileExistsError('Evaluation already started')
    write(OUT / 'EVAL_STARTED.json', dict(unix_time=time.time(), protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    reps, _ = build_representations(load_subjects(z['ids'].tolist()))
    ids = z['ids'].tolist()
    index = {q: i for i, q in enumerate(ids)}
    switch = z['switch']
    which = z['which']
    p1 = {r: np.zeros(len(ids)) for r in REPS}
    routed = {r: np.full(len(ids), REF, dtype=int) for r in REPS}
    alt_unconditional = {r: np.full(len(ids), -1, dtype=int) for r in REPS}
    sensitivity_routed = {r: np.full(len(ids), REF, dtype=int) for r in REPS}
    audit = []
    for fold in json.loads((OUT / 'FOLDS.json').read_text()):
        d = np.array([index[q] for q in fold['development_ids']])
        t = np.array([index[q] for q in fold['test_ids']])
        status('EVALUATING', fold=fold['fold'])
        base_rate = float(switch[d].mean())
        for rep in REPS:
            x = reps[rep]
            s1 = fit_linear(x[d], switch[d])
            p = s1['clf'].predict_proba(s1['scaler'].transform(x[t]))[:, 1]
            p1[rep][t] = p
            dev_switch = d[switch[d]]
            s2 = fit_linear(x[dev_switch], which[dev_switch])
            alt = stage2_apply(s2, x[t])
            alt_unconditional[rep][t] = alt
            routed[rep][t] = np.where(p >= SWITCH_THRESHOLD, alt, REF)
            sensitivity_routed[rep][t] = np.where(p >= base_rate, alt, REF)
            audit.append(dict(fold=fold['fold'], rep=rep, dev_n=int(len(d)), test_n=int(len(t)),
                              dev_switch=int(switch[d].sum()), dev_base_rate=base_rate,
                              stage2_classes=[SLOTS[c] for c in s2['clf'].classes_.tolist()],
                              predicted_switch_05=int((p >= SWITCH_THRESHOLD).sum()),
                              predicted_switch_baserate=int((p >= base_rate).sum())))
    np.savez_compressed(OUT / 'PREDICTIONS.npz', ids=z['ids'], quality=z['quality'],
                        **{f'{r}__p1': p1[r] for r in REPS},
                        **{f'{r}__routed': routed[r] for r in REPS},
                        **{f'{r}__alt_unconditional': alt_unconditional[r] for r in REPS},
                        **{f'{r}__sensitivity_routed': sensitivity_routed[r] for r in REPS})
    write(OUT / 'FIT_AUDIT.json', audit)
    write(OUT / 'PREDICTIONS_FROZEN.json', dict(predictions_sha256=sha(OUT / 'PREDICTIONS.npz'),
                                                protocol_sha256=sha(OUT / 'PROTOCOL.json'),
                                                fit_audit_sha256=sha(OUT / 'FIT_AUDIT.json')))
    status('EVAL_COMPLETE', representations=len(REPS), folds=3)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['encode', 'prepare', 'run'])
    args = ap.parse_args()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
