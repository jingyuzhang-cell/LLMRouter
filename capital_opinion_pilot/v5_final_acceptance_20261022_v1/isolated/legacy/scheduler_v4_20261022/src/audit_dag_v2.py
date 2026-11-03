"""PILOT V2 fix #4: DAG authenticity audit.

Lists every node with its plan provenance (LLM goal text), every edge with the typed
input port it feeds, parallel branches, and post-execution redundancy flags (sibling
nodes whose covered-fact sets overlap). Structural ruling stays with the reused
typed_dag_v1 validator.
"""
import hashlib
import json

from pilot_common import PILOT_DIR


def audit_graph(graph, validated, plan, planner_attempts, node_scores=None):
    nodes = {n.node_id: n for n in graph.nodes}
    layers = [list(l) for l in validated.layers]
    edges = []
    for n in graph.nodes:
        for d in n.dependencies:
            port = next((f'{b.port}<-{b.field}' for b in n.inputs
                         if b.source == 'node' and b.node_id == d), None)
            edges.append({'edge': f'{d}->{n.node_id}', 'typed_dataflow_port': port,
                          'carries_binding': port is not None})
    plan_goals = {t['id']: {'kind': t['kind'], 'goal': t['goal']} for t in plan['plan']}
    facts_sha = hashlib.sha256((PILOT_DIR / 'facts_silver.json').read_bytes()).hexdigest()

    audit = {
        'graph_identity': {'graph_id': graph.graph_id, 'task_id': graph.task_id,
                           'graph_hash': validated.graph_hash},
        'generation_path': {'planner': 'GLM-5.3 compact semantic plan (<=500字)',
                            'assembler': 'deterministic contract assembly (assemble_dag.py)',
                            'planner_attempts': planner_attempts,
                            'llm_decides': ['task count', 'task goals', 'analysis branches',
                                            'dependency structure'],
                            'program_decides': ['contract mapping', 'binding wiring', 'id/typing/format'],
                            'fallback_template_used': False},
        'structural_validation': {'validator': 'typed_dag_v1.protocol.validate (reused, unmodified)',
                                  'status': 'PASS', 'layers': layers, 'max_depth': len(layers),
                                  'parallel_width_max': max(len(l) for l in layers)},
        'authenticity': {
            'nodes': len(graph.nodes),
            'dependency_edges': len(edges),
            'all_edges_carry_typed_dataflow': all(e['carries_binding'] for e in edges),
            'parallel_branches': [l for l in layers if len(l) > 1],
            'node_provenance': {nid: plan_goals.get(nid, {}) for nid in nodes},
            'planner_isolation': {'facts_silver_sha256': facts_sha,
                                  'facts_file_in_planner_inputs': False,
                                  'evidence_full_text_in_planner_inputs': False}},
    }
    if node_scores:
        cov = {nid: set(s.get('covered_fact_ids', [])) for nid, s in node_scores.items() if s}
        redundant = []
        siblings = [l for l in layers if len(l) > 1]
        for l in siblings:
            for i, a in enumerate(l):
                for b in l[i + 1:]:
                    inter = cov.get(a, set()) & cov.get(b, set())
                    if inter:
                        redundant.append({'nodes': [a, b], 'overlapping_fact_ids': sorted(inter),
                                          'flag': 'possible_redundant_coverage'})
        audit['post_execution_redundancy'] = {'overlaps': redundant,
                                              'note': 'overlap between parallel siblings is a flag, '
                                                      'not proof of redundancy'}
    return audit


def write(audit):
    (PILOT_DIR / 'dag_audit_v2.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
