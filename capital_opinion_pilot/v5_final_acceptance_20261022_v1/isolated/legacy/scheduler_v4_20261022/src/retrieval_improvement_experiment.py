"""Zero-pay retrieval improvement experiment (2026-10-14, DEV stage, KDX only).

Compares, WITHOUT any model API call:
  frozen_10k_5050   : the unchanged frozen v2 baseline (10K global, 50/50 lines)
  rrf_10k_5050      : v3 RRF multi-facet ranking, same 50/50 split
  rrf_dyn_10k       : v3 ranking + dynamic line budgets (min 25%, fused-mass split)
  rrf_dyn_15k/20k/25k : window scaling of the best pre-committed variant

Post-hoc evaluation ONLY (after packing): RF1-RF4 evidence coverage, actual chars,
estimated tokens, source diversity, missing reasons, packing runtime. Facts files
are read exclusively by this evaluation step — never by retrieval construction.

Anti-leakage constraints honoured: facet terms are the frozen TASK_TERMS
vocabulary; no anchor positions, no gold/silver files in retrieval_v3.py; no
configuration picked by best post-hoc coverage (single pre-committed variant is
scaled across windows).
Output: retrieval_improvement_result.json (+ .md summary by the report writer).
"""
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
import evidence_packer as ep
import retrieval_v3 as rv

P = PILOT_DIR
LINE_DOCS = {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
             't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}
INDEX = ep.build_index()
OFFICIAL_RANKED = ep.rank_chunks(INDEX)
V3_RANKED, V3_FUSED = rv.fused_ranking(INDEX)


def load_facts():
    refs = json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
    return [f for f in refs if f['event_id'].startswith('kdx')]


def coverage(packs_text, facts, packs_items):
    hay = norm(packs_text)
    hits, missing = [], []
    for f in facts:
        ok = norm(f['anchor_quote']) in hay
        if not ok:
            for it in packs_items:
                if it['doc_id'] == f['doc_id'].split('_', 1)[1] and \
                   it['start'] < f['char_end'] and it['end'] > f['char_start']:
                    ok = True
                    break
        (hits if ok else missing).append(f['fact_id'])
    return hits, missing


def diversity(per_doc):
    shares = [v / sum(per_doc.values()) for v in per_doc.values()]
    H = -sum(s * math.log(s) for s in shares if s > 0)
    return {'docs': len(per_doc), 'per_doc_chars': per_doc,
            'entropy': round(H, 3), 'max_share': round(max(shares), 3)}


def evaluate(config, window, packs, budgets, elapsed_ms):
    text = packs['t1']['text'] + '\n' + packs['t2']['text']
    items = packs['t1']['items'] + packs['t2']['items']
    facts = load_facts()
    hits, missing = coverage(text, facts, items)
    chars = packs['t1']['chars'] + packs['t2']['chars']
    per_doc = {**packs['t1']['per_doc'], **packs['t2']['per_doc']}
    reasons = []
    for fid in missing:
        f = next(x for x in facts if x['fact_id'] == fid)
        doc = f['doc_id'].split('_', 1)[1]
        r = [i for i, c in enumerate(V3_RANKED) if c['doc_id'] == doc
             and c['start'] < f['char_end'] and c['end'] > f['char_start']]
        off = [i for i, c in enumerate(OFFICIAL_RANKED) if c['doc_id'] == doc
               and c['start'] < f['char_end'] and c['end'] > f['char_start']]
        reasons.append({'fact': fid, 'v3_fused_rank_of_anchor_chunk': r[:3],
                        'v1_rank_of_anchor_chunk': off[:3],
                        'line': 't1' if doc in LINE_DOCS['t1'] else 't2',
                        'line_budget_chars': budgets.get('t1' if doc in LINE_DOCS['t1'] else 't2')})
    return {'config': config, 'window': window, 'line_budgets': budgets,
            'actual_chars': chars, 'est_tok': math.ceil(chars * rv.TOK_PER_CHAR),
            'chunks': len(items), 'source_diversity': diversity(per_doc),
            't1_hits': f'{len(hits)}/4', 't1_covered': hits, 't1_missing': missing,
            'missing_reasons': reasons,
            'truncated_any': packs['t1']['truncated_any'] or packs['t2']['truncated_any'],
            'pack_runtime_ms': elapsed_ms}


def run_config(config, window):
    t0 = time.perf_counter()
    if config == 'frozen_10k_5050' or config == 'frozen':
        packs = ep.pack_lines(window, LINE_DOCS, ranked=OFFICIAL_RANKED)
        budgets = {'t1': window // 2, 't2': window // 2}
    elif config == 'rrf_5050':
        packs, budgets = rv.pack_v3(window, LINE_DOCS, V3_RANKED, V3_FUSED, dynamic=False)
    else:  # rrf_dyn
        packs, budgets = rv.pack_v3(window, LINE_DOCS, V3_RANKED, V3_FUSED, dynamic=True)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return evaluate(config.replace('_10k', ''), window, packs, budgets, ms)


def main():
    rows = []
    for cfg, w in [('frozen_10k_5050', 10000), ('rrf_5050', 10000), ('rrf_dyn', 10000),
                   ('frozen_10k_5050', 15000), ('rrf_dyn', 15000),
                   ('frozen_10k_5050', 20000), ('rrf_dyn', 20000),
                   ('frozen_10k_5050', 25000), ('rrf_dyn', 25000)]:
        r = run_config(cfg, w)
        rows.append(r)
        print(f"{cfg:16s} W={w:6d} chars={r['actual_chars']:6d} tok={r['est_tok']:6d} "
              f"chunks={r['chunks']:3d} docs={r['source_diversity']['docs']} "
              f"H={r['source_diversity']['entropy']:.2f} T1={r['t1_hits']} "
              f"missing={r['t1_missing']} budgets={r['line_budgets']} {r['pack_runtime_ms']}ms")
    out = {'experiment': 'retrieval_improvement_dev_kdx', 'date': '2026-10-14',
           'dev_stage_warning': ('developed on KDX DEV with known missing facts; '
                                 'independent-event validation REQUIRED before benchmark use; '
                                 'not protocol-equivalent to the frozen v2 baseline'),
           'anti_leakage': ('facet terms = frozen TASK_TERMS vocabulary; no gold/silver '
                            'access in retrieval_v3.py; single pre-committed variant scaled '
                            'across windows, no best-coverage config selection'),
           'rows': rows}
    (P / 'retrieval_improvement_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('saved retrieval_improvement_result.json')


if __name__ == '__main__':
    main()
