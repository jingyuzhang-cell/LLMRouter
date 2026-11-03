"""QP3 analysis primitives (zero calls): structure-aware stage normalizers,
decorated-amount parsing, and evidence-based fact matching across stages.

These are ANALYSIS-side diagnostics; they change no scorer, no gold, no frozen
file. The decorated-amount parser is deliberately more permissive than the QP2
candidate parser because round-1 prompts had no amount contract, so models
emitted decorated values ("亏损：12,500.00 万元（即 -12,500.00 万元）"). Whether
such normalization recovery should count as a mechanism gain is a scientific
claim the report argues explicitly; here we only measure it.
"""
import re, sys, unicodedata
from decimal import Decimal
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import scorer_qp1 as Q1
import qp2_amount as AM
import qp2_scorer as Q2

NEG_WORDS = ('亏损', '负', '−', '-', '减少')
NUM_UNIT = re.compile(r'(\d[\d,，.]*)\s*(亿元|万元|亿|万|元|%)')
NUM_BARE = re.compile(r'(\d[\d,，.]*)')


def _norm(x):
    return Q1._norm(x)


def deco_amount(text):
    """(signed Decimal, unit) from a decorated string; None if no number found.
    Unit '' means a bare number. Sign negative on a preceding loss marker."""
    t = unicodedata.normalize('NFKC', str(text or ''))
    m = NUM_UNIT.search(t)
    if m:
        num, unit = m.group(1), m.group(2)
    else:
        m = NUM_BARE.search(t)
        if not m:
            return None
        num, unit = m.group(1), ''
    num = num.replace(',', '').replace('，', '')
    try:
        v = Decimal(num)
    except Exception:
        return None
    prefix = t[:m.start()]
    if any(w in prefix for w in NEG_WORDS):
        v = -v
    return v, unit


def value_equal_anyway(answer_value, fact):
    """strict → qp2 tolerant → decorated-amount. Returns (ok, level)."""
    if Q1.TQ._value_equal({'value': answer_value, 'value_kind': fact.get('value_kind')}, dict(fact)):
        return True, 'strict'
    ok, _ = Q2.value_equal(answer_value, fact)
    if ok:
        return True, 'tolerant'
    a = deco_amount(answer_value)
    if a:
        gold = fact.get('value')
        g_direct = deco_amount(gold)
        if g_direct and AM.amount_equal(str(a[0]) + a[1], str(g_direct[0]) + g_direct[1]):
            return True, 'decorated'
        eff = Q2._gold_effective_yuan(fact)
        if eff and eff[0] == 'yuan' and a[1] != '%':
            ya = AM.to_yuan(a[0], a[1])
            if abs(ya - eff[1]) <= max(Decimal('0.001') * abs(eff[1]), Decimal('1')):
                return True, 'decorated'
        if eff and eff[0] == 'pct' and a[1] in ('%', ''):
            if abs(a[0] - eff[1]) <= Decimal('0.001') * abs(eff[1]):
                return True, 'decorated'
        if eff and eff[0] == 'yuan' and a[1] == '':
            if abs(a[0] - eff[1]) <= max(Decimal('0.001') * abs(eff[1]), Decimal('1')):
                return True, 'decorated'
    # text-kind formatting: the gold statement appears VERBATIM inside the
    # (decorated) answer. The reverse (answer shorter than gold) is
    # under-specification, NOT formatting, and stays an error.
    if isinstance(answer_value, str) and isinstance(fact.get('value'), str):
        g, av = _norm(fact['value']), _norm(answer_value)
        if g and g in av:
            return True, 'text_contained'
    return False, None


def normalize_stage(obj):
    """Flatten any round-1 stage output into entries.
    Handles: {bucket:{predicate:{doc,page,quote[,value]}}}, {facts:[...]},
    {answers:[...]}, and lists. Entries keep the bucket path for name matching."""
    out = []
    def walk(node, path):
        if isinstance(node, dict):
            if ('doc' in node or 'quote' in node) and not any(isinstance(v, (dict, list)) for v in node.values()):
                out.append(dict(bucket=path[0] if path and path[0] not in ('facts', 'answers') else None,
                                predicate=path[1] if len(path) > 1 else None,
                                field=node.get('field') or node.get('fact_id'),
                                value=node.get('value'), raw=node.get('raw'),
                                doc=node.get('doc'), page=node.get('page'),
                                quote=node.get('quote', '')))
                return
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for x in node:
                walk(x, path)
    walk(obj, [])
    return out


def name_matches(entry, f):
    keys = {str(f.get('bucket') or ''), str(f.get('subject') or ''), str(f.get('fact_id') or ''),
            str(f.get('predicate') or '')}
    names = {str(entry.get('bucket') or ''), str(entry.get('predicate') or ''),
             str(entry.get('field') or entry.get('fact_id') or '')}
    return bool(keys & names - {''})


def entry_has_info(entry, f):
    """The stage output carries the fact's information: strict/tolerant/decorated
    value equality, or (for value-less leaves) the gold value grounded in the quote."""
    v = entry.get('raw') or entry.get('value')
    if v not in (None, ''):
        ok, _ = value_equal_anyway(v, f)
        if ok:
            return True
    q = entry.get('quote', '')
    if q and Q1.value_in_quote(f.get('value'), q):
        return True
    return False


def entry_evidence_complete(entry, f, contract, require_name=True):
    """Complete correct evidence: doc+page+quote, quote verbatim in that page,
    and the gold value grounded in the quote. Name matching required by default
    so a same-number collision from another fact cannot fake completeness."""
    if require_name and not name_matches(entry, f):
        return False
    doc, page, quote = entry.get('doc'), entry.get('page'), entry.get('quote', '')
    if doc is None or page is None or not quote:
        return False
    pg = (contract['source_pages'].get(str(doc)) or {}).get('pages', {}).get(str(page))
    if not pg:
        return False
    if _norm(quote) not in _norm(pg.get('text', '')):
        return False
    v = entry.get('raw') or entry.get('value')
    grounded = (v not in (None, '') and Q1.value_in_quote(v, quote)) or \
               Q1.value_in_quote(f.get('value'), quote)
    return bool(grounded)
