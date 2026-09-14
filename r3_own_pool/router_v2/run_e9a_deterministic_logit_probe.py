"""E9a: deterministic logit probe — stable option-confidence signal without sampling.

One local Qwen2.5-7B-Instruct forward per query (no generation): append the
frozen suffix 'Answer:' to the raw panel prompt and read the next-token
distribution over the ten option-letter tokens. Three fixed arms on the frozen
E6 folds: A query-only (must reproduce E6 A exactly), B + logit statistics,
C + full option probability vector. No hidden states, structural features,
latency, or response lengths.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import time

import numpy as np
from sklearn.linear_model import Ridge

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e9a_deterministic_logit_probe'
E6 = ROOT / 'router_v2/e6_representation_objective_2x2'
E7 = ROOT / 'router_v2/e7_stable_preference_probe'
RAW = ROOT / 'data/repeat_compatibility_400'
LABELS = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
PANEL = ROOT / 'router_v2/mmlu_utility_panel_400'
QWEN = Path('/root/autodl-tmp/models/Qwen2.5-7B-Instruct')
SLOTS = ['medium', 'large', 'coder', 'reasoning']
OPTIONS = 'ABCDEFGHIJ'
ARMS = ['A_query', 'B_logit_stats', 'C_prob_vector']
SUFFIX = '\n\nAnswer:'
ALPHA = 1.0
BATCH = 8


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def fit_probe_lm_logits():
    """Score option letters with the LM head in one deterministic forward per query."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    OUT.mkdir(exist_ok=True)
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    ids = z['ids'].tolist()
    texts = {r['query_id']: r['query'] for r in map(json.loads, (PANEL / 'PANEL.jsonl').open())}
    ordered = [texts[q] + SUFFIX for q in ids]
    tokenizer = AutoTokenizer.from_pretrained(QWEN)
    letter_ids = []
    for letter in OPTIONS:
        piece = tokenizer.encode(' ' + letter, add_special_tokens=False)
        if len(piece) != 1:
            raise ValueError(f'Option letter is not a single token: {letter!r} -> {piece}')
        letter_ids.append(piece[0])
    if len(set(letter_ids)) != 10:
        raise ValueError('Letter tokens collide')
    model = AutoModelForCausalLM.from_pretrained(QWEN, dtype=torch.bfloat16).to('cuda').eval()
    probs = np.zeros((len(ordered), 10), dtype=np.float64)
    with torch.inference_mode():
        for i in range(0, len(ordered), BATCH):
            batch = tokenizer(ordered[i:i + BATCH], padding=True, truncation=True,
                              max_length=2048, return_tensors='pt').to('cuda')
            logits = model(**batch).logits[:, -1, :].float()  # last position: next-token logits
            letter_logits = logits[:, letter_ids]
            probs[i:i + BATCH] = torch.softmax(letter_logits, dim=-1).cpu().numpy()
    np.savez_compressed(OUT / 'LOGIT_PROBES.npz', ids=np.array(ids), probs=probs,
                        letter_token_ids=np.array(letter_ids))
    write(OUT / 'PROBE_PROVENANCE.json', dict(
        model=str(QWEN), dtype='bfloat16', device='cuda', mode='greedy forward, no generation',
        prompt='raw panel query verbatim + frozen suffix \\n\\nAnswer:',
        distribution='softmax over next-token logits of the 10 option-letter tokens (" A".." J")',
        batch=BATCH, max_length=2048,
        versions=dict(torch=torch.__version__, transformers=importlib.metadata.version('transformers')),
        hashes=dict(config=sha(QWEN / 'config.json'))))
    status('ENCODED', queries=len(ids))


def logit_statistics(probs):
    """16 frozen features: top-1 one-hot(10), top-1 prob, margin, entropy, variance, majority-consistency(2)."""
    top1 = probs.argmax(1)
    sorted_probs = np.sort(probs, axis=1)
    p1, p2 = sorted_probs[:, -1], sorted_probs[:, -2]
    entropy = -(probs * np.log(np.clip(probs, 1e-12, None))).sum(1)
    variance = probs.var(1)
    return np.column_stack([np.eye(10)[top1], p1, p1 - p2, entropy, variance]), top1


