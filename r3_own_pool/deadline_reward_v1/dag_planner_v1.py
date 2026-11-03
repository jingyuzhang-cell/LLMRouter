"""dag_planner_v1 — real LLM Planner validation (operator-authorized
2026-10-28: <=18 request attempts, incremental cash hard cap ¥0,
no auto-retry, no end-to-end execution). GLM-5.3-Flash subscription
(¥0/call frozen rate) via the shared transport.

Planner contract (no preset DAGs, no reference answers, no fixed
node templates): input = user NL question + allowed source index +
constraints + capability vocabulary; output = complete DAGSpec.
All raw responses saved, including parse failures and illegal DAGs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from deadline_reward_v1.r2fix_runner import call_ds, load_env_creds
import deadline_reward_v1.dag_runtime_v1 as R

HERE = ROOT / 'deadline_reward_v1'
OUT = HERE / 'fe_screening_runs' / 'planner_v1_20261028'
CAP_CALLS, CAP_CASH = 18, 0.0

ROLES_DOC = """可用节点角色（能力词汇表，规划器自行决定用哪些、几个、怎么连接）：
- extraction: 从指定证据文档抽取原子事实（facts）
- timeline: 事件时间线整理（dates）
- amounts: 金额类事实核算（amounts）
- penalties: 处罚决定梳理（penalty_items）
- entity_relations: 涉事主体及关系识别（entities）
- timeline_deep: 时间线阶段复核（stages）
- amounts_check: 金额交叉复核（amounts_checked）
- cross_check: 跨来源/跨节点核验（checked）
- merge: 多来源合并（merged）
- entity_graph: 主体关系图谱（entity_edges）
- synthesis: 最终调查结论（report）
每个节点必须声明 inputs（上游节点 id 列表）与 contract（produces 字段
列表；requires 为必须由上游提供的字段）。evidence 为该节点绑定的
source_index 中的 doc_id（仅 extraction/retrieval 类节点需要）。"""

QUESTIONS = [
    ('A_信息披露变化',
     '调查江苏舜天2018-2021年年报信息披露违法事实：虚增收入/利润的逐年变化、'
     '各年度虚假记载的具体金额，基于官方处罚与公告文档给出跨年度事实对比。'),
    ('B_调查至行政处罚',
     '梳理泽达易盛案从监管调查到行政处罚的全过程：监管认定的违法事实、'
     '责任主体及其角色、处罚种类与金额，并核验关键认定与处罚文件一致。'),
    ('C_并购与关联交易',
     '分析舜天专网通信业务中的关联交易结构与资金往来：涉事公司之间的交易'
     '关系、资金流向角色（客户/供应商/通道），识别隐蔽关联主体及其作用。'),
    ('D_重大事件与市场反应',
     '泽达易盛欺诈发行被强制退市事件的全景调查：事件时间线、监管处理过程、'
     '对投资者的赔付安排，以及该事件对市场与同类公司的警示意义分析。'),
]


def source_index():
    docs = []
    from deadline_reward_v1.full_dag_tasks import load_docs
    pool = load_docs()
    for k, v in pool.items():
        if v['event'] in ('舜天', 'jsst'):
            docs.append(dict(doc_id='jsst', title='舜天公告/处罚文书',
                             event='江苏舜天 专网通信虚假业务'))
        elif v['event'] == 'ydt':
            docs.append(dict(doc_id='ydt_d1', title='元道退相关公告',
                             event='元道退'))
    zeda = json.loads((HERE / 'h1v8_docs' / 'zeda_docs.json').read_text())
    for d in zeda['docs']:
        docs.append(dict(doc_id=d['doc_id'], title=d['title'],
                         event='泽达易盛(688555)欺诈发行案'))
    seen, out = set(), []
    for d in docs:
        if d['doc_id'] not in seen:
            seen.add(d['doc_id'])
            out.append(d)
    return out


PROMPT = """你是资本市场调查任务的 DAG 规划器。给定用户问题、可用证据源索引、
任务约束与节点能力词汇表，请规划一个有向无环图（DAG）的调查执行计划。

## 用户问题
{question}

## 可用证据源索引（仅可绑定此处列出的 doc_id；不得虚构来源）
{sources}

## 任务约束
截止期 {D}s，现金预算 ¥{Ccap}（Flash 免费、DS/Qwen 按量）。模型池：
Flash(快/便宜/质量中)、DS(付费/质量高)、Qwen(付费/质量中上)。

