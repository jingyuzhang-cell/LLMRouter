"""QP1 dev prompts. Arm-specific evidence requirements; everything else identical."""
import json

MAXTOK = {'E': 2000, 't': 1500, 'm': 2500, 'r': 2000, 'v': 2000, 'p': 4000}

E_SYS = ('你是精确的文书信息抽取器。只输出 JSON 对象，不得输出解释性文字。不得编造；'
         '原文没有的方面写 UNKNOWN。')
EVIDENCE_REQ = ('证据要求（本臂强制执行）：每个事实必须给出 doc（只能是本组文书 ID）、page（整数）、'
                'quote（被引文书中连续出现的逐字原文，禁止省略号、禁止拼接）；'
                '无法给出逐字证据的方面不要输出。')
BASELINE_REQ = '请抽取以下方面；输出 JSON：{"facts":[{"field":"方面","value":"结果"}]}。'

M_SYS = '你是严谨的多文档合并器。只输出 JSON：{"facts":[{"field":"...","value":"...","doc":"...","page":1,"quote":"..."}]}。不得编造。'
R_SYS = '你是严谨的跨文档推理器。只输出 JSON：{"relations":[{"relation":"...","value":"...","docs":["..."],"quote":"..."}]}。不得编造。'
V_SYS = '你是严谨的证据核验器。只输出 JSON：{"checks":[{"fact":"...","verdict":"SUPPORTED|UNSUPPORTED|UNKNOWN","reason":"..."}]}。'
P_SYS = ('你是严谨的最终答案汇总器。只输出 JSON：{"answers":[{"fact_id":"...","value":"...","doc":"...",'
         '"page":1,"quote":"连续原文片段"}],"abstentions":[{"item_id":"...","text":"明确理由"}],"complete":true}。'
         '不得使用给定上游材料之外的任何信息。')


def doc_block(contract, doc_ids):
    parts = []
    for d in doc_ids:
        doc = contract['source_pages'][d]
        pages = doc.get('pages', {})
        parts.append(f'\n=== 文档 {d} ===')
        for pno in sorted(pages, key=lambda x: int(x) if str(x).isdigit() else 0):
            parts.append(f'\n[第{pno}页]\n' + pages[pno].get('text', ''))
    return ''.join(parts)


def field_list(contract):
    out = []
    for f in contract['required_facts']:
        b = f.get('bucket') or f.get('subject') or f['fact_id']
        if b not in out:
            out.append(b)
    return out


def e_user(contract, doc_ids, arm):
    fields = '\n'.join(f'- {x}' for x in field_list(contract))
    ev = EVIDENCE_REQ if arm != 'Baseline' else BASELINE_REQ
    return (f"任务问题：{contract['question']}\n\n本节点负责的文书：{', '.join(doc_ids)}\n"
            f"{doc_block(contract, doc_ids)}\n\n请抽取以下方面：\n{fields}\n\n{ev}\n"
            '只输出 JSON。')


def m_user(contract, ups):
    return (f"任务问题：{contract['question']}\n\n各抽取节点的结果：\n"
            f"{json.dumps(ups, ensure_ascii=False)}\n\n请合并去重、保留逐字证据，输出统一事实表。")


def t_user(contract, e0_out):
    return (f"任务问题：{contract['question']}\n\n以下是第一组抽取结果：\n"
            f"{json.dumps(e0_out, ensure_ascii=False)}\n\n请整理其中的日期与时间线（保留原文引用）。")


def r_user(contract, merged):
    return (f"任务问题：{contract['question']}\n\n以下是合并后的事实表：\n"
            f"{json.dumps(merged, ensure_ascii=False)}\n\n请做跨文档关系判断（主体是否同一、编号/事件是否对应、"
            '金额/日期是否一致），只输出关系结论与原文引用。')


def v_user(contract, merged, relations):
    return (f"任务问题：{contract['question']}\n\n事实表：\n{json.dumps(merged, ensure_ascii=False)}\n\n"
            f"关系：\n{json.dumps(relations, ensure_ascii=False)}\n\n"
            '请逐条判断每个事实的引文是否支持其 value；输出 checks。')


def p_user(contract, merged, relations, verified, arm):
    slots = [{k: f.get(k) for k in ('fact_id', 'subject', 'predicate', 'value_kind', 'description')}
             for f in contract['required_facts']]
    unknowns = [{'item_id': u.get('item_id'), 'question': u.get('question')}
                for u in contract.get('unknown_items', [])]
    extra = ''
    if arm == 'E3':
        extra = ('\n注意：只允许使用“已核验事实”回答；未出现在已核验列表中的槽位必须写入 abstentions，'
                 '不得凭记忆或推断作答。\n已核验事实：' + json.dumps(verified, ensure_ascii=False))
    return (f"任务问题：{contract['question']}\n\n事实表：\n{json.dumps(merged, ensure_ascii=False)}\n\n"
            f"关系：\n{json.dumps(relations, ensure_ascii=False)}\n{extra}\n"
            '输出格式：answers 按槽位逐项填写 {"fact_id":..., "value":..., "doc": 文书ID, "page": 页码, '
            '"quote": 连续逐字原文}。金额与百分比保留原文单位；日期 YYYY-MM-DD。\n'
            f'槽位：{json.dumps(slots, ensure_ascii=False)}\n'
            f'unknown 项（无法确定时写入 abstentions）：{json.dumps(unknowns, ensure_ascii=False)}\n'
            '如认为上游不完整无法负责作答，置 complete=false。')
