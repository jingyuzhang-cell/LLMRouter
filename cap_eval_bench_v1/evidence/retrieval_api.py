"""Sanctioned evidence access API for ALL systems under evaluation (frozen).

Deterministic, budgeted, provenance-preserving segmented retrieval over the frozen
evidence store. Executors may see: task questions, this API, and its outputs.
They may NOT read evidence/texts directly, tasks_private*, or scoring/silver*.

Every call is appended to evidence/retrieval_log.jsonl for full cost accounting
(chars injected are charged to the calling run in E-cost).
"""
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from bench_common import norm  # noqa: E402

CHUNK_CHARS, OVERLAP = 450, 80
DATE_RE = re.compile(r'20\d{2}\s*年|\d{4}-\d{2}-\d{2}')
AMOUNT_RE = re.compile(r'[0-9,，]{7,}\s*元|\d+(\.\d+)?\s*万?亿元|1[:：][\d.]{4,}')
STRUCTURE_TERMS = ['立案', '问询', '虚增', '银行存款', '担保', '行政处罚', '市场禁入', '事先告知',
                   '处罚决定', '年报', '虚假记载', '当事人', '经查明', '责令改正', '罚款', '听证',
                   '决定书', '回复', '并处以', '给予警告', '收到', '未经', '批准', '换股', '吸收合并',
                   '核准', '终止上市', '上市日期', '差错更正', '总额法', '净额法', '摘牌', '风险警示',
                   '停牌', '涨跌幅', '约谈', '异常波动']

_INDEX = None


def docs():
    global _INDEX
    if _INDEX is None:
        _INDEX = json.loads((BENCH / 'evidence' / 'index.json').read_text())
    return {d['doc_id']: d for d in _INDEX}


def build_chunk_index(doc_ids=None):
    idx = []
    for doc_id, meta in docs().items():
        if doc_ids and doc_id not in doc_ids:
            continue
        text = (BENCH / 'evidence' / 'texts' / f'{doc_id}.txt').read_text()
        starts = list(range(0, max(1, len(text) - CHUNK_CHARS + 1), CHUNK_CHARS - OVERLAP)) or [0]
        for ci, s in enumerate(starts):
            chunk = text[s:s + CHUNK_CHARS]
            idx.append({'chunk_id': f'{doc_id}#c{ci:03d}', 'doc_id': doc_id,
                        'start': s, 'end': s + len(chunk),
                        'sha256_16': hashlib.sha256(chunk.encode()).hexdigest()[:16],
                        'public_date': meta['public_date'], 'text': chunk})
    return idx


def _idf(index, terms):
    n = len(index)
    return {t: math.log(max(1.0, n / max(1, sum(1 for c in index if norm(t) in norm(c['text']))))) + 1.0
            for t in terms}


def _score(chunk, terms, idf):
    t = norm(chunk)
    s = sum(c * max(2, len(term)) * idf[term]
            for term in terms for c in [t.count(norm(term))] if c)
    if DATE_RE.search(chunk):
        s += 15
    if AMOUNT_RE.search(chunk):
        s += 15
    return s


def retrieve(task_id, run_id, query_terms, budget_chars, scope_doc_ids=None, per_doc_topk=None):
    """Deterministic budgeted retrieval. Returns chunks + provenance; logs the call.

    task_id/run_id: for accounting only (no effect on results — fairness).
    scope_doc_ids: restrict to a task-scoped doc set (default: that task's frozen doc set).
    """
    tasks = {json.loads(l)['task_id']: json.loads(l)
             for l in (BENCH / 'tasks' / 'tasks_frozen.jsonl').read_text().splitlines() if l.strip()}
    scope = list(scope_doc_ids or tasks[task_id]['evidence_doc_ids'])
    index = build_chunk_index(scope)
    idf = _idf(index, set(list(query_terms) + STRUCTURE_TERMS))
    per_doc_topk = per_doc_topk or max(2, budget_chars // CHUNK_CHARS)
    by_doc = {}
    for c in sorted(index, key=lambda c: -_score(c['text'], set(query_terms) | set(STRUCTURE_TERMS), idf)):
        by_doc.setdefault(c['doc_id'], []).append(c)
    picked, used, rank = [], 0, 0
    order = [d for d in tasks[task_id]['evidence_doc_ids'] if d in by_doc]
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
    rec = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'run_id': run_id, 'task_id': task_id,
           'query_terms': list(query_terms), 'budget_chars': budget_chars,
           'scope_docs': scope, 'returned_chunks': len(picked), 'chars_injected': used,
           'chunk_ids': [c['chunk_id'] for c in picked]}
    with open(BENCH / 'evidence' / 'retrieval_log.jsonl', 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return picked, used


def retrieval_frontier_report():
    """Offline audit: for every task, seed-quote coverage of its silver facts at
    several per-node budgets (evaluation-side only; never used for snippet selection)."""
    out = {}
    for line in (BENCH / 'tasks' / 'tasks_frozen.jsonl').read_text().splitlines():
        t = json.loads(line)
        priv = json.loads((BENCH / 'scoring' / 'silver' / f"{t['task_id']}.silver.json").read_text())
        idx = build_chunk_index(t['evidence_doc_ids'])
        rows = {}
        for budget in (3300, 6600, 13200):
            picked, used = retrieve(t['task_id'], 'EVAL-AUDIT', ['调查'], budget)
            covered = sum(1 for f in priv['silver']
                          if any(norm(f['quote']) in norm(c['text']) for c in picked))
            rows[budget] = {'chars': used, 'coverage': f'{covered}/{len(priv["silver"])}'}
        out[t['task_id']] = {'n_silver': len(priv['silver']), 'frontier': rows,
                             'note': 'retrieval side never uses silver for selection'}
    (BENCH / 'evidence' / 'retrieval_coverage.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    print(json.dumps(retrieval_frontier_report(), ensure_ascii=False, indent=1))
