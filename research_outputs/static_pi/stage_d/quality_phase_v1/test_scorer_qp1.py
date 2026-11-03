"""Independent tests for the QP1 scorer (zero calls)."""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import scorer_qp1 as S

PAGE = '公司于2026年10月9日收到立案告知书（证监立案字001号），公司被罚款100万元。'
import hashlib
PAGE_SHA = hashlib.sha256(PAGE.encode()).hexdigest()
CON = dict(task_id='T', source_pages={'D1': dict(pages={'1': dict(text=PAGE, page_sha256=PAGE_SHA)})},
           required_facts=[
               dict(fact_id='A', value='证监立案字001号', value_kind='text', critical=True,
                    source_evidence=[dict(doc_id='D1', page=1, quote='（证监立案字001号）')]),
               dict(fact_id='B', value='100', value_kind='number', critical=False,
                    source_evidence=[dict(doc_id='D1', page=1, quote='罚款100万元')]),
               dict(fact_id='C', value='2026-10-09', value_kind='date', critical=False,
                    source_evidence=[dict(doc_id='D1', page=1, quote='2026年10月9日')]),
           ], unknown_items=[dict(item_id='U1', question='最终处罚金额是否已缴纳？')])
RES = []
def chk(n, c, d=''):
    RES.append((n, bool(c), str(d))); print(f'  {n:44s} {"PASS" if c else "FAIL"} {"" if c else d}')

def sink(ans, abst=None):
    return dict(answers=ans, abstentions=abst or [])

def A(fid, val, doc='D1', page=1, quote=''):
    return dict(fact_id=fid, value=val, doc=doc, page=page, quote=quote)

def main():
    perfect = sink([A('A', '证监立案字001号', quote='（证监立案字001号）'),
                    A('B', '100', quote='罚款100万元'),
                    A('C', '2026-10-09', quote='2026年10月9日')],
                   [dict(item_id='U1', text='未披露，无法判定')])
    r = S.score_task(CON, perfect)
    chk('perfect Q=1', r['q'] == 1.0, r['q'])
    chk('perfect gate PASS', r['critical_gate'] == 'PASS')
    chk('N uses task facts (3)', r['n_facts'] == 3)
    chk('unknown correct', r['unknown_accuracy'] == 1.0)

    r = S.score_task(CON, sink([A('A', '错误编号', quote='（证监立案字001号）'),
                                A('B', '100', quote='罚款100万元'),
                                A('C', '2026-10-09', quote='2026年10月9日')]))
    chk('wrong value flagged', r['rows'][0]['status'] == 'VALUE_WRONG', r['rows'][0])
    chk('gate FAIL on critical', r['critical_gate'] == 'FAIL')
    chk('Q not averaged over gate', r['q'] == round(2/3, 6), r['q'])

    r = S.score_task(CON, sink([A('A', '证监立案字001号', doc='D9', quote='（证监立案字001号）'),
                                A('B', '100', quote='罚款100万元'),
                                A('C', '2026-10-09', quote='2026年10月9日')]))
    chk('wrong doc -> LOC_WRONG', r['rows'][0]['status'] == 'LOC_WRONG', r['rows'][0])

    r = S.score_task(CON, sink([A('A', '证监立案字001号', quote='（证监立案字001号）'),
                                A('B', '100', quote='公司于2026年10月9日收到立案告知书'),
                                A('C', '2026-10-09', quote='2026年10月9日')]))
    chk('unsupported quote -> UNSUPPORTED', r['rows'][1]['status'] == 'UNSUPPORTED', r['rows'][1])

    r = S.score_task(CON, sink([A('A', '证监立案字001号', quote='（证监立案字001号）'),
                                A('C', '2026-10-09', quote='2026年10月9日')]))
    chk('missing fact -> ABSENT', r['rows'][1]['status'] == 'ABSENT')
    chk('unknown asserted penalised', S.score_task(CON, sink(
        [A('A', '证监立案字001号', quote='（证监立案字001号）')],
        [dict(item_id='U1', text='')]))['unknown_accuracy'] == 0.0)

    # derived fact: ANY citation supports; full coverage reported separately
    CON2 = dict(CON)
    CON2['required_facts'] = [dict(fact_id='D', value='100', value_kind='number', critical=False,
        source_evidence=[dict(doc_id='D1', page=1, quote='罚款100万元'),
                         dict(doc_id='D1', page=1, quote='公司于2026年10月9日收到立案告知书')])]
    r = S.score_task(CON2, sink([A('D', '100', quote='罚款100万元')]))
    chk('derived fact: ANY support counts', r['rows'][0]['status'] == 'TP', r['rows'][0])
    chk('full derivation coverage reported separately',
        r['rows'][0]['derivation_full_coverage'] is False)

    passed = sum(1 for _, ok, _ in RES if ok)
    print(f'\n{passed}/{len(RES)} PASS')
    json.dump(dict(batch='QP1_SCORER_TESTS', results=[dict(name=n, pass_=o, detail=d) for n, o, d in RES],
                   passed=passed, total=len(RES)),
              open('/root/research_outputs/static_pi/stage_d/quality_phase_v1/QP1_SCORER_TESTS.json', 'w'),
              ensure_ascii=False, indent=1)
    return 0 if passed == len(RES) else 1

if __name__ == '__main__':
    sys.exit(main())
