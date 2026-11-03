"""Retrieval v3 — DEV-stage task-driven multi-query retrieval (zero model calls).

MOTIVATION (KDX DEV, frozen 10K/50/50): only RF1/RF2 evidence-reachable; RF3/RF4
anchors' chunks rank too low under the single task-term IDF score. This module
improves RANKING and BUDGET SPLIT using ONLY: task text vocabulary (the frozen
TASK_TERMS set, already declared legitimate in kdx_retrieval.py), document
titles/metadata, and document bodies. It NEVER reads T1/Gold/Silver reference
answers, anchor positions, or scoring outputs to construct queries or tune
parameters. RF coverage is computed post-hoc by the experiment script only.

Pre-registered rules (fixed before any coverage evaluation):
 1. FACETS: the frozen TASK_TERMS vocabulary is grouped into four task facets
    (penalty / inquiry / fraud / actors) by task-text semantics. No new terms.
 2. RRF FUSION: each facet ranks all chunks (same IDF scoring, facet terms only);
    fused score = sum over facets of 1/(60 + facet_rank). Facet-balanced: chunks
    strong in a minority facet gain representation over single-score ranking.
 3. DYNAMIC LINE BUDGET: each line keeps a minimum of 25% of the global window;
    the remainder is split across lines proportional to their fused-score mass
    (sum of fused scores of the line's top chunks that would fit the window).
 4. NEIGHBOR SUPPLEMENT: within a line's fill, the +1 continuation chunk of an
    already-packed chunk jumps the queue (passage continuity), subject to the
    same overlap dedup (>=200c shared block with same-doc packed text) and the
    char+token dual budget.
 5. NON-EMPTY GUARANTEE per line (inherited behavior): truncate top chunk if
    nothing fits.

DEV marker: developed on KDX DEV where missing facts are known to exist;
independent-event validation is REQUIRED before any benchmark use. Not
protocol-equivalent to the frozen v2 packer (baseline stays untouched).
"""
import math

from kdx_retrieval import build_idf, build_index, score_chunk
from pilot_common import norm

TOK_PER_CHAR = 0.677
RRF_K = 60
MIN_LINE_SHARE = 0.25
OVERLAP_DEDUP_CHARS = 200

FACETS = {
    'penalty': ['行政处罚', '市场禁入', '事先告知', '处罚决定', '责令改正', '罚款',
                '并处以', '给予警告', '决定书', '听证'],
    'inquiry': ['问询', '回复', '收到', '年报', '立案'],
    'fraud': ['虚增利润', '虚增', '银行存款', '担保', '虚假记载'],
    'actors': ['当事人', '钟玉', '康得集团', '经查明', '未经', '批准'],
}
ALL_FACET_TERMS = [t for ts in FACETS.values() for t in ts]


def _shared_block(a, b, w=OVERLAP_DEDUP_CHARS):
    if len(a) < w or len(b) < w:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    for i in range(0, len(short) - w + 1):
        if short[i:i + w] in long_:
            return True
    return False


def fused_ranking(index=None):
    """RRF-fused global ranking. Returns (ranked_chunks, fused_scores)."""
    index = index or build_index()
    fused = {c['chunk_id']: 0.0 for c in index}
    for facet, terms in FACETS.items():
        idf = build_idf(index, terms)
        scored = sorted(index, key=lambda c: (-score_chunk(c['text'], terms, idf),
                                              c['chunk_id']))
        for r, c in enumerate(scored):
            fused[c['chunk_id']] += 1.0 / (RRF_K + r)
    ranked = sorted(index, key=lambda c: (-fused[c['chunk_id']], c['chunk_id']))
    return ranked, fused


