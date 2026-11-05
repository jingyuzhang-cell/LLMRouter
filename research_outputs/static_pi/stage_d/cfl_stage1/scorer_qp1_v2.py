"""Evaluation system v2 (frozen sidecar; v1 untouched — all historical reported
numbers remain v1-caliber).

Fixes (source-verified, symmetric — applies to BOTH gold and model output):
1. numeric/percent/amount parsing: NFKC, strip spaces & thousands separators,
   parse trailing unit (%|亿元|万元|亿|万|元); compare (number, unit) tuples —
   amount-scale semantics preserved ('150万元' != '150元').
2. text: trim a frozen list of meaningless leading connectives on both sides.
3. Gold representation patches (GOLD_V2_PATCHES.json): MVR1 F1-F6 stored bare
   numbers while the source carries 万元 — patched to source-verbatim form.
   Original contract files untouched.
"""
import json, re, sys, unicodedata
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
import terminal_quality as TQ  # frozen v1, read-only

HERE = Path(__file__).parent
UNIT_RE = re.compile(r'^(-?\d[\d,，.]*)\s*(%|亿元|万元|亿|万|元)?$')
PREFIX_TRIM = re.compile(r'^(通过|以|采用|使用|利用|借助)')
GOLD_V2_PATCHES_RAW = json.load(open(HERE / 'GOLD_V2_PATCHES_V2.json'))
# namespaced keys: {task}_{fid}; applied only when fact belongs to task
GOLD_V2_PATCHES = {k.split('_',1)[1]: v for k, v in GOLD_V2_PATCHES_RAW.items()}


def _num_unit(value):
    t = unicodedata.normalize('NFKC', str(value if value is not None else '')).strip()
    t = t.replace(' ', '')
    m = UNIT_RE.match(t)
    if not m:
        return None
    try:
        n = Decimal(m.group(1).replace(',', '').replace('，', ''))
    except Exception:
        return None
    u = m.group(2) or None
    if u in ('亿', '万'):
        u += '元'
    return (n, u)


def value_equal_v2(claim, fact):
    kind = fact.get('value_kind', 'text')
    left, right = claim.get('value'), fact.get('value')
    if kind == 'date':
        return TQ._date(left) is not None and TQ._date(left) == TQ._date(right)
    if kind in {'number', 'amount', 'ratio', 'percent'}:
        a, b = _num_unit(left), _num_unit(right)
        if a is None or b is None:
            return False
        tol = TQ._decimal(fact.get('tolerance', '0')) or Decimal('0')
        try:
            return a[1] == b[1] and abs(a[0] - b[0]) <= tol
        except ArithmeticError:
            return False
    if isinstance(right, list):
        return isinstance(left, list) and sorted(TQ._norm_text(x) for x in left) == \
            sorted(TQ._norm_text(x) for x in right)
    aliases = [TQ._norm_text(x) for x in fact.get('accepted_values', [])]

    def n2(v):
        t = TQ._norm_text(PREFIX_TRIM.sub('', str(v if v is not None else ''), count=1))
        return t
    return n2(left) == n2(right) or n2(left) in aliases


def patch_gold(contract):
    task_id = contract.get('task_id') or contract.get('event_key') or ''
    facts = contract.get('required_facts', [])
    # infer task from fact-id patterns if task_id absent
    if not task_id:
        fids = {f.get('fact_id','') for f in facts}
        if fids & {'F1','F2','F3','F4','F5','F6','F8','F9','F10','F11','F13','F14','F15'}:
            task_id = 'MVR1'
        elif fids & {'G1','G2','G3','G4','G5','G6','G7','DV1','DV2','DV3','DV4','H1','H2','H3','H4','H5','H6'}:
            task_id = 'E06'
    for f in facts:
        fid = f.get('fact_id')
        new = GOLD_V2_PATCHES_RAW.get(f'{task_id}_{fid}')
        if new and f.get('value') is not None:
            f['value'] = new['value'] if isinstance(new, dict) else new
    return contract


def score_task_v2(contract, sink):
    contract = patch_gold(json.loads(json.dumps(contract, ensure_ascii=False)))
    import scorer_qp1 as Q1
    # reuse the frozen scorer's structure with v2 value equality
    facts = [f for f in contract.get('required_facts', [])
             if f.get('status') not in ('EXCLUDED', 'NOT_APPLICABLE')]
    answers = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            answers.setdefault(a['fact_id'], a)
    rows = []
    tp = 0
    crit_tp = 0
    for f in facts:
        fid = f.get('fact_id')
        a = answers.get(fid)
        rec = dict(fact_id=fid, critical=bool(f.get('critical')))
        if not a or a.get('value') in (None, ''):
            rec.update(status='ABSENT'); rows.append(rec); continue
        v = bool(value_equal_v2({'value': a.get('value'), 'value_kind': f.get('value_kind')}, dict(f)))
        pages = contract.get('source_pages', {})
        doc = pages.get(str(a.get('doc')))
        page_rec = (doc or {}).get('pages', {}).get(str(a.get('page')))
        loc = bool(page_rec and a.get('quote') and Q1._norm(a.get('quote')) and
                   Q1._norm(a.get('quote')) in Q1._norm(page_rec.get('text', '')))
        s = bool(loc and Q1.value_in_quote(a.get('value'), a.get('quote', '')))
        status = 'TP' if (v and loc and s) else (
            'VALUE_WRONG' if not v else ('LOC_WRONG' if not loc else 'UNSUPPORTED'))
        rec.update(status=status)
        tp += status == 'TP'
        crit_tp += (status == 'TP') if f.get('critical') else 0
        rows.append(rec)
    n = len(facts)
    return dict(n_facts=n, q=round(tp / n, 6) if n else None,
                crit_tp=crit_tp, rows=rows)
