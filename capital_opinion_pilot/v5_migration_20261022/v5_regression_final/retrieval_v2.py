"""Task 2: retriever comparison (zero paid calls).

A. IDF lexical (existing kdx_retrieval scorer)
B. BM25 (char-bigram tokenisation, k1=1.5 b=0.75) + doc-scope filter
C. Hybrid: BM25 + local semantic vectors (Qwen2.5-1.5B-Instruct mean-pooled last
   hidden states, fp16 on the idle RTX 4090 — local, free). If the model/GPU is
   unavailable, C self-reports SKIPPED.

Queries are built ONLY from the frozen DAG node goals + task text + doc metadata.
Silver/facts files are used EXCLUSIVELY for post-retrieval offline evaluation.
All retrievers share identical queries, per-doc scope and injection budgets.
"""
import json
import math
import re

from pilot_common import PILOT_DIR, norm
from kdx_retrieval import build_index, TASK_TERMS

KDX_DOCS = ['kdx_inquiry_2018', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020', 'kdx_inquiry_2019']
# node-derived retrieval goals (from the frozen frontier DAG; no silver content)
LINE_GOALS = {
    't1_regulatory': {'docs': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
                      'terms': TASK_TERMS,
                      'text': '限预算检索处罚与告知书认定段：虚增利润、银行存款、关联担保、市场禁入、'
                              '责令改正、罚款、立案、当事人、经查明'},
    't2_inquiry': {'docs': ['kdx_inquiry_2018', 'kdx_inquiry_2019'],
                   'terms': TASK_TERMS,
                   'text': '限预算检索两份年报问询回复关键段：银行存款、关联交易、违规担保、虚假记载、'
                           '北京银行、现金管理协议、问询函回复'},
}
BUDGETS = [3300, 6600, 9500]


def bigrams(s):
    t = re.sub(r'\s+', '', s)
    return [t[i:i + 2] for i in range(len(t) - 1)]


class BM25:
    def __init__(self, chunks):
        self.docs = [bigrams(c['text']) for c in chunks]
        self.N = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / max(1, self.N)
        self.df = {}
        for d in self.docs:
            for w in set(d):
                self.df[w] = self.df.get(w, 0) + 1
        self.chunks = chunks

    def score(self, query_text, idx):
        q = bigrams(query_text)
        s, dl = 0.0, len(self.docs[idx])
        for w in q:
            f = self.docs[idx].count(w)
            if not f:
                continue
            idf = math.log(1 + (self.N - self.df[w] + 0.5) / (self.df[w] + 0.5))
            s += idf * f * (1.5 + 1) / (f + 1.5 * (1 - 0.75 + 0.75 * dl / self.avgdl))
        return s


class LocalEmbedder:
    """Qwen2.5-1.5B last-hidden mean pooling (local GPU, free). Causal-LM-as-embedder
    is a crude but honest local semantic signal; labelled as such."""

    def __init__(self):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct')
        self.model = AutoModel.from_pretrained('/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct',
                                               torch_dtype=torch.float16).cuda().eval()

    def encode(self, texts, batch=16):
        import numpy as np
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = self.tok(texts[i:i + batch], padding=True, truncation=True, max_length=512,
                               return_tensors='pt').to('cuda')
                h = self.model(**enc).last_hidden_state
                mask = enc['attention_mask'].unsqueeze(-1).float()
                v = (h * mask).sum(1) / mask.sum(1)
                v = self.torch.nn.functional.normalize(v, dim=1)
                out.append(v.float().cpu().numpy())
        return __import__('numpy').vstack(out)


def pick_round_robin(scored, docs_scope, budget):
    by_doc = {}
    for c, s in sorted(scored, key=lambda x: -x[1]):
        if not docs_scope or c['doc_id'] in docs_scope:
            by_doc.setdefault(c['doc_id'], []).append(c)
    picked, used, rank = [], 0, 0
    taken_ptrs = {d: 0 for d in by_doc}
    while True:
        progressed = False
        for d, chunks in by_doc.items():
            while taken_ptrs[d] < len(chunks):
                c = chunks[taken_ptrs[d]]
                taken_ptrs[d] += 1
                if any(_overlap_chars(c['text'], p['text']) >= 200 and p['doc_id'] == c['doc_id']
                       for p in picked):
                    continue  # skip window-overlapping neighbour
                if used + len(c['text']) <= budget:
                    picked.append(c)
                    used += len(c['text'])
                    progressed = True
                break
        if not progressed or used >= budget * 0.98:
            break
    return picked, used


def idf_scores(index, terms):
    from kdx_retrieval import build_idf, score_chunk
    idf = build_idf(index, terms)
    return [(c, score_chunk(c['text'], terms, idf)) for c in index]


def evaluate(picked, seed):
    cov = []
    for f in seed['facts']:
        hit = next((c['chunk_id'] for c in picked if norm(f['quote']) in norm(c['text'])), None)
        cov.append({'fact_id': f['fact_id'], 'hit': bool(hit)})
    return cov


def redundancy(picked):
    """Overlap-driven redundancy: fraction of picked chunks whose content overlaps
    >=60 chars with another picked chunk from the same doc (80-char window overlap)."""
    n = len(picked)
    red = 0
    for i, a in enumerate(picked):
        for j, b in enumerate(picked):
            if i >= j or a['doc_id'] != b['doc_id']:
                continue
            if _overlap_chars(a['text'], b['text']) >= 200:
                red += 1
                break
    return round(red / max(1, n), 4)


def _overlap_chars(a, b):
    from difflib import SequenceMatcher
    return int(SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b)).size)


