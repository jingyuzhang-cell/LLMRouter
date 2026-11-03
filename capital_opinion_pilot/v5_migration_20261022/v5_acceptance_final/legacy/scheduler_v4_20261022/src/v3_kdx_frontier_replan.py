"""KDX replanning with RESOURCE-FEASIBILITY FEEDBACK (the engineering-ised B-arm).

The planner receives the SAME task/tools/evidence catalog plus measured frontier
FACTS (per-doc minimum retrieval budgets for seed-quote coverage, the 3,300-char
per-node injection limit, segmented retrieval + facts_merge availability).
These are facts, not structure directives: the LLM still decides nodes/deps.
Envelope: <=2 calls (initial + at most one structured repair). No template
fallback; failure is reported as failure. Post-planning audit is zero-call.
"""
import json

from pilot_common import PILOT_DIR, Meter
import semantic_plan as SP
import assemble_dag as AD
from v3_kdx_resource_aware import TASK, CUTOFF, ctx_table, KDX_DOCS

CAPS = dict(max_calls=2, max_guaranteed_actual=5000)
FRONTIER = json.loads((PILOT_DIR / 'kdx_retrieval_frontier.json').read_text())


def frontier_block():
    pd = FRONTIER['per_doc_minimum_chars']
    lines = [f'- {doc}: 约 {chars:,} 字（词汇检索下覆盖该文档关键引文段落的最低预算）'
             for doc, chars in pd.items()]
    return (
        '\n\n【实测资源可行性通报（事实，非结构指示）】\n'
        '- 证据语料 127,598 字（5 文档；两份问询回复合计约 97,817 字）。\n'
        '- 当前执行协议：单节点直接证据注入上限约 3,300 字；超出部分无法注入。\n'
        '- 可用工具：按 doc_id+关键词的分段检索（每块带出处/偏移/哈希），以及 facts_merge'
        '（通用多源汇合契约，程序执行零模型调用，保留出处与冲突标记）。\n'
        '- 实测各文档最低检索预算（seed 引文覆盖前沿）：\n' + '\n'.join(lines) +
        f'\n- 分文档作用域全覆盖合计约 {FRONTIER["total_minimum_chars_approx"]:,} 字；'
          '单节点若引用全部文档将远超注入上限。\n'
        '请自行决定任务结构、检索组织与依赖，使计划在上述预算内真实可执行。')


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v3frontier.jsonl', **CAPS)
    sys_p = SP.plan_system_prompt()
    usr = SP.plan_user_prompt(TASK, ctx_table()).replace('信息截止2024-07-10', f'信息截止{CUTOFF}') \
        + frontier_block()
    rec, txt = meter.call('glm53', sys_p, usr, max_tokens=896,
                          purpose='v3frontier_planner_initial', timeout_s=60)
    attempts = [{'phase': 'initial', 'call_id': rec['call_id']}]
    plan, issues = None, ['parse']
    try:
        plan = SP.parse_plan(txt)
        issues = SP.validate_plan(plan, KDX_DOCS)
    except Exception as e:
        issues = [f'parse:{e}']
    attempts[0]['issues'] = issues
    if issues and meter.n_calls < meter.max_calls:
        rec2, txt2 = meter.call(
            'glm53', sys_p,
            usr + f'\n\n你的计划未通过结构检查：{json.dumps(issues, ensure_ascii=False)[:400]}。'
                  '请修复后重新输出完整计划JSON。',
            max_tokens=896, purpose='v3frontier_planner_repair', timeout_s=60)
        try:
            plan = SP.parse_plan(txt2)
            issues = SP.validate_plan(plan, KDX_DOCS)
        except Exception as e:
            issues = [f'parse:{e}']
        attempts.append({'phase': 'repair', 'call_id': rec2['call_id'], 'issues': issues})

    result = {'event': '康得新(002450)', 'mode': 'frontier-feedback replanning',
              'planner_attempts': attempts, 'budget': meter.summary()}
    if issues or plan is None:
        result['status'] = 'FAILED_WITHIN_ENVELOPE'
        result['issues'] = issues
        (PILOT_DIR / 'v3_frontier_replan.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print('FAILED within envelope; issues:', issues)
        return
    gv, iss = AD.assemble(plan)
    if gv is None:
        result['status'] = 'ASSEMBLY_INVALID'
        result['issues'] = iss
        (PILOT_DIR / 'v3_frontier_replan.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print('ASSEMBLY INVALID:', iss)
        return
    graph, validated = gv
    from kdx_retrieval import build_index, score_chunk, build_idf, TASK_TERMS, evaluate_coverage, CHUNK_CHARS
    feas = []
    for t in plan['plan']:
        if t['kind'] in ('extracts', 'extracts_f'):
            docs = [d for d in t.get('doc_ids', []) if d in set(KDX_DOCS)]
            budget = 3300
            # per-node SCOPED retrieval: rank only within the node's declared docs,
            # round-robin across them until the node budget fills
            sub = [c for c in build_index() if c['doc_id'] in set(docs)] if docs else []
            idf = build_idf(sub or build_index(), TASK_TERMS)
            by_doc = {}
            for c in sorted(sub, key=lambda c: -score_chunk(c['text'], TASK_TERMS, idf)):
                by_doc.setdefault(c['doc_id'], []).append(c)
            picked, used, rank = [], 0, 0
            while any(rank < len(v) for v in by_doc.values()):
                for d, chunks in by_doc.items():
                    if rank < len(chunks) and used + len(chunks[rank]['text']) <= budget:
                        picked.append(chunks[rank]); used += len(chunks[rank]['text'])
                rank += 1
                if used >= budget * 0.98:
                    break
            cov = evaluate_coverage(picked)
            feas.append({'node': t['id'], 'docs': docs, 'budget_chars': budget,
                         'scoped_chunks': len(picked), 'chars_used': used,
                         'seed_quote_coverage': f"{cov['covered']}/{cov['total']}",
                         'covered_ids': [r['fact_id'] for r in cov['detail'] if r['quote_found_in_chunk']]})
    result.update({'status': 'ASSEMBLED', 'plan': plan, 'graph': graph.to_dict(),
                   'layers': [list(l) for l in validated.layers],
                   'graph_hash': validated.graph_hash,
                   'executability_probe': feas})
    (PILOT_DIR / 'v3_frontier_replan.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    from collections import Counter
    print('ASSEMBLED layers:', [list(l) for l in validated.layers],
          'kinds:', dict(Counter(t['kind'] for t in plan['plan'])))
    for t in plan['plan']:
        print(f"  {t['id']:3s} {t['kind']:13s} deps={str(t['depends']):22s} | {t['goal'][:38]}")
    print('executability probe:', json.dumps(feas, ensure_ascii=False))
    print('budget:', meter.summary()['settled_actual_tokens'])


if __name__ == '__main__':
    main()
