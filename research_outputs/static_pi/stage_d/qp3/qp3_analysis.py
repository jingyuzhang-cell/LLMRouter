"""QP3 tasks 2-3: fact-level error attribution + counterfactual recoverability.

Zero model calls. Reads primary records only:
  QP1_LEDGER.jsonl node texts, task contracts (gold + evidence spans).

Scoring basis (frozen for this analysis): the QP1-final scorer semantics
(scorer_qp1.py as hash-frozen in MANIFEST_QP1) — strict value comparison,
localization = verbatim quote in cited page, support = quote grounds value.
Amount-tolerant comparison (qp2_scorer) is used ONLY as a counterfactual
diagnostic, never as the reported Q.

Attribution tree per (cell, gold fact), using the FINAL SINK row status:
  CORRECT
  AMOUNT_NORMALIZATION            strict value fails, tolerant passes (formatting only)
  A_EXTRACTION_MISS               no E entry for the bucket with the right value; SINK absent
  A_EXTRACTION_ERROR[subtype]     E entries exist for bucket but wrong value; SINK value wrong
  B_E_TO_M_LOSS                   E right, m lacks it
  B_M_TO_SINK_LOSS                E and m right, SINK value wrong or absent
  B_VERIFICATION_REJECT           E evidence complete+correct but code v rejected (E2/E3)
  C_LOC[subtype]                  value right, doc/page/verbatim fails
  D_SUPPORT                       value+loc right, quote does not ground value
  E_REASONING                     relation/derived bucket with wrong value
  ABSENT_DOWNSTREAM               sink absent though E+M right (booked under B_M_TO_SINK_LOSS)

Recoverability per cell:
  H1 ceiling   fraction of facts whose E output already contains a COMPLETE
               correct evidence entry (value amount-aware-correct; doc+page+quote
               with quote verbatim in page and grounding the value) — perfect
               relay+reuse would make exactly these TP.
  H2 ceiling   fraction TP if only the value axis is repaired by amount
               normalization (tolerant value AND current loc AND current sup).
  Combined     union of the two.
  Residual     facts in neither.
"""
import json, os, re, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import scorer_qp1 as Q1
import qp2_scorer as Q2
import qp2_chain as CH
from real_provider_v22 import extract_any
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
import qp3_primitives as P3

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
ROOT = '/root/research_outputs/static_pi/stage_d'
RELATION_WORDS = ('关系', '同一', '对应', '一致', '是否', '比对', '时间链', '演化')


def load_contract(ev):
    p = [t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']
         if t['event_key'] == ev][0]['contract']
    if not os.path.isabs(p):
        p = f'{ROOT}/v23a/{p}'
    return json.load(open(p))


def parse_or_none(text):
    try:
        return extract_any(text)
    except Exception:
        return None


def value_eq(a, f):
    return Q1.TQ._value_equal({'value': a, 'value_kind': f.get('value_kind')}, dict(f))


def value_tolerant(a, f):
    ok, _ = Q2.value_equal(a, f)
    return ok


def entry_matches_fact(entry, f):
    """E/m entry belongs to this fact's bucket."""
    field = str(entry.get('field') or entry.get('fact_id') or '')
    return field == (f.get('bucket') or f['fact_id']) or field == f['fact_id']


def stage_correct(stage_obj, f):
    """(strict, tolerant) — the stage carries the fact's information, matched by
    name first, then by value/evidence (stage field names differ across prompts)."""
    entries = P3.normalize_stage(stage_obj)
    strict = tol = False
    for e in entries:
        if not P3.name_matches(e, f):
            continue
        ok, level = P3.value_equal_anyway(e.get('raw') or e.get('value') or '', f)
        if ok:
            strict = strict or (level == 'strict')
            tol = True
            if strict:
                return True, True
        elif e.get('quote') and Q1.value_in_quote(f.get('value'), e.get('quote', '')):
            tol = True
    if strict:
        return True, True
    # value-based fallback (names differ): any entry carrying the info
    for e in entries:
        if P3.entry_has_info(e, f):
            return strict, True
    return False, False


def e_evidence_complete(contract, e_objs, f):
    """A complete, verbatim-grounded, correct evidence entry for f in E outputs."""
    for obj in e_objs:
        for e in P3.normalize_stage(obj):
            if P3.entry_evidence_complete(e, f, contract):
                return True
    return False


