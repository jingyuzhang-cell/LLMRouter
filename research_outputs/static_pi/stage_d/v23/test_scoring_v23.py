"""Independent tests for the Phase Pi V2.3 candidate scoring pipeline.

Run: python3 -u test_scoring_v23.py
The frozen scorer and the frozen stage_a adapter are imported read-only; their
file hashes are asserted so a silent edit fails the suite.
"""
import hashlib, json, sys, copy
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import executor as SA
import scorer_v23_candidate as C

FROZEN_QUALITY_SHA = '136b2e1b09c3fbc991da34a836e6638e36d5c04510975094fa90126ed37b352c'
FROZEN_EXECUTOR_SHA = '5f1de3c770aa4869c2b39daa54f8917a90dcd100a8a1952e3315862abf14f889'
QUALITY_PATH = '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4/terminal_quality.py'
EXECUTOR_PATH = '/root/research_outputs/static_pi/stage_a/executor.py'

RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(f'  {name:48s} {"PASS" if cond else "FAIL"} {detail if not cond else ""}')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


CON = C.load_contract()
SRC = CON['source_pages']
GOLD = {f['fact_id']: f for f in CON['required_facts']}
ALL_IDS = [f['fact_id'] for f in CON['required_facts']]


def perfect_sink(contract=CON):
    answers = []
    for f in contract['required_facts']:
        ev = (f.get('source_evidence') or [{}])[0]
        answers.append({'fact_id': f['fact_id'], 'value': f.get('value'),
                        'doc': ev.get('doc_id', 'D1'), 'page': ev.get('page', 1),
                        'quote': ev.get('quote', '')})
    return {'answers': answers,
            'abstentions': [{'item_id': 'U2', 'text': '原文未给出具体日期，无法判定'}],
            'complete': True}


def rel_fixture():
    """Synthetic fixture ONLY for testability; not a real adjudication."""
    return {'assessor_type': 'human_adjudicator', 'review_status': 'ADJUDICATED',
            'reviewer_ids': ['r1', 'r2'], 'blind_to_strategy': True,
            'blind_to_model': True, 'score': 1.0}


