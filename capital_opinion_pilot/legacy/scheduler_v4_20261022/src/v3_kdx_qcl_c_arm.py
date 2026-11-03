"""C-arm static heterogeneous assignment on KDX (authorized ~<=8 calls / 18,000).

Reuses the PAID frozen layers: retrieval (deterministic) + extraction facts
(salvaged real t1/t2 outputs). Assignment: t3/t4 (parallel analysis branches) =
GLM-5.3-Flash with deterministic salvage on contract failure; t5 verification and
t6 report = GLM-5.3. Identical inputs/contracts/caps as the B-arm downstream run —
only the branch models differ. Measures per-node Q(content)/contract/salvage/cost/
latency and end-to-end Q vs the B-arm (already persisted).
"""
import json
import time

from pilot_common import PILOT_DIR, Meter, fenced_json
from merge_facts import merge_facts, merge_stats
from flash_eval_v21 import salvage, PORT_OF_KIND
from v3_kdx_qcl_ab import SYSTEM
import scoring_kdx

CAPS = dict(max_calls=8, max_guaranteed_actual=18000)
NODE_CAPS = {'t3': 768, 't4': 768, 't5': 768, 't6': 1536}
NODE_DEFS = {
    't3': ('梳理2018问询至2020处罚禁入的关键时间节点（输入为多源合并事实，含出处）',
           '{"timeline":[{"date":"YYYY-MM-DD","event":"..","doc_id":..}]}', 'timeline'),
    't4': ('归集监管认定vs公司披露的主体事实及矛盾及未确认项',
           '{"entity_facts":[{"fact_key":"..","value":"..","doc_id":..}]}', 'entity_facts'),
    't5': ('交叉核验时间线与主体事实，逐条给出结论并标注无法确认事项',
           '{"verified_facts":[{"fact":"..","verdict":"SUPPORTED|UNSUPPORTED|UNRESOLVED","doc_id":..}]}', 'verified_facts'),
    't6': ('生成带准确证据引用的调查报告（不超过800字，无法确认事项单独标注）', '{"report":"报告全文"}', 'report')}
ASSIGN = {'t3': 'glm53flash', 't4': 'glm53flash', 't5': 'glm53', 't6': 'glm53'}


def salvage_value(raw, kind):
    port = PORT_OF_KIND.get(kind, kind)  # unknown kinds: the port name IS the key

    def find(o):
        if isinstance(o, dict):
            if port in o:
                return o[port]
            for v in o.values():
                r = find(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r is not None:
                    return r
        return None
    try:
        return find(fenced_json(raw))
    except Exception:
        return None


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_qclc.jsonl', **CAPS)
    salv = json.loads((PILOT_DIR / 'qclab_salvage_analysis.json').read_text())
    merged = merge_facts([salv['salvaged_t1'], salv['salvaged_t2']], ['t1_extracts_f', 't2_extracts_f'])
    merged_json = json.dumps(merged, ensure_ascii=False)

    upstream = {'t3': merged_json, 't4': merged_json}
    results, log = {}, []
    t0 = time.monotonic()
    for nid in ('t3', 't4', 't5', 't6'):
        if nid == 't5':
            data = json.dumps({'timeline': results.get('t3'), 'entity_facts': results.get('t4')},
                              ensure_ascii=False)
        elif nid == 't6':
            data = json.dumps({'verified_facts': (results.get('t5') or [])[:40]}, ensure_ascii=False)
        else:
            data = upstream[nid]
        goal, shape, port = NODE_DEFS[nid]
        alias = ASSIGN[nid]
        rec, txt = meter.call(alias, SYSTEM, f'subtask: {goal}\ninputs:\n{data[:9000]}\n输出 {shape}',
                              max_tokens=NODE_CAPS[nid], purpose=f'armC:{nid}', timeout_s=120)
        entry = {'node': nid, 'model': rec['model'], 'usage': rec['usage'], 'latency_s': rec['latency_s'],
                 'truncated': rec['stop_reason'] == 'max_tokens'}
        try:
            obj = fenced_json(txt)
            ok = isinstance(obj, dict) and port in obj
            status = 'OK' if ok else 'FAIL:shape'
        except Exception as e:
            obj, ok, status = None, False, f'FAIL:{str(e)[:60]}'
        sal_ok = False
        if not ok and alias == 'glm53flash':
            sal_ok, _ = salvage(txt, {'timeline': 'timeline', 'entity_facts': 'entity_facts',
                                      'verified_facts': 'verified_facts', 'report': 'report'}[port]
                                if port in PORT_OF_KIND else port)
            val = salvage_value(txt, port)
            if val is not None:
                obj = {port: val}
                sal_ok = True
        entry.update({'status': status, 'salvaged': sal_ok,
                      'Q_content_raw': scoring_kdx.score(txt)['fact_coverage']})
        results[nid] = obj.get(port) if obj else None
        if nid == 't6' and obj:
            results[nid] = obj.get('report', txt)
        log.append(entry)
        print(nid, alias, status, 'salvaged', sal_ok, 'Q_raw', entry['Q_content_raw'],
              'in/out', rec['usage']['input_tokens'], rec['usage']['output_tokens'])

    repC = results.get('t6') or ''
    if not isinstance(repC, str):
        repC = json.dumps(repC, ensure_ascii=False)
    sC = scoring_kdx.score(repC + '\n' + merged_json)
    # B-arm reference from persisted completion run
    bref = json.loads((PILOT_DIR / 'v3_kdx_qcl_complete_result.json').read_text())['armB']
    out = {'arm': 'C static heterogeneous (t3/t4=Flash+salvage; t5/t6=GLM-5.3; extraction layer reused)',
           'nodes': log, 'wall_s': round(time.monotonic() - t0, 2),
           'end_to_end': {'Q': sC['fact_coverage'], 'covered': sC['covered_fact_ids'],
                          'cite': sC['citation_accuracy'], 'marks_unresolved': sC['marks_unresolved']},
           'report': repC,
           'vs_armB': {'Q_B': bref['Q'], 'cite_B': bref['cite'],
                       'tokens_B_downstream': sum(n['usage']['input_tokens'] + n['usage']['output_tokens']
                                                  for n in bref['nodes']),
                       'note': 'identical inputs/contracts/caps; only t3/t4 model differs'},
           'budget': meter.summary()}
    (PILOT_DIR / 'v3_kdx_qcl_c_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('C end-to-end Q:', sC['fact_coverage'], sC['covered_fact_ids'], 'cite', sC['citation_accuracy'])
    print('B reference: Q', bref['Q'], 'cite', bref['cite'])
    print('budget:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
