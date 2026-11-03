"""Reproduce source-table arithmetic. Not a model call, terminal Gold or V5/RL run."""
from decimal import Decimal
from datetime import date
import json
BALANCES=['2452595.96','38597814.60','212882.62','0','267483496.32','0','3575208.18','3239459.09','149339.43','0','0','0']
INVESTMENTS=[('90000000','2024-01-04','2024-04-04'),('90000000','2024-01-04','2024-07-04'),('90000000','2024-01-04','2024-02-04'),('30000000','2024-01-04','2024-04-04'),('70000000','2024-03-28','2024-07-01'),('40000000','2024-04-30','2024-05-14'),('60000000','2024-04-30','2024-05-14'),('10000000','2024-06-26','2024-08-26'),('20000000','2024-06-26','2024-09-26'),('10000000','2024-06-26','2024-10-26'),('20000000','2024-06-26','2024-09-26'),('20000000','2024-06-26','2024-10-26')]
def calculate():
 rows=[(Decimal(v),date.fromisoformat(s),date.fromisoformat(e)) for v,s,e in INVESTMENTS]
 dates=sorted({d for _,s,e in rows for d in (s,e)})
 exposure=[{'date':d.isoformat(),'listed_outstanding_CNY':str(sum((v for v,s,e in rows if s<=d<e),Decimal(0)))} for d in dates]
 peak=max(Decimal(x['listed_outstanding_CNY']) for x in exposure)
 return {'status':'SOURCE_TRANSCRIPTION_ARITHMETIC_NOT_INDEPENDENT_GOLD','balances':BALANCES,'investments':INVESTMENTS,'interval_convention':'[start_date,end_date); contract end date does not prove actual repayment','currency':'CNY; foreign-account balances used exactly as disclosed converted amounts; no additional FX conversion','expected_candidate_values':{'account_total':'%.2f'%sum(map(Decimal,BALANCES)),'account_total_minus_disclosed_own_cash':'%.2f'%(sum(map(Decimal,BALANCES))-Decimal('2000000')),'listed_purchase_turnover':str(sum((v for v,_,_ in rows),Decimal(0))),'listed_peak_principal':str(peak),'listed_scheduled_yearend_principal':str(sum((v for v,s,e in rows if s<=date(2024,12,31)<e),Decimal(0))),'listed_peak_headroom_against_20231228_cap':str(Decimal('570000000')-peak)},'exposure_timeline':exposure,'independent_reference_confirmed':False,'limitations':['No proof actual redemption occurred on scheduled maturity','No complete audit of all investments or regulatory compliance','Own-cash deduction is an explicitly requested arithmetic scenario, not an official restatement of fundraising balance','Arithmetic reproduction does not validate source transcription independently']}
if __name__=='__main__':print(json.dumps(calculate(),ensure_ascii=False,indent=2))
