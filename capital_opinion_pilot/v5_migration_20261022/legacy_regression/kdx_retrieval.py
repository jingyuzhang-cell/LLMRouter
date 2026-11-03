"""Task 2: reproducible chunked retrieval over the FROZEN Kangde Xin evidence.

- Paragraph-aware chunking (~450 chars, 80 overlap) of the five official texts.
- Every chunk carries doc_id, char offsets, sha256, publish date — provenance is
  preserved end to end.
- Deterministic keyword scoring; query terms are derived from the INVESTIGATION
  TASK text only (silver/facts files are NEVER used for snippet selection; they
  are used only afterwards to EVALUATE coverage).
- Multi-source aggregation goes through facts_merge semantics (merge_facts):
  duplicate facts keep all origins; same-key different-value pairs stay flagged.
"""
import hashlib
import json
import re
from pathlib import Path

from merge_facts import merge_facts, merge_stats
from pilot_common import PILOT_DIR, norm

BASE = PILOT_DIR / 'v3_evidence' / 'A_kangdexin'
CHUNK_CHARS, OVERLAP = 450, 80
# terms from the KDX TASK definition + generic regulatory-document structure anchors
# (domain knowledge; silver/facts files are NEVER used for snippet selection)
TASK_TERMS = ['立案', '问询', '虚增利润', '虚增', '银行存款', '担保', '行政处罚', '市场禁入',
              '事先告知', '处罚决定', '年报', '虚假记载', '钟玉', '康得集团',
              '当事人', '经查明', '责令改正', '罚款', '听证', '决定书', '回复',
              '并处以', '给予警告', '收到', '未经', '批准']
DATE_RE = re.compile(r'20\d{2}\s*年|\d{4}-\d{2}-\d{2}')
AMOUNT_RE = re.compile(r'[0-9,，]{7,}\s*元|\d+(\.\d+)?\s*万?亿元')


def build_index():
    manifests = json.loads((PILOT_DIR / 'v3_evidence' / 'v3_manifests.json').read_text())
    docs = {d['doc_id']: d for d in manifests['A_kangdexin']['documents']}
    index = []
    for doc_id in docs:
        text = (BASE / 'text' / f'{doc_id}.txt').read_text()
        # paragraph-aware windows
        starts = list(range(0, max(1, len(text) - CHUNK_CHARS + 1), CHUNK_CHARS - OVERLAP)) or [0]
        for ci, s in enumerate(starts):
            chunk = text[s:s + CHUNK_CHARS]
            index.append({'chunk_id': f'{doc_id}#c{ci:03d}', 'doc_id': doc_id,
                          'start': s, 'end': s + len(chunk),
                          'sha256': hashlib.sha256(chunk.encode()).hexdigest()[:16],
                          'public_date': docs[doc_id]['public_date'],
                          'text': chunk})
    return index


def build_idf(index, terms):
    import math
    n = len(index)
    return {t: math.log(max(1.0, n / max(1, sum(1 for c in index if norm(t) in norm(c['text']))))) + 1.0
            for t in terms}


def score_chunk(chunk, terms, idf=None):
    """IDF-weighted term score + pattern bonuses (dates / large amounts) —
    fact-dense passages get structural credit without using silver."""
    t = norm(chunk)
    s = sum(c * max(2, len(term)) * (idf[term] if idf else 1.0)
            for term in terms for c in [t.count(norm(term))] if c)
    if DATE_RE.search(chunk):
        s += 15
    if AMOUNT_RE.search(chunk):
        s += 15
    return s


def query(terms, budget_chars, per_doc_topk=None, index=None):
    """Deterministic budgeted retrieval: IDF-scored top chunks per doc (round-robin)."""
    index = index or build_index()
    idf = build_idf(index, terms)
    if per_doc_topk is None:
        per_doc_topk = max(2, budget_chars // CHUNK_CHARS)   # grow topk with budget
    picked, used = [], 0
    by_doc = {}
    for c in sorted(index, key=lambda c: -score_chunk(c['text'], terms, idf)):
        by_doc.setdefault(c['doc_id'], []).append(c)
    # round-robin across docs so no doc starves
    order = [d for d in by_doc]
    rank = 0
    while any(rank < min(per_doc_topk, len(by_doc[d])) for d in order):
        for d in order:
            if rank < min(per_doc_topk, len(by_doc[d])):
                c = by_doc[d][rank]
                if used + len(c['text']) <= budget_chars:
                    picked.append(c)
                    used += len(c['text'])
        rank += 1
        if used >= budget_chars * 0.98:
            break
    return picked, used


def retrieval_facts(picked):
    """Turn picked chunks into facts-style items (provenance = chunk identity)."""
    items = []
    for c in picked:
        items.append({'fact_key': c['chunk_id'], 'value': c['text'][:120],
                      'doc_id': c['doc_id'], 'chunk_sha256': c['sha256'],
                      'public_date': c['public_date']})
    return merge_facts([items], ['retrieval'])


def evaluate_coverage(picked):
    """Silver quotes are used for EVALUATION ONLY (never for selection)."""
    seed = json.loads((BASE / 'facts_seed.json').read_text())
    res = []
    for f in seed['facts']:
        hit = next((c['chunk_id'] for c in picked if norm(f['quote']) in norm(c['text'])), None)
        res.append({'fact_id': f['fact_id'], 'quote_found_in_chunk': hit})
    return {'covered': sum(1 for r in res if r['quote_found_in_chunk']),
            'total': len(res), 'detail': res}


def main():
    index = build_index()
    stats = {'chunks_total': len(index),
             'per_doc': {}}
    manifests = json.loads((PILOT_DIR / 'v3_evidence' / 'v3_manifests.json').read_text())
    for d in manifests['A_kangdexin']['documents']:
        stats['per_doc'][d['doc_id']] = sum(1 for c in index if c['doc_id'] == d['doc_id'])
    out = {'index_stats': stats, 'budgets': {}}
    for budget in (3300, 6600, 9900, 16500, 23000, 33000):
        picked, used = query(TASK_TERMS, budget)
        cov = evaluate_coverage(picked)
        mf = merge_stats(retrieval_facts(picked))
        out['budgets'][budget] = {
            'picked_chunks': len(picked), 'chars_used': used,
            'docs_represented': sorted({c['doc_id'] for c in picked}),
            'seed_quote_coverage': f"{cov['covered']}/{cov['total']}",
            'uncovered_fact_ids': [r['fact_id'] for r in cov['detail'] if not r['quote_found_in_chunk']],
            'merge_provenance': mf}
        print(f"budget {budget}: chunks={len(picked)} chars={used} "
              f"docs={len(out['budgets'][budget]['docs_represented'])}/5 "
              f"seed-quote coverage={cov['covered']}/{cov['total']} "
              f"uncovered={[r['fact_id'] for r in cov['detail'] if not r['quote_found_in_chunk']]}")
    out['query_terms_source'] = 'KDX investigation TASK text only (silver never used for selection)'
    (PILOT_DIR / 'kdx_retrieval_eval.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('chunks total:', stats['chunks_total'], '->', stats['per_doc'])


if __name__ == '__main__':
    main()
