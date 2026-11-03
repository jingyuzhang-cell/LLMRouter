"""V2.1 authorized run: single-strong-model baseline FIRST, fixed-input extracts
comparison redo (with the injection fix), and a static heterogeneous DAG arm that
reuses persisted A2 outputs for unchanged nodes. Every call metered + persisted.

Arms:
  single   = GLM-5.3 one-shot with the same frozen evidence pack (run this session)
  fixed    = A2 all-GLM-5.3 DAG (persisted from V2 session; latency caveat noted)
  hetero   = {t0,t1: reuse glm53; t2,t3: GLM-5.3-Flash(+deterministic salvage,
             fallback-to-reuse on unsalvageable output, deviation recorded);
             t4,t5: GLM-5.3 re-executed on the changed inputs}
"""
import hashlib
import json
import time

from pilot_common import PILOT_DIR, Meter, BudgetExceeded, fenced_json
from execute_dag import TASK_QUESTION, build_ctx_table, evidence_pack
from execute_v2 import call_node, node_user_prompt, SYSTEM, NODE_RESULTS, _ports_by_contract
from flash_eval_v21 import salvage
import pilot_dag_contracts as C
import scoring

CAPS = dict(max_calls=11, max_guaranteed_actual=18000)
A2 = [e for e in (json.loads(l) for l in (PILOT_DIR / 'node_results_v2.jsonl').read_text().splitlines() if l.strip())
      if e['run'] == 'A2']
A2_FINAL = {}
for e in A2:
    A2_FINAL[e['node_id']] = e  # later attempts overwrite earlier
DAG = json.loads((PILOT_DIR / 'initial_dag_v2.json').read_text())
GRAPH = C.td.Graph.from_json(json.dumps(DAG['graph'], ensure_ascii=False))
NODES = {n.node_id: n for n in GRAPH.nodes}
KIND = {t['id']: t['kind'] for t in DAG['graph']['provenance']['plan']['plan']}
CTX = {'question': TASK_QUESTION, 'ctx_table': build_ctx_table()}


def reuse_lookup(run, node_id, alias, user_prompt, system=SYSTEM):
    sha = hashlib.sha256((system + '\x00' + user_prompt).encode()).hexdigest()
    for r in (json.loads(l) for l in NODE_RESULTS.read_text().splitlines() if l.strip()):
        if (r['run'], r['node_id'], r['model_alias'], r['prompt_sha256']) == (run, node_id, alias, sha) \
                and r['parse_status'] == 'OK':
            return r
    return None


