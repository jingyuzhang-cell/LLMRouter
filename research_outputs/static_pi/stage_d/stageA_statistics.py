#!/usr/bin/env python3
"""Stage A 完整统计复核（零调用）：正确 FMT 语义的三口径 + 16 对差值 + 效应量/CI/功效。"""
import json, glob, sys, copy, itertools
import numpy as np
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1/quality_v4')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
from executor import extract_json, apply_format_rules, build_terminal_output
from terminal_quality import evaluate_terminal_quality
from exact_perm import exact_paired_perm

BASE = '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/'
CON = {}
for label, f in (('old', 'TASK_CONTRACT_PHASE2B_v2_1.json'), ('v3', 'TASK_CONTRACT_PHASE2B_v3_DRAFT.json')):
    c = json.load(open(BASE + f))
    src = c.pop('source_pages')
    CON[label] = (c, src)
MAP = {'E1': 'D1', 'E2': 'D2', 'E3': 'D3', 'E4': 'D4'}
ARMS = ['Static', 'R-only', 'π-only', 'Simple-Dynamic', 'Fixed-Composite', 'Proposed-Dynamic']


def fmt_final_bypassed(d):
    entries = [e for e in d['exec_log'] if e['node'] == 'FMT']
    return entries[-1].get('bypassed', False) if entries else False


def score_parsed(parsed, contract, relabel):
    if parsed is None:
        return None
    pf = json.loads(json.dumps(parsed))
    if relabel:
        for a in pf.get('answers', []):
            if str(a.get('doc')) in MAP:
                a['doc'] = MAP[str(a['doc'])]
    try:
        term = build_terminal_output(pf)
    except Exception:
        return None
    c, src = CON[contract]
    q = evaluate_terminal_quality(copy.deepcopy(c), term, src)
    claims = q['claim_results']
    tp = sum(1 for x in claims if x['status'].startswith('CORRECT'))
    full = sum(1 for x in claims if x['status'] == 'CORRECT_GOLD')
    n = max(len(claims), 1)
    return {'tp': tp, 'full': round(full / n, 4), 'n': len(claims)}


def rescore(d):
    # 执行器语义对齐：仅当执行完成且 FMT 输出存在时才评分，否则 0（finish() 只解析 outputs["FMT"]）
    if d.get('status') != 'COMPLETE' or not any(e['node'] == 'FMT' for e in d.get('exec_log', [])):
        return {'v3_tp': 0, 'a1_full': 0.0, 'a1_tp': 0}
    st = [n['text'] for n in (d.get('raw', {}).get('nodes', {}).get('SINK') or []) if n.get('text')]
    if not st:
        return {'v3_tp': 0, 'a1_full': 0.0, 'a1_tp': 0}
    parsed = extract_json(st[-1])
    if parsed is None:
        return {'v3_tp': 0, 'a1_full': 0.0}
    if not fmt_final_bypassed(d):          # 尊重 FMT 实际状态（S4 旁路=不修复）
        parsed = apply_format_rules(json.loads(json.dumps(parsed)))[0]
    v3 = score_parsed(parsed, 'v3', False) or {'tp': 0, 'full': 0.0}
    a1 = score_parsed(parsed, 'old', True) or {'tp': 0, 'full': 0.0}
    return {'v3_tp': v3['tp'], 'v3_full': v3['full'], 'a1_tp': a1['tp'], 'a1_full': a1['full'], 'a1_tp_ok': True}


