"""QCL completion round (补全-2, authorized): rebuild Arm-B downstream (t3-t6) on the
SALVAGED 13 extraction facts (their real V2 outputs, deterministically recovered from
truncated JSON) and rerun ArmA at the corrected 1,536 output cap. Fixed-cap rule
applied (rich-input nodes never below 1K... report/extracts >=1,536; mid-chain 768).
Order: ArmA first (big reserve), then t3-t6. Guard: 6 calls / 38,000 guaranteed.
"""
import json
import time

from pilot_common import PILOT_DIR, Meter, fenced_json
from merge_facts import merge_facts, merge_stats
from v3_kdx_qcl_ab import TASK, CUTOFF, frozen_retrieval, pack_chunks, SYSTEM, SYSTEM_REPORT
import scoring_kdx

CAPS = dict(max_calls=6, max_guaranteed_actual=38000)
NODE_CAPS = {'t3': 768, 't4': 768, 't5': 768, 't6': 1536, 'armA': 1536}


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_qclcomplete.jsonl', **CAPS)
    salv = json.loads((PILOT_DIR / 'qclab_salvage_analysis.json').read_text())
    merged = merge_facts([salv['salvaged_t1'], salv['salvaged_t2']],
                         ['t1_extracts_f', 't2_extracts_f'])
    mstats = merge_stats(merged)
    merged_json = json.dumps(merged, ensure_ascii=False)
    print('merged facts:', mstats['items'], 'chars', len(merged_json))

    result = {'tier': 'completion (salvaged extraction layer + corrected output caps)',
              'merge_stats': mstats}

    # ---- ArmA rerun at corrected cap (first: biggest reserve) ----
    lines = frozen_retrieval()
    pack = pack_chunks(lines['t1_regulatory']['picked']) + '\n\n' + pack_chunks(lines['t2_inquiry']['picked'])
    recA, txtA = meter.call('glm53', SYSTEM_REPORT,
        '调查任务：' + TASK + f'\n\n证据材料（分段检索结果，两线合并，截止{CUTOFF}）：\n' + pack,
        max_tokens=NODE_CAPS['armA'], purpose='armA_single_v2', timeout_s=180)
    sA = scoring_kdx.score(txtA)
    result['armA'] = {'Q': sA['fact_coverage'], 'covered': sA['covered_fact_ids'],
                      'cite': sA['citation_accuracy'], 'unverified_dates': sA['unverified_dates'],
                      'marks_unresolved': sA['marks_unresolved'], 'tokens': recA['usage'],
                      'truncated': recA['stop_reason'] == 'max_tokens', 'chars': len(txtA),
                      'latency_s': recA['latency_s'], 'report': txtA}
    print('ArmA v2: Q', sA['fact_coverage'], sA['covered_fact_ids'], 'cite', sA['citation_accuracy'],
          'truncated', result['armA']['truncated'])

    # ---- ArmB downstream rebuild on salvaged facts ----
    node_defs = {
        't3': ('梳理2018问询至2020处罚禁入的关键时间节点（输入为多源合并事实，含出处）',
               '{"timeline":[{"date":"YYYY-MM-DD","event":"..","doc_id":..}]}'),
        't4': ('归集监管认定vs公司披露的主体事实及矛盾与未确认项',
               '{"entity_facts":[{"fact_key":"..","value":"..","doc_id":..}]}'),
        't5': ('交叉核验时间线与主体事实，逐条给出结论并标注无法确认事项',
               '{"verified_facts":[{"fact":"..","verdict":"SUPPORTED|UNSUPPORTED|UNRESOLVED","doc_id":..}]}'),
        't6': ('生成带准确证据引用的调查报告（不超过800字，无法确认事项单独标注）', '{"report":"报告全文"}')}
    upstream = {'t3': merged_json, 't4': merged_json}
    results = {}
    nodes_log = []
    tb = time.monotonic()
    for nid in ('t3', 't4', 't5', 't6'):
        if nid == 't5':
            data = json.dumps({'timeline': results.get('t3'), 'entity_facts': results.get('t4')},
                              ensure_ascii=False)
        elif nid == 't6':
            data = json.dumps({'verified_facts': (results.get('t5') or [])[:40]}, ensure_ascii=False)
        else:
            data = upstream[nid]
        goal, shape = node_defs[nid]
        rec, txt = meter.call('glm53', SYSTEM,
            f'subtask: {goal}\ninputs:\n{data[:9000]}\n输出 {shape}',
            max_tokens=NODE_CAPS[nid], purpose=f'armBv2:{nid}', timeout_s=120)
        try:
            obj = fenced_json(txt)
            status = 'OK'
        except Exception:
            obj, status = None, 'PARSE_FAIL'
        results[nid] = (obj.get('timeline') if nid == 't3' else
                        obj.get('entity_facts') if nid == 't4' else
                        obj.get('verified_facts') if nid == 't5' else
                        obj.get('report')) if obj else None
        nodes_log.append({'node': nid, 'usage': rec['usage'], 'latency_s': rec['latency_s'],
                          'status': status, 'truncated': rec['stop_reason'] == 'max_tokens'})
        print(nid, status, 'truncated', rec['stop_reason'] == 'max_tokens')
    repB = results.get('t6') or ''
    if not isinstance(repB, str):
        repB = json.dumps(repB, ensure_ascii=False)
    sB = scoring_kdx.score(repB + '\n' + merged_json)
    result['armB'] = {'nodes': nodes_log, 'wall_s': round(time.monotonic() - tb, 2),
                      'Q': sB['fact_coverage'], 'covered': sB['covered_fact_ids'],
                      'cite': sB['citation_accuracy'], 'unverified_dates': sB['unverified_dates'],
                      'marks_unresolved': sB['marks_unresolved'], 'report': repB}
    print('ArmB v2: Q', sB['fact_coverage'], sB['covered_fact_ids'], 'cite', sB['citation_accuracy'])
    result['budget'] = meter.summary()
    (PILOT_DIR / 'v3_kdx_qcl_complete_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print('budget:', json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == '__main__':
    main()
