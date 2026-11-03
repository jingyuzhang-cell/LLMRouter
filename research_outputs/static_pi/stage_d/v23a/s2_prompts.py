"""Phase V2.3-A / S2 prompt assembly.

Generic per-document extraction -> cross-document join -> sink. The evidence
directive (v23-1) is appended identically to every system prompt, and the SINK
slot table contains NO gold values. A/B conditions differ only in the target
field's presence in the extraction brief for the target document(s).
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import evidence_contract_v23 as EC

MAXTOK = {'E': 2000, 'J': 3000, 'SINK': 4000}

E_SYSTEM = ('你是精确的文书信息抽取器。只输出一个 JSON 对象，不得输出解释性文字：'
            '{"fields":[{"field":"方面名称","value":"抽取结果","quote":"完整原句逐字引用","page":页码}]}。'
            '不得编造；原文没有的方面，value 写 "UNKNOWN"，quote 留空。')

J_SYSTEM = ('你是严谨的跨文档核对器。只输出一个 JSON 对象：'
            '{"checks":[{"topic":"核对主题","finding":"结论","docs":["doc_id"],"quote":"完整原句","page":页码}],'
            '"notes":["说明"]}。不得引入给定材料之外的信息。')

SINK_SYSTEM = ('你是严谨的最终答案汇总器。只输出一个 JSON 对象：'
               '{"answers":[{"fact_id":"...","value":"...","doc":"doc_id","page":1,"quote":"连续原文片段"}],'
               '"abstentions":[{"item_id":"...","text":"明确拒答理由"}],"complete":true}。'
               '不得使用给定上游材料之外的任何信息。')


def doc_text(contract, doc_id):
    doc = (contract.get('source_pages') or {}).get(doc_id, {})
    pages = doc.get('pages', {})
    parts = []
    for pno in sorted(pages, key=lambda x: int(x) if str(x).isdigit() else 0):
        parts.append(f'\n[第{pno}页]\n' + pages[pno].get('text', ''))
    return ''.join(parts)


def e_user(question, doc_id, text, field_brief):
    lines = '\n'.join(f'- {f}' for f in field_brief)
    return (f'任务问题：{question}\n\n文档{doc_id}全文：\n{text}\n\n'
            f'请只抽取以下方面（逐项给出原文引用 quote 与页码 page；原文没有的写 UNKNOWN）：\n{lines}\n\n'
            '只输出 JSON：{"fields":[{"field":"方面名称","value":"抽取结果","quote":"完整原句逐字引用","page":页码}]}。')


def j_user(question, e_outputs):
    return (f'任务问题：{question}\n\n以下是各文档的抽取结果（按 doc_id）：\n'
            f'{json.dumps(e_outputs, ensure_ascii=False)}\n\n'
            '请核对：跨文档的主体是否同一；编号、金额、日期是否互相印证或冲突；每个事实的归属文档。\n'
            '输出 JSON：{"checks":[{"topic":"...","finding":"...","docs":["doc_id"],"quote":"完整原句","page":页码}],"notes":[...]}。')


def sink_user(question, join_output, contract):
    slots = [{k: f.get(k) for k in ('fact_id', 'subject', 'predicate', 'value_kind', 'description')}
             for f in contract.get('required_facts', [])]
    unknowns = [{'item_id': u.get('item_id'), 'question': u.get('question')}
                for u in contract.get('unknown_items', [])]
    return (f'任务问题：{question}\n\n以下是跨文档核对结果：\n'
            f'{json.dumps(join_output, ensure_ascii=False)}\n\n'
            '输出格式：answers 按槽位逐项填写 {"fact_id":..., "value":..., "quote": 上游所引完整原句, '
            '"doc": 文档ID, "page": 页码}。金额与百分比请保留原文单位（元/万元/亿元/%），不要自行换算；日期 YYYY-MM-DD。\n'
            f'槽位：{json.dumps(slots, ensure_ascii=False)}\n'
            f'unknown 项（无法确定且属下列项时写入 abstentions）：{json.dumps(unknowns, ensure_ascii=False)}\n'
            '如认为上游不完整无法负责作答，置 complete=false。')


def system(kind):
    return EC.apply_to_system({'E': E_SYSTEM, 'J': J_SYSTEM, 'SINK': SINK_SYSTEM}[kind])


def max_tokens(kind):
    return MAXTOK[kind]
