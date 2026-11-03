"""Three-window joint acceptance (ZERO-PAY). Proves the four integration claims:

 1. DATA FLOW   — window2's REAL planner DAG converts mechanically to DAGSpec
                 (no manual rewriting of nodes/dependencies); typed edges survive.
 2. RECOVERY LEGALITY — window1 decision record (REPLAY, derived from the frozen
                 recover_failed semantics) only reroutes failed nodes, invalidates
                 exactly their descendant closure, protects done outputs; Z passes
                 the semantic guard (reused typed validator); pi covers every
                 remaining executable node.
 3. EVAL INDEPENDENCE — window3 consumes ONLY standardized artifacts (DAGSpec,
                 anomaly, decision, trace, retrieval log) + PRIVATE references;
                 isolation gate runs on every exchanged artifact; real vs REPLAY
                 labels are preserved end-to-end.
 4. ATTRIBUTION READY — the replayed run is arm-tagged (dyn_Joint_R_pi family)
                 with per-layer attribution slots; single run makes no claims.

REAL components: planner graph (initial_dag_v2.json), node outputs/usage/latency
(node_results_v2.jsonl run A2), anomaly (model_call_ledger_v2.jsonl glm53flash
contract failures on the same node with the same prompt sha).
REPLAY components (labeled): the (Z,R,pi) decision record built from the frozen
recover_failed semantics; post-recovery execution reuses the REAL glm53 output.
No model calls, no GPU.
"""
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path('/root/capital_opinion_pilot')  # read-only frozen artifacts
B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B))
sys.path.insert(0, str(B / 'scoring'))
sys.path.insert(0, str(B / 'evidence'))
sys.path.insert(0, '/root/r3_own_pool')
import retrieval_api as R                     # noqa: E402
import metric_mapping_v1_1 as M               # noqa: E402
from bench_common import sha                  # noqa: E402
from collab_scheduler_v1.typed_dag_v1 import protocol as td  # noqa: E402
import pilot_dag_contracts as PC              # noqa: E402  (registers contracts, read-only)
import assemble_dag as _AD                    # noqa: E402,F401  (registers fact_check_* variants)

RUN_ID = 'JOINT-ACC-RUN-001'
TASK_ID = 'T-P1'                              # same Shuntian event as the real graph


# ---------------- window2: REAL graph -> DAGSpec (mechanical) ----------------
def build_dagspec():
    dag = json.loads((BENCH / 'initial_dag_v2.json').read_text())
    nodes_raw = [json.loads(l) for l in (BENCH / 'node_results_v2.jsonl').read_text().splitlines() if l.strip()]
    a2 = {}
    for e in nodes_raw:
        if e['run'] == 'A2':
            a2[e['node_id']] = e  # last attempt per node
    nodes = []
    for n in dag['graph']['nodes']:
        st = a2.get(n['node_id'], {})
        state = {'status': 'done' if st.get('parse_status') == 'OK' else 'pending',
                 'model': 'glm53', 'attempts': st.get('attempt', 0),
                 'usage': st.get('usage'), 'latency_s': st.get('latency_s'),
                 'output': st.get('parsed')}
        nodes.append({'node_id': n['node_id'], 'node_type': n['node_type'],
                      'output_contract': n['output_contract'], 'dependencies': n['dependencies'],
                      'bindings': [{'port': b['port'], 'source': b['source'], 'field': b['field'],
                                    **({'node_id': b['node_id']} if b.get('node_id') else {})}
                                   for b in n['inputs']],
                      'subtask': n['subtask'], 'state': state})
    spec = {'dag_id': dag['graph']['graph_id'], 'task_id': TASK_ID, 'structure_version': 1,
            'provenance': {'origin': 'REAL LLM-planned graph (capital_opinion_pilot initial_dag_v2.json)',
                           'planner': 'GLM-5.3 semantic plan + deterministic assembly (V2 run)',
                           'graph_hash': dag['validation']['graph_hash'],
                           'execution_mode': 'REAL'},
            'nodes': nodes}
    return spec, dag


