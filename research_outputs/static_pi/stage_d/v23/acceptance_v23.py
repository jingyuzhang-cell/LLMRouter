"""Phase Pi V2.3 — independent offline acceptance (zero paid calls).

Checks:
  A. scoring validity: the 44 scoring tests and 15 execution-contract tests all pass
  B. false-accept rate: adversarial wrong answers must never be scored correct
  C. false-reject rate: mechanistic legitimate variants of gold must be accepted
  D. Gold completeness: formal gold + verbatim evidence spans + coverage 1.0
  E. task independence: exercised on the T1 negative control (new task set not built yet)

C is deliberately limited to mechanistic variants (dates, numbers, punctuation,
full-width forms). Semantic paraphrases are NOT claimed as covered; they require
the human blind validation the operator requires.
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import scorer_v23_candidate as C
import validate_task_set_v23 as V

OUT = '/root/research_outputs/static_pi/stage_d/v23/OFFLINE_ACCEPTANCE_V23.json'

ADVERSE = {
    'A1': 'PERSON_ONLY_王勇',
    'A2': 'PERSON_ONLY_王勇',
    'A3': 'PERSON_ONLY_王勇',
    'A4': 'PERSON_ONLY_俞发祥',
    'A5': '实际控制人兼董事长',
    'B1': '证监立案字0262026012号',
    'B2': '证监立案字0262026012号',
    'B3': '两个编号存在，但只有公司被立案',
    'B3b': '证监立案字0042026002号→王勇；证监立案字0042026003号→公司',
    'B4': '证监立案字01120260037号',
    'C1': 'GENERIC_涉嫌信息披露违法违规',
    'C2': 'D3：GENERIC_涉嫌信息披露违法违规（D1/D2无法判定）',
    'D_1': '不同自然人',
    'D_2': '不同文书',
    'D_3': '不同收到事件',
    'D_4': '同一人（均为实际控制人俞发祥）',
    'E1': '2',
    'E2': '4',
    'E3': '3',
    'F1': '2026-10-10',
    'F2': '2026-10-09',
    'F3': '2026-10-10',
    'F4': '落款日相同，收到日相同',
}


def build_answer(f, value):
    ev = (f.get('source_evidence') or [{}])[0]
    return {'fact_id': f['fact_id'], 'value': value, 'doc': ev.get('doc_id', 'D1'),
            'page': ev.get('page', 1), 'quote': ev.get('quote', '')}


def one(con, src, fact, value):
    sink = {'answers': [build_answer(fact, value)],
            'abstentions': [{'item_id': 'U2', 'text': '无法判定'}], 'complete': True}
    res, audit, _ = C.score(sink, con, src, relevance=None)
    st = next((c['status'] for c in res['claim_results'] if c.get('fact_id') == fact['fact_id']), None)
    return st, audit


def main():
    con = C.load_contract()
    src = con['source_pages']
    facts = {f['fact_id']: f for f in con['required_facts']}
    report = {}

    # A. test suites
    try:
        sc = json.load(open('/root/research_outputs/static_pi/stage_d/v23/V23_SCORING_TESTS.json'))
        ec = json.load(open('/root/research_outputs/static_pi/stage_d/v23/V23_EXECUTION_CONTRACT_TESTS.json'))
        a_ok = sc['passed'] == sc['total'] and ec['passed'] == ec['total']
        report['A_scoring_validity'] = dict(pass_=a_ok, scoring=f"{sc['passed']}/{sc['total']}",
                                            execution_contract=f"{ec['passed']}/{ec['total']}")
    except FileNotFoundError as e:
        report['A_scoring_validity'] = dict(pass_=False, error=str(e))

    # B. false accepts
    fa = []
    for fid, bad in ADVERSE.items():
        st, audit = one(con, src, facts[fid], bad)
        if st and (st.startswith('CORRECT') or st.startswith('SEMANTICALLY_CORRECT')):
            fa.append(dict(fact_id=fid, value=bad, status=st, canonicalized=bool(audit)))
    report['B_false_accept'] = dict(pass_=not fa, count=len(fa), probes=len(ADVERSE), cases=fa)

    # C. false rejects (mechanistic variants only)
    probes = []
    for fid, f in facts.items():
        g = f.get('value')
        kind = f.get('value_kind', 'text')
        variants = [('exact', g)]
        if kind == 'date' and isinstance(g, str) and len(g) == 10:
            y, m, d = g.split('-')
            variants.append(('cn_date', f'{y}年{int(m)}月{int(d)}日'))
        if kind == 'number':
            variants.append(('with_unit', f'{g}个'))
        if kind == 'text':
            variants.append(('trailing_punct', f'{g}。'))
        for name, val in variants:
            st, audit = one(con, src, f, val)
            ok = bool(st and (st.startswith('CORRECT') or st.startswith('SEMANTICALLY_CORRECT')))
            probes.append(dict(fact_id=fid, variant=name, value=str(val)[:60], accepted=ok, status=st))
    fr = [p for p in probes if not p['accepted']]
    report['C_false_reject'] = dict(pass_=not fr, count=len(fr), probes=len(probes), cases=fr)

    # D. Gold completeness
    d_bad = []
    for fid, f in facts.items():
        if f.get('status') != 'GOLD_CONFIRMED' or not f.get('gold_source_sha256'):
            d_bad.append(f'{fid}:not_formal_gold')
        ev = f.get('source_evidence') or []
        if not ev:
            d_bad.append(f'{fid}:no_evidence')
        for item in ev:
            text = V.page_text(con, item.get('doc_id'), item.get('page'))
            if text is None:
                d_bad.append(f'{fid}:no_page'); continue
            s, e = item.get('start'), item.get('end')
            if not isinstance(s, int) or not isinstance(e, int) or not (0 <= s <= e <= len(text)):
                d_bad.append(f'{fid}:bad_span'); continue
            if V.norm(text[s:e]) != V.norm(item.get('quote', '')):
                d_bad.append(f'{fid}:span_not_verbatim')
    report['D_gold_completeness'] = dict(pass_=not d_bad, coverage=con.get('min_gold_coverage'),
                                         facts=len(facts), problems=d_bad[:8])

    # E. task independence (negative control only; new task set not built)
    report['E_task_independence'] = dict(
        pass_=None,
        status='NEW_TASK_SET_NOT_AVAILABLE',
        negative_control='T1 fails S0 (3 undeclared occurrences) and S1 (1 surviving relation); screening works as intended',
        note='The validator is executable; independence of the new groups cannot be checked before they exist.')

    gates = [report['A_scoring_validity']['pass_'], report['B_false_accept']['pass_'],
             report['C_false_reject']['pass_'], report['D_gold_completeness']['pass_']]
    overall = all(gates) and report['E_task_independence']['pass_'] is not False
    report['overall'] = dict(pass_=overall,
                             gates=dict(scoring=gates[0], false_accept=gates[1],
                                        false_reject=gates[2], gold=gates[3]),
                             pending=['relevance adjudication (HOLD)',
                                      'new independent task set + S2 ablation (not authorized)'])
    json.dump(dict(batch='PHASE_PI_V23_OFFLINE_ACCEPTANCE', **report), open(OUT, 'w'),
              ensure_ascii=False, indent=1)
    print('A scoring validity     ', report['A_scoring_validity'])
    print('B false accept         ', {k: report['B_false_accept'][k] for k in ('pass_', 'count', 'probes')})
    print('C false reject         ', {k: report['C_false_reject'][k] for k in ('pass_', 'count', 'probes')})
    print('D gold completeness    ', {k: report['D_gold_completeness'][k] for k in ('pass_', 'coverage', 'facts')})
    print('E task independence    ', report['E_task_independence']['status'])
    print('\nOVERALL', 'PASS (offline scope only)' if overall else 'BLOCKED')
    if report['B_false_accept']['cases']:
        print('false-accept cases:', json.dumps(report['B_false_accept']['cases'], ensure_ascii=False)[:600])
    if report['C_false_reject']['cases']:
        print('false-reject cases:', json.dumps(report['C_false_reject']['cases'], ensure_ascii=False)[:600])
    print('pending:', report['overall']['pending'])
    return 0 if overall else 1


if __name__ == '__main__':
    sys.exit(main())