def sampled_majority_options(ids):
    """Majority parsed option of the medium model's 5 sampled repeats; no ground truth."""
    rows = {}
    for line in (RAW / 'medium.jsonl').open():
        r = json.loads(line)
        rows.setdefault(r['query_id'], []).append(r)
    letters = np.full(len(ids), -1, dtype=int)
    exists = np.zeros(len(ids), dtype=float)
    for i, q in enumerate(ids):
        parsed = [r.get('extracted_option') for r in rows.get(q, []) if r.get('parse_succeeded')
                  and r.get('extracted_option') in OPTIONS]
        if not parsed:
            continue
        counts = np.bincount([OPTIONS.index(o) for o in parsed], minlength=10)
        best = counts.max()
        if (counts == best).sum() == 1:
            letters[i] = int(counts.argmax())
            exists[i] = 1.0
    return letters, exists


def build_features(e, probs, ids):
    stats, top1 = logit_statistics(probs)
    majority, exists = sampled_majority_options(ids)
    match = (exists * (top1 == majority).astype(float)).reshape(-1, 1)
    stats_full = np.hstack([stats, exists.reshape(-1, 1), match])
    return {'A_query': e,
            'B_logit_stats': np.hstack([e, stats_full]),
            'C_prob_vector': np.hstack([e, probs])}, dict(top1=top1, majority=majority, exists=exists)


def choose(pred_delta):
    return np.argmax(np.column_stack([pred_delta, np.zeros(len(pred_delta))]), axis=1)