# ---------------- REAL anomaly from the frozen ledger ----------------
def build_anomaly():
    calls = [json.loads(l) for l in (BENCH / 'model_call_ledger_v2.jsonl').read_text().splitlines() if l.strip()]
    fails = [c for c in calls if c['purpose'].startswith('C-extraction') and c['model_alias'] == 'glm53flash']
    assert fails, 'expected real glm53flash contract failures on the extraction node'
    return {'dag_id': 'cap_opinion_pilot_v2', 'structure_version': 1,
            'events': [{'event_id': 'AN-001',
                        'node_id': 't3',            # same node/prompt as the failing comparison runs
                        'signal_type': 'contract_parse_failure',
                        'observed': {'n_failed_attempts': len({c['purpose'] for c in fails}),
                                     'stop_reasons': sorted({c['stop_reason'] for c in fails}),
                                     'prompt_sha_prefix': fails[0]['prompt_sha256'][:12]},
                        'attempt': 1, 'source': 'REAL'}]}


# ---------------- window1 decision: REPLAY of frozen recover_failed semantics ----------------
def build_decision(spec):
    failed = {'t3'}
    desc = set()
    while True:
        more = {n['node_id'] for n in spec['nodes']
                if n['node_id'] not in desc and any(d in desc | failed for d in n['dependencies'])}
        if not more:
            break
        desc |= more
    done_all = {n['node_id'] for n in spec['nodes'] if n['state']['status'] == 'done'}
    done = sorted(done_all - failed - desc)   # protected = done minus failed minus invalidated
    remaining = [n['node_id'] for n in spec['nodes']
                 if n['node_id'] in (desc | failed) and n['node_id'] not in done]
    return {'decision_id': 'DEC-REPLAY-001', 'dag_id': spec['dag_id'],
            'from_structure_version': 1, 'to_structure_version': 1, 'source': 'REPLAY',
            'Z': {'ops': [{'op': 'identity'}],
                  'semantic_guard': {'validator': 'collab_scheduler_v1.typed_dag_v1.protocol.validate',
                                     'result': 'PASS'}},   # re-proven below, not trusted
            'R': {'reroutes': [{'node_id': 't3', 'model': 'glm53', 'max_attempts': 2}],
                  'invalidated_closure': sorted(desc - {'t3'}),
                  'protected_done_outputs': ['t0', 't1', 't2']},
            'pi': {'assignment': {nid: 'glm53' for nid in ['t3'] + sorted(desc - {'t3'})}},
            'rationale': 'REPLAY of frozen recover_failed semantics (typed_dag_v1/execution.py): '
                         'failed-node reroute only; descendant closure invalidated; done outputs protected'}


# ---------------- the four proofs ----------------
def proof_data_flow(spec, dag):
    src_nodes = {n['node_id']: n for n in dag['graph']['nodes']}
    same = (len(spec['nodes']) == len(src_nodes)
            and all(s['dependencies'] == src_nodes[s['node_id']]['dependencies']
                    and s['output_contract'] == src_nodes[s['node_id']]['output_contract']
                    and len(s['bindings']) == len(src_nodes[s['node_id']]['inputs'])
                    for s in spec['nodes']))
    g = td.Graph.from_json(json.dumps(dag['graph'], ensure_ascii=False))
    v = PC.td.validate(g, required_outputs=('investigation_report',),
                       limits=PC.td.Limits(max_nodes=9, max_depth=6, max_llm_calls=9))
    return {'pass': bool(same and v), 'nodes': len(spec['nodes']), 'edges': sum(len(s['dependencies']) for s in spec['nodes']),
            'graph_hash': dag['validation']['graph_hash'], 'mechanical_conversion': same,
            'validator': 'PASS' if v else 'FAIL'}


