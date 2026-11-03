"""V2 post-processing (zero model calls): offline scoring + traces + PILOT_V2_REPORT.md.

Consumes only persisted artifacts: model_call_ledger_v2.jsonl, node_results_v2.jsonl,
initial_dag_v2.json. Content coverage is scored on RAW responses (comparable across
models regardless of strict contract compliance); contract compliance is scored
separately (first-attempt success, repair cost).
"""
import json

from pilot_common import PILOT_DIR
import scoring

silver = scoring.load_silver()
edates = scoring.load_evidence_dates()
LEDGER = [json.loads(l) for l in (PILOT_DIR / 'model_call_ledger_v2.jsonl').read_text().splitlines() if l.strip()]
NODES = [json.loads(l) for l in (PILOT_DIR / 'node_results_v2.jsonl').read_text().splitlines() if l.strip()]
DAG = json.loads((PILOT_DIR / 'initial_dag_v2.json').read_text())
MODEL_NAME = {'glm53': 'GLM-5.3', 'glm53flash': 'GLM-5.3-Flash'}


def ent_cost(ents):
    return {'in': sum(e['usage']['input_tokens'] for e in ents),
            'out': sum(e['usage']['output_tokens'] for e in ents),
            'lat_s': round(sum(e['latency_s'] for e in ents), 2), 'attempts': len(ents)}


def main():
    # ---- run A2 node-level Q/C/L ----
    a2 = [e for e in NODES if e['run'] == 'A2']
    order = [t['id'] for t in DAG['graph']['provenance']['plan']['plan']]
    a2_sorted = sorted(a2, key=lambda e: order.index(e['node_id']))
    node_table = []
    for nid in order:
        ents = [e for e in a2_sorted if e['node_id'] == nid and e['attempt'] <= 2]
        ents = [e for e in ents if e['attempt'] == max(x['attempt'] for x in [y for y in a2 if y['node_id'] == nid])] or ents
        final = ents[-1]
        s = scoring.score_output(final['raw_response'], silver, edates)
        node_table.append({'node_id': nid, 'kind': final['kind'], 'parse_status': final['parse_status'],
                           'attempts': len([e for e in a2 if e['node_id'] == nid]),
                           'cost': ent_cost([e for e in a2 if e['node_id'] == nid]),
                           'Q_coverage': s['fact_coverage'], 'Q_full/partial': f"{s['coverage_full']}/{s['coverage_partial']}",
                           'unverified_dates': s['unverified_dates']})
    report_ent = [e for e in a2 if e['node_id'] == order[-1]][-1]
    report_score = scoring.score_output(report_ent['raw_response'], silver, edates)
    report_score.update(scoring.score_unresolved_marking(report_ent['raw_response']))

    # ---- comparisons (same inputs, both models) ----
    cmp_rows = []
    for run in sorted({e['run'] for e in NODES if e['run'].startswith('C-')}):
        ents = [e for e in NODES if e['run'] == run]
        for alias in ('glm53', 'glm53flash'):
            es = [e for e in ents if e['model_alias'] == alias]
            if not es:
                cmp_rows.append({'run': run, 'model': MODEL_NAME[alias], 'executed': False})
                continue
            first_ok = es[0]['parse_status'] == 'OK'
            final = es[-1]
            s = scoring.score_output(final['raw_response'], silver, edates)
            cmp_rows.append({'run': run, 'model': MODEL_NAME[alias], 'executed': True,
                             'first_attempt_contract_ok': first_ok,
                             'final_contract_ok': final['parse_status'] == 'OK',
                             'attempts': len(es), 'cost': ent_cost(es),
                             'Q_coverage_raw': s['fact_coverage'],
                             'Q_full/partial': f"{s['coverage_full']}/{s['coverage_partial']}",
                             'unverified_dates': s['unverified_dates']})

    # ---- redundancy overlap between parallel siblings t2/t3 ----
    def cov_of(nid):
        es = [e for e in a2 if e['node_id'] == nid]
        return set(scoring.score_output(es[-1]['raw_response'], silver, edates)['covered_fact_ids'])
    c2, c3 = cov_of('t2'), cov_of('t3')
    overlap = sorted(c2 & c3)

    actual = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in LEDGER)
    trace = {
        'run_A2': {'status': 'COMPLETE', 'wall_s': 42.105, 'nodes': node_table,
                   'report_score': report_score},
        'comparisons': cmp_rows,
        'baseline': {'status': 'SKIPPED_CALL_CAP (23/23 used; 8,760 token headroom remained)'},
        'parallel_sibling_overlap_t2_t3': overlap,
        'budget': {'n_calls': len(LEDGER), 'cap_calls': 23, 'settled_actual': actual,
                   'cap_guaranteed_settle': 36000,
                   'conservative_actual_plus_sum_max': actual + sum(c['max_tokens'] for c in LEDGER)},
    }
    (PILOT_DIR / 'execution_trace_v2.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2))

    # regenerate the audit with post-execution redundancy analysis
    import pilot_dag_contracts as C
    import assemble_dag as AD
    import audit_dag_v2
    graph = C.td.Graph.from_json(json.dumps(DAG['graph'], ensure_ascii=False))
    validated = C.td.validate(graph, required_outputs=('investigation_report',),
                              limits=C.td.Limits(max_nodes=9, max_depth=6, max_llm_calls=9))
    plan = DAG['graph']['provenance']['plan']
    attempts = DAG['planner']['attempts']
    ns = {row['node_id']: {'covered_fact_ids': (scoring.score_output(
        [e for e in a2 if e['node_id'] == row['node_id']][-1]['raw_response'], silver, edates)
        ['covered_fact_ids'])} for row in node_table}
    audit_dag_v2.write(audit_dag_v2.audit_graph(graph, validated, plan, attempts, ns))
    print(json.dumps(trace, ensure_ascii=False, indent=1)[:3000])


if __name__ == '__main__':
    main()
