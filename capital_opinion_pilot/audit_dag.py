"""DAG audit: validate the template-fallback graph with the REUSED typed_dag_v1
validator, run semantic-dependency review heuristics, update initial_dag.json and
write dag_audit.json. Zero model calls.
"""
import hashlib
import json

from pilot_common import PILOT_DIR
import pilot_dag_contracts as C


def semantic_review(graph, validated):
    """Heuristic semantic review: real-vs-fake dependencies, honesty of complexity."""
    nodes = {n.node_id: n for n in graph.nodes}
    dep_edges = []
    for n in graph.nodes:
        for d in n.dependencies:
            dep_edges.append({
                'edge': f'{d}->{n.node_id}',
                'carries_binding': any(b.source == 'node' and b.node_id == d for b in n.inputs),
                'consumed_port': next((f'{b.port}<-{b.field}' for b in n.inputs
                                       if b.source == 'node' and b.node_id == d), None)})
    subtasks = [n.subtask for n in graph.nodes]
    issues = []
    if any(not e['carries_binding'] for e in dep_edges):
        issues.append('dependency_without_dataflow')  # also structurally rejected by validator
    if len(set(subtasks)) != len(subtasks):
        issues.append('duplicate_subtasks')
    # honesty checks: no node exists only to inflate complexity (every node must either
    # consume a distinct upstream output or feed a distinct downstream consumer)
    for n in graph.nodes:
        has_upstream = bool(n.dependencies)
        feeds = sum(1 for m in graph.nodes if n.node_id in m.dependencies) + \
            sum(1 for o in graph.final_outputs if o.node_id == n.node_id)
        if not (has_upstream or feeds):
            issues.append(f'orphan_node:{n.node_id}')
    return {'dependency_edges': dep_edges,
            'all_edges_carry_explicit_dataflow': all(e['carries_binding'] for e in dep_edges),
            'binding_dependency_bijection_enforced_by': 'typed_dag_v1.protocol.validate '
                                                        '("Dependency without explicit input"/"Binding lacks dependency")',
            'duplicate_subtasks': len(set(subtasks)) != len(subtasks),
            'issues': issues,
            'semantic_status': 'HEURISTIC_PASS (declared semantic coverage NOT certified)' if not issues else 'ISSUES'}


def main():
    dag_file = PILOT_DIR / 'initial_dag.json'
    dag = json.loads(dag_file.read_text())

    graph = C.build_template_graph()
    validated = C.validate_graph(graph)  # raises if invalid

    facts_sha = hashlib.sha256((PILOT_DIR / 'facts_silver.json').read_bytes()).hexdigest()
    layers = [list(l) for l in validated.layers]
    audit = {
        'graph_identity': {'graph_id': graph.graph_id, 'task_id': graph.task_id,
                           'graph_hash': validated.graph_hash, 'schema_version': graph.schema_version},
        'structural_validation': {
            'validator': 'collab_scheduler_v1.typed_dag_v1.protocol.validate (reused verbatim, unmodified; '
                         'CONTRACTS extended in-process with 6 investigation contracts)',
            'checks_covered': ['id syntax', 'duplicate nodes', 'contract registration', 'contract/type match',
                               'dependency endpoints', 'binding<->dependency agreement', 'port type compatibility',
                               'required input coverage', 'acyclicity + layering (static_dag_v0.core.topology)',
                               'depth bound', 'final-output terminality', 'dead-branch reachability'],
            'status': 'PASS', 'layers': layers, 'max_depth': len(layers),
            'parallel_width_max': max(len(l) for l in layers)},
        'complexity_stats': {
            'nodes': len(graph.nodes),
            'node_types': {t: sum(1 for n in graph.nodes if n.node_type == t) for t in
                           ('extraction', 'reasoning', 'verification', 'transformation')},
            'llm_nodes': sum(1 for n in graph.nodes if n.node_type != 'transformation'),
            'dependency_edges': sum(len(n.dependencies) for n in graph.nodes),
            'parallelisable_layers': [l for l in layers if len(l) > 1],
            'honesty_note': 'complexity reflects the template actually used for execution; not inflated'},
        'semantic_review': semantic_review(graph, validated),
        'planner_isolation': {
            'planner_llm_generation_within_envelope': 'FAIL (2/2 requests truncated at output-token cap)',
            'fallback': 'registered investigation domain template (deterministic, zero model calls), '
                        'labelled as FALLBACK — NOT counted as successful LLM generation',
            'facts_silver_sha256': facts_sha,
            'facts_file_in_planner_inputs': False,
            'evidence_full_text_in_planner_inputs': False,
            'planner_saw': ['investigation task', 'contract registry', 'public evidence index (ids/titles/dates/hashes)',
                            'domain background']},
    }
    # update initial_dag.json: keep planner attempt history, attach the executed graph
    dag['graph'] = graph.to_dict()
    dag['validation'] = {'validator': 'typed_dag_v1.protocol.validate (reused)',
                         'required_outputs': list(C.REQUIRED_OUTPUTS),
                         'limits': C.LIMITS.__dict__,
                         'structural_status': 'PASS', 'graph_hash': validated.graph_hash, 'layers': layers}
    dag['graph_origin'] = 'registered_domain_template_fallback (planner envelope exhausted; see planner.attempts)'
    dag_file.write_text(json.dumps(dag, ensure_ascii=False, indent=2))
    (PILOT_DIR / 'dag_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))

    print('structural: PASS  hash=', validated.graph_hash[:16])
    print('layers:', layers, ' width=', audit['complexity_stats']['parallelisable_layers'])
    print('semantic:', audit['semantic_review']['semantic_status'],
          'issues=', audit['semantic_review']['issues'])
    print('edges:', [e['edge'] for e in audit['semantic_review']['dependency_edges']])


if __name__ == '__main__':
    main()