def data_for(node, outputs):
    return {b.port: CTX[b.field] if b.source == 'task' else outputs[b.node_id][b.field]
            for b in node.inputs}


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v21.jsonl', **CAPS)
    silver = scoring.load_silver()
    edates = scoring.load_evidence_dates()
    arms = {}

    # ---- 1) BASELINE FIRST (must not be crowded out; reuse persisted if present) ----
    led = PILOT_DIR / 'model_call_ledger_v21.jsonl'
    resp = PILOT_DIR / 'model_call_ledger_v21_responses.jsonl'
    prior = None
    if led.exists():
        calls21 = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
        prior = next((c for c in calls21 if c['purpose'] == 'v21_baseline'), None)
    if prior and resp.exists():
        r21 = [json.loads(l) for l in resp.read_text().splitlines() if l.strip()]
        txt = next(r['text'] for r in r21 if r['call_id'] == prior['call_id'])
        rec, b_wall = prior, None
        print('baseline: reused persisted call_id', rec['call_id'])
    else:
        t0 = time.monotonic()
        rec, txt = meter.call(
            'glm53', '你是资本市场调查员。基于证据撰写不超过500字调查报告，关键结论标注证据doc_id，无法确认事项单独标注。',
            '调查任务：' + TASK_QUESTION + '\n\n证据原文摘录（逐字，截止2024-07-10）：\n' + evidence_pack(),
            max_tokens=448, purpose='v21_baseline', timeout_s=60)
        b_wall = time.monotonic() - t0
    bs = scoring.score_output(txt, silver, edates)
    bs.update(scoring.score_unresolved_marking(txt))
    arms['single_strong_model'] = {'Q': bs['fact_coverage'], 'citation_accuracy': bs['citation_accuracy'],
                                   'coverage_full/partial': f"{bs['coverage_full']}/{bs['coverage_partial']}",
                                   'tokens': rec['usage']['input_tokens'] + rec['usage']['output_tokens'],
                                   'wall_s': rec['latency_s'], 'call_id': rec['call_id'],
                                   'wall_note': 'per-call service latency from the meter ledger '
                                                '(first run crashed post-call; call itself persisted)',
                                   'unverified_dates': bs['unverified_dates'], 'report_chars': len(txt),
                                   'price_cny': 'UNKNOWN (coding-plan subscription; no per-call billing; '
                                                'tokens are the cost basis)'}
    print('baseline:', arms['single_strong_model'])

    # ---- 2) extracts comparison redo WITH injection ----
    outputs = {nid: A2_FINAL[nid]['parsed'] for nid in A2_FINAL}
    t1 = NODES['t1']
    u_t1 = node_user_prompt(t1, data_for(t1, outputs), inject_docs=True)
    redo = {}
    g_reuse = reuse_lookup('A2', 't1', 'glm53', u_t1)
    if g_reuse:
        redo['glm53'] = {'source': 'reused_A2_call', 'call_id': g_reuse['call_id'],
                         'first_attempt_contract_ok': A2_FINAL['t1']['attempt'] == 1,
                         'Q_raw': scoring.score_output(g_reuse['raw_response'], silver, edates)['fact_coverage']}
    else:
        parsed, ent = call_node(meter, 'V21-C-extracts', 't1', 'extracts', 'glm53', u_t1)
        redo['glm53'] = {'source': 'fresh', 'Q_raw': scoring.score_output(ent['raw_response'], silver, edates)['fact_coverage']}
    try:
        parsed_f, ent_f = call_node(meter, 'V21-C-extracts', 't1', 'extracts', 'glm53flash', u_t1)
        ok_salv, _ = salvage(ent_f['raw_response'], 'extracts')
        redo['glm53flash'] = {'source': 'fresh', 'first_attempt_contract_ok': ent_f['attempt'] == 1,
                              'contract_ok': ent_f['parse_status'] == 'OK', 'salvage_ok': ok_salv,
                              'Q_raw': scoring.score_output(ent_f['raw_response'], silver, edates)['fact_coverage'],
                              'tokens': ent_f['usage']['input_tokens'] + ent_f['usage']['output_tokens'],
                              'lat_s': ent_f['latency_s']}
    except BudgetExceeded as e:
        redo['glm53flash'] = {'status': 'SKIPPED_BUDGET', 'reason': str(e)[:150]}
    print('extracts redo:', json.dumps(redo, ensure_ascii=False))

    # ---- 3) static heterogeneous DAG arm ----
    v2_calls = [json.loads(l) for l in (PILOT_DIR / 'model_call_ledger_v2.jsonl').read_text().splitlines() if l.strip()]
    planner_tok = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in v2_calls[:2])
    dag_tok = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in v2_calls[2:10])
    v2_t01_tok = sum(c['usage']['input_tokens'] + c['usage']['output_tokens']
                     for c in v2_calls if c['purpose'].startswith(('A2:t0', 'A2:t1')))
    h_outputs, h_log, h_new_tokens, h_lat = {}, [], 0, 0.0
    hetero_assign = {'t0': ('glm53', 'reuse'), 't1': ('glm53', 'reuse'),
                     't2': ('glm53flash', 'fresh'), 't3': ('glm53flash', 'fresh'),
                     't4': ('glm53', 'fresh'), 't5': ('glm53', 'fresh')}
    for layer in [['t0'], ['t1'], ['t2', 't3'], ['t4'], ['t5']]:
        for uid in layer:
            alias, mode = hetero_assign[uid]
            node = NODES[uid]
            u = node_user_prompt(node, data_for(node, h_outputs if mode == 'fresh' else outputs),
                                 inject_docs=(KIND[uid] == 'extracts'))
            if mode == 'reuse':
                h_outputs[uid] = outputs[uid]
                h_log.append({'node': uid, 'model': 'GLM-5.3(reused)', 'cost_new_tokens': 0})
                continue
            try:
                parsed, ent = call_node(meter, 'V21-H', uid, KIND[uid], alias, u)
            except BudgetExceeded as e:
                h_log.append({'node': uid, 'status': 'SKIPPED_BUDGET', 'reason': str(e)[:120]})
                h_outputs[uid] = outputs[uid]
                continue
            ent_tokens = ent['usage']['input_tokens'] + ent['usage']['output_tokens']
            h_new_tokens += ent_tokens
            h_lat += ent['latency_s']
            ok = ent['parse_status'] == 'OK'
            sal = False
            if not ok and alias == 'glm53flash':
                sal, _ = salvage(ent['raw_response'], KIND[uid])
            entry = {'node': uid, 'model': alias, 'contract_ok': ok, 'salvage_ok': sal,
                     'tokens': ent_tokens, 'lat_s': ent['latency_s'], 'attempts': ent['attempt']}
            if ok:
                h_outputs[uid] = parsed
            elif sal:
                h_outputs[uid] = {list(_ports_by_contract(node.output_contract))[0]:
                                  salvage_value(ent['raw_response'], KIND[uid])}
                entry['salvaged'] = True
            else:
                h_outputs[uid] = outputs[uid]
                entry['fallback'] = 'reused glm53 A2 output (hetero deviation recorded)'
            h_log.append(entry)
    rep_txt = h_outputs.get('t5', {}).get('report', '')
    if not isinstance(rep_txt, str):
        rep_txt = json.dumps(rep_txt, ensure_ascii=False)
    hs = scoring.score_output(rep_txt, silver, edates)
    arms['static_hetero_dag'] = {'Q': hs['fact_coverage'], 'citation_accuracy': hs['citation_accuracy'],
                                 'coverage_full/partial': f"{hs['coverage_full']}/{hs['coverage_partial']}",
                                 'new_tokens_this_session': h_new_tokens,
                                 'full_cost_tokens': planner_tok + v2_t01_tok + h_new_tokens,
                                 'full_cost_basis': 'planner(2,267) + V2 real cost of reused t0/t1 (%d) + '
                                                    'new calls this session; reused nodes are NOT zero in '
                                                    'the full-cost view (baseline has no equivalent cache)' % v2_t01_tok,
                                 'reused_nodes': ['t0', 't1'],
                                 'executed_lat_s': round(h_lat, 2),
                                 'latency_note': 'mixed-session (reused nodes carry no fresh latency); '
                                                 'descriptive only, not a paired comparison',
                                 'node_log': h_log, 'unverified_dates': hs['unverified_dates']}

    # ---- 4) fixed-DAG arm from persisted V2 (prior-session latency caveat) ----
    a2_txt = A2_FINAL['t5']['raw_response']
    a2s = scoring.score_output(a2_txt, silver, edates)
    arms['fixed_model_dag_A2'] = {'Q': a2s['fact_coverage'], 'citation_accuracy': a2s['citation_accuracy'],
                                  'coverage_full/partial': f"{a2s['coverage_full']}/{a2s['coverage_partial']}",
                                  'tokens_exec': dag_tok, 'planner_amortized': planner_tok,
                                  'full_cost_tokens': planner_tok + dag_tok,
                                  'wall_s_prior_session': 42.105,
                                  'price_cny': 'UNKNOWN (see single arm note)',
                                  'latency_caveat': 'A2 wall measured in the V2 session (~3h earlier, same host); '
                                                    'single/hetero arms measured in this session — descriptive '
                                                    'comparison only, not paired'}
    v2_t01_tok = sum(c['usage']['input_tokens'] + c['usage']['output_tokens']
                     for c in v2_calls if c['purpose'].startswith(('A2:t0', 'A2:t1')))

    out = {'arms': arms, 'extracts_redo': redo, 'budget': meter.summary(),
           'accounting_note': 'hetero arm reuses persisted A2 outputs for unchanged nodes (zero new tokens); '
                              'fixed arm fully from persisted V2 session'}
    (PILOT_DIR / 'execution_trace_v21.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ('node_log',)} for k, v in arms.items()},
                     ensure_ascii=False, indent=1))
    print('budget:', json.dumps(meter.summary(), ensure_ascii=False))


def salvage_value(raw, kind):
    from flash_eval_v21 import PORT_OF_KIND
    port = PORT_OF_KIND[kind]

    def find(obj):
        if isinstance(obj, dict):
            if port in obj:
                return obj[port]
            for v in obj.values():
                r = find(v)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = find(v)
                if r is not None:
                    return r
        return None
    return find(fenced_json(raw))


if __name__ == '__main__':
    main()
