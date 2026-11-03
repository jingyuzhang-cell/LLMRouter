"""Zero-call window experiment v2 (2026-10-14): evidence coverage with the FIXED packer.

Same frozen official KDX evidence + task as the v1 experiment (ONE_HOUR E1), but with
evidence_packer v2 (greedy global fill, non-empty guarantee, no answer-directed
selection). Windows: 600 / 1500 / 3000 / 6000 / 10000 / 19000 chars.

For each window, on BOTH the official ranking and the ORACLE upper bound
(anchor-containing chunks ranked first — REPORTING ONLY, never used as model input):
  actual chars, estimated input tokens, per-doc entry, T1 (RF1-RF4) evidence
  coverage, truncation flags, and per-missing-fact reasons (rank of the fact's
  best-ranked anchor chunk, minimal covering budget).

Zero model calls. Output: e1_window_vs_t1_v2.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
import evidence_packer as ep
from kdx_retrieval import TASK_TERMS

P = PILOT_DIR
WINDOWS = [600, 1500, 3000, 6000, 10000, 19000]
EST_USD_PER_TOK = 0.3 / 1e6  # same formula as v1 experiment (est_cost_usd)

INDEX = ep.build_index()
OFFICIAL_RANKED = ep.rank_chunks(INDEX)


def load_kdx_facts():
    facts = json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
    kdx = [f for f in facts if f['event_id'].startswith('kdx')]
    for f in kdx:  # facts use D{n}_doc_id naming; manifest ids drop the D-prefix
        f['doc'] = f['doc_id'].split('_', 1)[1]
    return kdx


FACTS = load_kdx_facts()


def anchor_chunks(fact):
    """Chunks whose span overlaps the fact's anchored offsets (or containing its quote)."""
    out = []
    for c in INDEX:
        if c['doc_id'] != fact['doc']:
            continue
        if c['start'] < fact['char_end'] and c['end'] > fact['char_start']:
            out.append(c)
        elif norm(fact['anchor_quote']) in norm(c['text']):
            out.append(c)
    return out


RANK_OF = {c['chunk_id']: i for i, c in enumerate(OFFICIAL_RANKED)}
ANCHOR_CHUNKS = {f['fact_id']: anchor_chunks(f) for f in FACTS}
# oracle ranking: anchor chunks first (by fact order), rest by official score
_oracle_first = []
for f in FACTS:
    _oracle_first += [c for c in ANCHOR_CHUNKS[f['fact_id']] if c not in _oracle_first]
ORACLE_RANKED = _oracle_first + [c for c in OFFICIAL_RANKED if c not in _oracle_first]


def covered(fact, pack):
    if norm(fact['anchor_quote']) in norm(pack['text']):
        return True
    for it in pack['items']:
        if it['doc_id'] == fact['doc'] and it['start'] < fact['char_end'] and it['end'] > fact['char_start']:
            return True
    return False


def min_covering_budget(fact):
    """Smallest window (search 450c grid up to 40000) at which the official pack covers f."""
    for b in range(450, 40001, 450):
        if covered(fact, ep.pack_global(b, ranked=OFFICIAL_RANKED)):
            return b
    return None


def describe(budget, ranked, label):
    pack = ep.pack_global(budget, ranked=ranked)
    hits, missing, reasons = [], [], []
    for f in FACTS:
        if covered(f, pack):
            hits.append(f['fact_id'])
        else:
            ranks = sorted(RANK_OF[c['chunk_id']] for c in ANCHOR_CHUNKS[f['fact_id']])
            best = ranks[0] if ranks else None
            why = ('anchor chunk ranked #%d globally (0-based); enters official pack at ~%dc'
                   % (best, min_covering_budget(f))) if best is not None else 'no chunk overlaps anchor offsets'
            if best is not None and ranks and best > 40:
                why += '; low score: chunk text matches few task terms'
            missing.append(f['fact_id'])
            reasons.append({'fact': f['fact_id'], 'doc': f['doc'],
                            'anchor': f['anchor_quote'][:30], 'reason': why,
                            'anchor_chunk_ranks': ranks[:5]})
    per_doc = {d: {'chars': v, 'chunks': sum(1 for it in pack['items'] if it['doc_id'] == d)}
               for d, v in pack['per_doc'].items()}
    return {'budget': budget, 'mode': label, 'actual_chars': pack['chars'],
            'est_tok': pack['est_tok'], 'est_cost_usd': round(pack['est_tok'] * EST_USD_PER_TOK, 6),
            'docs': len(pack['docs']), 'per_doc': per_doc,
            'truncated_any': pack['truncated_any'],
            't1_hits': f'{len(hits)}/{len(FACTS)}', 't1_covered': hits, 'missing': missing,
            'missing_reasons': reasons}


def main():
    rows = []
    for b in WINDOWS:
        rows.append(describe(b, OFFICIAL_RANKED, 'official'))
        rows.append(describe(b, ORACLE_RANKED, 'oracle_upper_bound'))
        print(f'window {b:6d} official: chars={rows[-2]["actual_chars"]:6d} '
              f'tok={rows[-2]["est_tok"]:6d} docs={rows[-2]["docs"]} T1={rows[-2]["t1_hits"]} '
              f'missing={rows[-2]["missing"]} | oracle T1={rows[-1]["t1_hits"]}')
    out = {'experiment': 'evidence_window_v2_fixed_packer', 'date': '2026-10-14',
           'facts': [{'id': f['fact_id'], 'doc': f['doc'], 'anchor': f['anchor_quote'][:30],
                      'anchor_chunk_ranks': sorted(RANK_OF[c['chunk_id']]
                                                   for c in ANCHOR_CHUNKS[f['fact_id']])[:5]}
                     for f in FACTS],
           'rows': rows}
    (P / 'e1_window_vs_t1_v2.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('saved e1_window_vs_t1_v2.json')


if __name__ == '__main__':
    main()
