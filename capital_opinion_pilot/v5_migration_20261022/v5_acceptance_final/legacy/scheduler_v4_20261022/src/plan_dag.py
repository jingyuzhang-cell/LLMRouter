"""Task 3: LLM planner generates the initial investigation DAG.

Isolation: the planner sees ONLY the investigation task, the registered contract
registry, the public evidence index (doc ids/titles/public dates/sha — no content,
no answers) and domain background. facts_silver.json is never read here; its hash
is recorded separately in the audit to prove non-overlap. Max 2 model requests,
60s timeout each. The graph is validated by the existing typed_dag_v1 validator
(contracts are extended in-process only; no frozen file is modified).
"""
import copy
import json
import sys

sys.path.insert(0, '/root/r3_own_pool')

from pilot_common import PILOT_DIR, Meter, fenced_json  # noqa: E402
from collab_scheduler_v1.typed_dag_v1 import protocol as td  # noqa: E402

# ---- in-process contract extension (frozen package files untouched) ----
INVESTIGATION_CONTRACTS = {
    'evidence_registry.v1': ('extraction', {'question': 'text', 'ctx_table': 'text'}, {'evidence_index': 'json'}),
    'doc_retrieval.v1': ('extraction', {'question': 'text', 'ctx_table': 'text'}, {'doc_extracts': 'json'}),
    'timeline.v1': ('reasoning', {'question': 'text', 'doc_extracts': 'json'}, {'timeline': 'json'}),
    'entity_facts.v1': ('extraction', {'question': 'text', 'doc_extracts': 'json'}, {'entity_facts': 'json'}),
    'fact_check.v1': ('verification', {'question': 'text', 'timeline': 'json', 'doc_extracts': 'json'},
                      {'verified_facts': 'json'}),
    'report.v1': ('reasoning', {'question': 'text', 'verified_facts': 'json'}, {'report': 'text'}),
}
for k, v in INVESTIGATION_CONTRACTS.items():
    td.CONTRACTS[k] = v

LIMITS = td.Limits(max_nodes=7, max_depth=5, max_llm_calls=7)
REQUIRED_OUTPUTS = ('investigation_report',)

TASK_QUESTION = ('请调查江苏舜天（600287）信息披露违法违规事件，追溯公开披露的调查过程，'
                 '核实监管处罚与公司公告，梳理涉及主体、关键时间节点及股票风险警示情况，'
                 '生成一份具有准确证据引用的调查报告。无法确认的事项必须明确标注。')
DOMAIN_BACKGROUND = (
    '领域背景：A股上市公司信息披露监管调查通常包含以下公开材料链：证监会立案告知书→行政处罚事先告知书→'
    '行政处罚决定书/市场禁入决定书→公司临时公告（收到文书、风险警示安排）→交易所风险警示实施（停牌、ST简称、涨跌幅限制）。'
    '调查信息截止日期固定为2024-07-10，截止日之后公开的材料一律不得使用。'
    '执行系统按 doc_id 向需要原文的节点注入证据摘录（工具能力，无网络检索）。')


def build_ctx_table():
    man = json.loads((PILOT_DIR / 'evidence_manifest.json').read_text())
    rows = [{'doc_id': d['doc_id'], 'title': d['title'], 'url': d['url'],
             'public_date': d['declared_public_date'], 'sha256': d['sha256_raw_file'][:16],
             'text_chars': d['text_chars']} for d in man['documents']]
    return json.dumps(rows, ensure_ascii=False)


PLANNER_SYSTEM = (
    '你是调查工作流规划器。只输出一个```json围栏的JSON对象（Graph），不要输出其他文字。'
    'Graph字段：graph_id(str), schema_version("typed-dag.v1"), graph_version(1), task_id(str), '
    'nodes(数组), final_outputs(数组), provenance(对象)。'
    '每个node字段：node_id(字母开头[A-Za-z][A-Za-z0-9_-]*), node_type, subtask(中文任务说明，含该节点要做什么、'
    '需要哪些doc_id的原文), inputs(数组), output_contract, dependencies(node_id数组), success_contract("schema.v1")。'
    '每个input(binding)字段：port(契约输入端口名), source("task"或"node"), field(task字段名)或node_id+field(上游输出端口名)。'
    '每个final_output字段：name(必须是"investigation_report"), node_id, port。'
    '硬性规则：(1)output_contract只能从注册契约表中选择且node_type必须匹配；'
    '(2)每条依赖边必须对应至少一个显式input binding，每个node binding的节点必须在dependencies中——禁止无数据流的伪依赖；'
    '(3)question/ctx_table/ctx_text是仅有的task字段；ctx_table是证据文档索引(JSON字符串)；'
    '(4)需要原文的节点在subtask中写明doc_id，执行器会注入摘录；'
    '(5)节点数按需生成（通常4-6个），宁少勿滥，禁止为凑复杂度添加节点；'
    '(6)final_output必须是终端节点输出。')


