"""Deterministic contract assembly: valid semantic plan -> executable Graph.

Node count, goals and dependency structure come from the LLM plan; this module only
maps kinds to registered contracts, wires typed bindings and lets the REUSED
typed_dag_v1 validator make the final structural ruling. No template is involved.
"""
import json

import pilot_dag_contracts as C
from semantic_plan import KINDS
from collab_scheduler_v1.typed_dag_v1 import protocol as td

# register the flexible fact-check variants (in-process, frozen files untouched)
for _cid, (_typ, _in, _out) in {
    'fact_check_tl.v1': ('verification', {'question': 'text', 'doc_extracts': 'json', 'timeline': 'json'},
                         {'verified_facts': 'json'}),
    'fact_check_ef.v1': ('verification', {'question': 'text', 'doc_extracts': 'json',
                                          'entity_facts': 'json'}, {'verified_facts': 'json'}),
    'fact_check_full.v1': ('verification', {'question': 'text', 'doc_extracts': 'json', 'timeline': 'json',
                                            'entity_facts': 'json'}, {'verified_facts': 'json'}),
    'fact_check_yr.v1': ('verification', {'question': 'text', 'facts': 'facts',
                                          'yearly_recon': 'json'}, {'verified_facts': 'json'}),
}.items():
    C.td.CONTRACTS[_cid] = (_typ, _in, _out)

TASK_ID = 'jsst_600287_disclosure_pilot_v2'


def assemble(plan):
    """plan -> (graph, issues). Issues empty iff the reused validator accepts the graph."""
    tasks = plan['plan']
    by_id = {t['id']: t for t in tasks}
    produces_of = {t['id']: KINDS[t['kind']]['produces'] for t in tasks if t.get('kind') in KINDS}
    nodes, issues = [], []
    for t in tasks:
        k = t.get('kind')
        if k not in KINDS:
            issues.append(f"{t['id']}: 未知kind")
            continue
        spec = KINDS[k]
        bindings = [td.Binding('question', 'task', 'question')]
        if 'ctx_table' in spec['task_fields']:
            bindings.append(td.Binding('ctx_table', 'task', 'ctx_table'))
        deps = []
        for d in t.get('depends', []):
            if d not in produces_of:
                continue
            port = produces_of[d]
            if port == 'facts' and 'facts' in spec['task_fields']:
                bindings.append(td.Binding('facts', 'node', 'facts', d))
                deps.append(d)
                continue
            if port == 'evidence_index' and 'evidence_index' in spec['task_fields']:
                bindings.append(td.Binding('evidence_index', 'node', 'evidence_index', d))
            elif port == 'doc_extracts' and 'doc_extracts' in spec['task_fields']:
                bindings.append(td.Binding('doc_extracts', 'node', 'doc_extracts', d))
            elif port == 'timeline' and 'timeline' in spec['task_fields']:
                bindings.append(td.Binding('timeline', 'node', 'timeline', d))
            elif port == 'yearly_recon' and 'yearly_recon' in spec['task_fields']:
                bindings.append(td.Binding('yearly_recon', 'node', 'yearly_recon', d))
            elif port == 'entity_facts' and 'entity_facts' in spec['task_fields']:
                bindings.append(td.Binding('entity_facts', 'node', 'entity_facts', d))
            elif port == 'verified_facts' and 'verified_facts' in spec['task_fields']:
                bindings.append(td.Binding('verified_facts', 'node', 'verified_facts', d))
            else:
                issues.append(f"{t['id']}: 依赖 {d} 的输出 {port} 无对应输入端口（类型不匹配）")
                continue
            deps.append(d)
        doc_note = f"；需要原文doc_id: {','.join(t['doc_ids'])}" if t.get('doc_ids') else ''
        nodes.append(td.Node(t['id'], spec_contract_type(k),
                             f"{t['goal']}{doc_note}", bindings, spec['contract'], deps))
    report_tasks = [t for t in tasks if t.get('kind') == 'report']
    if len(report_tasks) != 1:
        return None, issues + [f'report任务数={len(report_tasks)}，必须为1']
    finals = [td.Output('investigation_report', report_tasks[0]['id'], 'report')]
    graph = td.Graph(graph_id='cap_opinion_pilot_v2', schema_version='typed-dag.v1', graph_version=1,
                     task_id=TASK_ID, nodes=nodes, final_outputs=finals,
                     provenance={'origin': 'llm_semantic_plan + deterministic_assembly',
                                 'plan': plan,
                                 'assembler': 'assemble_dag.py (contract mapping + typed binding wiring)'})
    try:
        validated = C.td.validate(graph, required_outputs=('investigation_report',),
                                  limits=C.td.Limits(max_nodes=9, max_depth=6, max_llm_calls=9))
    except td.ValidationError as e:
        return None, issues + [f'validator: {e}']
    return (graph, validated), issues


def spec_contract_type(kind):
    return KINDS[kind] and {'index': 'extraction', 'extracts': 'extraction', 'timeline': 'reasoning',
                            'entity_facts': 'extraction', 'factcheck_tl': 'verification',
                            'factcheck_ef': 'verification', 'factcheck_full': 'verification', 'extracts_f': 'extraction',
                            'facts_merge': 'transformation',
                            'factcheck_yr': 'verification', 'yearly_recon': 'reasoning',
                            'report': 'reasoning'}[kind]


def graph_to_dict(graph):
    return graph.to_dict()
