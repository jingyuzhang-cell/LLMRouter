"""Global evidence packer v2 — fixes the 600-char zero-retrieval bug (2026-10-14).

BUG (v1): the GLOBAL char budget was split across the 5 evidence docs by
length-proportional allocation BEFORE chunk selection. At a 600c global budget
each doc's share (~120c) was smaller than the 450c chunk size, so ZERO chunks
could enter the context (measured: 0c retrieved, all four arms T1-starved).

v2 RULES (pre-registered; independent of model outputs AND of any gold/silver
answer file — selection uses only the frozen investigation-task terms):
 1. Rank all eligible chunks by the frozen task-term IDF score
    (kdx_retrieval.score_chunk), tie-broken by chunk_id. Deterministic.
 2. Greedily fill ONE global budget with WHOLE chunks. Overlap dedup: skip a
    chunk if its text overlaps >=200c with an already-packed chunk of the same
    doc (chunks are built with 80c overlap; this prevents double-paying).
 3. NON-EMPTY GUARANTEE: if budget > 0 and no whole chunk fits, pack the
    top-ranked chunk TRUNCATED to the remaining budget (flagged truncated;
    offsets of the retained span preserved).
 4. DUAL BUDGET: total chars <= budget_chars AND est tokens <= budget_tokens
    (est_tokens = ceil(chars * 0.677), the measured KDX chars->token ratio:
    900c->609 tok, 18450c->12499 tok). Both caps enforced simultaneously.
 5. PROVENANCE: every packed item keeps doc_id, chunk_id, start/end char
    offsets, sha256, public_date (= evidence available date), truncated flag.

This module performs ZERO file I/O and has no dependency on any gold/silver
answer file (answer-directed selection is forbidden — evaluation leakage).
"""
import math

from kdx_retrieval import TASK_TERMS, build_idf, build_index, score_chunk

TOK_PER_CHAR = 0.677  # measured KDX ratio (see module docstring)
OVERLAP_DEDUP_CHARS = 200


def token_est(chars):
    return math.ceil(chars * TOK_PER_CHAR)


def _overlap_len(a, b):
    # longest common prefix-style overlap is not enough; use simple containment check
    # via rolling window on the shorter string (chunks are short; O(n*m) acceptable)
    if len(a) > len(b):
        a, b = b, a
    for i in range(0, len(b) - len(a) + 1):
        if b[i:i + len(a)] == a:
            return len(a)
    # fallback: shared suffix/prefix heuristic is avoided; return 0
    return 0


def _text_overlap(a, b):
    """True if a and b share any >=200c contiguous block (approximated by
    checking whether any 200c window of the shorter text occurs in the longer)."""
    w = OVERLAP_DEDUP_CHARS
    if len(a) < w or len(b) < w:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    for i in range(0, len(short) - w + 1):
        if short[i:i + w] in long_:
            return True
    return False


def rank_chunks(index, terms=TASK_TERMS):
    """Deterministic global ranking: (-score, chunk_id). No answer knowledge."""
    idf = build_idf(index, terms)
    return sorted(index, key=lambda c: (-score_chunk(c['text'], terms, idf), c['chunk_id']))


def pack_global(budget_chars, budget_tokens=None, doc_ids=None, index=None,
                ranked=None):
    """Pack evidence chunks under a GLOBAL budget.

    Returns a dict with: items (provenance list), text (packed context),
    chars, est_tok, docs (sorted doc_ids), per_doc {doc_id: chars}, truncated
    (any item truncated). Raises ValueError on non-positive budget.
    """
    if budget_chars <= 0:
        raise ValueError('budget_chars must be > 0')
    if budget_tokens is None:
        budget_tokens = math.inf
    if ranked is None:
        ranked = rank_chunks(index or build_index())
    if doc_ids is not None:
        allowed = set(doc_ids)
        ranked = [c for c in ranked if c['doc_id'] in allowed]

    items, texts, chars = [], [], 0
    packed_texts_by_doc = {}

    def est_ok(extra_chars):
        return chars + extra_chars <= budget_chars and token_est(chars + extra_chars) <= budget_tokens

    for c in ranked:
        t = c['text']
        if any(_text_overlap(t, p) for p in packed_texts_by_doc.get(c['doc_id'], [])):
            continue  # overlap dedup: >=200c already packed from this doc
        if est_ok(len(t)):
            items.append(_item(c, start=c['start'], end=c['end'], truncated=False))
            texts.append(t)
            chars += len(t)
            packed_texts_by_doc.setdefault(c['doc_id'], []).append(t)

    if not items:
        # NON-EMPTY GUARANTEE: truncate the top-ranked eligible chunk to budget
        for c in ranked:
            t = c['text']
            keep = min(len(t), int(budget_chars))
            # respect the token cap too (shrink until est fits)
            while keep > 0 and token_est(keep) > budget_tokens:
                keep = int(keep * budget_tokens / token_est(keep)) - 1
            if keep > 0:
                items.append(_item(c, start=c['start'], end=c['start'] + keep, truncated=True))
                texts.append(t[:keep])
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
    return {'items': items, 'text': text, 'chars': chars, 'est_tok': token_est(chars),
            'docs': sorted(per_doc), 'per_doc': per_doc,
            'truncated_any': any(it['truncated'] for it in items)}


def _item(c, start, end, truncated):
    return {'chunk_id': c['chunk_id'], 'doc_id': c['doc_id'], 'start': start, 'end': end,
            'sha256': c['sha256'], 'public_date': c['public_date'],
            'available_date': c['public_date'], 'truncated': truncated}


def pack_lines(budget_chars, line_docs, budget_tokens=None, index=None, ranked=None):
    """Split a global budget across pre-registered evidence LINES (50/50),
    each line packed independently under budget_chars//2 with the same global
    ranking restricted to the line's docs. Non-empty guarantee per line.
    line_docs: {'line_A': [doc_ids], 'line_B': [doc_ids]}."""
    half = max(1, budget_chars // 2)
    return {line: pack_global(half, budget_tokens=budget_tokens, doc_ids=docs,
                              index=index, ranked=ranked)
            for line, docs in line_docs.items()}
