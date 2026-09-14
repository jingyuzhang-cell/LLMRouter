"""Frozen, local-only GTE input ablations on the existing 400-query panel.

prepare/encode use prompt text only. evaluate uses frozen fold allowlists and
leave-one-repeat-out targets, with no hyperparameter search or method selection.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e4_representation_20260914'
PANEL = ROOT / 'router_v2/mmlu_utility_panel_400'
BASE = ROOT / 'router_v2/experiment_repeat_compatibility_400_fold_local'
LABEL = ROOT / 'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
OLD_EMBED = ROOT / 'data/embeddings_full_v2_recovery1'
MODEL = Path('/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16')
SLOTS = ['medium', 'large', 'coder', 'reasoning']
VARIANTS = ['Original', 'Content', 'Stem', 'Options', 'SplitConcat']
SEED = 20260914
FOOTER = "\n\nLet's think step by step."


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def parse_prompt(query):
    """Reject unfamiliar formats; preserve subject and all supplied option text."""
    header, sep, body = query.partition('\n\n')
    match = re.fullmatch(
        r"Answer the following ([a-z ]+) question\. The last line of your response should be of the following format: 'Answer: \$LETTER' \(without quotes\) where LETTER is one of ABCDEFGHIJ\.",
        header,
    )
    if not match or not sep or not body.endswith(FOOTER):
        raise ValueError('Unrecognized prompt wrapper')
    body = body[:-len(FOOTER)]
    markers = list(re.finditer(r'(?m)^([A-J])\. ', body))
    if ''.join(m.group(1) for m in markers) != 'ABCDEFGHIJ':
        raise ValueError('Expected exactly ten ordered option markers')
    boundary = markers[0].start()
    if not body[:boundary].endswith('\n\n'):
        raise ValueError('Missing stem/options separator')
    stem, options = body[:boundary - 2], body[boundary:]
    if not stem.strip() or any(
        not body[m.end():markers[j + 1].start() if j < 9 else len(body)].strip()
        for j, m in enumerate(markers)
    ):
        raise ValueError('Empty stem or option')
    assert header + '\n\n' + stem + '\n\n' + options + FOOTER == query
    prefix = f'Subject: {match.group(1)}\n\n'
    return dict(subject=match.group(1), Content=prefix + body,
                Stem=prefix + stem, Options=prefix + options)


def prepare():
    OUT.mkdir(exist_ok=False)
    manifest = json.loads((PANEL / 'MANIFEST.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(PANEL / name) != digest:
            raise ValueError('Panel changed')
    rows = sorted((json.loads(s) for s in (PANEL / 'PANEL.jsonl').open()),
                  key=lambda r: r['query_id'])
    if len(rows) != 400 or len({r['query_id'] for r in rows}) != 400:
        raise ValueError('Expected 400 distinct prompts')
    texts = [dict(query_id=r['query_id'], **parse_prompt(r['query'])) for r in rows]
    text_path = OUT / 'TEXTS.jsonl'
    text_path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in texts))
    paths = [Path(__file__), text_path, PANEL / 'PANEL.jsonl', PANEL / 'MANIFEST.json',
             PANEL / 'FOLD_SELECTION.json', BASE / 'FOLDS.json', BASE / 'PREDICTIONS.npz',
             LABEL, OLD_EMBED / 'PLAN.json', OLD_EMBED / 'PROVENANCE.json',
             OLD_EMBED / 'EMBEDDINGS.npz', Path(manifest['groups']),
             ROOT / 'router_v2/e3_repeat_generalization_20260914/PER_QUERY.npz',
             Path(__file__).with_name('diagnose_rank_signal.py'),
             Path(__file__).with_name('data.py')]
    protocol = dict(
        role='exploratory ablation on an already-used, opportunity-enriched development panel',
        variants=VARIANTS, alpha=1.0, slots=SLOTS,
        primary='SplitConcat minus Original, query-fold-disjoint leave-one-repeat-out EQ',
        secondary='Each variant minus development-selected BestSingle; five-repeat-mean OOF',
        encoder='Same local GTE, fp16, batch1, normalized, no instruction prompt, no truncation',
        inputs='Subject retained identically in all three new text views; no response or correct answer',
        concatenation='concat(unit Stem, unit Options)/sqrt(2); unit norm, equal-weight sum of kernels',
        folds='Exact original frozen development allowlists; no new label-driven splits',
        repeats='Fit four repeats on development queries; evaluate fifth on disjoint queries; average 5 rotations',
        selection='No tuning, best-variant selection, thresholds, or new confirmation-set evaluation',
        bootstrap=dict(seed=SEED, resamples=10000, unit='prompt group',
                       intervals='95% paired; 98.75% Bonferroni intervals for four alternatives vs Original'),
        permutation=dict(count=39, seed=SEED, target='SplitConcat gain over BestSingle',
                         procedure='Jointly shuffle all model/repeat labels within subject in each development fold; test unchanged',
                         role='Diagnostic rank under restricted shuffles; not confirmatory p-value for adaptively selected panel'),
        limits=['Existing selected panel is not representative or independent confirmation.',
                'Intervals condition on fitted models; repeat positions may not be temporally exchangeable.',
                'Concatenation also changes dimensionality/kernel; no architecture-only causal claim.',
                'Repeated runs do not increase independent query count. No cost/latency utility claim.'],
        hashes={str(p): sha(p) for p in paths},
    )
    write(OUT / 'PROTOCOL.json', protocol)
    status('PREPARED', queries=len(texts), views=3)


def verify_protocol():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    for path, digest in protocol['hashes'].items():
        if sha(path) != digest:
            raise ValueError('Frozen input/code changed: ' + path)
    return protocol


def encode():
    from .embed_queries import gpu_free, hash_large
    verify_protocol()
    if (OUT / 'EMBEDDINGS.npz').exists():
        raise FileExistsError('Embedding complete; refusing overwrite')
    with (OUT / 'ENCODE.lock').open('a+') as job, (ROOT / 'collect/logs/local_gpu.lock').open('a+') as gpu:
        fcntl.flock(job, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(gpu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not gpu_free():
            raise RuntimeError('GPU occupied')
        old_plan = json.loads((OLD_EMBED / 'PLAN.json').read_text())
        old_prov = json.loads((OLD_EMBED / 'PROVENANCE.json').read_text())
        status('VERIFYING_ENCODER')
        for name, digest in old_plan['config_sha256'].items():
            if sha(MODEL / name) != digest:
                raise ValueError('Encoder config changed: ' + name)
        for name, digest in old_prov['weight_sha256'].items():
            if hash_large(MODEL / name) != digest:
                raise ValueError('Encoder weight changed: ' + name)
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        import importlib.metadata as metadata
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(4)
        status('LOADING_ENCODER')
        encoder = SentenceTransformer(str(MODEL), local_files_only=True,
                                      trust_remote_code=False, device='cuda',
                                      model_kwargs={'torch_dtype': torch.float16})
        encoder.max_seq_length = old_plan['max_sequence_length']
        if encoder.default_prompt_name is not None:
            raise ValueError('Unexpected default instruction prompt')
        rows = [json.loads(s) for s in (OUT / 'TEXTS.jsonl').open()]
        ids = [r['query_id'] for r in rows]
        raw = {r['query_id']: r['query'] for r in map(json.loads, (PANEL / 'PANEL.jsonl').open())}
        old = np.load(OLD_EMBED / 'EMBEDDINGS.npz', allow_pickle=False)
        old_index = {q: i for i, q in enumerate(old['ids'].tolist())}
        probe = encoder.encode([raw[ids[0]]], batch_size=1, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False).astype('float32')
        reference = old['vectors'][old_index[ids[0]]]
        if not np.allclose(probe[0], reference, atol=1e-5, rtol=1e-4):
            raise ValueError('Original embedding reproduction failed')
        provenance = dict(protocol_sha256=sha(OUT / 'PROTOCOL.json'),
                          weights_verified_against=str(OLD_EMBED / 'PROVENANCE.json'),
                          original_canary_max_abs=float(np.abs(probe[0] - reference).max()),
                          packages={n: metadata.version(n) for n in ['torch', 'transformers', 'sentence-transformers', 'numpy']})
        if (OUT / 'ENCODER_PROVENANCE.json').exists():
            if json.loads((OUT / 'ENCODER_PROVENANCE.json').read_text()) != provenance:
                raise ValueError('Encoder provenance changed on resume')
        else:
            write(OUT / 'ENCODER_PROVENANCE.json', provenance)
        chunks = OUT / 'chunks'
        chunks.mkdir(exist_ok=True)
        vectors, lengths = {}, {}
        for view in ['Content', 'Stem', 'Options']:
            texts = [r[view] for r in rows]
            counts = [len(v) for v in encoder.tokenizer(texts, truncation=False)['input_ids']]
            if max(counts) > encoder.max_seq_length:
                raise ValueError('Unexpected truncation')
            lengths[view] = dict(min=min(counts), max=max(counts), total=sum(counts))
            blocks = []
            for start in range(0, len(ids), 16):
                block_ids = ids[start:start + 16]
                file = chunks / f'{view}_{start:04d}.npz'
                if file.exists():
                    cached = np.load(file, allow_pickle=False)
                    if cached['ids'].tolist() != block_ids:
                        raise ValueError('Chunk IDs changed')
                    value = cached['vectors']
                else:
                    value = encoder.encode(texts[start:start + 16], batch_size=1,
                                           normalize_embeddings=True, convert_to_numpy=True,
                                           show_progress_bar=False).astype('float32')
                    np.savez_compressed(file, ids=np.array(block_ids), vectors=value)
                if value.shape != (len(block_ids), 3584) or not np.isfinite(value).all():
                    raise ValueError('Bad embeddings')
                if not np.allclose(np.linalg.norm(value, axis=1), 1, atol=.005):
                    raise ValueError('Non-unit embeddings')
                blocks.append(value)
                status('ENCODING', view=view, completed=start + len(block_ids), total=len(ids))
            vectors[view] = np.concatenate(blocks)
        np.savez_compressed(OUT / 'EMBEDDINGS.npz', ids=np.array(ids), **vectors)
        write(OUT / 'EMBEDDING_MANIFEST.json', dict(sha256=sha(OUT / 'EMBEDDINGS.npz'),
              lengths=lengths, truncated=0, chunks={p.name: sha(p) for p in chunks.glob('*.npz')}))
        del encoder
        torch.cuda.empty_cache()
        status('ENCODED', queries=len(ids), texts=3 * len(ids))


def cross_repeat(x, v, folds, permutation=None):
    """No held-out query labels enter fitting; permutation applies to train only."""
    from sklearn.linear_model import Ridge
    n = len(x)
    scores = np.empty((n, 5)); choices = np.empty((n, 5), int)
    base = np.empty((n, 5)); predictions = np.empty((n, 5, 4))
    for fi, (dev, test) in enumerate(folds):
        label_ids = dev if permutation is None else permutation[fi]
        for held in range(5):
            train_y = v[label_ids][:, :, np.arange(5) != held].mean(2)
            pred = Ridge(alpha=1.0).fit(x[dev], train_y).predict(x[test])
            pick = pred.argmax(1)
            scores[test, held] = v[test, pick, held]
            choices[test, held] = pick
            base[test, held] = v[test, int(train_y.mean(0).argmax()), held]
            predictions[test, held] = pred
    return scores, choices, base, predictions


def evaluate():
    from sklearn.linear_model import Ridge
    from .diagnose_rank_signal import load_inputs
    protocol = verify_protocol()
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('Evaluation complete; refusing overwrite')
    if (OUT / 'EVALUATION_STARTED.json').exists():
        raise FileExistsError('Previous evaluation started; inspect before rerun')
    write(OUT / 'EVALUATION_STARTED.json', dict(unix_time=time.time(), protocol_sha256=sha(OUT / 'PROTOCOL.json')))
    status('VALIDATING_INPUTS')
    em = json.loads((OUT / 'EMBEDDING_MANIFEST.json').read_text())
    if sha(OUT / 'EMBEDDINGS.npz') != em['sha256']:
        raise ValueError('Embedding changed')
    z = np.load(BASE / 'PREDICTIONS.npz', allow_pickle=False)
    ids = z['ids'].tolist(); n = len(ids); index = {q: i for i, q in enumerate(ids)}
    labels = {r['query_id']: r for r in map(json.loads, LABEL.open())}
    ls = json.loads((LABEL.parent / 'STATUS.json').read_text())
    if sha(LABEL) != ls['labels_sha256']:
        raise ValueError('Labels changed')
    v = np.array([[labels[q]['models'][m]['values'] for m in SLOTS] for q in ids], dtype='float32')
    if v.shape != (400, 4, 5) or not np.isin(v, [0, 1]).all() or not np.allclose(v.mean(2), z['quality']):
        raise ValueError('Incomplete/misaligned scores')
    manifest = json.loads((PANEL / 'MANIFEST.json').read_text())
    for name, digest in manifest['source_files'].items():
        if sha(Path(manifest['source']) / name) != digest:
            raise ValueError('Historical feature source changed')
    features, original, _ = load_inputs(manifest['source'])
    fi = {q: i for i, q in enumerate(features['ids'])}
    x = {'Original': original[[fi[q] for q in ids]].astype('float32')}
    emb = np.load(OUT / 'EMBEDDINGS.npz', allow_pickle=False)
    if emb['ids'].tolist() != ids:
        raise ValueError('Embedding order mismatch')
    for view in ['Content', 'Stem', 'Options']:
        x[view] = emb[view].astype('float32')
    # Independently normalize concatenated blocks because stored fp16 vectors
    # are approximately unit length. Original features retain the exact baseline.
    blocks = [x[k] / np.linalg.norm(x[k], axis=1, keepdims=True) for k in ['Stem', 'Options']]
    x['SplitConcat'] = np.concatenate(blocks, axis=1) / np.sqrt(np.float32(2.0))
    if any(not np.isfinite(a).all() for a in x.values()):
        raise ValueError('Non-finite feature')
    if sha(manifest['groups']) != manifest['groups_sha256']:
        raise ValueError('Groups changed')
    group_map = json.loads(Path(manifest['groups']).read_text())['groups']
    groups = np.array([group_map[q] for q in ids])
    selection = json.loads((PANEL / 'FOLD_SELECTION.json').read_text())
    folds = []; coverage = np.zeros(n, int)
    for fold in json.loads((BASE / 'FOLDS.json').read_text()):
        dev = np.array([index[q] for q in fold['development_ids']])
        test = np.array([index[q] for q in fold['test_ids']])
        expected = set(selection[str(fold['fold'])]) & set(ids)
        if set(fold['development_ids']) != expected:
            raise ValueError('Development allowlist mismatch')
        if set(groups[dev]) & set(groups[test]) or not np.all(z['folds'][test] == fold['fold']):
            raise ValueError('Fold/group leakage')
        coverage[test] += 1; folds.append((dev, test))
    if not np.all(coverage == 1):
        raise ValueError('Test coverage mismatch')
    unique, inv = np.unique(groups, return_inverse=True)
    rng = np.random.default_rng(SEED)
    bootstrap = rng.integers(0, len(unique), (10000, len(unique)))
    counts = np.bincount(inv)

    def interval(diff, level=95):
        sums = np.bincount(inv, weights=diff)
        means = sums[bootstrap].sum(1) / counts[bootstrap].sum(1)
        return (100 * np.percentile(means, [(100 - level) / 2, 100 - (100 - level) / 2])).tolist()

    arrays = {}; full = {}; oof = {}; base_scores = None
    for name in VARIANTS:
        score, choice, base, prediction = cross_repeat(x[name], v, folds)
        arrays[f'{name}_scores'] = score
        arrays[f'{name}_choices'] = choice
        arrays[f'{name}_predictions'] = prediction
        if base_scores is None:
            base_scores = base
        elif not np.array_equal(base_scores, base):
            raise ValueError('BestSingle must be common across representations')
        oof[name] = score.mean(1)
        pick = np.empty(n, int)
        for dev, test in folds:
            pick[test] = Ridge(alpha=1.).fit(x[name][dev], v[dev].mean(2)).predict(x[name][test]).argmax(1)
        arrays[f'{name}_full_choices'] = pick
        full[name] = v.mean(2)[np.arange(n), pick]
        if name == 'Original':
            if not np.array_equal(pick, z['choice_QueryOnlyRidge']):
                raise ValueError('Historical Ridge decisions not reproduced')
            e3 = np.load(ROOT / 'router_v2/e3_repeat_generalization_20260914/PER_QUERY.npz', allow_pickle=False)
            if e3['ids'].tolist() != ids or not np.allclose(oof[name], e3['k4_Ridge']):
                raise ValueError('E3 cross-repeat Ridge not reproduced')
        status('FITTED', variant=name)
    base = base_scores.mean(1); arrays['BestSingle_scores'] = base_scores
    methods = {}
    for name in VARIANTS:
        gain = oof[name] - base; diff = oof[name] - oof['Original']
        switched = arrays[f'{name}_choices'] != arrays['Original_choices']
        rotation_diff = arrays[f'{name}_scores'] - arrays['Original_scores']
        methods[name] = dict(eq=float(oof[name].mean()), gain_vs_best_pp=float(100 * gain.mean()),
            gain_vs_best_ci95_pp=interval(gain), gain_vs_original_pp=float(100 * diff.mean()),
            gain_vs_original_ci95_pp=interval(diff), gain_vs_original_ci9875_pp=interval(diff, 98.75),
            full_repeat_oof_eq=float(full[name].mean()),
            by_fold_eq={str(f): float(oof[name][z['folds'] == f].mean()) for f in sorted(set(z['folds'].tolist()))},
            by_held_repeat_eq=arrays[f'{name}_scores'].mean(0).tolist(),
            selection_counts=dict(zip(SLOTS, np.bincount(arrays[f'{name}_choices'].ravel(), minlength=4).tolist())),
            switches_vs_original=dict(rotations=int(switched.sum()),
                helped=int((rotation_diff > 0).sum()), harmed=int((rotation_diff < 0).sum()),
                tied=int((switched & (rotation_diff == 0)).sum())),
            dimensions=x[name].shape[1])
    np.savez_compressed(OUT / 'PREDICTIONS.npz', ids=np.array(ids), groups=groups,
                        folds=z['folds'], **arrays)
    # Predeclared subject-conditional shuffle, preserving the four-model/five-repeat
    # vector together and never moving any test label into training.
    texts = {r['query_id']: r for r in map(json.loads, (OUT / 'TEXTS.jsonl').open())}
    subjects = np.array([texts[q]['subject'] for q in ids])
    rng = np.random.default_rng(SEED)
    null = []
    for b in range(protocol['permutation']['count']):
        perms = []
        for dev, test in folds:
            p = dev.copy()
            for subject in sorted(set(subjects[dev])):
                positions = np.flatnonzero(subjects[dev] == subject)
                p[positions] = rng.permutation(dev[positions])
            if set(p) != set(dev) or not np.array_equal(subjects[p], subjects[dev]):
                raise ValueError('Invalid subject-conditional permutation')
            perms.append(p)
        scores, _, null_base, _ = cross_repeat(x['SplitConcat'], v, folds, permutation=perms)
        null.append(float((scores - null_base).mean()))
        if (b + 1) % 5 == 0:
            status('SHUFFLE_CONTROL', completed=b + 1, total=39)
    observed = float((oof['SplitConcat'] - base).mean())
    result = dict(n=n, prompt_groups=len(unique), best_single_eq=float(base.mean()),
                  methods=methods, primary='SplitConcat',
                  shuffle=dict(null_gain_pp=[100 * a for a in null], observed_gain_pp=100 * observed,
                               rank_tail_fraction=(1 + sum(a >= observed for a in null)) / (len(null) + 1)),
                  protocol_sha256=sha(OUT / 'PROTOCOL.json'), prediction_sha256=sha(OUT / 'PREDICTIONS.npz'))
    write(OUT / 'RESULTS.json', result)
    write(OUT / 'VALIDATION.json', dict(input_hashes=True, encoder_canary=True, no_truncation=True,
          complete_binary_400_4_5=True, fold_group_disjoint=True, allowlists_exact=True,
          each_query_evaluated_once=True, historical_ridge_decisions_exact=True,
          e3_cross_repeat_ridge_reproduced=True, external_api_calls=0))
    report(result)
    status('COMPLETE', primary_gain_vs_original_pp=methods['SplitConcat']['gain_vs_original_pp'])


def report(result):
    methods = result['methods']; main = methods['SplitConcat']
    lines = ['# E4：题干与选项表示消融', '',
        '沿用400题、四模型、每题每模型五次重复及原始分折。主指标：开发题目上用四次重复拟合，在不同题目的剩余一次重复评分，再平均五轮。固定 GTE 与 Ridge(alpha=1)，未搜索参数。', '',
        f'固定最佳模型质量：{result["best_single_eq"]:.2%}。', '',
        '| 表示 | 跨重复质量 | 对固定模型增益 pp（95% CI） | 对原始表示增益 pp（95% CI） | 五重复均值 OOF |',
        '|---|---:|---|---|---:|']
    for name, m in methods.items():
        a, b = m['gain_vs_best_ci95_pp'], m['gain_vs_original_ci95_pp']
        lines.append(f'| {name} | {m["eq"]:.2%} | {m["gain_vs_best_pp"]:+.2f} [{a[0]:.2f}, {a[1]:.2f}] | '
                     f'{m["gain_vs_original_pp"]:+.2f} [{b[0]:.2f}, {b[1]:.2f}] | {m["full_repeat_oof_eq"]:.2%} |')
    lines += ['', 'Original 为历史完整提示嵌入；Content 删除答题模板但保留题干与选项；Stem/Options 分别只保留题干/选项。所有新文本视图显式保留学科。SplitConcat 将两个单位向量等权拼接并归一化，等价于等权组合两个线性核，维度变为7168。', '',
        '主比较预先固定为 SplitConcat−Original，不根据外折结果挑选胜者。四项与 Original 的比较另附98.75% Bonferroni区间于 RESULTS.json。', '',
        f'预定 SplitConcat 学科内标签打乱对照：观察增益 {result["shuffle"]["observed_gain_pp"]:+.2f} pp，'
        f'39次打乱的加一右尾比例 {result["shuffle"]["rank_tail_fraction"]:.3f}。这是已选择面板上的诊断排名，不能解释为独立确认检验。', '',
        '结论：' + ('主比较95%区间高于0，可作为进一步独立确认的候选。' if main['gain_vs_original_ci95_pp'][0] > 0 else
                    '主比较未显示可靠优于原始表示，不能宣称拆分题干/选项解决了路由可学习性问题。'), '',
        '边界：这是已反复用于开发且经过机会富集的面板；不是新测试。区间按题目组配对重采样，条件于已拟合预测，不含重训方差。重复不增加独立题目数量。编码拆分同时改变输入上下文、核和部分维度，不能单独归因于某一种机制。未重用100题确认集进行选择。', '',
        '复现：`python -m router_v2.experiment_e4_representation prepare` → `encode` → `evaluate`，工作目录 `/root/r3_own_pool`，使用既有 `llmrouterbench_r2_venv`。完成目录拒绝覆盖。协议、输入文本、编码器校验、逐题逐重复预测与全部比较均已保留。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['prepare', 'encode', 'evaluate'])
    args = ap.parse_args()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