def loc_subcause(contract, a):
    pages = contract['source_pages']
    doc = pages.get(str(a.get('doc')))
    if not doc:
        return 'doc_not_found'
    pg = (doc.get('pages') or {}).get(str(a.get('page')))
    if not pg:
        return 'page_not_found'
    q = str(a.get('quote', '') or '')
    if not q.strip():
        return 'quote_missing'
    if Q1._norm(q) not in Q1._norm(pg.get('text', '')):
        return 'quote_not_verbatim'
    return 'other'


def classify(contract, f, res_row, sink_answer, e0, e1, m, arm):
    fid = f['fact_id']
    bucket = f.get('bucket') or fid
    e_ok_strict, e_ok_tol = (stage_correct(e0, f)[0], None)
    e0s, e0t = stage_correct(e0, f)
    e1s, e1t = stage_correct(e1, f)
    e_any = e0s or e1s
    e_any_tol = e0s or e1s or e0t or e1t
    ms, _ = stage_correct(m, f)
    status = res_row['status']
    rec = dict(fact_id=fid, bucket=bucket, kind=f.get('value_kind'),
               critical=bool(f.get('critical')), status=status)

    if status == 'TP':
        rec['cause'] = 'CORRECT'
        return rec
    if sink_answer is None or sink_answer.get('value') in (None, ''):
        if e_any:
            rec['cause'] = 'B_M_TO_SINK_LOSS'
        elif e_any_tol:
            rec['cause'] = 'B_M_TO_SINK_LOSS_TOL'   # E right only up to format
        else:
            rec['cause'] = 'A_EXTRACTION_MISS'
        return rec
    a_val = sink_answer.get('value')
    if not value_eq(a_val, f):
        ok_any, level = P3.value_equal_anyway(a_val, f)
        if ok_any and level in ('tolerant', 'decorated'):
            rec['cause'] = 'AMOUNT_FORMAT'
            rec['got'] = str(a_val)[:60]
            return rec
        if ok_any and level == 'text_contained':
            rec['cause'] = 'TEXT_DECORATION'
            rec['got'] = str(a_val)[:60]
            return rec
        is_relation = any(w in str(bucket) for w in RELATION_WORDS) or len(
            f.get('source_evidence') or []) > 1
        if is_relation:
            rec['cause'] = 'E_REASONING'
            rec['got'] = str(a_val)[:60]
            return rec
        if e_any:
            rec['cause'] = 'B_M_TO_SINK_LOSS' if ms else 'B_E_TO_M_LOSS'
        else:
            txt = str(bucket)
            sub = ('amount' if (f.get('value_kind') in ('number', 'percent') or
                                any(k in txt for k in ('金额', '罚款', '收入', '利润', '占用', '担保', '对价', '比例')))
                   else 'date' if (f.get('value_kind') == 'date' or any(k in txt for k in ('日期', '时点')))
                   else 'subject' if any(k in txt for k in ('对象', '主体', '职务'))
                   else 'other')
            rec['cause'] = f'A_EXTRACTION_ERROR_{sub}'
            rec['got'] = str(a_val)[:60]
        return rec
    # value right but evidence fails
    if not res_row.get('localization'):
        rec['cause'] = f'C_LOC_{loc_subcause(contract, sink_answer)}'
        return rec
    rec['cause'] = 'D_SUPPORT'
    return rec


