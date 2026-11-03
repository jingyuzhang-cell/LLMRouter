"""Zero-pay ST (江苏舜天) window validation — independent-event check of the
KDX-DEV finding that window size (10K->20K) dominates retrieval-ranking tweaks.

Uses the FROZEN retrieval method only (single IDF score per line, 50/50 line
split, greedy whole-chunk fill, overlap dedup, non-empty guarantee) on the ST
event's four official documents. Windows: 10000 / 15000 / 20000 (+25000 for the
curve). Task terms derive from the ST investigation TASK TEXT + the same generic
regulatory-document structure anchors used for KDX (declared legitimate in
kdx_retrieval.py). No reading of reference facts/anchors at construction time;
coverage is computed post-hoc only.

DEV marker: this event is now used to CHOOSE a window candidate -> it becomes
development data; truly independent confirmation must come from a fresh event
under a frozen protocol.
Output: st_window_validation.json
"""
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
from kdx_retrieval import build_idf, score_chunk
import evidence_packer as ep

P = PILOT_DIR
CHUNK_CHARS, OVERLAP = 450, 80
LINE_DOCS = {'t1': ['csrc_penalty_2024_41', 'st_advance_notice_2023'],
             't2': ['st_announce_2024_020', 'st_announce_2024_021']}
# from TASK_ST text (e4_controlled_experiment.py) + generic regulatory anchors
ST_TERMS = ['专网通信', '虚假', '自循环', '虚增', '营业收入', '信息披露', '立案',
            '行政处罚', '风险提示', '责令改正', '罚款', '警告', '当事人', '违法',
            '年报', '事先告知', '经查明', '决定书', '并处以', '给予警告', '听证',
            '回复', '收到', '承担责任', '调查']
WINDOWS = [10000, 15000, 20000, 25000]


def build_st_index():
    man = json.loads((P / 'evidence_manifest.json').read_text())
    docs = {d['doc_id']: d for d in man['documents']}
    index = []
    for doc_id in (LINE_DOCS['t1'] + LINE_DOCS['t2']):
        text = (P / 'evidence' / 'text' / f'{doc_id}.txt').read_text()
        starts = list(range(0, max(1, len(text) - CHUNK_CHARS + 1), CHUNK_CHARS - OVERLAP)) or [0]
        for ci, s in enumerate(starts):
            chunk = text[s:s + CHUNK_CHARS]
            index.append({'chunk_id': f'{doc_id}#c{ci:03d}', 'doc_id': doc_id,
                          'start': s, 'end': s + len(chunk),
                          'sha256': hashlib.sha256(chunk.encode()).hexdigest()[:16],
                          'public_date': docs[doc_id].get('declared_public_date', ''),
                          'text': chunk})
    return index


def rank_st(index):
    idf = build_idf(index, ST_TERMS)
    return sorted(index, key=lambda c: (-score_chunk(c['text'], ST_TERMS, idf), c['chunk_id']))


def load_st_facts():
    refs = json.loads((P / 'kdx_st_reference_facts.json').read_text())['facts']
    return [f for f in refs if not f['event_id'].startswith('kdx')]


def coverage(packs, facts):
    text = norm(packs['t1']['text'] + '\n' + packs['t2']['text'])
    items = packs['t1']['items'] + packs['t2']['items']
    hits, missing = [], []
    for f in facts:
        ok = norm(f['anchor_quote']) in text
        if not ok:
            for it in items:
                if it['doc_id'] == f['doc_id'] and it['start'] < f['char_end'] and it['end'] > f['char_start']:
                    ok = True
                    break
        (hits if ok else missing).append(f['fact_id'])
    return hits, missing


def main():
    index = build_st_index()
    ranked = rank_st(index)
    rank_of = {c['chunk_id']: i for i, c in enumerate(ranked)}
    facts = load_st_facts()
    rows = []
    for w in WINDOWS:
        packs = {line: ep.pack_global(w // 2, doc_ids=docs, index=index, ranked=ranked)
                 for line, docs in LINE_DOCS.items()}
        hits, missing = coverage(packs, facts)
        chars = packs['t1']['chars'] + packs['t2']['chars']
        per_doc = {**packs['t1']['per_doc'], **packs['t2']['per_doc']}
        reasons = []
        for fid in missing:
            f = next(x for x in facts if x['fact_id'] == fid)
            r = [rank_of[c['chunk_id']] for c in index
                 if c['doc_id'] == f['doc_id'] and c['start'] < f['char_end'] and c['end'] > f['char_start']]
            reasons.append({'fact': fid, 'anchor_chunk_ranks': r[:3],
                            'line': 't1' if f['doc_id'] in LINE_DOCS['t1'] else 't2'})
        rows.append({'window': w, 'actual_chars': chars,
                     'est_tok': math.ceil(chars * 0.677), 'chunks': len(per_doc),
                     'per_doc_chars': per_doc, 't1_hits': f'{len(hits)}/{len(facts)}',
                     't1_covered': hits, 't1_missing': missing, 'missing_reasons': reasons,
                     'est_extract_lat_s_per_line': round((w // 2) * 0.677 / 800 + 1, 1)})
        print(f"ST W={w:6d} chars={chars:6d} tok={rows[-1]['est_tok']:6d} "
              f"T1={rows[-1]['t1_hits']} missing={missing} per_doc={per_doc}")
    out = {'experiment': 'st_window_validation_dev', 'date': '2026-10-14',
           'dev_marker': ('this event is now used to select the window candidate -> '
                          'development data; independent confirmation requires a fresh '
                          'event under a frozen protocol'),
           'terms_legitimacy': 'ST_TERMS derive from the ST TASK text + generic regulatory anchors; '
                               'reference facts read ONLY post-hoc for evaluation',
           'facts': [{'id': f['fact_id'], 'doc': f['doc_id'], 'anchor': f['anchor_quote'][:20]}
                     for f in facts],
           'rows': rows}
    (P / 'st_window_validation.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('saved st_window_validation.json')


if __name__ == '__main__':
    main()
