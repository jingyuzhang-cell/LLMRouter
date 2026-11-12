"""SC-E1 terminal scorer, contract v1.1 (operator decision 2026-11-06).

Primary:   Q_all = TP / N
Auxiliary: Q_terminal = 0.5*F + 0.3*E + 0.2*C (P2 section 4), E_literal (P2 literal evidence caliber)

TP = value correct, cited doc in the slot's whitelist, quote verbatim in that doc, quote grounds the
slot. Whitelists and grounding rules are read from the contract, whose sha256 is pinned here. number
and date equality is scorer_qp1_v2.value_equal_v2, pinned by sha256. score() receives only the parsed
SINK object and the contract: the run, arm and condition are not available to it.
"""
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SD = Path('/root/research_outputs/static_pi/stage_d')
sys.path[:0] = [str(SD / 'quality_phase_v1'), str(SD / 'cfl_stage1')]
import scorer_qp1_v2 as V2  # noqa: E402

CONTRACT_PATH = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/SC_E1_ZHANGZIDAO/'
                     'TASK_CONTRACT_SC_E1_v1_1.json')
CONTRACT_SHA256 = 'ad0f0454b57e75030a2d7155cbc48bfcaa160f56bb415f2a73d91dec400f7c0d'
WEIGHTS = {'F': 0.5, 'E': 0.3, 'C': 0.2}
MIN_QUOTE_CHARS = 6

PINNED_SHA256 = {
    V2.__file__: '7417f3abeff214f1',
    V2.TQ.__file__: '136b2e1b09c3fbc9',
}

_DOC_NUMBER_RE = re.compile(r'[【\[〔(](\d{4})[】\]〕)](\d+)号')
_DENIAL_RE = re.compile(r'未触及|不触及|没有触及|未触发|不触发|不构成|未构成|不涉及|未涉及')
_AMOUNT_RE = re.compile(r'(\d[\d,.]*)(%|亿元|万元|亿|万|元)')
_DATE_RE = re.compile(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})')
_PAGE_MARK_RE = re.compile(r'\s*\d{1,3}\s*\x0c')
_ABSTENTIONS = {'', 'null', 'none', 'n/a', 'na', 'unknown', '未知', '未载明', '不详', '无法确定',
                '无法判断', '无', '待定', '未提及', '未披露', '缺失', '未找到', '不确定'}


def verify_pins():
    for path, prefix in PINNED_SHA256.items():
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if not actual.startswith(prefix):
            raise RuntimeError(f'scoring dependency drifted: {path} is {actual[:16]}, pinned {prefix}')


def norm_text(x):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))


def norm_doc(text):
    return norm_text(_PAGE_MARK_RE.sub('', text))


def load_contract(path=CONTRACT_PATH):
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != CONTRACT_SHA256:
        raise RuntimeError(f'not the frozen contract v1.1: {path} is {actual[:16]}')
    return json.loads(raw)


def doc_index(contract):
    return {d: norm_doc(v['pages']['1']['text']) for d, v in contract['source_pages'].items()}


def is_abstention(value):
    return value is None or norm_text(value).lower() in _ABSTENTIONS


def _single_amount(text):
    found = {(m.group(1).replace(',', ''), m.group(2)) for m in _AMOUNT_RE.finditer(text)}
    return ''.join(found.pop()) if len(found) == 1 else None


def _claim_number(value, fact):
    text = norm_text(value)
    parsed = V2._num_unit(text)
    if parsed is None:
        text = _single_amount(text) or text
        parsed = V2._num_unit(text)
    if parsed is not None and parsed[1] is None and fact.get('unit'):
        text += fact['unit']
    return text


def _claim_date(value):
    text = norm_text(value)
    found = {tuple(int(g) for g in m.groups()) for m in _DATE_RE.finditer(text)}
    if len(found) != 1:
        return text
    y, mo, d = found.pop()
    return f'{y:04d}-{mo:02d}-{d:02d}'


def _denies(value):
    if value is False:
        return True
    text = norm_text(value)
    return bool(_DENIAL_RE.search(text)) or text.startswith('否') or text.endswith('否')


def _doc_tokens(text):
    return set(_DOC_NUMBER_RE.findall(norm_text(text)))


def _has_titles(text, fact):
    titles = norm_text(fact['value']).split('、')
    for title in titles:
        text = text.replace('副' + title, '')
    return all(title in text for title in titles)


def value_correct(fact, value):
    rule = fact['grounding']['rule']
    if rule == 'doc_number':
        return _doc_tokens(value) == _doc_tokens(fact['value'])
    if rule == 'title_set':
        return _has_titles(norm_text(value), fact)
    if rule == 'negation':
        return _denies(value)
    if isinstance(value, bool):
        return False
    if rule == 'date':
        return V2.value_equal_v2({'value': _claim_date(value)}, fact)
    gold = dict(fact, value=f"{fact['value']}{fact.get('unit', '')}")
    return V2.value_equal_v2({'value': _claim_number(value, fact)}, gold)


