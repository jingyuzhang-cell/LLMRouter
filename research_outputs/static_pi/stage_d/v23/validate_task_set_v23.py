"""Executable acceptance checks for a Phase Pi V2.3 task set (zero cost).

Usage:
  python3 validate_task_set_v23.py <manifest.json> [--min-groups N]

Checks independence, formal-Gold coverage, verbatim evidence spans, and the
preregistered non-substitutability declarations. T1 (the V2 task) is included
as a negative example: it has no substitutability declaration.
"""
import hashlib, json, sys, unicodedata


def n(x):
    return unicodedata.normalize('NFKC', str(x if x is not None else ''))


def norm(x):
    import re
    return re.sub(r'\s+', '', n(x))


def page_text(contract, doc_id, page):
    doc = contract.get('source_pages', {}).get(doc_id)
    if not isinstance(doc, dict):
        return None
    pg = doc.get('pages', {}).get(str(page))
    return pg.get('text') if isinstance(pg, dict) else None


def check_group(g):
    out = []
    c = json.loads(open(g['contract_path'], encoding='utf-8').read())
    facts = c.get('required_facts', [])
    formal = all(f.get('status') == 'GOLD_CONFIRMED' and f.get('gold_source_sha256') for f in facts)
    out.append(('formal_gold', bool(facts) and formal, f'{len(facts)} facts'))
    out.append(('gold_coverage', float(c.get('min_gold_coverage', 0)) == 1.0,
                c.get('min_gold_coverage')))
    # verbatim evidence spans
    bad = []
    for f in facts:
        ev = f.get('source_evidence') or []
        if not ev:
            bad.append(f"{f['fact_id']}:no_evidence")
            continue
        for item in ev:
            text = page_text(c, item.get('doc_id'), item.get('page'))
            if text is None:
                bad.append(f"{f['fact_id']}:no_page"); continue
            s, e = item.get('start'), item.get('end')
            q = item.get('quote', '')
            if not isinstance(s, int) or not isinstance(e, int) or not (0 <= s <= e <= len(text)):
                bad.append(f"{f['fact_id']}:bad_span"); continue
            if norm(text[s:e]) != norm(q):
                bad.append(f"{f['fact_id']}:span_not_verbatim"); continue
            if '…' in q or '...' in q:
                bad.append(f"{f['fact_id']}:elided_quote")
    out.append(('evidence_verbatim', not bad, bad[:5]))
    # declarations
    st = g.get('substitutability') or {}
    out.append(('S0_declared', bool(st.get('S0', {}).get('pass') is True), st.get('S0')))
    out.append(('S1_declared', bool(st.get('S1', {}).get('pass') is True), st.get('S1')))
    out.append(('split_target_declared', bool((g.get('split_target') or {}).get('field')),
                g.get('split_target')))
    out.append(('question_present', bool(c.get('question')), ''))
    # S0/S1 mechanical screening (only when the group declares a split target)
    spec = g.get('split_target') or {}
    if spec.get('entities') and spec.get('affected_slots'):
        outside = s0_scan(c, spec)
        declared = (st.get('S0') or {}).get('non_carrying_occurrences') or []
        req = {(x.get('doc_id'), str(x.get('page')), x.get('start')) for x in declared if isinstance(x, dict)}
        undeclared = [x for x in outside
                      if (x['doc_id'], str(x['page']), x['start']) not in req]
        out.append(('S0_mechanical', not undeclared,
                    dict(outside=len(outside), undeclared=len(undeclared), sample=undeclared[:3])))
        hits = s1_scan(c, spec)
        out.append(('S1_ablation', not hits,
                    dict(hits=len(hits), sample=hits[:2])))
    return c, out


# ── S0 / S1 substitutability screening (zero cost) ──────────────────────────
def _pages(contract):
    out = []
    for doc_id, doc in (contract.get('source_pages') or {}).items():
        for page, rec in (doc.get('pages') or {}).items():
            if isinstance(rec, dict) and isinstance(rec.get('text'), str):
                out.append((doc_id, str(page), rec['text']))
    return out


def _affected_spans(contract, slots):
    spans = []
    for f in contract.get('required_facts', []):
        if f.get('fact_id') in (slots or []):
            for ev in (f.get('source_evidence') or []):
                if isinstance(ev.get('start'), int) and isinstance(ev.get('end'), int):
                    spans.append(dict(doc_id=ev.get('doc_id'), page=str(ev.get('page')),
                                      start=ev['start'], end=ev['end'], fact_id=f['fact_id']))
    return spans