## {roles}

## 输出要求
只输出一个 JSON 对象（禁止其他文本）：
{{"task_class": "简短任务类型名",
 "nodes": [{{"id": "n1", "role": "角色", "inputs": ["上游id"],
             "contract": {{"produces": ["字段"], "requires": ["字段"]}},
             "evidence": "doc_id 或 null"}}],
 "rationale": "一段话：为什么这样规划"}}
要求：节点数按需（5-10）；只规划必要的节点，不凑数；依赖必须反映真实
信息流；单一终节点产出最终报告；不同类型问题应有不同结构。"""


def parse_spec(txt):
    import re
    t = txt.strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    m = re.search(r'\{.*\}', t, re.S)
    if m:
        t = m.group(0)
    obj = json.loads(t)
    spec = dict(task_id='planned', task_class=obj.get('task_class', '?'),
                evidence=[], constraints=dict(D=140.0, Ccap=0.02),
                nodes=[])
    for n in obj.get('nodes', []):
        spec['nodes'].append(dict(
            id=str(n['id']), role=str(n['role']),
            inputs=[str(x) for x in n.get('inputs', [])],
            contract=dict(produces=list(n.get('contract', {}).get(
                'produces', [])),
                requires=list(n.get('contract', {}).get('requires', []))),
            evidence=n.get('evidence')))
    return spec, obj.get('rationale', '')


def main():
    if os.environ.get('PLANNER_V1_GO') != '1':
        raise PermissionError('requires PLANNER_V1_GO=1')
    OUT.mkdir(parents=True, exist_ok=True)
    creds = load_env_creds()
    ledger = open(OUT / 'LEDGER.jsonl', 'w')
    src_idx = source_index()
    calls = 0
    cash = 0.0
    records = []
    t0 = time.monotonic()
    try:
        for cls, q in QUESTIONS:
            for rep in (1, 2, 3):
                if calls >= CAP_CALLS:
                    raise RuntimeError('cap')
                prompt = PROMPT.format(
                    question=q,
                    sources=json.dumps(src_idx, ensure_ascii=False),
                    D=140, Ccap=0.02, roles=ROLES_DOC)
                o = call_ds(prompt, creds, max_out_tokens=3072)
                calls += 1
                cash += float(o.get('cash_cny', 0.0) or 0.0)
                if cash > CAP_CASH + 1e-9:
                    raise RuntimeError(f'cash cap: {cash}')
                raw = o['answer']
                (OUT / f'{cls}_r{rep}_raw.txt').write_text(raw)
                rec = dict(cls=cls, rep=rep, call=calls,
                           in_tok=o['tokens_in'], out_tok=o['tokens_out'],
                           lat=round(o['latency_s'], 1),
                           cash=o.get('cash_cny', 0.0))
                try:
                    spec, why = parse_spec(raw)
                    ok, reasons = R.check_legality(spec)
                    rec.update(nodes=len(spec['nodes']),
                               parse_ok=True, legal=ok, reasons=reasons,
                               roles=[n['role'] for n in spec['nodes']],
                               evidence_bound=sorted(set(
                                   n['evidence'] for n in spec['nodes']
                                   if n.get('evidence'))))
                    if ok:
                        (OUT / f'{cls}_r{rep}_spec.json').write_text(
                            json.dumps(spec, ensure_ascii=False, indent=1))
                    rec['rationale'] = why[:200]
                except Exception as e:
                    rec.update(parse_ok=False, legal=False,
                               err=repr(e)[:120])
                records.append(rec)
                ledger.write(json.dumps(rec, ensure_ascii=False) + '\n')
                ledger.flush()
                print(json.dumps(rec, ensure_ascii=False)[:300],
                      flush=True)
        with open(OUT / 'PLANNER_V1_RESULTS.json', 'w') as f:
            json.dump(dict(status='COMPLETE', calls=calls, cash=cash,
                           wall_s=round(time.monotonic() - t0, 1),
                           records=records), f, ensure_ascii=False,
                      indent=1)
        print(f'COMPLETE calls={calls} cash={cash}')
    except BaseException as e:
        with open(OUT / 'PLANNER_V1_INCOMPLETE.json', 'w') as f:
            json.dump(dict(reason=repr(e), calls=calls, cash=cash,
                           records=records), f, ensure_ascii=False,
                      indent=1)
        print(f'INCOMPLETE: {e} calls={calls} cash={cash}')


if __name__ == '__main__':
    main()