def planner_user(ctx_table):
    reg = '\n'.join(f'{k}: node_type={v[0]}, 输入端口={list(v[1])}, 输出端口={list(v[2])}'
                    for k, v in INVESTIGATION_CONTRACTS.items())
    return ('调查任务：' + TASK_QUESTION +
            '\n\n注册契约表：\n' + reg +
            '\n\n可用证据索引（ctx_table的内容，执行器按doc_id提供原文摘录）：\n' + ctx_table +
            '\n\n' + DOMAIN_BACKGROUND +
            '\n\n请生成执行该调查的初始DAG，只输出Graph JSON。')


def try_validate(graph_dict):
    try:
        g = td.Graph.from_json(json.dumps(graph_dict, ensure_ascii=False))
        v = td.validate(g, required_outputs=REQUIRED_OUTPUTS, limits=LIMITS)
        return g, v, None
    except td.ValidationError as e:
        return None, None, str(e)
    except Exception as e:
        return None, None, f'{type(e).__name__}: {e}'


def main():
    meter = Meter()
    ctx_table = build_ctx_table()
    user = planner_user(ctx_table)

    rec, txt = meter.call('glm53', PLANNER_SYSTEM, user, max_tokens=896,
                          purpose='dag_planning_initial', timeout_s=60)
    candidate, parse_err = None, None
    try:
        candidate = fenced_json(txt)
    except Exception as e:
        parse_err = str(e)

    graph = validated = None
    attempts = [{'call_id': rec['call_id'], 'phase': 'initial',
                 'parse_error': parse_err, 'prompt_sha256': rec['prompt_sha256']}]

    if candidate is not None:
        graph, validated, verr = try_validate(candidate)
        attempts[-1]['validation_error'] = verr
        attempts[-1]['structural_status'] = 'PASS' if graph else 'FAIL'

    # bounded repair round (second and final planner request)
    if graph is None and meter.n_calls < 20:
        err = attempts[-1].get('validation_error') or attempts[-1]['parse_error'] or 'no JSON'
        rec2, txt2 = meter.call(
            'glm53', PLANNER_SYSTEM,
            user + f'\n\n你上一次输出未通过验证，错误：{err[:500]}。请修正后重新输出完整Graph JSON。',
            max_tokens=896, purpose='dag_planning_repair', timeout_s=60)
        try:
            candidate2 = fenced_json(txt2)
            graph, validated, verr2 = try_validate(candidate2)
            attempts.append({'call_id': rec2['call_id'], 'phase': 'repair', 'validation_error': verr2,
                             'structural_status': 'PASS' if graph else 'FAIL',
                             'prompt_sha256': rec2['prompt_sha256']})
            if graph:
                candidate = candidate2
        except Exception as e:
            attempts.append({'call_id': rec2['call_id'], 'phase': 'repair', 'parse_error': str(e),
                             'structural_status': 'FAIL'})

    out = {
        'planner': {'model': 'GLM-5.3', 'max_requests': 2, 'request_timeout_s': 60,
                    'planner_inputs': ['investigation_task', 'contract_registry', 'public_evidence_index(ctx_table)',
                                       'domain_background'],
                    'planner_isolated_from': ['facts_silver.json (answers)', 'evidence full text'],
                    'attempts': attempts},
        'contract_extension': {'source': 'collab_scheduler_v1.typed_dag_v1.protocol.CONTRACTS (in-process extension)',
                               'added': {k: list(v) for k, v in INVESTIGATION_CONTRACTS.items()}},
        'validation': {'validator': 'typed_dag_v1.protocol.validate (reused, unmodified)',
                       'required_outputs': list(REQUIRED_OUTPUTS), 'limits': LIMITS.__dict__,
                       'structural_status': 'PASS' if graph else 'FAIL',
                       'graph_hash': validated.graph_hash if validated else None,
                       'layers': [list(l) for l in validated.layers] if validated else None},
        'graph': candidate,
    }
    (PILOT_DIR / 'initial_dag.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    if graph:
        print('DAG PASS:', validated.graph_hash[:16], 'layers:', validated.layers)
        for n in graph.nodes:
            print(f"  {n.node_id} [{n.node_type}/{n.output_contract}] deps={n.dependencies}")
            print(f"    subtask: {n.subtask[:80]}")
    else:
        print('DAG GENERATION FAILED:', json.dumps(attempts, ensure_ascii=False)[:800])
    print('meter:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