def main():
    recs = {}
    for p in glob.glob('/root/research_outputs/static_pi/stage_d/runs_final/*.json'):
        d = json.load(open(p))
        if 'exec_id' in d:
            recs[d['exec_id']] = d
    sc = {eid: rescore(d) for eid, d in recs.items()}

    KEY = {'old': None, 'v3': 'v3_tp', 'a1_full': 'a1_full'}

    def val(eid, m):
        if m == 'old':
            return recs[eid]['tp']
        return sc[eid].get(KEY[m], 0)

    metrics = ['old', 'v3', 'a1_full']     # A1-TP 恒等于 old（192/192 已证），事实口径只报 old/v3
    pairs = []
    for s_ in ('S3', 'S4'):
        for r in range(1, 9):
            p_ = f'Proposed-Dynamic|{s_}|r{r}'
            s2 = f'Simple-Dynamic|{s_}|r{r}'
            pairs.append((s_, r, {m: val(p_, m) - val(s2, m) for m in metrics}))
    print('=== 16 对逐项差值（Proposed − Simple）===')
    print(f"{'对':<8}{'old':>5}{'v3':>5}{'a1_full*100':>12}")
    for s_, r, dd in pairs:
        print(f"{s_}|r{r:<4}{dd['old']:>5}{dd['v3']:>5}{round(dd['a1_full']*100,1):>12}")

    # 2) 符号翻转精确 CI（对均值，枚举 2^16）
    def ci_mean(diffs, alpha=0.05):
        a = np.array(diffs, float)
        n = len(a)
        idx = np.arange(1 << n, dtype=np.int64)
        S = np.empty((1 << n, n), dtype=np.float64)
        for i in range(n):
            S[:, i] = ((idx >> i) & 1) * 2 - 1
        dist = S @ a / n
        dist.sort()
        lo = dist[int(alpha / 2 * len(dist))]
        hi = dist[int((1 - alpha / 2) * len(dist)) - 1]
        return round(float(lo), 3), round(float(hi), 3)

    # 3) 功效（经验自助 + exact 检验；N 大于 20 非零时用 DP 版本不必要——自助样本零差多）
    from exact_perm_dp import exact_p_dp as dp_perm

    def power_empirical(diffs, N, nsim=2000, seed=20261103):
        rng = np.random.default_rng(seed)
        d = np.array(diffs, float)
        sig = 0
        for _ in range(nsim):
            sample = list(rng.choice(d, size=N, replace=True))
            pv = dp_perm(sample)         # 返回 p 值（DP 支持 m>16）
            sig += (pv < 0.05)
        return sig / nsim

    print('\n=== 主表 ===')
    rows = []
    for m in metrics:
        diffs = [p[2][m] for p in pairs]
        nz = sum(1 for x in diffs if x != 0)
        pv = dp_perm(diffs)
        r = {'p_value': pv, 'significant': pv < 0.05}
        lo, hi = ci_mean(diffs)
        pw16 = power_empirical(diffs, 16)
        n80 = n90 = None
        for N in range(16, 130, 2):
            p_ = power_empirical(diffs, N, nsim=1000)
            if n80 is None and p_ >= 0.80:
                n80 = N
            if n90 is None and p_ >= 0.90:
                n90 = N
                break
        rows.append({'metric': m, 'mean': round(float(np.mean(diffs)), 3), 'ci95': (lo, hi),
                     'nonzero': nz, 'p': r['p_value'], 'sig': r['significant'],
                     'power_N16': round(pw16, 3), 'N_for_80': n80, 'N_for_90': n90})
        print(f"{m:<10} mean={rows[-1]['mean']:>7} CI95=[{lo},{hi}] 非零={nz}/16 "
              f"p={r['p_value']:.4f} sig={r['significant']} 功效@16={pw16:.2f} N80={n80} N90={n90}")

    # 4) S3/S4 分解
    print('\n=== S3/S4 分解（均值差）===')
    for m in metrics:
        for s_ in ('S3', 'S4'):
            dd = [p[2][m] for p in pairs if p[0] == s_]
            print(f"{m:<10}{s_}: mean={np.mean(dd):>6.2f}  diffs={dd}")

    # 5) A1-TP 恒等复核
    same = sum(1 for eid, v in sc.items() if v.get('a1_tp') == recs[eid]['tp'])
    print(f'\nA1-TP == 执行器old-TP（正确 FMT 管线）: {same}/192')

    json.dump({'pairs': pairs, 'main_table': rows,
               'note': 'A1-TP 恒等于 old-TP（引用重标不影响值层），A1 的事实口径无独立意义；'
                       'A1 辅助口径以 full/evidence 为准。FMT 语义按记录 bypassed 标志重现。'},
              open('/root/research_outputs/static_pi/stage_d/runs_final/STAGE_A_STATISTICS.json', 'w'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
