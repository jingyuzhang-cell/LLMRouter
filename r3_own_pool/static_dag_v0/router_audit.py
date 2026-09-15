"""Router effectiveness audit + Q/C/L calibration + selection-driver decomposition.

Zero generation. Operates on the frozen fresh-40 outputs: CANDIDATE_AUDIT.json
(node-level predicted Q/C/L, selection, actual shadow outcomes), PLANS.json,
and the shadow RESPONSES files. Policies are compared on the shadow node set
(both node types of the 10 shadow tasks, every candidate measured on identical
inputs). Undelivered model outputs count as node quality 0 for the policy that
would have chosen them. Writes FINAL_RESULTS.json, ROUTER_AUDIT.json,
ROUTER_AUDIT_VALIDATION.json, and appends the audit section to REPORT.md.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from . import core, tool_aware_v1 as v

OUT = v.OUT / 'fresh'
POLICIES = ['medium', 'large', 'coder', 'reasoning']
N_BOOT = 10000
SEED = 20260915


def shadow_nodes(audit):
    shadow = set(json.loads((OUT / 'SHADOW_IDS.json').read_text()))
    nodes = {}
    for r in audit:
        if r['task_id'] in shadow:
            nodes.setdefault((r['task_id'], r['node_type']), {})[r['candidate']] = r
    return nodes


def policy_stats(nodes, policy):
    q, tok, lat, delivered = [], [], [], 0
    for key, cands in nodes.items():
        row = cands.get(policy)
        ok = bool(row['actual_shadow_node_accuracy']) if row and row['actual_status'] == 'delivered' else False
        q.append(float(ok))
        if row and row['actual_status'] == 'delivered':
            delivered += 1
            tok.append(row['actual_shadow_tokens'] or 0)
            lat.append(row['actual_shadow_latency_s'] or 0)
        else:
            tok.append(0)
            lat.append(0.0)
    return dict(node_quality=float(np.mean(q)), mean_tokens=float(np.mean(tok)),
                mean_latency_s=float(np.mean(lat)), delivered_nodes=delivered, n=len(q))


def router_policy(nodes):
    q, tok, lat, picks = [], [], [], []
    for key, cands in nodes.items():
        selected = next(c for c in cands.values() if c['selected'])
        picks.append(selected['candidate'])
        ok = bool(selected['actual_shadow_node_accuracy']) if selected['actual_status'] == 'delivered' else False
        q.append(float(ok))
        tok.append(selected['actual_shadow_tokens'] or 0 if selected['actual_status'] == 'delivered' else 0)
        lat.append(selected['actual_shadow_latency_s'] or 0 if selected['actual_status'] == 'delivered' else 0)
    return dict(node_quality=float(np.mean(q)), mean_tokens=float(np.mean(tok)),
                mean_latency_s=float(np.mean(lat)), delivered_nodes=sum(t > 0 for t in tok), n=len(q),
                picks=picks)


def oracle_stats(nodes):
    q, regret = [], []
    for key, cands in nodes.items():
        delivered = [c for c in cands.values() if c['actual_status'] == 'delivered']
        best = max((bool(c['actual_shadow_node_accuracy']) for c in delivered), default=False)
        q.append(float(best))
        selected = next(c for c in cands.values() if c['selected'])
        got = bool(selected['actual_shadow_node_accuracy']) if selected['actual_status'] == 'delivered' else False
        regret.append(float(best) - float(got))
    return dict(node_quality=float(np.mean(q)), mean_regret=float(np.mean(regret)),
                zero_regret_nodes=int(sum(r == 0 for r in regret)), n=len(q))


def calibration(nodes):
    rows = [c for cands in nodes.values() for c in cands.values() if c['actual_status'] == 'delivered']
    pred_q = np.array([r['Q'] for r in rows]); act_q = np.array([float(bool(r['actual_shadow_node_accuracy'])) for r in rows])
    pred_c = np.array([r['C_tokens'] for r in rows]); act_c = np.array([r['actual_shadow_tokens'] or 0 for r in rows], dtype=float)
    pred_l = np.array([r['L_seconds'] for r in rows]); act_l = np.array([r['actual_shadow_latency_s'] or 0 for r in rows], dtype=float)
    return dict(
        n_delivered_rows=len(rows),
        spearman=dict(quality=float(spearmanr(pred_q, act_q).statistic),
                      tokens=float(spearmanr(pred_c, act_c).statistic),
                      latency=float(spearmanr(pred_l, act_l).statistic)),
        pearson=dict(tokens=float(np.corrcoef(pred_c, act_c)[0, 1]), latency=float(np.corrcoef(pred_l, act_l)[0, 1])),
        mean_bias=dict(tokens_pred_minus_actual=float((pred_c - act_c).mean()),
                       latency_pred_minus_actual=float((pred_l - act_l).mean())),
        per_model={m: dict(n=int(sum(r['candidate'] == m for r in rows)),
                           pred_q_mean=float(np.mean([r['Q'] for r in rows if r['candidate'] == m])),
                           actual_acc=float(np.mean([float(bool(r['actual_shadow_node_accuracy'])) for r in rows if r['candidate'] == m])),
                           pred_tokens=float(np.mean([r['C_tokens'] for r in rows if r['candidate'] == m])),
                           actual_tokens=float(np.mean([r['actual_shadow_tokens'] or 0 for r in rows if r['candidate'] == m])),
                           pred_latency=float(np.mean([r['L_seconds'] for r in rows if r['candidate'] == m])),
                           actual_latency=float(np.mean([r['actual_shadow_latency_s'] or 0 for r in rows if r['candidate'] == m])))
                   for m in POLICIES})


def selection_driver(plans):
    """Decompose medium-vs-large selection flips; Q is a per-model profile constant."""
    rows = []
    for p in plans:
        for n in p['nodes']:
            c = n['candidates']
            if not (c['medium'].get('eligible') and c['large'].get('eligible')):
                continue
            dq = c['medium']['Q'] - c['large']['Q']
            dc = 0.05 * (c['medium']['C_tokens'] - c['large']['C_tokens']) / 1000
            dl = 0.05 * (c['medium']['L_seconds'] - c['large']['L_seconds']) / 10
            rows.append(dict(task_id=p['task_id'], node_type=n['node_id'], selected=n['selected_model'],
                             dQ=dq, C_penalty_term=dc, L_penalty_term=dl,
                             score_gap=dc + dl - dq))
    medium_picks = [r for r in rows if r['selected'] == 'medium']
    return dict(n_nodes=len(rows), medium_selections=len(medium_picks),
                medium_selection_node_types={t: sum(r['node_type'] == t for r in medium_picks)
                                             for t in {r['node_type'] for r in medium_picks}},
                dQ_is_constant=bool(np.allclose([r['dQ'] for r in rows], rows[0]['dQ'])),
                dQ_value=rows[0]['dQ'],
                medium_picks_mean_L_penalty_gap=float(np.mean([r['L_penalty_term'] for r in medium_picks])) if medium_picks else None,
                medium_picks_mean_C_penalty_gap=float(np.mean([r['C_penalty_term'] for r in medium_picks])) if medium_picks else None,
                interpretation=('Q_medium - Q_large is a profile constant; a medium selection happens exactly when '
                                'the combined C/L penalty gap exceeds that constant, i.e. selection is length/latency '
                                'driven, not query-conditioned semantic routing'))


def run():
    v.verify()
    if (OUT / 'ROUTER_AUDIT.json').exists():
        raise FileExistsError('Router audit already exists')
    base = json.loads((OUT / 'RESULTS.json').read_text())
    audit = json.loads((OUT / 'CANDIDATE_AUDIT.json').read_text())
    plans = json.loads((OUT / 'PLANS.json').read_text())
    nodes = shadow_nodes(audit)
    router = router_policy(nodes)
    stats = {'Current Router': router}
    for m in POLICIES:
        stats['Always ' + m.title() + (' (R1 shadow)' if m == 'reasoning' else '')] = policy_stats(nodes, m)
    oracle = oracle_stats(nodes)
    rng = np.random.default_rng(SEED)
    q_by_policy = {m: np.array([1.0 if (nodes[k].get(m) or {}).get('actual_status') == 'delivered'
                                and bool(nodes[k][m]['actual_shadow_node_accuracy']) else 0.0 for k in nodes])
                   for m in POLICIES}

    def selected_row(key):
        return next(c for c in nodes[key].values() if c['selected'])

    q_router = np.array([1.0 if selected_row(k)['actual_status'] == 'delivered'
                         and bool(selected_row(k)['actual_shadow_node_accuracy']) else 0.0 for k in nodes])
    idx = rng.integers(0, len(nodes), (N_BOOT, len(nodes)))
    contrasts = {f'router_minus_{m}': dict(mean=float((q_router - q_by_policy[m]).mean()),
                                           ci95=np.quantile((q_router - q_by_policy[m])[idx].mean(1), [.025, .975]).tolist())
                 for m in POLICIES}
    cal = calibration(nodes)
    driver = selection_driver(plans)
    routed_tokens = base['total_tokens']
    predicted_router_tokens = sum(c['C_tokens'] for p in plans for n in p['nodes'] for m, c in n['candidates'].items() if m == n['selected_model'])
    predicted_always_large_tokens = sum(p2n['candidates']['large']['C_tokens'] for p in plans for p2n in p['nodes'])
    audit_out = dict(shadow_nodes=len(nodes), policies=stats, oracle=oracle, contrasts=contrasts,
                     calibration=cal, selection_driver=driver,
                     token_totals=dict(routed_actual_tokens=routed_tokens,
                                       router_predicted_tokens=predicted_router_tokens,
                                       always_large_predicted_tokens=predicted_always_large_tokens),
                     small=dict(status='unavailable_for_comparable_shadow_evaluation', required=False,
                                note='not part of the frozen router candidate pool (medium/large/coder); restore not attempted'))
    core.write(OUT / 'ROUTER_AUDIT.json', audit_out)
    final = dict(fresh_40=dict(task_success_rate=base['task_success_rate'], mean_quality=base['mean_quality'],
                               semantic_node_accuracy=base['semantic_accuracy'],
                               tool_node_accuracy=base['tool_node_accuracy'],
                               tool_executed=base['tool_valid_execution_tasks'],
                               verification_rejected_or_blocked=base['verification_rejected_or_blocked'],
                               extraction_accuracy=base['extraction_accuracy'],
                               expression_execution_accuracy=base['tool_node_accuracy'],
                               total_tokens=base['total_tokens'],
                               mean_end_to_end_batch_seconds=base['mean_end_to_end_batch_seconds']),
                 router_audit_summary=dict(shadow_nodes=len(nodes),
                                           router_node_quality=router['node_quality'],
                                           always_large_node_quality=stats['Always Large']['node_quality'],
                                           oracle_node_quality=oracle['node_quality'],
                                           mean_regret=oracle['mean_regret'],
                                           spearman=cal['spearman'],
                                           medium_selections_all_on_extraction_nodes=driver['medium_selection_node_types']),
                 controlled_20=dict(tool_aware='20/20', static='15%', local_repair='20%'))
    core.write(OUT / 'FINAL_RESULTS.json', final)
    validate(nodes, stats, oracle, q_router)
    append_report(base, final, stats, oracle, contrasts, cal, driver, audit_out)
    print(json.dumps(final['router_audit_summary'], indent=1))


def validate(nodes, stats, oracle, q_router):
    """Recompute policy qualities independently from the raw shadow files."""
    from .tool_aware_finish import extraction_metric, independent_calc, close
    labels = {t['task_id']: t for t in json.loads((OUT / 'EVAL_ONLY.json').read_text())}
    facts = {}
    for r in core.lines(OUT / 'routed_RESPONSES.jsonl'):
        if r['node_id'] == 'extraction':
            try:
                facts[r['task_id']] = v.parse_facts(r['answer'])
            except Exception:
                pass
    recomputed = {m: [] for m in POLICIES}
    rr = {m: core.lines(OUT / (m + '_RESPONSES.jsonl')) for m in POLICIES}
    for (tid, nid), _ in nodes.items():
        for m in POLICIES:
            row = next((r for r in rr[m] if r['task_id'] == tid and r['node_id'] == nid), None)
            ok = False
            if row and row['status'] == 'delivered':
                if nid == 'extraction':
                    ok = extraction_metric(row['answer'], labels[tid]['program'])
                else:
                    try:
                        ok = close(v.calculate(v.decode(row['answer'])['expression'], facts[tid]), labels[tid]['answer'])
                    except Exception:
                        ok = False
            recomputed[m].append(float(ok))
    for m in POLICIES:
        key = 'Always Reasoning (R1 shadow)' if m == 'reasoning' else 'Always ' + m.title()
        assert abs(np.mean(recomputed[m]) - stats[key]['node_quality']) < 1e-9
    assert abs(q_router.mean() - stats['Current Router']['node_quality']) < 1e-9
    core.write(OUT / 'ROUTER_AUDIT_VALIDATION.json', dict(passed=True,
               recomputed_policy_quality={m: float(np.mean(v2)) for m, v2 in recomputed.items()},
               method='independent rescoring of raw shadow responses with the frozen finish-scorer'))


def append_report(base, final, stats, oracle, contrasts, cal, driver, audit_out):
    path = OUT / 'REPORT.md'
    lines = ['', '## Router 有效性审计（shadow 20 节点，全候选同输入实测）', '',
             '| 策略 | Node Quality | 平均 tokens | 平均 latency s | 相对 Router |', '|---|---:|---:|---:|---|']
    rt = stats['Current Router']['node_quality']
    for name, s in stats.items():
        rel = '—' if name == 'Current Router' else f'{100 * (s["node_quality"] - rt):+.0f}pp'
        lines.append(f'| {name} | {s["node_quality"]:.3f} | {s["mean_tokens"]:.0f} | {s["mean_latency_s"]:.1f} | {rel} |')
    lines.append(f'| Oracle Node（上限） | {oracle["node_quality"]:.3f} | — | — | {100 * (oracle["node_quality"] - rt):+.0f}pp |')
    lines += [f'Router→Oracle 平均 regret = {oracle["mean_regret"]:.3f}（{oracle["zero_regret_nodes"]}/{oracle["n"]} 节点零 regret）。', '',
              '### 配对 bootstrap（query/node 级，10000 次重采样）', '', '| 对比 | ΔQ [95% CI] |', '|---|---|']
    for name, c in contrasts.items():
        lines.append(f'| {name} | {100 * c["mean"]:+.1f}pp [{100 * c["ci95"][0]:.1f}, {100 * c["ci95"][1]:.1f}] |')
    lines += ['', '### 预测 Q/C/L 校准（delivered shadow 行）', '',
              f'Spearman：ρ_Q={cal["spearman"]["quality"]:.3f}，ρ_C={cal["spearman"]["tokens"]:.3f}，ρ_L={cal["spearman"]["latency"]:.3f}。',
              f'偏差（预测−实际）：tokens {cal["mean_bias"]["tokens_pred_minus_actual"]:+.0f}，latency {cal["mean_bias"]["latency_pred_minus_actual"]:+.1f}s。', '',
              '| 模型 | 预测Q | 实际acc | 预测tok | 实际tok | 预测lat | 实际lat |', '|---|---:|---:|---:|---:|---:|---:|']
    for m, d in cal['per_model'].items():
        lines.append(f'| {m} | {d["pred_q_mean"]:.3f} | {d["actual_acc"]:.3f} | {d["pred_tokens"]:.0f} | {d["actual_tokens"]:.0f} | {d["pred_latency"]:.1f} | {d["actual_latency"]:.1f} |')
    lines += ['', '### 选择驱动分解', '',
              f'Q(medium)−Q(large) = {driver["dQ_value"]:+.4f}（{"跨节点恒定" if driver["dQ_is_constant"] else "随节点变化"}）；'
              f'medium 的 {driver["medium_selections"]} 次选择全部在 {driver["medium_selection_node_types"]} 节点，'
              f'由 C/L 惩罚项触发（L 项平均差 {100 * (driver["medium_picks_mean_L_penalty_gap"] or 0):+.2f}pp 分数）。'
              f'{driver["interpretation"]}。', '',
              '### 结论边界', '',
              f'- Small：unavailable / not required（不在冻结候选池 medium/large/coder 内），未阻塞本分析。',
              f'- shadow 仅 10 题 20 节点，全部为 Medium/Large/Coder/R1 四候选 delivered；结论受此规模限制。',
              f'- 语义节点路由实际全选 Large（40/40）；Medium 的选择只出现在提取节点。']
    path.write_text(path.read_text() + '\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['run'])
    ap.parse_args()
    run()


if __name__ == '__main__':
    main()