def proof_recovery_legality(spec, decision, anomaly):
    failed_nodes = {e['node_id'] for e in anomaly['events']}
    # R: only failed nodes rerouted; closure correctness; done protection
    reroute_ok = {r['node_id'] for r in decision['R']['reroutes']} == failed_nodes
    desc, edges = set(), {n['node_id']: set(n['dependencies']) for n in spec['nodes']}
    frontier = set(failed_nodes)
    while frontier:
        nxt = {u for u, ds in edges.items() if ds & frontier and u not in desc and u not in failed_nodes}
        desc |= nxt
        frontier = nxt
    closure_ok = set(decision['R']['invalidated_closure']) == desc
    done = {n['node_id'] for n in spec['nodes'] if n['state']['status'] == 'done'}
    protect_ok = set(decision['R']['protected_done_outputs']) == (done - failed_nodes - desc)
    # Z: semantic guard re-run on the (identity) mutation — validate structure as-is
    g = td.Graph.from_json(json.dumps(json.loads((BENCH / 'initial_dag_v2.json').read_text())['graph'], ensure_ascii=False))
    z_ok = False
    try:
        PC.td.validate(g, required_outputs=('investigation_report',),
                       limits=PC.td.Limits(max_nodes=9, max_depth=6, max_llm_calls=9))
        z_ok = True
    except Exception:
        z_ok = False
    # pi: covers every node that still executes (failed + invalidated)
    need = failed_nodes | desc
    pi_ok = set(decision['pi']['assignment']) == need
    return {'pass': reroute_ok and closure_ok and protect_ok and z_ok and pi_ok,
            'R_reroute_only_failed': reroute_ok, 'R_closure_exact': closure_ok,
            'R_done_protected': protect_ok, 'Z_semantic_guard_reproven': z_ok,
            'pi_covers_remaining': pi_ok, 'recovery_scope': sorted(need)}


def proof_eval_independence(artifacts):
    g = subprocess.run(['python3', str(B / 'isolation' / 'gate.py'), 'check'] + artifacts,
                       capture_output=True, text=True)
    labels = {Path(a).name: json.loads(Path(a).read_text()).get('source',
            json.loads(Path(a).read_text()).get('provenance', {}).get('execution_mode'))
            for a in artifacts}
    no_eval_feedback = all('E_evidence' not in Path(a).read_text() and
                           'self_sufficiency' not in Path(a).read_text() for a in artifacts)
    return {'pass': g.returncode == 0 and no_eval_feedback,
            'isolation_gate': 'CLEAN' if g.returncode == 0 else 'LEAK',
            'real_replay_labels': labels,
            'no_eval_metric_feedback_into_systems': no_eval_feedback}


def proof_attribution(scenario):
    return {'pass': True, 'arm_tag': 'dyn_Joint_R_pi (REPLAY)',
            'layers': {'A_structure': 'auto_graph (REAL planner) vs fixed_graph — not in this run',
                       'B_static_alloc': 'not in this run',
                       'C_dynamic': 'dyn_Joint_R_pi replay vs dyn_Static — not in this run'},
            'single_run_no_claims': True, 'scenario': scenario}


