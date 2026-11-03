"""Chain module tests (zero calls)."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp2_chain as C

PAGE = ('经查明，康美药业《2016 年年度报告》虚增营业收入 89.99 亿元，多计利息收入 1.51 亿元。'
        '公司于 2026 年 10 月 9 日收到《调查通知书》（编号：粤证调查通字 180199 号）。')
CON = dict(source_pages={'D1': dict(pages={'1': dict(text=PAGE)})})
RES=[]
def chk(n,c,d=''):
    RES.append((n,bool(c),str(d))); print(f'  {n:52s} {"PASS" if c else "FAIL"} {"" if c else d}')

def main():
    e = {'e0': {'facts': [
        dict(field='虚增营业收入', raw='89.99 亿元', unit='亿元', value='89.99亿元',
             doc='D1', page=1, quote='虚增营业收入 89.99 亿元'),
        dict(field='调查通知书编号', value='粤证调查通字180199号',
             doc='D1', page=1, quote='（编号：粤证调查通字 180199 号）'),
        dict(field='伪造条目', value='99.99亿元', doc='D1', page=1, quote='不存在的原文'),
        dict(field='错页条目', value='89.99 亿元', doc='D1', page=9, quote='虚增营业收入 89.99 亿元'),
    ]}}
    t = C.build_evidence_table(e)
    chk('table built from E outputs', len(t)==4)
    ok, bad = C.verify_evidence(t, CON)
    chk('verified keeps grounded+verbatim', len(ok)==2, [x['field'] for x in ok])
    chk('fabricated quote rejected', any(x['field']=='伪造条目' for x in bad))
    chk('wrong page rejected', any(x['field']=='错页条目' for x in bad))
    instr = C.build_sink_instruction(ok)
    chk('instruction carries verbatim-reuse mandate', '逐字复制' in instr and 'abstentions' in instr)
    chk('instruction lists verified entries', '虚增营业收入' in instr)

    good_sink = dict(answers=[
        dict(fact_id='B1', value='89.99亿元', doc='D1', page=1, quote='虚增营业收入 89.99 亿元')])
    chk('reuse check passes exact copy', C.check_reuse(good_sink, ok)['n_violations']==0)
    bad_sink = dict(answers=[
        dict(fact_id='B1', value='89.99亿元', doc='D1', page=1, quote='虚增营业收入 89.99 亿元，多计利息收入 1.51 亿元')])
    r = C.check_reuse(bad_sink, ok)
    chk('rewritten quote flagged', r['n_violations']==1)
    # chain fix regression: the round-1 defect (SINK rewriting quotes) must be caught
    chk('round-1 defect detectable', C.check_reuse(dict(answers=[
        dict(fact_id='B1', value='x', doc='D1', page=1, quote='模型自己写的引文')], abstentions=[]), ok)['n_violations']==1)
    passed=sum(1 for _,okk,_ in RES if okk)
    print(f'\n{passed}/{len(RES)} PASS')
    import json
    json.dump(dict(batch='QP2_CHAIN_TESTS',results=[dict(name=n,pass_=o,detail=d) for n,o,d in RES],passed=passed,total=len(RES)),
              open('/root/research_outputs/static_pi/stage_d/quality_phase_v1/QP2_CHAIN_TESTS.json','w'),ensure_ascii=False,indent=1)
    return 0 if passed==len(RES) else 1

if __name__=='__main__':
    sys.exit(main())
