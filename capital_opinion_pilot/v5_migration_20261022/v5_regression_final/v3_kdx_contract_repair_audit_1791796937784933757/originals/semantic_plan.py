"""PILOT V2 fix #1: LLM semantic planning with deterministic DAG assembly.

The round-1 planner failed because a full Graph JSON (long Chinese subtasks +
bindings) exceeded the output budget. V2 splits responsibility:

  LLM  ->  compact semantic plan (task selection, goals, doc needs, dependencies)
 程序  ->  deterministic contract assembly + validation via the reused typed_dag_v1
           validator (ids, bindings, port typing, acyclicity, terminal outputs).

The plan — NOT a fixed template — decides how many tasks exist, which analysis
branches exist (timeline / entity-facts / both), and which task consumes which.
Assembly only enforces typing; a declared dependency that carries no usable data
is rejected with structured feedback for one bounded planner repair round.
"""
import json

from pilot_common import fenced_json

KINDS = {
    'index': {'contract': 'evidence_registry.v1', 'needs_upstream_kinds': [],
              'task_fields': ['question', 'ctx_table'], 'produces': 'evidence_index'},
    'extracts': {'contract': 'doc_retrieval.v1', 'needs_upstream_kinds': ['index'],
                 'task_fields': ['question', 'evidence_index'], 'produces': 'doc_extracts'},
    'timeline': {'contract': 'timeline.v1', 'needs_upstream_kinds': ['extracts'],
                 'task_fields': ['question', 'doc_extracts'], 'produces': 'timeline'},
    'entity_facts': {'contract': 'entity_facts.v1', 'needs_upstream_kinds': ['extracts'],
                     'task_fields': ['question', 'doc_extracts'], 'produces': 'entity_facts'},
    'extracts_f': {'contract': 'doc_retrieval_facts.v1', 'needs_upstream_kinds': ['index'],
                   'task_fields': ['question', 'evidence_index'], 'produces': 'facts'},
    'facts_merge': {'contract': 'facts_merge.v1', 'needs_upstream_kinds': ['extracts_f'],
                    'task_fields': ['question', 'facts'], 'produces': 'doc_extracts',
                    'note': '通用多源汇合节点（程序合并，零模型调用）：可接入任意数量 extracts_f 检索线，'
                            '输出保留每条事实的来源节点/文档出处并标记同键值冲突；下游分析/核查契约不变'},
    'yearly_recon': {'contract': 'yearly_recon.v1', 'needs_upstream_kinds': ['extracts_f'],
                     'task_fields': ['question', 'facts'], 'produces': 'yearly_recon'},
    # note: 'facts' port is the protocol's mergeable multi-binding input
    'factcheck_yr': {'contract': 'fact_check_yr.v1', 'needs_upstream_kinds': ['extracts_f', 'yearly_recon'],
                     'task_fields': ['question', 'facts', 'yearly_recon'],
                     'produces': 'verified_facts'},
    'factcheck_tl': {'contract': 'fact_check_tl.v1', 'needs_upstream_kinds': ['extracts', 'timeline'],
                     'task_fields': ['question', 'doc_extracts', 'timeline'], 'produces': 'verified_facts'},
    'factcheck_ef': {'contract': 'fact_check_ef.v1', 'needs_upstream_kinds': ['extracts', 'entity_facts'],
                     'task_fields': ['question', 'doc_extracts', 'entity_facts'], 'produces': 'verified_facts'},
    'factcheck_full': {'contract': 'fact_check_full.v1',
                       'needs_upstream_kinds': ['extracts', 'timeline', 'entity_facts'],
                       'task_fields': ['question', 'doc_extracts', 'timeline', 'entity_facts'],
                       'produces': 'verified_facts'},
    'report': {'contract': 'report.v1',
               'needs_upstream_kinds': [],
               'needs_one_of_upstream_kinds': ['factcheck_tl', 'factcheck_ef', 'factcheck_full', 'factcheck_yr'],
               'task_fields': ['question', 'verified_facts'], 'produces': 'report'},
}
VALID_DOC_IDS = ['csrc_penalty_2024_41', 'st_announce_2024_020', 'st_announce_2024_021',
                 'st_advance_notice_2023']

