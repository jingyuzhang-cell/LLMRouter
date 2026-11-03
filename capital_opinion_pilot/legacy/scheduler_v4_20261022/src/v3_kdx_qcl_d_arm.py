"""D-arm feedback-driven recovery on KDX (authorized <=9 calls / 18,000).

Base: the REAL completed C-arm run (node outputs recovered zero-call from its
response ledger). Fault injection = deterministic transport-level outage of the
planned model at a seed-bound node (experimental treatment, zero tokens).
Recovery = re-route ONLY the failed node to the alternative model (real, metered,
salvage available for Flash), then re-run descendants whose inputs changed
(recover_failed semantics: completed outputs protected, blocked descendants reset).
Comparison: vs C-arm clean run (Q 0.4286 / cite 0.6667 / downstream 8,082 tok)
and vs the analytic no-recovery outcome (chain INCOMPLETE).
"""
import json
import time

from pilot_common import PILOT_DIR, Meter, fenced_json
from merge_facts import merge_facts
from v3_kdx_qcl_ab import SYSTEM
from v3_kdx_qcl_c_arm import NODE_DEFS, NODE_CAPS, salvage_value
import scoring_kdx

CAPS = dict(max_calls=9, max_guaranteed_actual=18000)
PLANNED = {'t3': 'glm53flash', 't4': 'glm53flash', 't5': 'glm53', 't6': 'glm53'}
ALTERNATE = {'t3': 'glm53', 't4': 'glm53', 't5': 'glm53flash', 't6': 'glm53flash'}
SEEDS = {1: 't3', 2: 't4', 3: 't5'}          # fault-bound nodes
DESC = {'t3': ['t5', 't6'], 't4': ['t5', 't6'], 't5': ['t6']}


def load_c_outputs():
    rs = {json.loads(l)['purpose']: json.loads(l)
          for l in (PILOT_DIR / 'model_call_ledger_qclc_responses.jsonl').read_text().splitlines() if l.strip()}
    out = {}
    for nid in ('t3', 't4', 't5'):
        raw = rs[f'armC:{nid}']['text']
        port = NODE_DEFS[nid][2]
        try:
            obj = fenced_json(raw)
            out[nid] = obj.get(port) if isinstance(obj, dict) else salvage_value(raw, port)
        except Exception:
            out[nid] = salvage_value(raw, port)
    out['t6'] = rs['armC:t6']['text']
    return out


def run_node(meter, seed_tag, nid, alias, data):
    goal, shape, port = NODE_DEFS[nid]
    rec, txt = meter.call(alias, SYSTEM, f'subtask: {goal}\ninputs:\n{data[:9000]}\n输出 {shape}',
                          max_tokens=NODE_CAPS[nid], purpose=f'armD:{seed_tag}:{nid}', timeout_s=120)
    try:
        obj = fenced_json(txt)
        ok = isinstance(obj, dict) and port in obj
    except Exception:
        obj, ok = None, False
    val = (obj.get(port) if ok else salvage_value(txt, port))
    salvaged = (not ok) and val is not None
    return {'nid': nid, 'model': rec['model'], 'usage': rec['usage'], 'latency_s': rec['latency_s'],
            'contract_ok': ok, 'salvaged': salvaged, 'value': val,
            'Q_raw': scoring_kdx.score(txt)['fact_coverage']}


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_qcld.jsonl', **CAPS)
    salv = json.loads((PILOT_DIR / 'qclab_salvage_analysis.json').read_text())
    merged_json = json.dumps(merge_facts([salv['salvaged_t1'], salv['salvaged_t2']],
                                         ['t1_extracts_f', 't2_extracts_f']), ensure_ascii=False)
    c_out = load_c_outputs()
    seeds = {}
    for seed, fault_node in SEEDS.items():
        t0 = time.monotonic()
        outputs = dict(c_out)                      # completed outputs protected
        log = [{'event': 'fault_injected', 'node': fault_node,
                'planned_model_unavailable': PLANNED[fault_node], 'tokens': 0}]
        # 1) recover the failed node via alternate model (REAL call)
        rec = run_node(meter, f's{seed}r', fault_node, ALTERNATE[fault_node], merged_json)
        outputs[fault_node] = rec['value']
        log.append({'event': 'node_recovered', **{k: rec[k] for k in
                                                  ('nid', 'model', 'usage', 'latency_s', 'contract_ok', 'salvaged', 'Q_raw')}})
        # 2) re-run descendants whose inputs changed (planned models, REAL calls)
        for dn in DESC[fault_node]:
            if dn == 't5':
                data = json.dumps({'timeline': outputs['t3'], 'entity_facts': outputs['t4']}, ensure_ascii=False)
            else:
                data = json.dumps({'verified_facts': (outputs.get('t5') or [])[:40]}, ensure_ascii=False)
            r = run_node(meter, f's{seed}', dn, PLANNED[dn], data)
            outputs[dn] = r['value']
            log.append({'event': 'descendant_rerun', **{k: r[k] for k in
                                                        ('nid', 'model', 'usage', 'latency_s', 'contract_ok', 'salvaged', 'Q_raw')}})
        rep = outputs.get('t6') or ''
        if not isinstance(rep, str):
            rep = json.dumps(rep, ensure_ascii=False)
        s = scoring_kdx.score(rep + '\n' + merged_json)
        spent = sum(e['usage']['input_tokens'] + e['usage']['output_tokens'] for e in log
                    if 'usage' in e)
        seeds[f'seed{seed}'] = {'fault_node': fault_node, 'log': log,
                                'tokens_spent': spent, 'wall_s': round(time.monotonic() - t0, 2),
                                'final_Q': s['fact_coverage'], 'covered': s['covered_fact_ids'],
                                'final_cite': s['citation_accuracy'],
                                'no_recovery_counterfactual': 'INCOMPLETE (t6 blocked by failed node)'}
        print(f"seed{seed} fault@{fault_node}: recovered->", rec['model'],
              'final Q', s['fact_coverage'], 'cite', s['citation_accuracy'], 'spent', spent)
    cref = json.loads((PILOT_DIR / 'v3_kdx_qcl_c_result.json').read_text())
    out = {'arm': 'D feedback-driven recovery (fault-injected; recovery calls real)',
           'base_C_reference': {'Q': cref['end_to_end']['Q'], 'cite': cref['end_to_end']['cite'],
                                 'downstream_tokens': 8082},
           'seeds': seeds, 'budget': meter.summary()}
    (PILOT_DIR / 'v3_kdx_qcl_d_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('budget:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