def quote_grounds(fact, quote):
    grounding = fact['grounding']
    text = norm_text(quote)
    for anchor in (grounding.get('subject_anchor'), grounding.get('predicate_anchor')):
        if anchor and norm_text(anchor) not in text:
            return False
    rule = grounding['rule']
    if rule == 'doc_number':
        return _doc_tokens(fact['value']) <= _doc_tokens(text)
    if rule == 'title_set':
        return _has_titles(text, fact)
    if rule == 'negation':
        return bool(_DENIAL_RE.search(text))
    if rule == 'penalty_line_sum':
        return bool(re.search(r'\d万元罚款', text))
    if rule == 'date':
        gold = tuple(int(x) for x in str(fact['value']).split('-'))
        found = re.findall(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        return gold in {tuple(int(g) for g in m) for m in found}
    bare = text.replace(',', '')
    return bool(re.search(rf"(?<![\d.]){re.escape(str(fact['value']))}{re.escape(fact.get('unit', ''))}", bare))


def _row_status(fact, answer, docs):
    doc = str(answer.get('doc') or '').strip()
    quote = norm_text(answer.get('quote'))
    verbatim = doc in docs and len(quote) >= MIN_QUOTE_CHARS and quote in docs[doc]
    if not value_correct(fact, answer.get('value')):
        return 'VALUE_WRONG', False
    if not verbatim or doc not in fact['allowed_citation_docs']:
        return 'LOC_WRONG', verbatim
    if not quote_grounds(fact, answer.get('quote')):
        return 'UNSUPPORTED', verbatim
    return 'TP', verbatim


def score(sink, contract):
    """Score one parsed SINK object; every slot gets a status and the result is never NULL."""
    facts = contract['required_facts']
    gold_ids = {f['fact_id'] for f in facts}
    docs = doc_index(contract)
    sink = sink if isinstance(sink, dict) else {}
    answers = sink.get('answers') if isinstance(sink.get('answers'), list) else []
    unknown = sink.get('unknown_slots') if isinstance(sink.get('unknown_slots'), list) else []
    unknown = {str(u) for u in unknown}

    grouped, abstained, out_of_contract, malformed = defaultdict(list), set(), [], 0
    for a in answers:
        if not isinstance(a, dict):
            malformed += 1
            continue
        fid = a.get('fact_id')
        if fid not in gold_ids:
            out_of_contract.append(str(fid))
        elif is_abstention(a.get('value')):
            abstained.add(fid)
        else:
            grouped[fid].append(a)

    rows = []
    for f in facts:
        fid = f['fact_id']
        rec = {'fact_id': fid, 'critical': bool(f.get('critical'))}
        given = grouped.get(fid)
        if not given:
            rec.update(status='ABSENT', declared_unknown=fid in unknown or fid in abstained,
                       value_correct=False, literal_cite=False)
            rows.append(rec)
            continue
        if len({norm_text(a.get('value')) for a in given}) > 1:
            status, verbatim = 'CONFLICT', False
        else:
            status, verbatim = _row_status(f, given[0], docs)
        rec.update(status=status, value=given[0].get('value'), doc=given[0].get('doc'), quote=given[0].get('quote'),
                   value_correct=status in ('TP', 'LOC_WRONG', 'UNSUPPORTED'),
                   literal_cite=status in ('TP', 'LOC_WRONG', 'UNSUPPORTED') and verbatim,
                   answered_and_unknown=fid in unknown)
        rows.append(rec)

    n = len(facts)
    asserted = sum(r['status'] != 'ABSENT' for r in rows)
    correct = sum(r['value_correct'] for r in rows)
    tp = sum(r['status'] == 'TP' for r in rows)
    literal = sum(r['literal_cite'] for r in rows)
    wrong = sum(r['status'] in ('VALUE_WRONG', 'CONFLICT') for r in rows)
    critical = [r for r in rows if r['critical']]
    critical_tp = sum(r['status'] == 'TP' for r in critical)

    F = correct / asserted if asserted else 0.0
    E = tp / asserted if asserted else 0.0
    C = asserted / n
    return {
        'Q_all': round(tp / n, 6),
        'Q_terminal': round(WEIGHTS['F'] * F + WEIGHTS['E'] * E + WEIGHTS['C'] * C, 6),
        'F': round(F, 6), 'E': round(E, 6), 'C': round(C, 6),
        'E_literal': round(literal / asserted, 6) if asserted else 0.0,
        'error_rate': round(wrong / asserted, 6) if asserted else 0.0,
        'asserted': asserted, 'correct': correct, 'tp': tp, 'wrong': wrong, 'total': n,
        'critical_tp': critical_tp, 'critical_total': len(critical),
        'critical_gate': 'PASS' if critical_tp == len(critical) else 'FAIL',
        'out_of_contract': out_of_contract, 'malformed_answers': malformed,
        'zero_assertions': asserted == 0,
        'rows': rows,
    }
