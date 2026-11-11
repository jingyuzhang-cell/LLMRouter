"""Full-DAG discriminative comparison: task construction (zero calls).

Real diamond DAGs from verified benchmark documents (ruling item 3):

      fact_extraction(doc)
       /              \\
  timeline(facts)   entity_relations(doc)
       \\              /
      cross_verification(tl_out, er_out)   <- JOIN

Recovery closures DIFFER by fault location (the property the operator
demanded): fe fault -> {tl, er, xc} all re-run; tl or er fault -> {xc}
only; xc fault -> {xc}. Fault schedule, deadline tiers and the planned
heterogeneous assignment are frozen (seeded) and IDENTICAL for every
arm.

Unified citation contract v2 (ruling item 1 — fairness fix): every
node prompt EXPLICITLY states the evidence doc_id(s) it must cite, so
the citation requirement is satisfiable. Under v1 the doc_id never
appeared in the prompt (contract_unverifiable); v2 makes citation
faults model-attributable for ALL arms equally.

Tasks (15): 元道退 D1/D2/D3, 舜天 penalty doc, KDX penalty doc,
*ST卓然 x3, *ST纳川 x3, 欢瑞世纪 x3, ST西王 x1 — all real verified
documents from benchmark_v1 + the frozen screening samples.

Run: python3 -m deadline_reward_v1.full_dag_tasks
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
HERE = Path(__file__).resolve().parent
PILOT = Path('/root/capital_opinion_pilot')
BENCH = PILOT / 'benchmark_v1'

SEED = 20261014
NODES = ('fe', 'tl', 'er', 'xc')
# REAL structure (corrected 2026-10-14 per operator ruling): er reads
# the raw document INDEPENDENTLY — there is NO fe->er edge. Branch:
# fe and er start in parallel; join: xc consumes tl AND er outputs.
EDGES = {'fe': ['tl'], 'tl': ['xc'], 'er': ['xc'], 'xc': []}
# NOTE xc cross-check nature: tl and er BOTH derive from the SAME
# document -> intra-document cross-check (single-source), NOT
# cross-document verification. Recorded per task in xcheck_nature.

# planned heterogeneous assignment — SAME for all arms (frozen)
PLANNED_PI = {'fe': 'GLM-5.3', 'tl': 'GLM-5.3',
              'er': 'deepseek-flash', 'xc': 'qwen-plus'}

# deadline tiers (s) from observed real latencies: critical path =
# fe + max(tl, er) + xc over GLM/DS/qwen ranges 8-35s per call
DEADLINE_TIERS = {'tight': 90.0, 'medium': 120.0, 'loose': 160.0}

# fault schedule: node rotates; type mix 10 F_TRUNCATED / 5 F_JSON
FAULT_NODES = ['fe', 'tl', 'er', 'xc', 'tl', 'er', 'xc', 'fe', 'tl',
               'er', 'xc', 'tl', 'er', 'xc', 'fe']
FAULT_TYPES = ['F_TRUNCATED'] * 10 + ['F_JSON'] * 5


def downstream(node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in EDGES[n]:
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def closure_required(faulted, executed):
    return {faulted} | (downstream(faulted) & set(executed))


def _pdf_text(pdf_path: Path) -> str:
    import subprocess
    r = subprocess.run(['pdftotext', '-q', str(pdf_path), '-'],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def load_docs():
    """Doc units from real sources, FULL texts only:
    (a) FE V2 samples (full evidence): 元道退 D1/D2/D3, 舜天
        csrc_penalty_2024_41 + st_advance_notice_2023;
    (b) pilot evidence/text/: 舜天 st_announce_2024_020;
    (c) benchmark_v1 verified PDFs mapped by (pool_id, bytes),
        text extracted locally (pdftotext; zero API calls)."""
    docs = {}
    v2 = json.loads((HERE / 'FACT_EXTRACTION_SAMPLES_V2.json').read_text())
    for s in v2['samples']:
        docs[f"{s['event']}#{s['evidence_doc_id']}"] = dict(
            event=s['event'], doc_id=s['evidence_doc_id'],
            text=s['evidence_full_text'], title=s['evidence_doc_id'],
            public_date=s.get('information_cutoff', ''),
            source='FACT_EXTRACTION_SAMPLES_V2 full text')
    extra = (PILOT / 'evidence' / 'text' / 'st_announce_2024_020.txt')
    if extra.exists():
        docs['舜天#st_announce_2024_020'] = dict(
            event='舜天', doc_id='st_announce_2024_020',
            text=extra.read_text(errors='replace'),
            title='st_announce_2024_020', public_date='',
            source='pilot evidence/text')
    manifest = json.loads((BENCH / 'verified_docs_manifest.json')
                          .read_text())
    pdf_by_size = {}
    for p in (BENCH / 'docs').glob('*.pdf'):
        pdf_by_size[p.stat().st_size] = p
    for d in manifest:
        if d['company'] in ('元道退', '舜天', 'KDX'):
            continue  # pilot events already have full texts above
        pdf = pdf_by_size.get(d.get('bytes'))
        if pdf is None:
            continue
        text = _pdf_text(pdf)
        if len(text) < 400:
            continue
        key = f"{d['company']}#{d['pool_id']}:{pdf.stem}"
        docs[key] = dict(
            event=d['company'], doc_id=pdf.stem, text=text,
            title=d['title'], public_date=d.get('date', ''),
            source=f'benchmark_v1 {pdf.name}')
    return docs


def select_task_docs(docs):
    """15 task doc units: 元道退(ydt) x3, 舜天(jsst+st_announce) x3,
    *ST卓然 x3, *ST纳川 x3, 欢瑞世纪 x3 (all real, full texts)."""
    norm = {'ydt': '元道退', 'jsst': '舜天'}
    want = {'元道退': 3, '舜天': 3, '*ST卓然': 3, '*ST纳川': 3,
            '欢瑞世纪': 3}
    chosen, counts = [], {}
    for slot in sorted(docs):
        ev = norm.get(docs[slot]['event'], docs[slot]['event'])
        if counts.get(ev, 0) < want.get(ev, 0):
            chosen.append(slot)
            counts[ev] = counts.get(ev, 0) + 1
    return chosen


# ---- unified citation contract v2 prompts --------------------------------
def prompt_fe(doc_id, text):
    return (
        '你是一个资本市场事件调查助手。\n\n'
        '## 任务类型：fact_extraction\n'
        f'## 证据文档 doc_id：{doc_id}（输出中每条事实的 evidence_doc_id '
        '必须使用此 id）\n'
        '## 任务描述\n从证据文档中抽取原子事实：涉及主体、处罚决定（罚款'
        '金额、警告、市场禁入）、违法行为类型，每条含事实陈述、数值/日期、'
        f'evidence_doc_id（={doc_id}）。\n\n'
        f'## 证据文档 [{doc_id}]\n{text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每个元素包含 fact, date, '
        'entities, evidence_doc_id 字段\n- 输出契约：entity_facts.v2'
        '（引用契约可满足版）\n- 只抽取有证据支持的事实，不得虚构\n\n'
        '请严格按照输出要求完成任务。')


def prompt_tl(doc_id, facts_json, text_head):
    return (
        '你是一个资本市场事件调查助手。\n\n'
        '## 任务类型：timeline\n'
        f'## 证据文档 doc_id：{doc_id}（时间线每项的 evidence 引用此 id）\n'
        '## 任务描述\n基于抽取事实构建事件时间线（立案、告知、听证、处罚'
        '决定、公司公告），每项含日期、描述、证据。\n\n'
        f'## 上游抽取事实 [{doc_id}]\n{facts_json}\n\n'
        f'## 证据文档片段 [{doc_id}]\n{text_head}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每项包含 date, event, '
        'evidence 字段\n- 输出契约：timeline.v2\n\n'
        '请严格按照输出要求完成任务。')


def prompt_er(doc_id, text):
    return (
        '你是一个资本市场事件调查助手。\n\n'
        '## 任务类型：entity_relations\n'
        f'## 证据文档 doc_id：{doc_id}（每条关系的 evidence_doc_id 使用'
        '此 id）\n'
        '## 任务描述\n识别涉事主体（公司、责任人、业务对手方）及其关系'
        '（处罚对象、连带责任），每条含主体名称、角色、证据。\n\n'
        f'## 证据文档 [{doc_id}]\n{text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每条包含 entity, role, '
        'relation, evidence_doc_id 字段\n- 输出契约：entity_relations.v2\n\n'
        '请严格按照输出要求完成任务。')


def prompt_xc(doc_a, facts_a, doc_b, facts_b):
    return (
        '你是一个资本市场事件调查助手。\n\n'
        '## 任务类型：cross_verification\n'
        f'## 来源A doc_id：{doc_a}\n## 来源B doc_id：{doc_b}\n'
        '## 任务描述\n将两条来源的事实逐条对照核查（日期、金额、主体名称'
        '），输出核查结论。\n\n'
        f'## 来源A事实 [{doc_a}]\n{facts_a}\n\n'
        f'## 来源B事实 [{doc_b}]\n{facts_b}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每条包含 claim, source_a, '
        'source_b, verdict(SUPPORTED/UNSUPPORTED/CONFLICT) 字段\n'
        '- 输出契约：fact_check.v2\n\n'
        '请严格按照输出要求完成任务。')


def build_tasks():
    docs = load_docs()
    chosen = select_task_docs(docs)
    assert len(chosen) == 15, f'need 15 task docs, got {len(chosen)}'
    norm = {'ydt': '元道退', 'jsst': '舜天'}
    tier_cycle = ['medium', 'tight', 'loose']
    tasks = []
    for i, slot in enumerate(chosen):
        d = dict(docs[slot])
        d['event'] = norm.get(d['event'], d['event'])
        text = d['text'] or ''
        assert len(text) > 200, f'{slot}: no usable document text'
        doc_id = d['doc_id']
        fe_p = prompt_fe(doc_id, text)
        er_p = prompt_er(doc_id, text)
        tasks.append(dict(
            task_id=f'T{i+1:02d}', event=d['event'], doc_slot=slot,
            doc_id=doc_id,
            nodes=dict(
                fe=dict(prompt=fe_p, depends=[]),
                tl=dict(prompt='RUNTIME(facts from fe)', depends=['fe']),
                er=dict(prompt=er_p, depends=[]),
                xc=dict(prompt='RUNTIME(tl_out, er_out)',
                        depends=['tl', 'er'])),
            runtime_prompt_builders=dict(
                tl=lambda fe_out, text_head=text[:1200], doc_id=doc_id:
                prompt_tl(doc_id, fe_out[:4000], text_head),
                xc=lambda a_out, b_out: prompt_xc(
                    doc_id, a_out[:4000], doc_id, b_out[:4000])),
            fault_node=FAULT_NODES[i],
            fault_type=FAULT_TYPES[i],
            deadline_s=DEADLINE_TIERS[tier_cycle[i % 3]],
            planned_pi=dict(PLANNED_PI)))
    return tasks


def freeze():
    tasks = build_tasks()
    doc = dict(
        version='FULL_DAG_TASKS_v1_1',
        correction='v1.1: removed the VIRTUAL fe->er edge (er reads '
                   'the raw document independently). Task identities, '
                   'fault assignment, planned pi, deadlines UNCHANGED '
                   'from v1. xc is an INTRA-document cross-check '
                   '(tl and er both derive from the same document), '
                   'not cross-document verification.',
        seed=SEED, n_tasks=len(tasks),
        dag=dict(nodes=list(NODES), edges=EDGES,
                 xcheck_nature='intra-document (single source doc)'),
        unified_contract='entity_facts.v2 / timeline.v2 / '
                         'entity_relations.v2 / fact_check.v2 — '
                         'doc_id EXPLICITLY stated in every prompt '
                         '(citation requirement satisfifiable for all '
                         'arms)',
        closure_semantics=dict(
            fe='fault -> re-run fe, tl, xc (er UNAFFECTED: '
               'independent branch)',
            tl='fault -> re-run tl, xc',
            er='fault -> re-run er, xc',
            xc='fault -> re-run xc'),
        fault_schedule=dict(
            note='injected identically for every arm; frozen seed',
            nodes=FAULT_NODES, types=FAULT_TYPES),
        deadline_tiers=DEADLINE_TIERS, planned_pi=PLANNED_PI,
        tasks=[dict(
            task_id=t['task_id'], event=t['event'], doc_id=t['doc_id'],
            doc_slot=t['doc_slot'], fault_node=t['fault_node'],
            fault_type=t['fault_type'], deadline_s=t['deadline_s'],
            planned_pi=t['planned_pi'],
            xcheck_nature='intra-document',
            prompt_sha256=dict(
                fe=hashlib.sha256(t['nodes']['fe']['prompt']
                                  .encode()).hexdigest()[:16],
                er=hashlib.sha256(t['nodes']['er']['prompt']
                                  .encode()).hexdigest()[:16]))
            for t in tasks])
    out = HERE / 'FULL_DAG_TASKS.json'
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    # full prompts kept in a separate artifact (large)
    (HERE / 'FULL_DAG_TASKS_PROMPTS.json').write_text(json.dumps(
        [dict(task_id=t['task_id'],
              fe_prompt=t['nodes']['fe']['prompt'],
              er_prompt=t['nodes']['er']['prompt'])
         for t in tasks], indent=1, ensure_ascii=False))
    return doc


if __name__ == '__main__':
    doc = freeze()
    from collections import Counter
    print(f"tasks: {doc['n_tasks']}")
    print('events:', dict(Counter(t['event'] for t in doc['tasks'])))
    print('fault nodes:', dict(Counter(t['fault_node']
                                       for t in doc['tasks'])))
    print('fault types:', dict(Counter(t['fault_type']
                                       for t in doc['tasks'])))
    print('deadlines:', dict(Counter(t['deadline_s']
                                     for t in doc['tasks'])))
    print('planned pi:', doc['planned_pi'])
