"""Amount module tests (zero calls)."""
import sys
from decimal import Decimal
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp2_amount as A

RES=[]
def chk(n,c,d=''):
    RES.append((n,bool(c),str(d))); print(f'  {n:52s} {"PASS" if c else "FAIL"} {"" if c else d}')

def main():
    chk('parse plain yuan', A.parse_amount('43,497,313.43 元')==(Decimal('43497313.43'),'元'))
    chk('parse wanyuan', A.parse_amount('89.99 亿元')==(Decimal('89.99'),'亿元'))
    chk('parse percent', A.parse_amount('41.13%')==(Decimal('41.13'),'%'))
    chk('parse RMB prefix', A.parse_amount('人民币1,000.00万元')==(Decimal('1000.00'),'万元'))
    chk('parse rejects prose', A.parse_amount('约三十万元') is None)
    chk('yuan conversion', A.to_yuan(Decimal('89.99'),'亿元')==Decimal('8999000000'))
    chk('amount_equal cross-unit', A.amount_equal('89.99亿元','8,999,000,000元'))
    chk('amount_equal comma variants', A.amount_equal('3,068.52万元','3068.52 万元'))
    chk('amount_equal rounding within tol', A.amount_equal('225.49亿元','22,548,513,485.42元'))
    chk('amount_equal rejects real mismatch', not A.amount_equal('2.5亿元','3,068.52万元'))
    chk('percent vs yuan rejected', not A.amount_equal('41.13%','41.13元'))
    chk('percent equal', A.amount_equal('41.13%','41.13 %'))
    chk('prompt block present', 'normalized_yuan' in A.AMOUNT_PROMPT_BLOCK and '连续逐字原文' in A.AMOUNT_PROMPT_BLOCK)
    passed=sum(1 for _,ok,_ in RES if ok)
    print(f'\n{passed}/{len(RES)} PASS')
    import json
    json.dump(dict(batch='QP2_AMOUNT_TESTS',results=[dict(name=n,pass_=o,detail=d) for n,o,d in RES],passed=passed,total=len(RES)),
              open('/root/research_outputs/static_pi/stage_d/quality_phase_v1/QP2_AMOUNT_TESTS.json','w'),ensure_ascii=False,indent=1)
    return 0 if passed==len(RES) else 1

if __name__=='__main__':
    sys.exit(main())
