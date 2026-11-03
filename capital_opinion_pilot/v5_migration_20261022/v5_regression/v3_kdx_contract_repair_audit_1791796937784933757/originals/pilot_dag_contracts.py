"""Shared investigation contract registry (in-process extension of typed_dag_v1).

The frozen package's CONTRACTS dict is extended at runtime only; no file in
r3_own_pool is modified. Node types reuse the protocol's four registered kinds
(extraction / transformation / reasoning / verification).
"""
import sys

sys.path.insert(0, '/root/r3_own_pool')
from collab_scheduler_v1.typed_dag_v1 import protocol as td  # noqa: E402

INVESTIGATION_CONTRACTS = {
    'yearly_recon.v1': ('reasoning', {'question': 'text', 'facts': 'facts'}, {'yearly_recon': 'json'}),
    'doc_retrieval_facts.v1': ('extraction', {'question': 'text', 'evidence_index': 'json'}, {'facts': 'facts'}),
    # Generic multi-source convergence (V3-KDX contract repair): a TRANSFORMATION node —
    # program-only, zero LLM calls. Merges N facts-typed retrieval lines into one
    # doc_extracts-typed value, preserving per-item provenance (source_node, doc_id)
    # and flagging same-key value conflicts. Downstream analysis/verification contracts
    # consume the merged value unchanged (full backward compatibility).
    'facts_merge.v1': ('transformation', {'question': 'text', 'facts': 'facts'}, {'doc_extracts': 'json'}),
    'evidence_registry.v1': ('extraction', {'question': 'text', 'ctx_table': 'text'}, {'evidence_index': 'json'}),
    'doc_retrieval.v1': ('extraction', {'question': 'text', 'evidence_index': 'json'}, {'doc_extracts': 'json'}),
    'timeline.v1': ('reasoning', {'question': 'text', 'doc_extracts': 'json'}, {'timeline': 'json'}),
    'entity_facts.v1': ('extraction', {'question': 'text', 'doc_extracts': 'json'}, {'entity_facts': 'json'}),
    'fact_check.v1': ('verification', {'question': 'text', 'timeline': 'json', 'entity_facts': 'json',
                                       'doc_extracts': 'json'}, {'verified_facts': 'json'}),
    'report.v1': ('reasoning', {'question': 'text', 'verified_facts': 'json'}, {'report': 'text'}),
}

for _k, _v in INVESTIGATION_CONTRACTS.items():
    td.CONTRACTS[_k] = _v

LIMITS = td.Limits(max_nodes=7, max_depth=5, max_llm_calls=7)
REQUIRED_OUTPUTS = ('investigation_report',)


def build_template_graph(task_id='jsst_600287_disclosure_pilot'):
    """Explicitly registered investigation domain template (deterministic, zero LLM calls).

    Structure reflects genuine data dependencies of a disclosure-violation probe:
    index -> retrieve raw extracts -> {timeline, entity/penalty facts} in parallel ->
    cross-check against extracts -> cited report.
    """
    G = td.Graph
    N, B, O = td.Node, td.Binding, td.Output
    return G(
        graph_id='cap_opinion_pilot_v1', schema_version='typed-dag.v1', graph_version=1, task_id=task_id,
        nodes=[
            N('doc_index', 'extraction',
              '整理证据索引：阅读ctx_table中的证据文档清单（doc_id、标题、URL、公开日期、哈希、字符数），'
              '按监管文书/公司公告分类，标注每份文档在调查中的角色与公开日期，输出evidence_index。',
              [B('question', 'task', 'question'), B('ctx_table', 'task', 'ctx_table')],
              'evidence_registry.v1', []),
            N('doc_retrieval', 'extraction',
              '原文检索与摘录：依据evidence_index与调查任务，从执行器注入的证据摘录中定位关键段落：'
              'csrc_penalty_2024_41（违法事实、处罚决定、落款日期）、st_announce_2024_020（立案与收到文书披露）、'
              'st_announce_2024_021（停牌与风险警示安排）、st_advance_notice_2023（事先告知）。'
              '输出doc_extracts：每条含doc_id、要点、逐字引文（<=40字）、公开日期。',
              [B('question', 'task', 'question'), B('evidence_index', 'node', 'evidence_index', 'doc_index')],
              'doc_retrieval.v1', ['doc_index']),
            N('timeline', 'reasoning',
              '事件时间线梳理：基于doc_extracts构建调查过程时间线（立案、事先告知、听证、处罚决定、公司公告、'
              '停牌与风险警示实施），每项含日期(YYYY-MM-DD)、事件描述、证据doc_id。',
              [B('question', 'task', 'question'), B('doc_extracts', 'node', 'doc_extracts', 'doc_retrieval')],
              'timeline.v1', ['doc_retrieval']),
            N('entity_facts', 'extraction',
              '主体与处罚事实抽取：基于doc_extracts抽取涉及主体（公司、责任人员、业务对手方）、处罚决定'
              '（罚款金额、警告、市场禁入）与虚增金额等原子事实，每条含事实陈述、数值/日期、证据doc_id。',
              [B('question', 'task', 'question'), B('doc_extracts', 'node', 'doc_extracts', 'doc_retrieval')],
              'entity_facts.v1', ['doc_retrieval']),
            N('fact_check', 'verification',
              '交叉核查：将timeline与entity_facts逐条对照doc_extracts中的引文核查（日期、金额、主体名称），'
              '输出verified_facts：每条含事实、核查结论(SUPPORTED/UNSUPPORTED)、证据doc_id；'
              '无法确认的明确标注UNRESOLVED。',
              [B('question', 'task', 'question'), B('timeline', 'node', 'timeline', 'timeline'),
               B('entity_facts', 'node', 'entity_facts', 'entity_facts'),
               B('doc_extracts', 'node', 'doc_extracts', 'doc_retrieval')],
              'fact_check.v1', ['doc_retrieval', 'timeline', 'entity_facts']),
            N('report', 'reasoning',
              '调查报告整合：基于verified_facts撰写不超过500字的调查报告，涵盖调查过程时间线、涉及主体、'
              '处罚结论、风险警示安排，每个关键结论标注证据doc_id；无法确认事项单独标注。输出report文本。',
              [B('question', 'task', 'question'), B('verified_facts', 'node', 'verified_facts', 'fact_check')],
              'report.v1', ['fact_check']),
        ],
        final_outputs=[O('investigation_report', 'report', 'report')],
        provenance={'origin': 'registered_domain_template_fallback',
                    'reason': 'planner LLM envelope (2 requests) exhausted with truncated outputs; '
                              'typed_dag_v1 documented fallback pattern applied',
                    'planner_attempts_ref': 'initial_dag.json planner.attempts (call_id 4,5)'})


def validate_graph(graph):
    return td.validate(graph, required_outputs=REQUIRED_OUTPUTS, limits=LIMITS)
