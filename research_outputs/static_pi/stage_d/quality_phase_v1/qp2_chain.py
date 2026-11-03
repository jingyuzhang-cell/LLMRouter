"""QP2 evidence-chain module (zero calls): E -> V -> SINK evidence relay.

Fixes the measured round-1 defect: verification filtered facts, but SINK
rewrote quotes itself, so verified evidence never reached the terminal answer.

Design:
  - The evidence table is built in CODE from the E-layer outputs (each entry
    carries field/value/doc/page/quote). It never depends on the m/r models to
    preserve evidence.
  - verify_evidence() checks each entry deterministically: quote verbatim in
    the cited page AND value grounded in that quote (amount-aware for amounts).
  - build_sink_instruction() renders the verified table and the verbatim-reuse
    mandate for the SINK prompt (arms B/C/D).
  - check_reuse() audits a finished SINK output: every answer's doc/page/quote
    must match a verified entry exactly; violations are flagged per answer,
    never silently repaired.
"""
import json, re, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp2_amount as AM
from scorer_qp1 import value_in_quote


def _norm(x):
    import unicodedata
    t = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', t)


def build_evidence_table(e_outputs):
    """Union of E-layer facts that carry evidence fields. e_outputs: {node: obj}."""
    table = []
    for node, obj in (e_outputs or {}).items():
        for f in (obj.get('facts') or []) if isinstance(obj, dict) else []:
            if not isinstance(f, dict):
                continue
            if f.get('doc') and f.get('quote'):
                table.append(dict(source=node, field=f.get('field') or f.get('fact_id'),
                                  value=f.get('value'), raw=f.get('raw'),
                                  unit=f.get('unit'), doc=f.get('doc'),
                                  page=f.get('page'), quote=f.get('quote', '')))
    return table


def value_grounded(entry):
    """Deterministic grounding of the entry's value inside its own quote.
    Reuses QP1's value_in_quote (dates, numbers, text core) so the verifier and
    the scorer can never disagree on what counts as grounded."""
    v = entry.get('raw') or entry.get('value')
    q = entry.get('quote', '')
    if v is None or not q:
        return False
    if value_in_quote(v, q):
        return True
    parsed = AM.parse_amount(v)
    if parsed:  # amount whose unit sits outside the quote: number must match
        nums = re.findall(r'\d[\d,.]*', str(v))
        qt = _norm(q).replace(',', '')
        return any(n.replace(',', '') in qt for n in nums)
    return False


def verify_evidence(table, contract):
    """Split entries into verified / rejected against the contract's pages."""
    pages = contract.get('source_pages', {})
    ok, bad = [], []
    for e in table:
        doc = pages.get(str(e.get('doc')))
        page = (doc or {}).get('pages', {}).get(str(e.get('page')))
        verbatim = bool(page and _norm(e.get('quote', '')) and
                        _norm(e['quote']) in _norm(page.get('text', '')))
        grounded = value_grounded(e)
        rec = dict(e)
        rec['verbatim'], rec['grounded'] = verbatim, grounded
        (ok if verbatim and grounded else bad).append(rec)
    return ok, bad


def build_sink_instruction(verified):
    """The verbatim-reuse mandate + the verified evidence table for SINK."""
    lines = ['已核验证据表（SINK 只允许使用下表作答）：']
    for i, e in enumerate(verified, 1):
        lines.append(f"{i}. field={e['field']} | value={e.get('raw') or e.get('value')} "
                     f"| doc={e['doc']} | page={e['page']} | quote={e['quote']}")
    lines.append(
        '复用规则（强制）：answers 中每一条的 doc、page、quote 必须从上表逐字复制'
        '（含标点与空格，不得改写、不得拼接、不得换行改写）；value 按槽位要求填，'
        '但金额必须与上表 value 一致（可换算单位，数值不得变）；'
        '上表没有的槽位写入 abstentions，不得凭记忆作答。')
    return '\n'.join(lines)


def check_reuse(sink_out, verified):
    """Audit SINK output against the verified table. Returns per-answer flags."""
    allowed = {(_norm(e['doc']), str(e['page']), _norm(e['quote'])) for e in verified}
    rows = []
    for a in (sink_out or {}).get('answers', []) if isinstance(sink_out, dict) else []:
        key = (_norm(a.get('doc')), str(a.get('page')), _norm(a.get('quote', '')))
        rows.append(dict(fact_id=a.get('fact_id'), reused=key in allowed))
    violations = [r for r in rows if not r['reused']]
    return dict(rows=rows, n=len(rows), n_violations=len(violations),
                violation_rate=round(len(violations) / len(rows), 4) if rows else None)
