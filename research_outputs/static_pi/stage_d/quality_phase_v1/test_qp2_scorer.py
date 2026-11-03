"""QP2 scorer tests (zero calls): QP1 semantics preserved + amount tolerance."""
import sys, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp2_scorer as S

PAGE = '公司于2026年10月9日收到立案告知书（证监立案字001号），虚增营业收入 89.99 亿元，被罚款100万元。'
SHA = hashlib.sha256(PAGE.encode()).hexdigest()
CON = dict(task_id='T', source_pages={'D1': dict(pages={'1': dict(text=PAGE, page_sha256=SHA)})},
           required_facts=[
               dict(fact_id='A', value='证监立案字001号', value_kind='text', critical=True,
                    source_evidence=[dict(doc_id='D1', page=1, quote='（证监立案字001号）')]),
               dict(fact_id='B', value='8999000000', value_kind='number', critical=False,
                    source_evidence=[dict(doc_id='D1', page=1, quote='虚增营业收入 89.99 亿元')]),
               dict(fact_id='C', value='100', value_kind='number', critical=False,
                    source_evidence=[dict(doc_id='D1', page=1, quote='罚款100万元')]),
           ], unknown_items=[dict(item_id='U1', question='x')])
RES=[]
def chk(n,c,d=''):
    RES.append((n,bool(c),str(d))); print(f'  {n:56s} {"PASS" if c else "FAIL"} {"" if c else d}')
def A(fid,val,doc='D1',page=1,quote=''):
    return dict(fact_id=fid,value=val,doc=doc,page=page,quote=quote)

def main():
    # amount answered in a different unit, grounded in the quote → TP with tolerant flag
    r = S.score_task(CON, dict(answers=[
        A('A','证监立案字001号',quote='（证监立案字001号）'),
        A('B','89.99亿元',quote='虚增营业收入 89.99 亿元'),
        A('C','100万元',quote='罚款100万元')]))
    chk('cross-unit amount is TP', r['rows'][1]['status']=='TP', r['rows'][1])
    chk('tolerant flag recorded', r['rows'][1]['tolerant_value_match'] is True)
    chk('wanyuan amount TP', r['rows'][2]['status']=='TP')
    chk('Q=1 with unit variants', r['q']==1.0, r['q'])
    chk('tolerant count reported', r['tolerant_value_matches']==2, r['tolerant_value_matches'])
    # genuinely wrong amount stays wrong
    r = S.score_task(CON, dict(answers=[
        A('A','证监立案字001号',quote='（证监立案字001号）'),
        A('B','8.99亿元',quote='虚增营业收入 89.99 亿元'),
        A('C','100万元',quote='罚款100万元')]))
    chk('real amount mismatch rejected', r['rows'][1]['status']=='VALUE_WRONG')
    # QP1 semantics intact
    r = S.score_task(CON, dict(answers=[
        A('A','错值',quote='（证监立案字001号）'),
        A('B','89.99亿元',quote='虚增营业收入 89.99 亿元'),
        A('C','100万元',quote='罚款100万元')]))
    chk('critical value wrong -> gate FAIL', r['critical_gate']=='FAIL')
    r = S.score_task(CON, dict(answers=[
        A('A','证监立案字001号',doc='D9',quote='（证监立案字001号）'),
        A('B','89.99亿元',quote='虚增营业收入 89.99 亿元'),
        A('C','100万元',quote='罚款100万元')]))
    chk('LOC_WRONG preserved', r['rows'][0]['status']=='LOC_WRONG')
    r = S.score_task(CON, dict(answers=[A('A','证监立案字001号',quote='（证监立案字001号）')]))
    chk('ABSENT preserved', r['rows'][2]['status']=='ABSENT')
    passed=sum(1 for _,ok,_ in RES if ok)
    print(f'\n{passed}/{len(RES)} PASS')
    import json
    json.dump(dict(batch='QP2_SCORER_TESTS',results=[dict(name=n,pass_=o,detail=d) for n,o,d in RES],passed=passed,total=len(RES)),
              open('/root/research_outputs/static_pi/stage_d/quality_phase_v1/QP2_SCORER_TESTS.json','w'),ensure_ascii=False,indent=1)
    return 0 if passed==len(RES) else 1

if __name__=='__main__':
    sys.exit(main())