PLAN_SYSTEM = (
    '你是调查工作流规划器，输出一个【紧凑】语义计划JSON（总输出<=500字），格式：'
    '{"plan":[{"id":"t1","kind":"...","goal":"<=40字中文目标","doc_ids":[...],"depends":["t0"]}],'
    '"rationale":"<=60字"}。可用kind及硬性上游要求：\n{kinds}\n'
    '规则：depends 只写该任务真实消费其输出的上游任务；每个kind必须恰好声明其所需上游kinds'
    '（report 的上游给一个 factcheck 即可）；extracts 类任务在 doc_ids 中列出需要的证据 doc_id；'
    '节点数按需（通常4-7个），禁止凑数；不得输出任何事实答案或引文。')


def plan_system_prompt():
    kinds = '\n'.join(f"{k}: 需要上游kinds {v['needs_upstream_kinds'] or '无'}"
                      for k, v in KINDS.items())
    return PLAN_SYSTEM.replace('{kinds}', kinds)


def plan_user_prompt(task_question, ctx_table):
    return ('调查任务：' + task_question +
            '\n\n可用证据索引（doc_id｜标题｜公开日期）：\n' + ctx_table +
            '\n\n信息截止2024-07-10。请输出语义计划JSON。')


def validate_plan(plan, doc_ids_available=None):
    """Program-side structural validation of the semantic plan. Returns issue list."""
    doc_ids_available = doc_ids_available or VALID_DOC_IDS
    issues = []
    if not isinstance(plan, dict) or not isinstance(plan.get('plan'), list) or not plan['plan']:
        return ['plan必须是非空对象，含plan数组']
    tasks = plan['plan']
    ids = [t.get('id') for t in tasks]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
        issues.append('任务id缺失或重复')
    idset = set(ids)
    kinds_of = {}
    for t in tasks:
        k = t.get('kind')
        if k not in KINDS:
            issues.append(f"未知kind:{k}")
            continue
        kinds_of[t['id']] = k
        if not isinstance(t.get('goal'), str) or not t['goal'].strip():
            issues.append(f"{t['id']}: goal为空")
        deps = t.get('depends', [])
        if not isinstance(deps, list) or any(d not in idset for d in deps) or t['id'] in deps:
            issues.append(f"{t['id']}: depends引用不存在或自依赖")
        for d in t.get('doc_ids', []):
            if d not in doc_ids_available:
                issues.append(f"{t['id']}: 未知doc_id {d}")
        need = KINDS[k]['needs_upstream_kinds']
        dep_kinds = [kinds_of.get(d) for d in deps if d in kinds_of]
        for req in need:
            if req not in dep_kinds:
                issues.append(f"{t['id']}: kind={k} 缺少所需上游kind={req}")
        one_of = KINDS[k].get('needs_one_of_upstream_kinds')
        if one_of and not any(o in dep_kinds for o in one_of):
            issues.append(f"{t['id']}: report 需要恰好一个 factcheck 上游（可选:{one_of}）")
        if one_of and sum(1 for o in one_of if o in dep_kinds) > 1:
            issues.append(f"{t['id']}: report 只允许一个 factcheck 上游")
        # every declared dep must feed a consumed port (no decorative edges):
        # the task's contract inputs consume the produces of required (+one-of) upstream kinds
        consumed = {KINDS[r]['produces'] for r in need if r in KINDS}
        if one_of:
            consumed |= {KINDS[o]['produces'] for o in one_of if o in KINDS}
        for d, dk in zip(deps, dep_kinds):
            produces = KINDS.get(dk, {}).get('produces')
            if produces is None or produces not in consumed:
                issues.append(f"{t['id']}: 依赖 {d}(kind={dk}) 的输出未被任何输入端口消费（装饰性依赖）")
    reports = [t for t in tasks if t.get('kind') == 'report']
    if len(reports) != 1:
        issues.append(f'必须有且仅有一个report任务，当前{len(reports)}个')
    # acyclicity
    adj = {t['id']: [d for d in t.get('depends', []) if d in idset] for t in tasks if t.get('id')}
    state = {}

    def dfs(u):
        state[u] = 1
        for v in adj.get(u, []):
            if state.get(v) == 1:
                return True
            if state.get(v, 0) == 0 and dfs(v):
                return True
        state[u] = 2
        return False

    if any(state.get(u, 0) == 0 and dfs(u) for u in list(adj)):
        issues.append('计划存在依赖环')
    return issues


def parse_plan(text):
    obj = fenced_json(text)
    return obj if isinstance(obj, dict) and 'plan' in obj else {'plan': obj}
