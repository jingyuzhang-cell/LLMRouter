"""Part 2 (AUTHORIZED: <=2 calls, cumulative actual+in-flight reserve <=4,000):
structured repair of the frozen A/B plans. Each planner sees its ORIGINAL plan,
its ORIGINAL validation errors, and the unified new-contract description
(generic facts_merge). No silver answers, no templates, no manual node edits.
A failed repair is recorded INVALID — no retries.
"""
import json

from pilot_common import PILOT_DIR, Meter
import semantic_plan as SP
import assemble_dag as AD
from v3_kdx_resource_aware import TASK, CUTOFF, ctx_table, CONSTRAINT_BLOCK, KDX_DOCS, feasibility

CAPS = dict(max_calls=2, max_guaranteed_actual=4000)
MERGE_NOTE = (
    '\n\n【新增通用契约说明】facts_merge（transformation，程序执行零模型调用）：'
    '可将任意数量 extracts_f 检索线的输出汇合为一个 doc_extracts，程序合并时保留每条事实的'
    '来源节点/文档出处并标记同键值冲突；下游 timeline/entity_facts/factcheck_* 契约消费方式不变。'
    '多检索线汇合必须通过 facts_merge（或已有 facts 合并口契约），不得把两条 extracts 线直连标量端口。')

ARM_DIRECTIVE = {
    'A': '\n\n【修复要求】你的计划存在未被最终报告消费的死分支节点。请修复：只有当某节点确属必要时'
         '保留并为其建立真实的下游数据依赖；确无必要的节点直接删除。',
    'B': '\n\n【修复要求】你的核查节点缺少上游依赖，且多检索线的汇合不合法。请修复：利用合法的'
         '多输入契约（facts_merge 或 facts 合并口）表达两条检索分支的汇合，并补齐核查节点所需的'
         '全部上游种类。',
}


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v3kdxrepair.jsonl', **CAPS)
    sys_p = SP.plan_system_prompt()
    out = {'arms': []}
    for arm in ('A', 'B'):
        frozen = json.loads((PILOT_DIR / 'v3_kdxra_frozen' / f'arm_{arm}_original.json').read_text())
        base_usr = SP.plan_user_prompt(TASK, ctx_table()).replace('信息截止2024-07-10', f'信息截止{CUTOFF}')
        if arm == 'B':
            base_usr += CONSTRAINT_BLOCK
        user = (base_usr + MERGE_NOTE
                + '\n\n你的上一版语义计划（原始输出）：\n' + frozen['raw_response']
                + '\n\n该计划未通过的结构检查错误：\n' + json.dumps(frozen['validation_errors'], ensure_ascii=False)
                + ARM_DIRECTIVE[arm]
                + '\n\n请输出修复后的完整计划JSON（仅计划本身）。')
        rec, txt = meter.call('glm53', sys_p, user, max_tokens=640,
                              purpose=f'v3kdxrepair_{arm}', timeout_s=60)
        entry = {'arm': arm, 'call_id': rec['call_id'], 'usage': rec['usage'],
                 'raw_response': txt, 'repair_directive': ARM_DIRECTIVE[arm][2:12]}
        try:
            plan = SP.parse_plan(txt)
            issues = SP.validate_plan(plan, KDX_DOCS)
        except Exception as e:
            plan, issues = None, [f'parse:{e}']
        entry['issues'] = issues
        if plan is not None and not issues:
            gv, iss = AD.assemble(plan)
            if gv is None:
                entry['issues'] = iss
                entry['status'] = 'ASSEMBLY_INVALID'
            else:
                graph, validated = gv
                entry.update({'status': 'REPAIRED', 'plan': plan, 'graph': graph.to_dict(),
                              'layers': [list(l) for l in validated.layers],
                              'graph_hash': validated.graph_hash,
                              'feasibility': feasibility({'plan': plan})})
        else:
            entry['status'] = 'PLAN_INVALID'
        out['arms'].append(entry)
        print(f"== arm {arm}: {entry['status']} in={rec['usage']['input_tokens']} "
              f"out={rec['usage']['output_tokens']} issues={str(entry.get('issues'))[:120]}")
        if entry['status'] == 'REPAIRED':
            from collections import Counter
            print('   layers:', entry['layers'], ' kinds:', dict(Counter(t['kind'] for t in plan['plan'])))
            for t in plan['plan']:
                print(f"   {t['id']:3s} {t['kind']:13s} deps={str(t['depends']):20s} | {t['goal'][:36]}")
    out['budget'] = meter.summary()
    (PILOT_DIR / 'v3_kdx_repair.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('budget:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
