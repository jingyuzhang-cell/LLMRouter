"""E9: routing label learnability audit — is the supervision itself decidable?

Zero generation. For every query, put a Jeffreys Beta posterior on each model's
success rate from its 5 binary repeats, compare alternatives to R1 with
P(theta_m > theta_R1), and classify each query as confident-switch /
confident-stay / confident-tie / uncertain. Also reports the delta-margin
(switch-worthiness) variant, per-fold effective positive counts, overlap with
the E7 stable-switch rule, and a posterior-predictive simulation of what
adding 5/10/15 repeats would resolve.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
from scipy.stats import beta as beta_dist
from scipy.special import roots_legendre

from .data import sha
from .run_e7_stable_preference_probe import stable_switch_labels

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e9_routing_label_audit'
E6 = ROOT / 'router_v2/e6_representation_objective_2x2'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
ALTS = [0, 1, 2]
REF = 3
CONF = 0.9
DELTA = 0.1
MC_DRAWS = 500
MC_SEED = 20260914
GAUSS_NODES = 64


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def status(phase, **extra):
    row = dict(phase=phase, unix_time=time.time(), **extra)
    write(OUT / 'STATUS.json', row)
    print(json.dumps(row), flush=True)


def p_greater(a1, b1, a2, b2):
    """P(X>Y) for independent X~Beta(a1,b1), Y~Beta(a2,b2); 1-D quadrature."""
    value, _ = quad(lambda x: beta_dist.pdf(x, a1, b1) * beta_dist.cdf(x, a2, b2), 0, 1, limit=200)
    return value


def p_gain(a1, b1, a2, b2, margin):
    """P(X - Y > margin)."""
    value, _ = quad(lambda y: beta_dist.pdf(y, a2, b2) * beta_dist.sf(y + margin, a1, b1), 0, 1, limit=200)
    return value


def p_tie(a1, b1, a2, b2, band):
    """P(|X - Y| < band)."""
    value, _ = quad(lambda x: beta_dist.pdf(x, a1, b1) *
                    (beta_dist.cdf(min(1, x + band), a2, b2) - beta_dist.cdf(max(0, x - band), a2, b2)), 0, 1, limit=200)
    return value


def classify(p_win, p_stay_min, p_tie_best):
    """Frozen hierarchy: switch > stay > tie > uncertain."""
    if (p_win > CONF).any():
        return 'switch'
    if p_stay_min > CONF:
        return 'stay'
    if p_tie_best > CONF:
        return 'tie'
    return 'uncertain'


def audit(repeats):
    v = np.asarray(repeats, dtype=float)
    n = len(v)
    k = v.sum(2)                                     # successes out of 5
    alpha = k + 0.5
    beta_ = 5 - k + 0.5
    rows = []
    for i in range(n):
        a_ref, b_ref = alpha[i, REF], beta_[i, REF]
        p_win = np.array([p_greater(alpha[i, m], beta_[i, m], a_ref, b_ref) for m in ALTS])
        p_gain_d = np.array([p_gain(alpha[i, m], beta_[i, m], a_ref, b_ref, DELTA) for m in ALTS])
        p_stay = np.array([p_greater(a_ref, b_ref, alpha[i, m], beta_[i, m]) for m in ALTS])
        best = int(np.argmax(alpha[i, :3] / (alpha[i, :3] + beta_[i, :3])))
        tie_best = p_tie(alpha[i, best], beta_[i, best], a_ref, b_ref, DELTA)
        label = classify(p_win, p_stay.min(), tie_best)
        rows.append(dict(query_index=i, label=label, best_alt=best if label == 'switch' else -1,
                         p_win=p_win.tolist(), p_gain_delta=p_gain_d.tolist(), p_stay=p_stay.tolist(),
                         p_tie_best=float(tie_best)))
    return rows, alpha, beta_


def vectorized_p_greater(a1, b1, a2, b2, nodes, weights):
    """Broadcasting Gauss-Legendre estimate of P(X>Y); inputs are flattened."""
    a1 = np.asarray(a1, dtype=float).ravel()
    b1 = np.asarray(b1, dtype=float).ravel()
    a2 = np.asarray(a2, dtype=float).ravel()
    b2 = np.asarray(b2, dtype=float).ravel()
    x = nodes[None, :]
    pdf = beta_dist.pdf(x, a1[:, None], b1[:, None])
    cdf = beta_dist.cdf(x, a2[:, None], b2[:, None])
    return (pdf * cdf * weights[None, :]).sum(1)


def predictive_resolution(alpha, beta_, extra_repeats):
    """Posterior-predictive: add hypothetical repeats, reclassify (switch/stay/unresolved)."""
    rng = np.random.default_rng(MC_SEED)
    n = len(alpha)
    theta = rng.beta(alpha[None, :, :], beta_[None, :, :], size=(MC_DRAWS, n, 4))
    extra = rng.binomial(extra_repeats, theta)
    a2 = alpha[None] + extra
    b2 = beta_[None] + extra_repeats - extra
    nodes, weights = roots_legendre(GAUSS_NODES)
    switch_flag = np.zeros((MC_DRAWS, n), dtype=bool)
    stay_flag = np.ones((MC_DRAWS, n), dtype=bool)
    for m in ALTS:
        p_win = vectorized_p_greater(a2[:, :, m], b2[:, :, m], a2[:, :, REF], b2[:, :, REF], nodes, weights)
        p_stay = vectorized_p_greater(a2[:, :, REF], b2[:, :, REF], a2[:, :, m], b2[:, :, m], nodes, weights)
        switch_flag |= p_win.reshape(MC_DRAWS, n) > CONF
        stay_flag &= p_stay.reshape(MC_DRAWS, n) > CONF
    fractions = dict(
        switch=switch_flag.mean(0),
        stay=(~switch_flag & stay_flag).mean(0),
        unresolved=~(switch_flag | stay_flag))
    return {k: v.mean() for k, v in fractions.items()}, (~switch_flag & stay_flag), switch_flag


def run():
    if OUT.exists():
        raise FileExistsError('E9 audit output directory already exists')
    z = np.load(E6 / 'INPUTS.npz', allow_pickle=False)
    e6_protocol = json.loads((E6 / 'PROTOCOL.json').read_text())
    if sha(E6 / 'INPUTS.npz') != e6_protocol['hashes'][str(E6 / 'INPUTS.npz')]:
        raise ValueError('E6 inputs changed')
    folds = json.loads((E6 / 'FOLDS.json').read_text())
    rows, alpha, beta_ = audit(z['repeats'])
    labels = np.array([r['label'] for r in rows])
    stable, switch_e7, which_e7, _, _ = stable_switch_labels(z['repeats'])
    ids = z['ids'].tolist()
    index = {q: i for i, q in enumerate(ids)}
    switch_rows = [r for r in rows if r['label'] == 'switch']
    strict_switch = sum((np.array(r['p_gain_delta']) > CONF).any() for r in rows)
    overlap = sum(bool(switch_e7[r['query_index']]) for r in switch_rows)
    fold_pos = []
    for fold in folds:
        dev = [index[q] for q in fold['development_ids']]
        dev_labels = labels[dev]
        fold_pos.append(dict(fold=fold['fold'], dev_n=len(dev),
                             switch=int((dev_labels == 'switch').sum()),
                             stay=int((dev_labels == 'stay').sum()),
                             tie=int((dev_labels == 'tie').sum()),
                             uncertain=int((dev_labels == 'uncertain').sum()),
                             switch_by_alt={SLOTS[m]: int(sum(r['best_alt'] == m for r in switch_rows
                                                               if r['query_index'] in dev)) for m in ALTS}))
    predictive = {}
    for extra in (5, 10, 15):
        overall, stay_flag, switch_flag = predictive_resolution(alpha, beta_, extra)
        mask = labels == 'uncertain'
        predictive[f'+{extra}'] = {**{k: float(v) for k, v in overall.items()},
                                   'unresolved_among_currently_uncertain': float(
                                       (~(switch_flag | stay_flag)).mean(0)[mask].mean())}
    OUT.mkdir()
    counts = {c: int((labels == c).sum()) for c in ['switch', 'stay', 'tie', 'uncertain']}
    result = dict(
        experiment='E9 Routing Label Learnability Audit', n=len(ids),
        method=dict(prior='Jeffreys Beta(k+0.5, 5-k+0.5) per query-model, independent',
                    comparisons='P(theta_m > theta_R1) via 1-D quadrature; no assumed repeat pairing',
                    classification=f'frozen hierarchy: switch if any p_win>{CONF}; stay if min p_stay>{CONF}; '
                                   f'tie if P(|theta_best-theta_R1|<{DELTA})>{CONF}; else uncertain',
                    switch_worthiness=f'P(theta_m - theta_R1 > {DELTA}) > {CONF} reported as strict variant'),
        four_numbers=dict(
            best_model_clear=counts['switch'] + counts['stay'],
            confident_tie=counts['tie'],
            undecidable_with_5_repeats=counts['uncertain'],
            reliable_switch_samples=dict(bayesian_switch=counts['switch'], strict_delta_switch=int(strict_switch),
                                         e7_stable_rule=int(switch_e7.sum()),
                                         overlap_bayesian_with_e7=int(overlap))),
        class_counts=counts, fold_effective_positives=fold_pos,
        predictive_extension=dict(method=f'posterior-predictive with {MC_DRAWS} draws, seed {MC_SEED}; '
                                         'MC classes switch/stay/unresolved (tie folded into unresolved); '
                                         'last column = unresolved fraction among currently-uncertain queries',
                                  by_extra_repeats=predictive),
        hashes=dict(inputs=sha(E6 / 'INPUTS.npz'), code=sha(Path(__file__)),
                    protocol_reference=sha(E6 / 'PROTOCOL.json')),
        packages={p: importlib.metadata.version(p) for p in ['numpy', 'scipy']})
    write(OUT / 'RESULTS.json', result)
    (OUT / 'PER_QUERY.jsonl').write_text(''.join(json.dumps(dict(query_id=ids[r['query_index']], **{
        k: v for k, v in r.items() if k != 'query_index'}), ensure_ascii=False) + '\n' for r in rows))
    paths = [Path(__file__), Path(__file__).with_name('test_e9_routing_label_audit.py'),
             E6 / 'INPUTS.npz', E6 / 'FOLDS.json', E6 / 'PROTOCOL.json', OUT / 'RESULTS.json', OUT / 'PER_QUERY.jsonl']
    write(OUT / 'PROTOCOL.json', dict(experiment='E9 Routing Label Learnability Audit',
                                      frozen=dict(CONF=CONF, DELTA=DELTA, MC_DRAWS=MC_DRAWS, MC_SEED=MC_SEED,
                                                  GAUSS_NODES=GAUSS_NODES),
                                      constraints=['Zero generation', 'No threshold search (CONF/DELTA frozen)',
                                                   'Audit only; no router trained'],
                                      hashes={str(p): sha(p) for p in paths}))
    report(result)
    status('COMPLETE', counts=counts)


def report(r):
    four = r['four_numbers']
    c = r['class_counts']
    pred = r['predictive_extension']['by_extra_repeats']
    lines = ['# E9：Routing Label Learnability Audit（零生成）', '',
             '每个query-model的5次binary repeat上放Jeffreys后验，配对比较 P(θ_m>θ_R1)（1-D quadrature，不假定repeat配对）。冻结层级：switch(任一 p_win>0.9) → stay(min p_stay>0.9) → tie(P(|θ_best−θ_R1|<0.1)>0.9) → uncertain。', '',
             '## 四个数字', '',
             f"1. 最佳模型统计上明确：**{four['best_model_clear']}/400**（switch {c['switch']} + stay {c['stay']}）",
             f"2. 实际是 tie：**{four['confident_tie']}/400**",
             f"3. 5次repeat无法判断：**{four['undecidable_with_5_repeats']}/400**",
             f"4. 可靠switch样本：Bayesian **{four['reliable_switch_samples']['bayesian_switch']}**，"
             f"δ-margin严格版（P(θ_m−θ_R1>0.1)>0.9）**{four['reliable_switch_samples']['strict_delta_switch']}**，"
             f"E7频繁主义规则 {four['reliable_switch_samples']['e7_stable_rule']}（与Bayesian重合 {four['reliable_switch_samples']['overlap_bayesian_with_e7']}）", '',
             '## 每折有效正样本', '', '| fold | dev n | switch | stay | tie | uncertain | switch按模型 |', '|---|---:|---:|---:|---:|---:|---|']
    for f in r['fold_effective_positives']:
        lines.append(f"| {f['fold']} | {f['dev_n']} | {f['switch']} | {f['stay']} | {f['tie']} | {f['uncertain']} | "
                     + ', '.join(f"{k}:{v}" for k, v in f['switch_by_alt'].items()) + ' |')
    lines += ['', '## 加repeat能买到什么（后验预测，500 draws，种子冻结）', '',
              '| 加repeat数 | switch | stay | unresolved(全量) | unresolved(当前uncertain子集内) |', '|---|---:|---:|---:|---:|']
    for extra, v in pred.items():
        lines.append(f"| {extra} | {v['switch']:.3f} | {v['stay']:.3f} | {v['unresolved']:.3f} | "
                     f"{v['unresolved_among_currently_uncertain']:.3f} |")
    lines += ['', '## 决策映射（预注册）', '',
              '- uncertain 占比高（>30–40%）→ 先加 repeats（标签精度不足是主因）；',
              '- 标签已稳定但 switch 少 → 加 opportunity-enriched 新 query；',
              '- 标签稳定且 switch 不少 → representation/架构才可能是瓶颈。', '',
              '## 边界', '',
              '- 独立Beta后验未建模模型间相关；0.9/0.1为冻结常数非调参。',
              '- 预测模拟假设未来repeat与现有5次同分布（temp 0.7）。',
              '- tie类的层级判定用了 p_win/p_stay 的补集近似（保守）。', '',
              '文件：RESULTS.json / PER_QUERY.jsonl / PROTOCOL.json。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['run'])
    args = ap.parse_args()
    globals()[args.stage]()


if __name__ == '__main__':
    main()