def s0_scan(contract, spec):
    """Entity occurrences outside the affected slots' gold spans."""
    spans = _affected_spans(contract, spec.get('affected_slots'))
    outside = []
    for entity in (spec.get('entities') or []):
        for doc_id, page, text in _pages(contract):
            start = 0
            while True:
                i = text.find(entity, start)
                if i < 0:
                    break
                inside = any(s['doc_id'] == doc_id and s['page'] == page
                             and s['start'] <= i < s['end'] for s in spans)
                if not inside:
                    outside.append(dict(doc_id=doc_id, page=page, start=i, entity=entity,
                                        context=text[max(0, i - 18):i + len(entity) + 18]))
                start = i + len(entity)
    return outside


def _sentence_bounds(text, start, end):
    left = 0
    for ch in ('。', '！', '？', '\n'):
        i = text.rfind(ch, 0, start)
        if i >= 0:
            left = max(left, i + 1)
    right = len(text)
    for ch in ('。', '！', '？', '\n'):
        i = text.find(ch, end)
        if i >= 0:
            right = min(right, i + 1)
    return left, right


def s1_scan(contract, spec, window=120):
    """Ablate the WHOLE SENTENCE containing each affected gold span, then look
    for surviving co-occurrence of an answer entity with a relation keyword.
    Sentence-level ablation is required: a relation can be stated around the
    gold span, not only inside it."""
    pages = _pages(contract)
    spans = _affected_spans(contract, spec.get('affected_slots'))
    hits = []
    for doc_id, page, text in pages:
        masked = list(text)
        for s in spans:
            if s['doc_id'] == doc_id and s['page'] == page:
                lo, hi = _sentence_bounds(text, s['start'], s['end'])
                for k in range(max(0, lo), min(len(masked), hi)):
                    masked[k] = '\u3000'
        masked = ''.join(masked)
        for entity in (spec.get('entities') or []):
            start = 0
            while True:
                i = masked.find(entity, start)
                if i < 0:
                    break
                w = masked[max(0, i - window):i + len(entity) + window]
                for kw in (spec.get('relation_keywords') or []):
                    if kw in w:
                        hits.append(dict(doc_id=doc_id, page=page, start=i, entity=entity,
                                         keyword=kw, context=w[:160]))
                        break
                start = i + len(entity)
    return hits


def main(argv):
    manifest = json.loads(open(argv[1], encoding='utf-8').read())
    min_groups = int(argv[argv.index('--min-groups') + 1]) if '--min-groups' in argv else 12
    groups = manifest.get('groups', [])
    results, contracts = [], []
    print(f'groups: {len(groups)} (min {min_groups})')
    ok_all = len(groups) >= min_groups
    for g in groups:
        c, checks = check_group(g)
        contracts.append((g, c))
        for name, ok, detail in checks:
            results.append(dict(group=g.get('group_id'), check=name, pass_=ok, detail=str(detail)))
            print(f"  {str(g.get('group_id')):8s} {name:24s} {'PASS' if ok else 'FAIL'} {'' if ok else detail}")
            ok_all &= ok
    # cross-group independence
    hashes, questions, entities = {}, {}, {'companies': set(), 'persons': set()}
    dup = []
    for g, c in contracts:
        gid = g.get('group_id')
        for doc_id, doc in c.get('source_pages', {}).items():
            h = doc.get('raw_sha256')
            if h in hashes:
                dup.append(f'{gid}:{doc_id} duplicates {hashes[h]}')
            elif h:
                hashes[h] = f'{gid}:{doc_id}'
        q = norm(c.get('question'))
        if q in questions:
            dup.append(f'{gid}: question duplicates {questions[q]}')
        elif q:
            questions[q] = gid
        for comp in (g.get('entities') or {}).get('companies', []):
            if comp in entities['companies']:
                dup.append(f'{gid}: company reused {comp}')
            entities['companies'].add(comp)
        for person in (g.get('entities') or {}).get('persons', []):
            if person in entities['persons']:
                dup.append(f'{gid}: person reused {person}')
            entities['persons'].add(person)
    results.append(dict(check='cross_group_independence', pass_=not dup, detail=str(dup[:6])))
    print(f"  cross_group_independence     {'PASS' if not dup else 'FAIL'} {'' if not dup else dup[:6]}")
    ok_all &= not dup

    print(f"\n{'PASS' if ok_all else 'BLOCKED'} ({len(groups)} groups, {len(results)} checks)")
    json.dump(dict(batch='PHASE_PI_V23_TASK_SET_VALIDATION', manifest=argv[1],
                   min_groups=min_groups, groups=len(groups), pass_=ok_all,
                   results=results), open(argv[2] if len(argv) > 2 else
                                          '/root/research_outputs/static_pi/stage_d/v23/TASK_SET_VALIDATION.json', 'w'),
              ensure_ascii=False, indent=1)
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