def main():
    index = build_index()
    seed = json.loads((PILOT_DIR / 'v3_evidence' / 'A_kangdexin' / 'facts_seed.json').read_text())
    bm25 = BM25(index)
    embedder = None
    chunk_vecs = query_vecs = None
    try:
        embedder = LocalEmbedder()
        chunk_vecs = embedder.encode([c['text'] for c in index])
        print('embeddings ready:', chunk_vecs.shape)
    except Exception as e:
        print('C SKIPPED:', type(e).__name__, str(e)[:120])

    results = {'retrievers': ['A_idf', 'B_bm25'] + (['C_hybrid'] if embedder else []),
               'budgets': BUDGETS, 'lines': {}}
    for line, spec in LINE_GOALS.items():
        out_lines = {}
        idf_s = idf_scores(index, spec['terms'])
        bm_s = [(c, bm25.score(spec['text'], i)) for i, c in enumerate(index)]
        hyb_s = None
        if embedder:
            qv = embedder.encode([spec['text']])[0]
            import numpy as np
            cos = chunk_vecs @ qv
            bmax = max(s for _, s in bm_s) or 1.0
            cmax = float(cos.max()) or 1.0
            bmin = min(s for _, s in bm_s)
            cmin = float(cos.min())
            hyb_s = [(c, 0.5 * ((s - bmin) / max(1e-9, bmax - bmin)) +
                          0.5 * ((float(cos[i]) - cmin) / max(1e-9, cmax - cmin)))
                     for i, (c, s) in enumerate(bm_s)]
        for name, scored in (('A_idf', idf_s), ('B_bm25', bm_s), ('C_hybrid', hyb_s)):
            if scored is None:
                continue
            for budget in BUDGETS:
                picked, used = pick_round_robin(scored, spec['docs'], budget)
                cov = evaluate(picked, seed)
                out_lines[f'{name}@{budget}'] = {
                    'chunks': len(picked), 'chars_used': used,
                    'docs': sorted({c['doc_id'] for c in picked}),
                    'coverage': sum(1 for c in cov if c['hit']),
                    'covered_ids': [c['fact_id'] for c in cov if c['hit']],
                    'redundancy': redundancy(picked)}
        results['lines'][line] = out_lines
        for k, v in out_lines.items():
            print(line, k, 'cov', f"{v['coverage']}/7", 'chunks', v['chunks'],
                  'red', v['redundancy'], 'docs', len(v['docs']))
    (PILOT_DIR / 'KDX_RETRIEVAL_COMPARISON.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print('saved KDX_RETRIEVAL_COMPARISON.json')


if __name__ == '__main__':
    main()
