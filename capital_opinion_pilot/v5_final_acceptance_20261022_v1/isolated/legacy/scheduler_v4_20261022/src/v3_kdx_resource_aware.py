"""V3 Kangde Xin resource-aware planning A/B contrast (AUTHORIZED: <=2 calls,
hard cap 3,500 guaranteed-settle; no repair budget — a failed plan is reported as-is).

A: normal planning  — identical task/tools/evidence catalog as the prior KDX run
   (fresh sample also probes planner determinism vs the previous output).
B: resource-aware   — same inputs PLUS real runtime constraints stated as facts
   (corpus size, per-node direct-injection budget, segmented-retrieval capability).
Neither arm sees silver answers, node-count directives, or templates.
"""
import json

from pilot_common import PILOT_DIR, Meter
import semantic_plan as SP
import assemble_dag as AD

CAPS = dict(max_calls=2, max_guaranteed_actual=3500)
KDX_DOCS = ['kdx_inquiry_2018', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020', 'kdx_inquiry_2019']
TASK = ('请调查康得新（002450）跨年度财务披露违法违规事件：追溯2018-2019年年报问询、证监会立案与'
        '行政处罚/市场禁入的过程，核实跨年度虚假记载（虚增利润、银行存款、关联担保）的监管认定与'
        '公司披露，梳理涉及主体、关键时间节点，生成具有准确证据引用的调查报告。'
        '无法确认的事项必须明确标注。')
CUTOFF = '2021-06-30'
CONSTRAINT_BLOCK = (
    '\n\n【真实运行资源约束（事实通报，非结构指示）】\n'
    '- 证据语料总量约 127,598 字（5 份文档；单篇最大 57,409 字，两份问询回复合计约 97,817 字）。\n'
    '- 当前执行协议：单个节点的直接证据注入上限约 3,300 字。\n'
    '- 可用工具能力：按 doc_id+关键词的分段检索与证据定位，可将定位片段（而非全文）注入节点；'
    '模型调用与预算有限。\n'
    '请自行判断如何组织证据获取与任务结构。')


def ctx_table():
    manifests = json.load(open(PILOT_DIR / 'v3_evidence' / 'v3_manifests.json'))
    rows = [{'doc_id': d['doc_id'], 'title': d['title'], 'public_date': d['public_date'],
             'sha256': str(d.get('sha256', ''))[:12], 'text_chars': d['text_chars']}
            for d in manifests['A_kangdexin']['documents']]
    return json.dumps(rows, ensure_ascii=False)


def run_arm(meter, arm, extra):
    sys_p = SP.plan_system_prompt()
    usr = SP.plan_user_prompt(TASK, ctx_table()).replace('信息截止2024-07-10', f'信息截止{CUTOFF}') + extra
    rec, txt = meter.call('glm53', sys_p, usr, max_tokens=576,
                          purpose=f'v3kdxra_{arm}', timeout_s=60)
    try:
        plan = SP.parse_plan(txt)
        issues = SP.validate_plan(plan, KDX_DOCS)
    except Exception as e:
        plan, issues = None, [f'parse:{e}']
    entry = {'arm': arm, 'call_id': rec['call_id'], 'usage': rec['usage'],
             'issues': issues, 'raw_chars': len(txt)}
    if plan and not issues:
        gv, iss = AD.assemble(plan)
        if gv is None:
            entry['issues'] = iss
        else:
            graph, validated = gv
            entry['plan'] = plan
            entry['graph'] = graph.to_dict()
            entry['layers'] = [list(l) for l in validated.layers]
            entry['graph_hash'] = validated.graph_hash
    return entry


def feasibility(entry):
    """Zero-call evidence-need feasibility vs the ~3,300-char direct-injection budget."""
    if 'plan' not in entry:
        return None
    manifests = json.load(open(PILOT_DIR / 'v3_evidence' / 'v3_manifests.json'))
    chars = {d['doc_id']: d['text_chars'] for d in manifests['A_kangdexin']['documents']}
    per_node, covered = [], set()
    for t in entry['plan']['plan']:
        if t['kind'] in ('extracts', 'extracts_f'):
            docs = [d for d in t.get('doc_ids', []) if d in chars] or \
                   [d for d in KDX_DOCS if d in t.get('goal', '')]
            need = sum(chars.get(d, 0) for d in docs)
            seg = any(k in t.get('goal', '') for k in ('分段', '检索', '定位', '窗口'))
            per_node.append({'node': t['id'], 'docs': docs, 'need_chars': need,
                             'direct_injection_feasible': need <= 3300,
                             'declares_segmented_strategy': seg})
            covered |= set(docs)
    return {'per_extracts_node': per_node,
            'docs_planned': sorted(covered),
            'all_docs_planned': set(covered) == set(KDX_DOCS),
            'cross_year_planned': bool({'kdx_inquiry_2018', 'kdx_inquiry_2019'} & covered)}


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v3kdxra.jsonl', **CAPS)
    A = run_arm(meter, 'A', '')
    B = run_arm(meter, 'B', CONSTRAINT_BLOCK)
    for e in (A, B):
        e['feasibility'] = feasibility(e)
    out = {'authorized': {'calls': 2, 'guaranteed_settle_cap': 3500},
           'arms': A and B and [A, B],
           'budget': meter.summary()}
    (PILOT_DIR / 'v3_kdx_resource_aware.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for e in (A, B):
        ok = 'plan' in e
        print(f"== arm {e['arm']}: {'ASSEMBLED' if ok else 'INVALID'} call={e['call_id']} "
              f"in={e['usage']['input_tokens']} out={e['usage']['output_tokens']} issues={e['issues'][:2]}")
        if ok:
            from collections import Counter
            kinds = Counter(t['kind'] for t in e['plan']['plan'])
            print('   layers:', e['layers'], ' kinds:', dict(kinds))
            for t in e['plan']['plan']:
                print(f"   {t['id']:3s} {t['kind']:13s} deps={str(t['depends']):18s} | {t['goal'][:40]}")
        print('   feasibility:', json.dumps(e['feasibility'], ensure_ascii=False)[:300])
    print('budget:', json.dumps(meter.summary()['settled_actual_tokens']))


if __name__ == '__main__':
    main()
