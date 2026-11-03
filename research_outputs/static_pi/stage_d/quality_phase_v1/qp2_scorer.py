"""QP2 scorer: QP1 semantics + amount-aware value comparison (zero calls).

Unchanged from QP1: three-axis scoring (value/localization/support), UNKNOWN
separate, Critical Gate independent of Q, relevance external, ANY-citation
support, reference-span match as diagnostic.

Added (preregistered before any round-2 call): if the strict comparison fails
but BOTH gold and answer parse as amounts (unit-aware), compare after unit
normalization with 0.1% relative tolerance. Strict and tolerant rates are both
reported so the choice stays auditable. Applied uniformly to all arms.
"""
import sys
sys.path.insert(0, '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import terminal_quality as TQ
import qp2_amount as AM
from scorer_qp1 import _norm, value_in_quote


NUMERIC_KINDS = {'number', 'amount', 'ratio', 'percent'}
_UNIT_RE = None


def _gold_effective_yuan(fact):
    """Gold stated as a bare number whose unit lives in its evidence quote."""
    import re
    global _UNIT_RE
    if _UNIT_RE is None:
        _UNIT_RE = re.compile(r'(亿元|万元|亿|万|元|%)')
    if fact.get('value_kind') not in NUMERIC_KINDS:
        return None
    num = TQ._decimal(fact.get('value'))
    if num is None:
        return None
    for e in (fact.get('source_evidence') or []):
        m = _UNIT_RE.search(str(e.get('quote', '')))
        if m:
            u = m.group(1)
            return ('pct', num) if u == '%' else ('yuan', num * AM.UNITS[u])
    return None


def value_equal(claim_value, fact):
    """Strict first; amount-tolerant fallbacks (preregistered, arm-uniform):
    1) both sides parse as amounts → unit-aware comparison;
    2) gold is a bare number whose unit is evidenced in its quote → normalize
       gold by that unit, then compare against the parsed answer."""
    claim = {'value': claim_value, 'value_kind': fact.get('value_kind')}
    if TQ._value_equal(claim, fact):
        return True, False
    if AM.amount_equal(claim_value, fact.get('value')):
        return True, True
    parsed = AM.parse_amount(claim_value)
    eff = _gold_effective_yuan(fact)
    if parsed and eff:
        kind, target = eff
        if kind == 'pct':
            if parsed[1] == '%' and abs(parsed[0] - target) <= AM.Decimal('0.001') * abs(target):
                return True, True
        else:
            if parsed[1] != '%' and abs(AM.to_yuan(parsed[0], parsed[1]) - target) \
                    <= max(AM.Decimal('0.001') * abs(target), AM.Decimal('1')):
                return True, True
    return False, False


def score_task(contract, sink):
    facts = [f for f in contract.get('required_facts', [])
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
    pages = contract.get('source_pages', {})
    answers = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            answers.setdefault(a['fact_id'], a)
    abst = {x.get('item_id'): str(x.get('text', ''))
            for x in (sink or {}).get('abstentions', []) if isinstance(x, dict)} \
        if isinstance(sink, dict) else {}

    rows = []
    tp = value_ok = value_ok_tol = loc_ok = sup_ok = 0
    crit = [f for f in facts if f.get('critical')]
    crit_tp = 0
    for f in facts:
        fid = f.get('fact_id')
        a = answers.get(fid)
        rec = dict(fact_id=fid, critical=bool(f.get('critical')),
                   value_kind=f.get('value_kind'), bucket=f.get('bucket'))
        if not a or a.get('value') in (None, ''):
            rec.update(status='ABSENT')
            rows.append(rec)
            continue
        fact = dict(f)
        v, tolerant = value_equal(a.get('value'), fact)
        cites = [{'doc_id': a.get('doc'), 'page': a.get('page'), 'quote': a.get('quote', '')}]
        refs = [e for e in (fact.get('source_evidence') or []) if isinstance(e, dict)]
        doc = pages.get(str(a.get('doc')))
        page_rec = (doc or {}).get('pages', {}).get(str(a.get('page')))
        loc = bool(page_rec and a.get('quote') and
                   _norm(a.get('quote')) in _norm(page_rec.get('text', '')))
        s = bool(loc and value_in_quote(a.get('value'), a.get('quote', '')))
        ref_match = any(TQ._citation_matches_evidence(c, e, pages)
                        for c in cites for e in refs) if refs else False
        value_ok += v
        value_ok_tol += (v and tolerant)
        loc_ok += (v and loc)
        sup_ok += (v and loc and s)
        status = 'TP' if (v and loc and s) else (
            'VALUE_WRONG' if not v else ('LOC_WRONG' if not loc else 'UNSUPPORTED'))
        rec.update(status=status, localization=loc, support=s,
                   tolerant_value_match=tolerant, reference_span_match=ref_match)
        tp += status == 'TP'
        crit_tp += (status == 'TP') if f.get('critical') else 0
        rows.append(rec)

    unknown_rows = []
    unk_hit = 0
    for u in contract.get('unknown_items', []):
        uid = u.get('item_id')
        correct = bool(abst.get(uid, '').strip())
        unk_hit += correct
        unknown_rows.append(dict(item_id=uid, correct_abstention=correct,
                                 asserted=uid in answers))
    n = len(facts)
    gate = 'PASS' if crit and crit_tp == len(crit) else ('FAIL' if crit else 'NA')
    return dict(
        n_facts=n,
        q=round(tp / n, 6) if n else None,
        fact_value_correct_rate=round(value_ok / n, 6) if n else None,
        tolerant_value_matches=value_ok_tol,
        evidence_localization_rate=round(loc_ok / n, 6) if n else None,
        evidence_support_rate=round(sup_ok / n, 6) if n else None,
        unknown_accuracy=round(unk_hit / len(unknown_rows), 6) if unknown_rows else None,
        critical_gate=gate,
        critical_fact_correct_rate=round(crit_tp / len(crit), 6) if crit else None,
        rows=rows, unknown_rows=unknown_rows,
        relevance='REPORTED SEPARATELY (blind human review; not part of Q)')
