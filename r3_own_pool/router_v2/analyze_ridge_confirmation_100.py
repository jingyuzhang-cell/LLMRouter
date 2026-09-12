"""Analyze the frozen 100-query Ridge confirmation without tuning."""
import hashlib,json
from pathlib import Path
import numpy as np
from .data import load_cohort,read_rows,sha
from .rescore_glm_pilot import extract_option
from .mmlu_learnability import group_ci
ROOT=Path(__file__).resolve().parents[1];FROZEN=ROOT/'router_v2/ridge_confirmation_100';R1=ROOT/'data/ridge_confirmation_100_reasoning/reasoning.jsonl';SELECTED=ROOT/'data/ridge_confirmation_100_selected';OUT=ROOT/'router_v2/experiment_ridge_confirmation_100'

def score(rows,slot,expected,cohort):
 if len(rows)!=expected or len({(r['query_id'],int(r['repeat_index'])) for r in rows})!=expected:raise ValueError(f'Incomplete/duplicate {slot}: {len(rows)}/{expected}')
 result={};parse_fail=0
 for r in rows:
  option=extract_option(r.get('answer') or '') if r.get('status')!='failed' else None;gt=str(cohort[r['query_id']]['ground_truth']).strip().upper()[-1];quality=float(option==gt) if option else 0.;parse_fail+=option is None
  result.setdefault(r['query_id'],[]).append(quality)
 return result,parse_fail

def main():
 if OUT.exists():raise FileExistsError(OUT)
 protocol=json.loads((FROZEN/'PROTOCOL.json').read_text());plan=json.loads((FROZEN/'ANALYSIS_PLAN.json').read_text())
 if sha(FROZEN/'PANEL.jsonl')!=protocol['source_sha256']['panel'] or sha(FROZEN/'FROZEN_DECISIONS.jsonl')!=protocol['source_sha256']['decisions']:raise ValueError('Frozen artifacts changed')
 panel=read_rows(FROZEN/'PANEL.jsonl');decisions={r['query_id']:r for r in read_rows(FROZEN/'FROZEN_DECISIONS.jsonl')};cohort,_=load_cohort(ROOT/'data/cohort_full_v2')
 r1,r1fail=score(read_rows(R1),'reasoning',500,cohort);large,largefail=score(read_rows(SELECTED/'large.jsonl'),'large',45,cohort);medium,mediumfail=score(read_rows(SELECTED/'medium.jsonl'),'medium',5,cohort)
 gain=[];baseline=[];routed=[];switch=[]
 for row in panel:
  q=row['query_id'];b=np.mean(r1[q]);slot=decisions[q]['choice_slot'];v=b if slot=='reasoning' else np.mean((large if slot=='large' else medium)[q]);baseline.append(b);routed.append(v);gain.append(v-b)
  if slot!='reasoning':switch.append({'query_id':q,'slot':slot,'baseline_r1':float(b),'routed':float(v),'gain':float(v-b)})
 grouping=json.loads((ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json').read_text())['groups'];groups=np.array([grouping[r['query_id']] for r in panel]);gain=np.array(gain);ci=group_ci(gain,groups,42);point=float(gain.mean())
 verdict='positive_confirmation' if ci[0]>0 else ('supportive_only' if point>0 else 'not_confirmed')
 result={'n':100,'r1_expected_quality':float(np.mean(baseline)),'routed_expected_quality':float(np.mean(routed)),'gain':point,'gain_ci95':ci,'verdict':verdict,'switch_n':len(switch),'switch_mean_gain':float(np.mean([r['gain'] for r in switch])),'switch_wins':sum(r['gain']>0 for r in switch),'switch_ties':sum(r['gain']==0 for r in switch),'switch_losses':sum(r['gain']<0 for r in switch),'selection_counts':{s:sum(d['choice_slot']==s for d in decisions.values()) for s in ['medium','large','coder','reasoning']},'parse_failures':{'reasoning':r1fail,'large':largefail,'medium':mediumfail}}
 checkpoint=Path('/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8');weight_files=sorted(checkpoint.glob('*.safetensors'));checkpoint_manifest={p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in weight_files}
 OUT.mkdir(parents=True);(OUT/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n');(OUT/'SWITCH_AUDIT.json').write_text(json.dumps(switch,indent=2)+'\n');(OUT/'PROTOCOL.json').write_text(json.dumps({'frozen_protocol_sha256':sha(FROZEN/'PROTOCOL.json'),'analysis_plan_sha256':sha(FROZEN/'ANALYSIS_PLAN.json'),'decisions_sha256':sha(FROZEN/'FROZEN_DECISIONS.jsonl'),'raw_sha256':{'reasoning':sha(R1),'large':sha(SELECTED/'large.jsonl'),'medium':sha(SELECTED/'medium.jsonl')},'analyzer_sha256':sha(Path(__file__)),'checkpoint_manifest':checkpoint_manifest},indent=2)+'\n')
 lines=['# Frozen Ridge prospective confirmation（100题）','',f"R1={result['r1_expected_quality']:.2%}；Routed={result['routed_expected_quality']:.2%}；Gain={result['gain']:+.2%}；95% CI={result['gain_ci95']}。",'',f"预注册判定：**{verdict}**。",'',f"离开R1：{len(switch)}题；胜/平/负={result['switch_wins']}/{result['switch_ties']}/{result['switch_losses']}；条件平均增益={result['switch_mean_gain']:+.2%}。",'',f"解析失败：{result['parse_failures']}。",'','本确认集穷尽了未进入既有三个开发panel的100道train-split MMLU-Pro题；它验证新的随机生成结果，但不是公开benchmark test split。未收集全四模型，因此不报告Oracle Gap。']
 (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