def main():
    ledger = {}
    for line in open(f'{QP}/QP1_LEDGER.jsonl'):
        r = json.loads(line)
        p = r['purpose'].split('|')
        if len(p) == 5:
            ledger[(p[1], p[2], p[3], p[4])] = r
    matrix = json.load(open('/root/research_outputs/static_pi/stage_d/qp3/QP3_MATRIX.json'))['cells']

    attrib, funnel, recover = [], [], []
    for cell in matrix:
        if cell['status'] != 'COMPLETED':
            continue
        t, arm, rep = cell['task'], cell['arm'], cell['rep']
        contract = load_contract(t)
        e0 = parse_or_none(ledger[(t, arm, f'r{rep}', 'e0')]['text'])
        e1 = parse_or_none(ledger[(t, arm, f'r{rep}', 'e1')]['text'])
        m = parse_or_none(ledger[(t, arm, f'r{rep}', 'm')]['text'])
        sink = parse_or_none(ledger[(t, arm, f'r{rep}', 'p')]['text'])
        res = Q1.score_task(contract, sink)
        ans = {}
        for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
            if isinstance(a, dict) and a.get('fact_id'):
                ans.setdefault(a['fact_id'], a)

        n = len(res['rows'])
        c_e = c_m = c_sinkval = c_tp = c_evid = c_toltp = c_h1 = 0
        for f in contract['required_facts']:
            row = next(r for r in res['rows'] if r['fact_id'] == f['fact_id'])
            rec = classify(contract, f, row, ans.get(f['fact_id']), e0, e1, m, arm)
            rec.update(task=t, arm=arm, rep=rep)
            attrib.append(rec)
            e0s, _ = stage_correct(e0, f)
            e1s, _ = stage_correct(e1, f)
            ms, _ = stage_correct(m, f)
            a = ans.get(f['fact_id'])
            c_e += (e0s or e1s)
            c_m += ms
            c_sinkval += bool(a and value_eq(a.get('value'), f))
            c_tp += row['status'] == 'TP'
            c_evid += e_evidence_complete(contract, (e0, e1), f)
            okc, _ = P3.value_equal_anyway(a.get('value'), f) if a else (False, None)
            c_toltp += bool(a and okc and row.get('localization') and row.get('support'))
            c_h1 += (e_evidence_complete(contract, (e0, e1), f) or row['status'] == 'TP')
        funnel.append(dict(task=t, arm=arm, rep=rep, n=n,
                           e_correct=round(c_e / n, 4), m_correct=round(c_m / n, 4),
                           sink_value=round(c_sinkval / n, 4), tp=round(c_tp / n, 4),
                           e_evidence_complete=round(c_evid / n, 4)))
        recover.append(dict(task=t, arm=arm, rep=rep, n=n,
                            q_current=round(c_tp / n, 4),
                            h2_ceiling=round(c_toltp / n, 4),
                            h1_ceiling=round(c_h1 / n, 4)))
    json.dump(dict(batch='QP3_FACT_ATTRIBUTION', model_calls=0, rows=attrib),
              open('/root/research_outputs/static_pi/stage_d/qp3/QP3_FACT_ATTRIBUTION.json', 'w'),
              ensure_ascii=False, indent=1)
    json.dump(dict(batch='QP3_FUNNEL', funnel=funnel, recoverability=recover),
              open('/root/research_outputs/static_pi/stage_d/qp3/QP3_RECOVERABILITY.json', 'w'),
              ensure_ascii=False, indent=1)

    cnt = collections.Counter(r['cause'] for r in attrib)
    print('=== error causes (all completed cells, fact-instances) ===')
    for k, v in cnt.most_common():
        print(f'  {k:28s} {v:4d}  {v/len(attrib)*100:5.1f}%')
    print(f'  TOTAL {len(attrib)}')
    print('\n=== funnel (mean over cells) by arm ===')
    by = collections.defaultdict(list)
    for f in funnel:
        by[f['arm']].append(f)
    for a, g in by.items():
        print(f"  {a:9s} E={st.mean(x['e_correct'] for x in g):.3f} M={st.mean(x['m_correct'] for x in g):.3f} "
              f"SINKval={st.mean(x['sink_value'] for x in g):.3f} TP={st.mean(x['tp'] for x in g):.3f} "
              f"E-evid={st.mean(x['e_evidence_complete'] for x in g):.3f}")
    print('\n=== recoverability ceilings by arm (cell mean) ===')
    by2 = collections.defaultdict(list)
    for f in recover:
        by2[f['arm']].append(f)
    for a, g in by2.items():
        print(f"  {a:9s} Q={st.mean(x['q_current'] for x in g):.3f} "
              f"H1={st.mean(x['h1_ceiling'] for x in g):.3f} H2={st.mean(x['h2_ceiling'] for x in g):.3f}")
    print('\n=== per task (E1 arm, mechanism reference) ===')
    for t in ('E06', 'MVR1', 'KANGMEI'):
        g = [x for x in recover if x['task'] == t]
        print(f"  {t:9s} Q={st.mean(x['q_current'] for x in g):.3f} "
              f"H1={st.mean(x['h1_ceiling'] for x in g):.3f} H2={st.mean(x['h2_ceiling'] for x in g):.3f}")


if __name__ == '__main__':
    main()