def prepare():
    if not (OUT / 'LOGIT_PROBES.npz').exists():
        raise FileNotFoundError('Run encode first')
    e6_protocol = json.loads((E6 / 'PROTOCOL.json').read_text())
    frozen = json.loads((E6 / 'PREDICTIONS_FROZEN.json').read_text())
    if sha(E6 / 'INPUTS.npz') != e6_protocol['hashes'][str(E6 / 'INPUTS.npz')]:
        raise ValueError('E6 inputs changed')
    if sha(E6 / 'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('E6 protocol changed')
    if sha(LABELS) != json.loads((LABELS.parent / 'STATUS.json').read_text())['labels_sha256']:
        raise ValueError('Labels changed')
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    probe = np.load(OUT / 'LOGIT_PROBES.npz', allow_pickle=False)
    if probe['ids'].tolist() != z['ids'].tolist() or probe['probs'].shape != (400, 10):
        raise ValueError('Probe matrix mismatch')
    if not np.allclose(probe['probs'].sum(1), 1.0, atol=1e-6):
        raise ValueError('Probe rows are not distributions')
    OUT.mkdir(exist_ok=True)
    write(OUT / 'FOLDS.json', json.loads((E6 / 'FOLDS.json').read_text()))
    np.savez_compressed(OUT / 'INPUTS.npz', ids=z['ids'], x=z['x'], repeats=z['repeats'],
                        quality=z['quality'], groups=z['groups'], outer_fold=z['outer_fold'],
                        probe_probs=probe['probs'])
    paths = [Path(__file__), Path(__file__).with_name('summarize_e9a_deterministic_logit_probe.py'),
             Path(__file__).with_name('test_e9a_deterministic_logit_probe.py'),
             E6 / 'INPUTS.npz', E6 / 'FOLDS.json', E6 / 'PROTOCOL.json', E6 / 'PREDICTIONS_FROZEN.json',
             E6 / 'PREDICTIONS.npz', E7 / 'PROTOCOL.json', LABELS, RAW / 'medium.jsonl',
             PANEL / 'MANIFEST.json', PANEL / 'PANEL.jsonl',
             OUT / 'LOGIT_PROBES.npz', OUT / 'PROBE_PROVENANCE.json', OUT / 'INPUTS.npz', OUT / 'FOLDS.json']
    write(OUT / 'PROTOCOL.json', dict(
        experiment='E9a Deterministic Logit Probe', arms=ARMS,
        question='Does a deterministic option-confidence profile (one Qwen2.5-7B forward, no sampling) carry routing signal that query-only lacks?',
        probe=dict(model='local Qwen2.5-7B-Instruct (medium slot model)', prompt='raw panel query + frozen suffix Answer:',
                   readout='softmax over next-token logits of the 10 option-letter tokens A-J at the suffix position',
                   determinism='greedy forward, temperature-free, single pass, no generation',
                   consistency_feature='top-1 option equals the majority parsed option of the medium 5 sampled repeats (no ground truth)'),
        arms_detail=dict(A_query='GTE embedding only; must reproduce E6 A choices exactly',
                         B_logit_stats='query + top-1 one-hot(10) + top-1 prob + top-2 margin + entropy + prob variance + majority-exists + top1-equals-majority (3584+16)',
                         C_prob_vector='query + full 10-dim option probability vector (3584+10)'),
        target='mean5 quality difference vs R1 (identical to E6 A); Ridge alpha=1 three delta heads, R1 score 0, first-max tie order',
        folds='E6 frozen folds', evaluation='outer-test mean5 EQ, identical scale to the 73.50% anchor',
        bootstrap=dict(resamples=10000, seed=20260914, unit='400 unique queries',
                       bonferroni='97.5% intervals for B/C vs A reported as context'),
        success='EQ>73.50% AND paired query bootstrap CI95 lower>0 vs A; AUC-style metrics are diagnostics only',
        branches=dict(on_pass='final method candidate: Query Representation + Model Confidence Profile router',
                      on_fail='one small-scale E9b pilot (cheap partial response + verifier/confidence); if that fails, stop signal search and re-scope the thesis'),
        inference_limits=['Probe distribution is measured on the raw prompt without CoT; a CoT-conditioned distribution may differ.',
                          'Consistency feature uses the five historical medium repeats (deployment would use fresh samples).',
                          'Bootstrap conditions on fitted models.'],
        constraints=['Zero generation (forward pass only)', 'No ground truth in any feature', 'No hidden states/structure/latency/length features',
                     'No hyperparameter or threshold search', 'No additional queries', 'No outer-test selection'],
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scikit-learn']},
        hashes={str(p): sha(p) for p in paths}))
    status('PREPARED', arms=len(ARMS))


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
    quality = z['quality']
    e = z['x'].astype(np.float64)
    arms_x, detail = build_features(e, z['probe_probs'], ids)
    targets = quality[:, :3] - quality[:, [3]]
    e6 = np.load(E6 / 'PREDICTIONS.npz', allow_pickle=False)
    anchor_choice = e6['A_QueryOnly_choice']
    n = len(ids)
    choices, eq = {}, {}
    for arm in ARMS:
        choices[arm] = np.zeros(n, dtype=int)
        eq[arm] = np.zeros(n)
    for fold in json.loads((OUT / 'FOLDS.json').read_text()):
        d = np.array([index[q] for q in fold['development_ids']])
        t = np.array([index[q] for q in fold['test_ids']])
        status('EVALUATING', fold=fold['fold'])
        for arm in ARMS:
            model = Ridge(alpha=ALPHA).fit(arms_x[arm][d], targets[d])
            pick = choose(model.predict(arms_x[arm][t]))
            choices[arm][t] = pick
            eq[arm][t] = quality[t, pick]
    if not np.array_equal(choices[ARMS[0]], anchor_choice):
        raise ValueError('A did not exactly reproduce E6 QueryOnly decisions')
    np.savez_compressed(OUT / 'PREDICTIONS.npz', ids=z['ids'], quality=quality,
                        anchor_choice=anchor_choice, probe_top1=detail['top1'],
                        sampled_majority=detail['majority'], majority_exists=detail['exists'],
                        **{f'{a}__choice': choices[a] for a in ARMS},
                        **{f'{a}__eq': eq[a] for a in ARMS})
    write(OUT / 'PREDICTIONS_FROZEN.json', dict(predictions_sha256=sha(OUT / 'PREDICTIONS.npz'),
                                                protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    status('EVAL_COMPLETE', arms=len(ARMS), a_reproduced=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['encode', 'prepare', 'run'])
    args = ap.parse_args()
    if args.stage == 'encode':
        fit_probe_lm_logits()
    else:
        globals()[args.stage]()


if __name__ == '__main__':
    main()