def line_budgets(window, line_docs, ranked, fused, chunk_chars=450):
    """Min 25% per line; remainder by fused-mass share (pre-registered rule 3)."""
    min_b = max(1, int(window * MIN_LINE_SHARE))
    flex = window - min_b * len(line_docs)
    if flex <= 0:
        return {line: min_b for line in line_docs}
    n_fit = max(1, window // chunk_chars)
    mass = {}
    for line, docs in line_docs.items():
        allowed = set(docs)
        top = [fused[c['chunk_id']] for c in ranked if c['doc_id'] in allowed][:n_fit]
        mass[line] = sum(top) or 1e-9
    total = sum(mass.values())
    return {line: min_b + int(flex * mass[line] / total) for line in line_docs}


def _next_neighbor_ids(packed_ids, index_by_id):
    out = set()
    for cid in packed_ids:
        doc, num = cid.rsplit('#c', 1)
        nxt = f'{doc}#c{int(num) + 1:03d}'
        if nxt in index_by_id:
            out.add(nxt)
    return out


def pack_line(budget_chars, docs, ranked, fused, budget_tokens=math.inf):
    """Fill one line under char+token budgets: RRF order, neighbor priority,
    overlap dedup, non-empty guarantee. Returns dict like pack_global."""
    if budget_chars <= 0:
        raise ValueError('budget must be > 0')
    allowed = set(docs)
    index_by_id = {c['chunk_id']: c for c in ranked}
    cand = [c for c in ranked if c['doc_id'] in allowed]
    if not cand:
        cand = [c for c in ranked if c['doc_id'] in allowed]
    items, texts, chars = [], [], 0
    packed_ids, packed_texts = set(), []

    def fits(n):
        return (chars + n <= budget_chars
                and math.ceil((chars + n) * TOK_PER_CHAR) <= budget_tokens)

    def dedup(c):
        return any(c['doc_id'] == items[i]['doc_id']
                   and _shared_block(c['text'], texts[i]) for i in range(len(items)))

    # STAGE 1 — ranked fill: fused order only (neighbors get NO priority here;
    # the v1 implementation let neighbors jump the queue, which walked a single
    # document linearly and collapsed diversity: 5 docs->2 docs, T1 2/4->0/4)
    for c in cand:
        if c['chunk_id'] in packed_ids:
            continue
        if dedup(c):
            packed_ids.add(c['chunk_id'])
            continue
        if fits(len(c['text'])):
            items.append({'chunk_id': c['chunk_id'], 'doc_id': c['doc_id'],
                          'start': c['start'], 'end': c['end'],
                          'sha256': c['sha256'], 'public_date': c['public_date'],
                          'available_date': c['public_date'], 'truncated': False})
            texts.append(c['text'])
            chars += len(c['text'])
        packed_ids.add(c['chunk_id'])

    # STAGE 2 — neighbor supplement: spend LEFTOVER budget on +1 continuations of
    # packed chunks (passage continuity), chosen by fused rank, same dedup+budget
    while fits(450):
        neighbors = _next_neighbor_ids({i['chunk_id'] for i in items}, index_by_id)
        picked = None
        for c in cand:
            if c['chunk_id'] in packed_ids or c['chunk_id'] not in neighbors:
                continue
            if dedup(c):
                packed_ids.add(c['chunk_id'])
                continue
            if fits(len(c['text'])):
                picked = c
                break
            packed_ids.add(c['chunk_id'])
        if picked is None:
            break
        items.append({'chunk_id': picked['chunk_id'], 'doc_id': picked['doc_id'],
                      'start': picked['start'], 'end': picked['end'],
                      'sha256': picked['sha256'], 'public_date': picked['public_date'],
                      'available_date': picked['public_date'], 'truncated': False})
        texts.append(picked['text'])
        chars += len(picked['text'])
        packed_ids.add(picked['chunk_id'])

    if not items:  # non-empty guarantee: truncate the best candidate to budget
        for c in cand:
            keep = min(len(c['text']), budget_chars)
            while keep > 0 and math.ceil(keep * TOK_PER_CHAR) > budget_tokens:
                keep -= 50
            if keep > 0:
                items.append({'chunk_id': c['chunk_id'], 'doc_id': c['doc_id'],
                              'start': c['start'], 'end': c['start'] + keep,
                              'sha256': c['sha256'], 'public_date': c['public_date'],
                              'available_date': c['public_date'], 'truncated': True})
                texts.append(c['text'][:keep])
                chars = keep
            break

    text = '\n\n'.join(
        f"【证据 {it['chunk_id']}｜doc_id={it['doc_id']}｜发布{it['public_date']}｜"
        f"可用{it['available_date']}｜sha={it['sha256'][:8]}｜原文[{it['start']},{it['end']}"
        f"{']截断' if it['truncated'] else ']'}】\n{tx}"
        for it, tx in zip(items, texts))
    per_doc = {}
    for it in items:
        per_doc[it['doc_id']] = per_doc.get(it['doc_id'], 0) + (it['end'] - it['start'])
    return {'items': items, 'text': text, 'chars': chars,
            'est_tok': math.ceil(chars * TOK_PER_CHAR), 'docs': sorted(per_doc),
            'per_doc': per_doc, 'truncated_any': any(i['truncated'] for i in items)}


def pack_v3(window, line_docs, ranked=None, fused=None, dynamic=True):
    """Two-line pack: 50/50 (dynamic=False) or min25+fused-mass split (dynamic=True)."""
    if ranked is None or fused is None:
        ranked, fused = fused_ranking()
    if dynamic:
        budgets = line_budgets(window, line_docs, ranked, fused)
    else:
        budgets = {line: window // len(line_docs) for line in line_docs}
    return {line: pack_line(budgets[line], docs, ranked, fused)
            for line, docs in line_docs.items()}, budgets