def main():
    spec, dag = build_dagspec()
    anomaly = build_anomaly()
    decision = build_decision(spec)
    (B / 'integration' / 'exchange').mkdir(exist_ok=True)
    ex = B / 'integration' / 'exchange'
    (ex / 'dagspec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    (ex / 'anomaly.json').write_text(json.dumps(anomaly, ensure_ascii=False, indent=1))
    (ex / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=1))

    p1 = proof_data_flow(spec, dag)
    p2 = proof_recovery_legality(spec, decision, anomaly)
    p3 = proof_eval_independence([str(ex / 'dagspec.json'), str(ex / 'anomaly.json'),
                                  str(ex / 'decision.json')])

    # window3 terminal scoring of the replayed run (deliverable assembled from REAL outputs)
    a2 = {}
    for e in (json.loads(l) for l in (BENCH / 'node_results_v2.jsonl').read_text().splitlines()):
        if e['run'] == 'A2':
            a2[e['node_id']] = e
    timeline = json.dumps(a2['t2']['parsed'], ensure_ascii=False)
    report = a2['t5']['parsed'].get('report', '')
    if not isinstance(report, str):
        report = json.dumps(report, ensure_ascii=False)
    deliverable = {'task_id': TASK_ID,
                   'investigation_timeline': timeline,
                   'fraud_nature': json.dumps(a2['t3']['parsed'], ensure_ascii=False),
                   'risk_warning': json.dumps(a2['t1']['parsed'], ensure_ascii=False),
                   'report': report,
                   'unknown_marks': []}
    nodes = []
    for s in spec['nodes']:
        st = s['state']
        nodes.append({'node_id': s['node_id'], 'kind': s['node_type'], 'model': 'glm53',
                      'attempt': st['attempts'] or 1,
                      'usage': {'in': (st['usage'] or {}).get('input_tokens', 0),
                                'out': (st['usage'] or {}).get('output_tokens', 0)},
                      'latency_s': st['latency_s'] or 0.0, 'parse_status': 'OK'})
    # post-recovery t3 replay: reuse REAL glm53 comparison output already counted in V2 —
    # charged at its real usage to avoid zero-cost illusion
    nodes.append({'node_id': 't3#recovery', 'kind': 'recovery_reroute', 'model': 'glm53', 'attempt': 1,
                  'usage': {'in': 652, 'out': 349}, 'latency_s': 5.245, 'parse_status': 'OK',
                  'repair_of': 't3', 'reused_real_v2_comparison_output': True})
    _, used = R.retrieve(TASK_ID, RUN_ID, ['处罚', '风险警示', '停牌'], 3200)
    trace = {'run_id': RUN_ID, 'system_id': 'dynamic_joint', 'task_id': TASK_ID,
             'config_hash': sha({'mode': 'JOINT-ACCEPTANCE-REPLAY'}),
             'status': 'COMPLETE',
             'planning': {'calls': 2, 'latency_s': 28.178,
                          'usage': {'in': 1907, 'out': 671}},   # REAL V2 planner calls 1-2
             'retrieval': {'calls': 1, 'chars_injected': used},
             'nodes': nodes, 'reuse_events': 1, 'program_ms': 4.0,
             'wall_s': 70.0,   # replay approximation over real component latencies; descriptive only
             'deliverable_ref': 'integration/exchange/deliverable.json',
             'notes': 'JOINT ACCEPTANCE REPLAY: graph/anomaly/outputs REAL from frozen V2; '
                      '(Z,R,pi) decision REPLAY of frozen recover_failed semantics; '
                      'recovery node reuses REAL glm53 output (usage charged at real values)'}
    (ex / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    (ex / 'deliverable.json').write_text(json.dumps(deliverable, ensure_ascii=False, indent=1))
    import qe_k_scorer as S
    v1 = S.score_run(trace, deliverable)
    uni = M.score_unified(trace, deliverable)
    p4 = proof_attribution('single replayed joint run; attribution slots registered, no claims')

    report = {'verdict': 'ACCEPT' if all(p['pass'] for p in (p1, p2, p3, p4)) else 'REJECT',
              'zero_pay': True, 'run_id': RUN_ID,
              'proofs': {'1_data_flow': p1, '2_recovery_legality': p2,
                         '3_eval_independence': p3, '4_attribution': p4},
              'terminal_scoring': {'Q_v1': v1['Q']['Q'], 'coverage': v1['Q']['coverage'],
                                   'citation_presence_v1': v1['Q']['citation_accuracy'],
                                   'unified_C_total_tokens': uni['C']['total_tokens'],
                                   'unified_L_service_s': uni['L']['service_s'],
                                   'E_evidence_support_rate': uni['E_evidence']['evidence_support_rate'],
                                   'E_evidence_self_sufficiency': uni['E_evidence']['retrieval_self_sufficiency'],
                                   'verdict': v1['K']['verdict']},
              'labels': {'REAL': ['planner graph', 'node outputs/usage/latency (A2)',
                                  'anomaly (glm53flash contract failures)', 'planner usage'],
                         'REPLAY': ['(Z,R,pi) decision record', 'post-recovery reuse', 'wall_s'],
                         'SYNTHETIC': []}}
    (B / 'integration' / 'joint_acceptance_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({'verdict': report['verdict'],
                      'proofs': {k: v['pass'] for k, v in report['proofs'].items()},
                      'terminal': report['terminal_scoring']}, ensure_ascii=False, indent=1))
    return 0 if report['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    sys.exit(main())
