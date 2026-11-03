"""Phase V2.3-A silver builder: turn hand-authored fact lists into contract-
shaped Silver files with verbatim evidence spans.

The author writes facts as (doc_id, page_hint, quote). This tool:
  1. splits each pdftotext -layout output into pages on form feeds;
  2. locates each quote (normalized-whitespace containment, same as the frozen
     scorer's _norm_text) and computes exact (start, end);
  3. validates the span is verbatim (round-trip check);
  4. emits a TASK_CONTRACT_<EV>_SILVER.json in stage_a/T1 shape (source_pages
     with per-page text + sha256, required_facts with source_evidence spans).

Silver is machine/assistant-derived. Formal Gold promotion stays a separate,
human-adjudicated step and is NOT performed here.
"""
import hashlib, json, os, re, sys, unicodedata


def norm(x):
    x = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', x)


def sha_text(t):
    return hashlib.sha256(t.encode('utf-8')).hexdigest()


def load_pages(text_file):
    raw = open(text_file, encoding='utf-8').read()
    pages = raw.split('\f')
    return {str(i + 1): t for i, t in enumerate(pages) if t.strip() != ''}


def locate(pages, doc_id, quote):
    q = norm(quote)
    hits = []
    for pno, text in pages.items():
        n = norm(text)
        # walk raw text, tracking normalized offset -> raw offset
        i_raw, norm_buf, start_raw = 0, '', 0
        positions = []  # norm_index -> raw_index map built lazily per page
        # build map once
        m = {}
        ni = 0
        for ri, ch in enumerate(text):
            c = unicodedata.normalize('NFKC', ch)
            if c.strip() == '':
                continue
            for k, cc in enumerate(c):
                m[ni + k] = ri
            ni += len(c)
        ntext = norm(text)
        idx = ntext.find(q)
        while idx >= 0:
            # map norm idx back to raw via m; end = map of idx+len(q)-1 plus len of that raw char
            s_raw = m.get(idx)
            e_norm = idx + len(q) - 1
            e_raw = m.get(e_norm)
            if s_raw is None or e_raw is None:
                idx = ntext.find(q, idx + 1)
                continue
            # extend e_raw over the raw char
            e_raw_end = e_raw + 1
            while e_raw_end < len(text) and norm(text[e_raw_end]) == '':
                e_raw_end += 1
            # include trailing part of a multi-char raw sequence
            while e_raw_end < len(text) and unicodedata.normalize('NFKC', text[e_raw_end]).strip() != '' and (m.get(e_norm + 1) == e_raw_end):
                break
            hits.append((pno, s_raw, e_raw_end))
            idx = ntext.find(q, idx + 1)
    return hits


def build(event, docs, facts, unknowns, meta, out_dir):
    """docs: {doc_id: text_file}; facts: list of dicts with
    fact_id, subject, predicate, value, value_kind, weight, critical,
    evidence_required, quote, doc_id; unknowns: list of {item_id, question}."""
    source_pages = {}
    doc_pages = {}
    for did, tf in docs.items():
        pages = load_pages(tf)
        doc_pages[did] = pages
        raw = open(tf, encoding='utf-8').read()
        source_pages[did] = dict(pages={p: dict(text=t, page_sha256=sha_text(t))
                                        for p, t in pages.items()},
                                 raw_sha256=sha_text(raw))
    out_facts = []
    problems = []
    for f in facts:
        pages = doc_pages.get(f['doc_id'])
        if pages is None:
            problems.append(f"{f['fact_id']}:no_doc"); continue
        hits = locate(pages, f['doc_id'], f['quote'])
        if not hits:
            problems.append(f"{f['fact_id']}:quote_not_found"); continue
        pno, s, e = hits[0]
        text = pages[pno]
        if norm(text[s:e]) != norm(f['quote']):
            problems.append(f"{f['fact_id']}:span_roundtrip_fail"); continue
        out_facts.append(dict(
            fact_id=f['fact_id'], status='SILVER_CANDIDATE',
            gold_provenance='assistant_derived_pending_adjudication',
            weight=f.get('weight', 1.0), critical=f.get('critical', False),
            evidence_required=f.get('evidence_required', True),
            value_kind=f.get('value_kind', 'text'),
            subject=f.get('subject', ''), predicate=f.get('predicate', ''),
            value=f['value'],
            source_evidence=[dict(doc_id=f['doc_id'], page=int(pno),
                                  quote=f['quote'], start=s, end=e,
                                  page_sha256=sha_text(text), raw_sha256=source_pages[f['doc_id']]['raw_sha256'])],
            bucket=f.get('bucket', ''), description=f.get('description', '')))
    contract = dict(
        task_id=meta['task_id'], reference_type='silver_v23a',
        question=meta['question'], cutoff=meta.get('cutoff', ''),
        min_gold_coverage=1.0, dimension_weights={},
        required_facts=out_facts,
        unknown_items=[dict(item_id=u['item_id'], question=u.get('question', '')) for u in unknowns],
        conflict_groups=[], source_pages=source_pages,
        provenance=dict(nature=meta.get('nature', ''), model_calls=0,
                        built_by='ZCode Phase V2.3-A silver builder',
                        target_field=meta.get('target_field'),
                        target_slots=meta.get('target_slots', []),
                        e_node_of_target=meta.get('e_node_of_target', '')),
    )
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"TASK_CONTRACT_{event}_SILVER.json")
    json.dump(contract, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return path, out_facts, problems


if __name__ == '__main__':
    print('silver builder module — import build() to use')
