"""Real provider for Phase Pi V2.2.1. GLM thinking=low / DeepSeek thinking=disabled.

Builds the FROZEN stage_a prompts per node. Spec-level defects are expressed as
different CONTRACTS (persistent), never as one-shot output corruption.
"""
import json, os, sys, time, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import executor as SA
from stage_d_v2_transport import Transport, Ledger, MODEL_CFG

MAXTOK = {'E': 2000, 'J1': 3000, 'J2': 4000, 'SINK': 4000}

def doc_text(doc_id):
    return ''.join(rec['text'] for rec in SA.SRC[doc_id]['pages'].values())

def _by_doc_role(ups):
    """Map upstream outputs to logical roles by node-name prefix, so a split
    (E2 -> E2_merge) still feeds J1's 'E2' slot. Without this, Z would be
    structurally starved of half its input."""
    slots = {'E1': '', 'E2': '', 'J1': '', 'E3': '', 'E4': '', 'J2': ''}
    for name, out in ups.items():
        for role in slots:
            if name == role or name.startswith(role + '_'):
                slots[role] = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return slots

def build(node, spec, doc, ups, sink_slots):
    """Return (system, user, max_tokens)."""
    q = SA.QUESTION
    if spec == 'E_POS':                 # normal E1/E2 contract
        return SA.E_SYSTEM + SA.E_POSITION_ADDENDUM, SA.e_user(node), MAXTOK['E']
    if spec == 'E_POS_DEFECTIVE':       # S1/S1b: contract WITHOUT the positions requirement
        return SA.E_SYSTEM, SA.e_user(node), MAXTOK['E']
    if spec == 'E_POS_ONLY':            # derived sub-task: positions only
        t = doc_text(doc)
        u = (f'任务问题：{q}\n\n文档{doc}全文：\n{t}\n\n'
             f'只抽取：涉事人员职务相关表述（positions 字段）。输出 JSON：'
             f'{{"positions":[{{"field":"任职状况","value":"逐字原文","quote":"完整原句","page":页码}}]}}；'
             f'原文无职务表述则输出空数组。不得推断。')
        return SA.E_SYSTEM + SA.E_POSITION_ADDENDUM, u, MAXTOK['E']
    if spec == 'E_NO_POS':              # derived sub-task: everything EXCEPT positions
        t = doc_text(doc)
        u = (f'任务问题：{q}\n\n文档{doc}全文：\n{t}\n\n'
             f'抽取立案对象、告知书编号、全部日期、立案事由及原文引用。'
             f'不要输出 positions 字段。按系统约定输出 JSON。')
        return SA.E_SYSTEM, u, MAXTOK['E']
    if spec == 'E':
        return SA.E_SYSTEM, SA.e_user(node), MAXTOK['E']
    if spec == 'J1':
        s = _by_doc_role(ups)
        return SA.J1_SYSTEM, SA.j1_user(json.dumps({'E1': s['E1'], 'E2': s['E2']}, ensure_ascii=False)), MAXTOK['J1']
    if spec == 'J2':
        s = _by_doc_role(ups)
        return SA.J2_SYSTEM, SA.j2_user(json.dumps({'J1': s['J1'], 'E3': s['E3'], 'E4': s['E4']}, ensure_ascii=False)), MAXTOK['J2']
    if spec == 'SINK':
        s = _by_doc_role(ups)
        return SA.SINK_SYSTEM, SA.sink_user(s['J2']), MAXTOK['SINK']
    raise ValueError('unknown spec ' + spec)

class RealProvider:
    def __init__(self, tr, ledger, scenario, cap_calls=16, tag=''):
        self.tr, self.ledger, self.scenario, self.cap = tr, ledger, scenario, cap_calls
        self.tag = tag
        self.calls = []
    def call(self, node, spec, doc, ups, defective=False, model=None):
        if len(self.calls) >= self.cap: raise RuntimeError('call cap')
        system, user, mt = build(node, spec, doc, ups, None)
        alias = model if model in ('glm53flash', 'deepseek') else 'glm53flash'
        rec = self.tr.call(alias, system, user, mt, purpose=f'{self.tag}{self.scenario}:{node}:{spec}')
        self.calls.append(rec)
        if rec['stop_reason'] == 'max_tokens':
            self.calls.append(dict(rec, truncated=True))
        try:
            return extract_any(rec['text'])
        except Exception:
            raise ValueError(f'parse_fail {node}: {rec["text"][:120]}')

def _strip(t):
    return (t or '').strip()

def extract_any(t):
    """First complete JSON value; tolerates fences and trailing prose."""
    c = _strip(t)
    if c.startswith('```'):
        ls = c.split('\n')[1:]
        if ls and ls[-1].strip().startswith('```'): ls = ls[:-1]
        c = '\n'.join(ls).strip()
    try:
        return json.loads(c)
    except Exception:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(c):
        if ch in '{[':
            try:
                return dec.raw_decode(c[i:])[0]
            except Exception:
                continue
    raise ValueError('no JSON value')
