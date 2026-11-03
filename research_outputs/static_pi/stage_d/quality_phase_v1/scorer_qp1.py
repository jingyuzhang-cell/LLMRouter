"""QP1 task-adapted terminal scorer (NEW version; does not modify any frozen file).

Differences from the frozen R4 scorer (kept intact):
  - supports the task's actual Gold count N (no fixed 13 slots);
  - scores each fact on three separate axes: value, evidence localization, evidence support;
  - UNKNOWN items are evaluated separately (correct abstention vs asserted);
  - Critical Gate is reported as PASS/FAIL and is NOT averaged into Q;
  - relevance is NOT part of Q (handled by blind human review, reported separately).

Value/date/number comparison and citation-support logic are imported read-only from
the frozen terminal_quality v1.2.3 so the semantics do not drift.
"""
import sys
sys.path.insert(0, '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
import terminal_quality as TQ


def _norm(x):
    import re, unicodedata
    t = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', t)


def value_in_quote(value, quote):
    """Deterministic grounding: the fact's value is present in the cited quote."""
    q = _norm(quote)
    if not q:
        return False
    v = _norm(value)
    # dates: compare YYYYMMDD forms
    import re as _r
    dv = _r.match(r'^(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})', v)
    dq = _r.search(r'(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})', q)
    if dv and dq:
        return tuple(int(x) for x in dv.groups()) == tuple(int(x) for x in dq.groups())
    nums = _r.findall(r'\d[\d,，.]*', v)
    if nums:
        return any(n.replace(',', '').replace('，', '') in q.replace(',', '').replace('，', '') for n in nums)
    core = v.split('_')[-1][:12]
    return bool(core and core in q)


def score_task(contract, sink):
    """Return per-fact statuses + the five operator-required metrics."""
    facts = [f for f in contract.get('required_facts', [])
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
    unknowns = {u.get('item_id') for u in contract.get('unknown_items', [])
                if isinstance(u, dict) and u.get('item_id') not in (None, '')}
    pages = contract.get('source_pages', {})
    answers = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            answers.setdefault(a['fact_id'], a)
    abst = {x.get('item_id'): str(x.get('text', ''))
            for x in (sink or {}).get('abstentions', []) if isinstance(x, dict)} \
        if isinstance(sink, dict) else {}

    rows = []
    tp = value_ok = loc_ok = sup_ok = 0
    crit = [f for f in facts if f.get('critical')]
    crit_tp = 0
    for f in facts:
        fid = f.get('fact_id')
        a = answers.get(fid)
        rec = dict(fact_id=fid, critical=bool(f.get('critical')),
                   value_kind=f.get('value_kind'), bucket=f.get('bucket'))
        if not a or a.get('value') in (None, ''):
            rec.update(status='ABSENT'); rows.append(rec); continue
        fact = dict(f)
        claim = {'value': a.get('value'), 'value_kind': f.get('value_kind')}
        v = bool(TQ._value_equal(claim, fact))
        cites = [{'doc_id': a.get('doc'), 'page': a.get('page'), 'quote': a.get('quote', '')}]
        refs = [e for e in (fact.get('source_evidence') or []) if isinstance(e, dict)]
        doc = pages.get(str(a.get('doc')))
        page_rec = (doc or {}).get('pages', {}).get(str(a.get('page')))
        loc = bool(page_rec and a.get('quote') and _norm(a.get('quote')) and
                   _norm(a.get('quote')) in _norm(page_rec.get('text', '')))
        # QP1 support = the cited quote is verbatim in the page AND grounds the value.
        # Matching the exact gold reference span is a SEPARATE diagnostic, not Q.
        s = bool(loc and value_in_quote(a.get('value'), a.get('quote', '')))
        ref_match = any(TQ._citation_matches_evidence(c, e, pages) for c in cites for e in refs) if refs else False
        full_cov = all(any(TQ._citation_matches_evidence(c, e, pages) for c in cites) for e in refs) if refs else False
        value_ok += v
        loc_ok += (v and loc)
        sup_ok += (v and loc and s)
        status = 'TP' if (v and loc and s) else (
            'VALUE_WRONG' if not v else ('LOC_WRONG' if not loc else 'UNSUPPORTED'))
        rec.update(status=status, localization=loc, support=s, reference_span_match=ref_match,
                   derivation_full_coverage=full_cov)
        tp += status == 'TP'
        crit_tp += (status == 'TP') if f.get('critical') else 0
        rows.append(rec)

    unknown_rows = []
    unk_hit = 0
    for u in contract.get('unknown_items', []):
        uid = u.get('item_id')
        text = abst.get(uid, '')
        correct = bool(text.strip())
        unk_hit += correct
        unknown_rows.append(dict(item_id=uid, correct_abstention=correct,
                                 asserted=uid in answers))
    n = len(facts)
    gate = 'PASS' if crit and crit_tp == len(crit) else ('FAIL' if crit else 'NA')
    return dict(
        n_facts=n,
        q=round(tp / n, 6) if n else None,
        fact_value_correct_rate=round(value_ok / n, 6) if n else None,
        evidence_localization_rate=round(loc_ok / n, 6) if n else None,
        evidence_support_rate=round(sup_ok / n, 6) if n else None,
        reference_span_match_rate=round(sum(1 for r in rows if r.get('reference_span_match')) / n, 6) if n else None,
        unknown_accuracy=round(unk_hit / len(unknown_rows), 6) if unknown_rows else None,
        critical_gate=gate,
        critical_fact_correct_rate=round(crit_tp / len(crit), 6) if crit else None,
        rows=rows, unknown_rows=unknown_rows,
        relevance='REPORTED SEPARATELY (blind human review; not part of Q)')
