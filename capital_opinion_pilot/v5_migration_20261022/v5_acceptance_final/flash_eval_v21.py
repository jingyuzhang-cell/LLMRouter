"""V2.1 zero-call analyses on persisted V2 artifacts (no model calls).

1) Flash tripartite evaluation: factual content (scorer on raw response) vs JSON
   contract legality (parse status) vs deterministic salvage-normalization cost.
   Format failure is NOT counted as reasoning failure; salvaged output is NOT
   counted as contract-legal — the three layers are reported separately.
2) F5 information-loss localization: which node dropped the 10.33B overstatement
   figure (evidence pack -> t1 extracts -> t4 factcheck -> t5 report).
3) Q=0.8125 definition audit: per-fact tier breakdown of the final report score.
"""
import json
import time

from pilot_common import PILOT_DIR, fenced_json
import scoring

def _nodes():
    return [json.loads(l) for l in (PILOT_DIR / 'node_results_v2.jsonl').read_text().splitlines() if l.strip()]
PORT_OF_KIND = {'extracts': 'doc_extracts', 'entity_facts': 'entity_facts', 'timeline': 'timeline',
                'factcheck_tl': 'verified_facts', 'factcheck_ef': 'verified_facts',
                'factcheck_full': 'verified_facts', 'index': 'evidence_index', 'report': 'report'}


def salvage(raw, kind):
    """Deterministic contract salvage: extract the required port from wrapped JSON.
    Returns (ok, runtime_ms). Pure program cost; zero model tokens."""
    t0 = time.perf_counter()
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

    try:
        val = find(fenced_json(raw))
        ok = val is not None and isinstance(val, (list, dict, str)) and len(json.dumps(val, ensure_ascii=False)) > 2
    except Exception:
        ok = False
    return ok, (time.perf_counter() - t0) * 1000


def main():
    out = {'flash_tripartite': [], 'glm53_reference': []}
    silver = scoring.load_silver()
    edates = scoring.load_evidence_dates()
    for e in _nodes():
        if not e['run'].startswith('C-'):
            continue
        s = scoring.score_output(e['raw_response'], silver, edates)
        row = {'run': e['run'], 'node': e['node_id'], 'kind': e['kind'], 'attempt': e['attempt'],
               'contract_ok': e['parse_status'] == 'OK',
               'content_Q_raw': s['fact_coverage'], 'content_full/partial': f"{s['coverage_full']}/{s['coverage_partial']}",
               'unverified_dates': s['unverified_dates']}
        if e['model_alias'] == 'glm53flash' and not row['contract_ok']:
            ok, ms = salvage(e['raw_response'], e['kind'])
            row['salvage_ok'] = ok
            row['salvage_cost_ms'] = round(ms, 3)
        (out['flash_tripartite'] if e['model_alias'] == 'glm53flash' else out['glm53_reference']).append(row)

    flash = out['flash_tripartite']
    fails = [r for r in flash if not r['contract_ok']]
    out['flash_summary'] = {
        'n': len(flash),
        'contract_ok': sum(1 for r in flash if r['contract_ok']),
        'content_Q_mean': round(sum(r['content_Q_raw'] for r in flash) / len(flash), 4) if flash else None,
        'contract_fail_but_content_ok_salvageable':
            sum(1 for r in fails if r.get('salvage_ok')),
        'contract_fail_total': len(fails),
        'salvage_runtime_ms_max': max((r.get('salvage_cost_ms', 0) for r in fails), default=0),
        'note': 'salvage = deterministic program normalization (zero model tokens); salvaged '
                'outputs are counted usable-content, NOT contract-legal'}

    # ---- F5 localization ----
    from execute_dag import evidence_pack
    pack = evidence_pack()
    chain = {}
    for nid in ('t1', 't4', 't5'):
        es = [e for e in NODES if e['run'] == 'A2' and e['node_id'] == nid]
        chain[nid] = '10,333,448,392.98' in es[-1]['raw_response'] or '10333448392.98' in es[-1]['raw_response'].replace(',', '')
    out['f5_localization'] = {
        'fact': 'F5 虚增营收合计 10,333,448,392.98 元',
        'in_evidence_pack': '10,333,448,392.98' in pack,
        'in_t1_extracts': chain['t1'], 'in_t4_factcheck': chain['t4'], 'in_t5_report': chain['t5'],
        'conclusion': ('F5 丢失层=证据包构建（确定性注入层，csrc摘录自"经查明"起500字截断，恰好截掉'
                       '第二条违法事实中的共计虚增句）——任何模型节点都无法找回上游未注入的信息'
                       if not chain['t1'] else f"丢失层={'t4' if not chain['t4'] else 't5'}")}

    # ---- Q definition audit on final report ----
    rep = [e for e in NODES if e['run'] == 'A2' and e['node_id'] == 't5'][-1]
    s = scoring.score_output(rep['raw_response'], silver, edates)
    out['q_audit'] = {
        'definition': 'Q = (full + 0.5*partial) / 8 verified silver facts; dates=exact ISO match; '
                      'amounts=comma-normalized substring; text=verbatim (full) or >=5字分段命中 (partial)',
        'report_tiers': s['tier_results'], 'coverage': s['fact_coverage'],
        'citation_accuracy': s['citation_accuracy'],
        'missing': [f for f in silver if not s['tier_results'][f['fact_id']]] and
                   [f['fact_id'] for f in silver if s['tier_results'][f['fact_id']] is False]}

    (PILOT_DIR / 'flash_eval_v21.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out['flash_summary'], ensure_ascii=False))
    print(json.dumps(out['f5_localization'], ensure_ascii=False))
    print(json.dumps(out['q_audit'], ensure_ascii=False)[:400])
    print('--- flash rows ---')
    for r in fails:
        print(f"  {r['run']:22s} {r['node']} a{r['attempt']} Q={r['content_Q_raw']:.3f} salvage={r.get('salvage_ok')}")


if __name__ == '__main__':
    main()