def main():
    # 1. frozen files unchanged
    check('frozen terminal_quality.py unchanged', sha(QUALITY_PATH) == FROZEN_QUALITY_SHA)
    check('frozen stage_a/executor.py unchanged', sha(EXECUTOR_PATH) == FROZEN_EXECUTOR_SHA)

    # 2. root cause: frozen adapter never sets delivery_valid / claims_complete
    term_frozen = SA.build_terminal_output(perfect_sink())
    check('frozen adapter leaves delivery_valid unset', 'delivery_valid' not in term_frozen)
    check('frozen adapter leaves claims_complete unset', 'claims_complete' not in term_frozen)

    # 3. candidate adapter fills them from the contract policy
    term = C.build_terminal_output(perfect_sink(), CON, SRC)
    check('candidate claims_complete true for well-formed sink', term['claims_complete'] is True)
    check('candidate delivery_valid true for non-empty sink', term['delivery_valid'] is True)
    bad = perfect_sink(); del bad['answers'][3]['fact_id']
    check('claims_complete false when an answer lacks fact_id',
          C.build_terminal_output(bad, CON, SRC)['claims_complete'] is False)
    dup = perfect_sink(); dup['answers'][1]['fact_id'] = dup['answers'][0]['fact_id']
    check('claims_complete false on duplicate fact_id',
          C.build_terminal_output(dup, CON, SRC)['claims_complete'] is False)
    empty = {'answers': [], 'abstentions': [], 'complete': False}
    check('delivery_valid false on empty answers',
          C.build_terminal_output(empty, CON, SRC)['delivery_valid'] is False)

    # 4. document-id normalization
    cases = {'E1(D1)': 'D1', 'E2_pos': 'D2', 'E1_merge': 'D1', 'D3': 'D3',
             '文档D4': 'D4', 'E4': 'D4', 'X9': 'X9'}
    check('doc-id normalization', all(C.normalize_doc(k) == v for k, v in cases.items()),
          {k: C.normalize_doc(k) for k in cases})

    # 5. E3 numeric-contract repair
    res_frozen, _, _ = C.score(perfect_sink(), CON, SRC, relevance=rel_fixture())
    check('candidate clears blocker 1 (CLAIM_EXTRACTION_INCOMPLETE)',
          'CLAIM_EXTRACTION_INCOMPLETE' not in res_frozen['blocking_reasons'])
    check('candidate clears blocker 2 (DELIVERY_INVALID...)',
          'DELIVERY_INVALID_SEMANTIC_QUALITY_UNAVAILABLE' not in res_frozen['blocking_reasons'])
    check('candidate clears blocker 3 (GOLD_CONTRACT_INVALID_VALUE:E3)',
          not any(b.startswith('GOLD_CONTRACT_INVALID_VALUE') for b in res_frozen['blocking_reasons']))
    check('candidate clears blocker 4 with a valid relevance assessment',
          'QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED' not in res_frozen['blocking_reasons'])
    check('perfect sink scores Q=1.0', res_frozen['Q_final'] == 1.0,
          res_frozen['Q_final'])
    check('perfect sink critical gate PASS', res_frozen['critical_gate']['status'] == 'PASS')

    # 6. frozen contract still rejects E3 gold (documents the defect, not a regression)
    res_bad_contract, _, _ = C.score(perfect_sink(SA.CONTRACT), SA.CONTRACT, SA.SRC)
    check('parent contract still flags GOLD_CONTRACT_INVALID_VALUE:E3',
          any(b.startswith('GOLD_CONTRACT_INVALID_VALUE') for b in res_bad_contract['blocking_reasons']))

    # 7. without relevance the scorer still blocks (no synthetic value invented)
    res_norel, _, _ = C.score(perfect_sink(), CON, SRC, relevance=None)
    check('without adjudication Q stays blocked',
          'QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED' in res_norel['blocking_reasons']
          and res_norel['Q_final'] is None)

    # 8. canonicalization positives
    pos = [
        ('A4', 'COMPANY_ONLY_福建纳川管材科技股份有限公司'),
        ('A5', '实际控制人（两家上市公司均为实际控制人）'),
        ('C1', 'SPECIFIC_公司2023年年报涉嫌信息披露违法违规'),
        ('C2', 'GENERIC_涉嫌信息披露违法违规'),
        ('D_1', '同一人（均为实际控制人俞发祥）'),
        ('D_2', '同一份立案告知书（编号同为证监立案字01120260037号）'),
        ('D_3', '同一收到事件（均于2026年10月9日收到）'),
        ('D_4', '非同一公司（祥源文旅与交建股份为两家不同上市公司）'),
        ('E2', '4'),  # must NOT canonicalize: wrong count
        ('E3', '2个'),  # measure word is a formatting variant
    ]
    for fid, val in pos:
        sink = {'answers': [{'fact_id': fid, 'value': val, 'doc': 'D1', 'page': 1, 'quote': ''}],
                'abstentions': [{'item_id': 'U2', 'text': 'x'}], 'complete': True}
        res, audit, t = C.score(sink, CON, SRC)
        applied = bool(audit)
        if fid == 'E2':
            check(f'canonicalization rejects wrong count {fid}={val}', not applied)
        else:
            check(f'canonicalization maps {fid} variant', applied,
                  (val, audit))

    # 9. canonicalization negatives: contradictions must stay wrong
    neg = [
        ('D_4', '同一人（均为实际控制人俞发祥）'),
        ('A1', 'PERSON_ONLY_王勇'),
        ('A3', 'PERSON_ONLY_王勇'),
        ('A4', 'PERSON_ONLY_俞发祥'),
        ('C1', 'GENERIC_涉嫌信息披露违法违规'),
        ('D_1', '不同自然人'),
        ('A5', '实际控制人兼董事长'),
        ('E3', '3个'),
        ('E3', '2(实际为1)'),
        ('C2', 'D3：GENERIC_涉嫌信息披露违法违规（D1/D2无法判定）'),
    ]
    for fid, val in neg:
        sink = {'answers': [{'fact_id': fid, 'value': val, 'doc': 'D1', 'page': 1, 'quote': ''}],
                'abstentions': [{'item_id': 'U2', 'text': 'x'}], 'complete': True}
        res, audit, _ = C.score(sink, CON, SRC)
        status = next(c['status'] for c in res['claim_results'] if c.get('fact_id') == fid)
        check(f'contradiction stays wrong {fid}={val[:28]}',
              not audit and status.startswith('WRONG'))

    # 10. critical gate still bites
    s = perfect_sink()
    for a in s['answers']:
        if a['fact_id'] == 'A3':
            a['value'] = 'COMPANY_ONLY_纳川公司'   # critical fact now wrong
    res_gate, _, _ = C.score(s, CON, SRC, relevance=rel_fixture())
    check('critical gate FAIL still zeroes Q', res_gate['Q_final'] == 0.0
          and res_gate['critical_gate']['status'] == 'FAIL')

    # 11. evidence requirement still bites: correct values, empty quotes
    s2 = perfect_sink()
    for a in s2['answers']:
        a['quote'] = ''
    res_ev, _, _ = C.score(s2, CON, SRC, relevance=rel_fixture())
    check('evidence-required critical facts still gate', res_ev['critical_gate']['status'] == 'FAIL')

    # 12. determinism
    r1, a1, _ = C.score(perfect_sink(), CON, SRC, relevance=rel_fixture())
    r2, a2, _ = C.score(perfect_sink(), CON, SRC, relevance=rel_fixture())
    check('deterministic', json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
          and a1 == a2)

    # 13. frozen scorer parity: the same perfect sink is unchanged by the candidate
    #     except the intended adapter/canonicalization layers
    res_fr, _, _ = C.score(perfect_sink(SA.CONTRACT), SA.CONTRACT, SA.SRC, relevance=rel_fixture())
    check('parent contract defect is isolated to E3 gold',
          res_fr['Q_final'] is None and
          [b for b in res_fr['blocking_reasons'] if not b.startswith('GOLD_CONTRACT_INVALID_VALUE')] == [],
          res_fr['blocking_reasons'])

    # 14. relevance registry scope enforcement (operator ruling 2026-11-02)
    sink = perfect_sink()
    h = C.sink_sha256(sink)
    out_reg = {'scope': 'output_answer', 'entries': {h: {'scope': 'output_answer',
               'assessment': rel_fixture()}}}
    res_ok, _, _ = C.score(sink, CON, SRC, answer_registry=out_reg)
    check('output-scope adjudication unblocks Q', res_ok['Q_final'] == 1.0, res_ok['Q_final'])
    task_reg = {'scope': 'task_material', 'entries': {h: {'scope': 'task_material',
                'assessment': rel_fixture()}}}
    res_ts, _, _ = C.score(sink, CON, SRC, answer_registry=task_reg)
    check('task-scope relevance may NOT supply question_relevance',
          res_ts['Q_final'] is None and
          'QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED' in res_ts['blocking_reasons'])
    single = {'scope': 'output_answer', 'entries': {h: {'scope': 'output_answer',
              'assessment': dict(rel_fixture(), reviewer_ids=['r1'])}}}
    res_sg, _, _ = C.score(sink, CON, SRC, answer_registry=single)
    check('single-reviewer adjudication rejected', res_sg['Q_final'] is None)
    unblind = {'scope': 'output_answer', 'entries': {h: {'scope': 'output_answer',
               'assessment': dict(rel_fixture(), blind_to_model=False)}}}
    res_ub, _, _ = C.score(sink, CON, SRC, answer_registry=unblind)
    check('unblinded adjudication rejected', res_ub['Q_final'] is None)
    wrong = {'scope': 'output_answer', 'entries': {'0' * 64: {'scope': 'output_answer',
             'assessment': rel_fixture()}}}
    res_wr, _, _ = C.score(sink, CON, SRC, answer_registry=wrong)
    check('hash-mismatched adjudication ignored', res_wr['Q_final'] is None)

    # 15. five required metrics are reported together with the gate
    m = C.metrics_summary(res_frozen, C.build_terminal_output(perfect_sink(), CON, SRC), CON)
    need = {'critical_gate', 'critical_gate_pass', 'critical_value_correct_rate',
            'evidence_localization_rate', 'evidence_support_rate', 'q_partial_diagnostic', 'q_final'}
    check('five-metric summary present', need <= set(m), sorted(set(m)))
    check('gate PASS and Q_final reported together',
          m['critical_gate'] == 'PASS' and m['critical_gate_pass'] == 1.0 and m['q_final'] == 1.0, m)
    check('localization rate is computed from bound citations',
          m['evidence_localization_rate'] == 1.0, m['evidence_localization_rate'])

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f'\n{passed}/{len(RESULTS)} PASS')
    json.dump(dict(batch='PHASE_PI_V23_SCORING_TESTS',
                   frozen_quality_sha256=FROZEN_QUALITY_SHA,
                   frozen_executor_sha256=FROZEN_EXECUTOR_SHA,
                   results=[dict(name=n, pass_=ok, detail=str(d)) for n, ok, d in RESULTS],
                   passed=passed, total=len(RESULTS)),
              open('/root/research_outputs/static_pi/stage_d/v23/V23_SCORING_TESTS.json', 'w'),
              ensure_ascii=False, indent=1)
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
