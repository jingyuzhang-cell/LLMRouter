"""CapitalEvent-DAGBench node screening: real DEV/VAL → 20 node inputs
→ 80-call plan. Zero real model calls.

Node types (operator's four classes mapped to DAG semantics):
  fact_extraction  — extract atomic facts from evidence documents
  timeline         — construct event chronology from evidence
  entity_relations — identify entities, penalties, relationships
  cross_verification — cross-check facts against multiple sources

Events with REAL verified documents (benchmark_v1):
  元道退(301139)     3 docs — VAL gold annotation package exists (40 candidates)
  *ST卓然(688121)    3 docs
  *ST纳川(300198)    3 docs
  欢瑞世纪(000892)   3 docs
  中铁装配(300374)   3 docs
  ST西王(000639)     3 docs
  祥源文旅(600576)   1 doc
  交建股份(603815)   1 doc
Plus the fully executed 舜天 DAGs (DEV) and KDX (VAL).

Gold status: ALL SILVER (auto-verified / cross-model AI check).
元道退 has a 40-candidate annotation PACKAGE (not yet human-verified).
No event has completed independent human gold annotation.

Run: python3 -m deadline_reward_v1.capital_event_screening
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path('/root/r3_own_pool')
PILOT = ROOT.parent / 'capital_opinion_pilot'
BENCH = PILOT / 'benchmark_v1'

NODE_TYPES = ('fact_extraction', 'timeline', 'entity_relations',
              'cross_verification')


def _doc_text(path: Path) -> str:
    try:
        return path.read_text(errors='replace')[:200]
    except Exception:
        return ''


def load_real_node_inputs() -> List[dict]:
    """20 node inputs: 4 events × 4 node types + 舜天 DAG nodes.
    Each carries real evidence documents, contracts, and gold status."""
    inputs = []
    manifest = json.loads((BENCH / 'verified_docs_manifest.json').read_text())

    # group docs by company
    by_company = {}
    for d in manifest:
        by_company.setdefault(d['company'], []).append(d)

    # select 4 events with 3+ docs each (richest evidence)
    events = sorted(
        [(c, ds) for c, ds in by_company.items() if len(ds) >= 3],
        key=lambda x: x[0])
    # priority: 元道退 first (VAL gold package exists), then others
    priority = ['元道退', '*ST卓然', '*ST纳川', '欢瑞世纪']
    selected_events = []
    for p in priority:
        if p in dict(events):
            selected_events.append((p, dict(events)[p]))
    # fill remaining slots from other events if needed
    for c, ds in events:
        if len(selected_events) >= 4:
            break
        if c not in [s[0] for s in selected_events]:
            selected_events.append((c, ds))

    # per-event prompts for the four node types
    TYPE_PROMPTS = {
        'fact_extraction': '从证据文档中抽取原子事实：涉及主体、处罚'
                           '决定（罚款金额、警告、市场禁入）、虚增金额，'
                           '每条含事实陈述、数值/日期、证据doc_id。',
        'timeline': '基于证据文档构建事件时间线（立案、告知、听证、'
                    '处罚决定、公司公告），每项含日期、描述、证据。',
        'entity_relations': '识别涉事主体（公司、责任人、业务对手方）'
                            '及其关系（处罚对象、连带责任），每条含'
                            '主体名称、角色、证据doc_id。',
        'cross_verification': '将抽取的事实与时间线逐条对照多个证据'
                              '文档核查（日期、金额、主体名称），'
                              '输出核查结论(SUPPORTED/UNSUPPORTED)。',
    }
    TYPE_CONTRACTS = {
        'fact_extraction': 'entity_facts.v1',
        'timeline': 'timeline.v1',
        'entity_relations': 'entity_relations.v1',
        'cross_verification': 'fact_check.v1',
    }

    gold_packages = {'元道退': 'VAL_GOLD_ANNOTATION_PACKAGE '
                              '(40 candidates, NOT yet human-verified)'}

    # executed 舜天 DAG nodes: real node-level prompts with full contracts
    dag1 = json.loads((PILOT / 'initial_dag.json').read_text())
    # map DAG node types to operator's 4-class taxonomy
    type_map = {'extraction': 'fact_extraction',
                'reasoning': 'timeline',
                'verification': 'cross_verification'}
    # pick one node per operator type from the executed DAG
    used_types = set()
    for node in dag1['graph']['nodes']:
        op_type = type_map.get(node['node_type'], '')
        if op_type and op_type not in used_types:
            used_types.add(op_type)
            inputs.append(dict(
                event='jsst_600287',
                node_type=op_type,
                subtask=node['subtask'],
                output_contract=node['output_contract'],
                evidence_docs=[{'doc_id': d['doc_id']} for d in
                               json.loads((PILOT / 'evidence_manifest.json')
                                         .read_text())['documents']],
                evidence_summary='舜天 executed DAG node (real contract '
                                'and real evidence chain)',
                information_cutoff='2024-07-10',
                gold_status='SILVER_AUTO_VERIFIED',
                gold_package='facts_silver.json (8/10 verified)',
                split='DEV'))
    # entity_relations from the entity_facts node
    ef = next((n for n in dag1['graph']['nodes']
               if n['node_id'] == 'entity_facts'), None)
    if ef and 'entity_relations' not in used_types:
        inputs.append(dict(
            event='jsst_600287', node_type='entity_relations',
            subtask=ef['subtask'], output_contract=ef['output_contract'],
            evidence_docs=[], evidence_summary='舜天 entity_facts node',
            information_cutoff='2024-07-10',
            gold_status='SILVER_AUTO_VERIFIED',
            gold_package='facts_silver.json', split='DEV'))

    for company, docs in selected_events:
        doc_refs = [dict(doc_id=d.get('pool_id', d.get('title', '')),
                         title=d['title'], url=d.get('url', ''),
                         sha256=d.get('sha256', ''),
                         public_date=d.get('date', '')) for d in docs]
        doc_texts = []
        for d in docs:
            pdf = BENCH / 'docs' / f"{d.get('pool_id','')}.pdf"
            if pdf.exists():
                doc_texts.append(f"[{d.get('pool_id','')}] {d['title']}")
        evidence_summary = '\n'.join(doc_texts) if doc_texts else \
            json.dumps(doc_refs, ensure_ascii=False)

        for ntype in NODE_TYPES:
            inputs.append(dict(
                event=company,
                node_type=ntype,
                subtask=TYPE_PROMPTS[ntype],
                output_contract=TYPE_CONTRACTS[ntype],
                evidence_docs=doc_refs,
                evidence_summary=evidence_summary[:500],
                information_cutoff='2026-08-29',
                gold_status='SILVER_AUTO_VERIFIED',
                gold_package=gold_packages.get(company, 'none'),
                split='VAL' if company == '元道退' else 'DEV'))

    return inputs


CLOUD_MODELS = {
    'M1_glm53': dict(family='GLM', model_id='GLM-5.3',
                      provider='zhipu', verified_calls=15,
                      source='capital_opinion_pilot ledgers'),
    'M2_glm53flash': dict(family='GLM', model_id='GLM-5.3-Flash',
                           provider='zhipu', verified_calls=15,
                           source='capital_opinion_pilot ledgers'),
    'M3_deepseek': dict(family='DeepSeek', model_id='TBD',
                        provider='deepseek', verified_calls=0,
                        blocked_reason='model_id + pricing unverified'),
    'M4_qwen_cloud': dict(family='Qwen', model_id='TBD',
                           provider='alibaba_cloud', verified_calls=0,
                           blocked_reason='model_id + pricing unverified'),
}


def build_screening_plan(inputs: List[dict]) -> dict:
    assignments = {}
    for inp in inputs:
        pair_id = f"{inp['event']}_{inp['node_type']}"
        for mk, mc in CLOUD_MODELS.items():
            aid = f'{mk}|{pair_id}'
            assignments[aid] = dict(
                model_key=mk, model_id=mc['model_id'],
                node_type=inp['node_type'], event=inp['event'],
                subtask=inp['subtask'], evidence=inp['evidence_summary'],
                max_output_tokens=700,
                gold_status=inp['gold_status'],
                status='PENDING',
                blocked=bool(mc.get('blocked_reason')),
                pairing_id=pair_id)
    return dict(
        version='CAPITAL_EVENT_SCREENING_PLAN_v1',
        total_calls=len(assignments), assignments=assignments,
        models=CLOUD_MODELS,
        note=f'{len(inputs)} inputs x {len(CLOUD_MODELS)} models = '
             f'{len(assignments)} calls. M3/M4 blocked until verified. '
             'Gold: ALL SILVER (auto-verified). 元道退 has annotation '
             'package but no human gold yet.')


def freeze(inputs, plan):
    return dict(
        version='CAPITAL_EVENT_NODE_SCREENING_FREEZE_v1',
        n_inputs=len(inputs),
        inputs_sha256=hashlib.sha256(json.dumps(
            [f'{i["event"]}:{i["node_type"]}' for i in inputs],
            sort_keys=True).encode()).hexdigest(),
        plan_sha256=hashlib.sha256(json.dumps(
            plan, sort_keys=True).encode()).hexdigest(),
        inputs=inputs, plan=plan,
        gold_summary=dict(
            silver_auto_verified=len(inputs), human_gold=0,
            annotation_package='元道退 VAL_GOLD_ANNOTATION_PACKAGE '
                              '(40 candidates, dual-annotator not yet '
                              'executed)'),
        data_boundary=dict(
            tatqa_panel='PRESERVED (sha a1acf9db, NOT overwritten)',
            capital_event='NEW (real benchmark_v1 documents + VAL gold '
                          'annotation package)',
            node_types='fact_extraction/timeline/entity_relations/'
                       'cross_verification — DISTINCT from TAT-QA '
                       'e1/e2/r/v; no automatic equivalence assumed'))


if __name__ == '__main__':
    inputs = load_real_node_inputs()
    plan = build_screening_plan(inputs)
    f = freeze(inputs, plan)
    out = ROOT / 'deadline_reward_v1' / 'CAPITAL_EVENT_NODE_SCREENING_FREEZE.json'
    out.write_text(json.dumps(f, indent=1, ensure_ascii=False))
    types = {}
    for i in inputs:
        types[i['node_type']] = types.get(i['node_type'], 0) + 1
    print(f'inputs: {len(inputs)} ({types})')
    print(f'plan calls: {plan["total_calls"]}')
    print(f'gold: {f["gold_summary"]["silver_auto_verified"]} silver, '
          f'{f["gold_summary"]["human_gold"]} human gold')
    print(f'sha: {f["inputs_sha256"][:16]}')
    print(f'events: {sorted(set(i["event"] for i in inputs))}')
