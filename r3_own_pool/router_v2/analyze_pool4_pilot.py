"""Wait for GLM pilot then compare frozen model subsets, train-only development."""
import json,time,argparse
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from .data import read_rows,sha
from .diagnose_rank_signal import load_inputs
from .mmlu_learnability import group_ci
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'router_v2/pool4_pilot_120';D=ROOT/'data/pool4_glm_pilot_120';O=ROOT/'router_v2/pool4_pilot_results'
def quality_value(response):
 quality=response.get('quality')
 if (response.get('status')=='failed' or response.get('error')
     or str(response.get('evaluation_status','')).startswith(('generation_failure','infrastructure_failure'))):
  raise ValueError('Failed response cannot be used as a quality label')
 if isinstance(quality,dict):
  if quality.get('quality_source')=='infrastructure_failure_missing':
   raise ValueError('Infrastructure failure cannot be used as a quality label')
  quality=quality.get('final')
 if not isinstance(quality,(int,float)) or quality not in (0,1):
  raise ValueError(f'Expected binary quality, got {quality!r}')
 return float(quality)

def save_status(phase,**kw):
 p=P/'ANALYSIS_STATUS.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(dict(phase=phase,ts=time.time(),**kw),indent=2)+'\n');t.replace(p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--wait',action='store_true');a=ap.parse_args();deadline=time.monotonic()+24*3600
 while True:
  try:status=json.loads((D/'STATUS.json').read_text())
  except (FileNotFoundError,json.JSONDecodeError):status={}
  phase=status.get('phase','UNKNOWN')
  if phase=='COLLECTION_FINISHED':break
  if phase.startswith('BLOCKED'):save_status('BLOCKED_COLLECTION',collector=status);return
  if not a.wait or time.monotonic()>deadline:save_status('NOT_READY',collector=status);return
  save_status('WAITING_FOR_COLLECTION',collector=status);time.sleep(30)
 protocol=json.loads((P/'PROTOCOL.json').read_text());assert sha(P/'PANEL.jsonl')==protocol['panel_sha256'];old=read_rows(P/'EXISTING_3MODEL_MATRIX.jsonl');new=read_rows(D/'glm.jsonl');assert len(new)==120 and len({r['query_id'] for r in new})==120
 glm={r['query_id']:r for r in new};slots=['medium','large','glm','reasoning'];ids=np.array([r['query_id'] for r in old]);assert set(ids)==set(glm)
 quality=[]
 for row in old:
  responses={r['slot']:r for r in row['responses']};responses['glm']=glm[row['query_id']]
  assert responses['glm']['panel_sha256']==protocol['panel_sha256']
  quality.append([quality_value(responses[s]) for s in slots])
 y=np.array(quality,dtype=float);f,allx,ds=load_inputs(ROOT/'router_v2/objective_verified_20260910');idx={q:i for i,q in enumerate(f['ids'])};ii=np.array([idx[q] for q in ids]);x=allx[ii];ds=ds[ii];folds=f['folds'][ii];gp=ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json';g=json.loads(gp.read_text())['groups'];groups=np.array([g[q] for q in ids]);subsets={'old_pair':[1,3],'proposed_three':[0,2,3],'full_four':[0,1,2,3]};results={};predictions={}
 for name,cols in subsets.items():
  q=y[:,cols];choices={n:np.zeros(len(ids),dtype=int) for n in ['BestSingle','DatasetBest','Ridge']}
  for fold in sorted(set(folds)):
   tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold);assert not set(groups[tr])&set(groups[va]);choices['BestSingle'][va]=q[tr].mean(0).argmax()
   for task in set(ds[va]):
    t=tr[ds[tr]==task];assert len(t)>0;choices['DatasetBest'][va[ds[va]==task]]=q[t].mean(0).argmax()
   choices['Ridge'][va]=Ridge(alpha=1.).fit(x[tr],q[tr]).predict(x[va]).argmax(1)
  oracle=q.max(1);base=q[np.arange(len(q)),choices['DatasetBest']];gap=float((oracle-base).mean());methods={}
  for method,choice in choices.items():
   routed=q[np.arange(len(q)),choice];gain=routed-base;ci=group_ci(gain,groups);methods[method]=dict(quality=float(routed.mean()),regret=float((oracle-routed).mean()),gain_vs_datasetbest=float(gain.mean()),gain_ci95=ci,gap_recovery=float(gain.mean()/gap) if gap>0 else None,selection_counts=dict(zip([slots[c] for c in cols],np.bincount(choice,minlength=len(cols)).tolist())))
   predictions[name+'_'+method]=np.array(cols)[choice]
  results[name]=dict(slots=[slots[c] for c in cols],oracle=float(oracle.mean()),gap=gap,methods=methods)
 unique={s:int(((y[:,i]>np.delete(y,i,axis=1).max(1))).sum()) for i,s in enumerate(slots)}
 O.mkdir(exist_ok=False);np.savez_compressed(O/'PREDICTIONS.npz',ids=ids,quality=y,folds=folds,**predictions)
 report=dict(n=120,pools=results,unique_strict_wins=unique,per_model_quality=dict(zip(slots,y.mean(0).tolist())),limits=['Random stratified original-train pilot, one generation per query/model; no repeat stability claim','Fixed Ridge alpha1, group-isolated inherited folds, no outer tuning','Small sample and inherited deployment/quantization differences; latency not a matched-load comparison','Original test exposed, not independent confirmation'])
 (O/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');(O/'PROTOCOL.json').write_text(json.dumps(dict(inputs={str(p):sha(p) for p in [P/'PROTOCOL.json',P/'PANEL.jsonl',P/'EXISTING_3MODEL_MATRIX.jsonl',D/'glm.jsonl',gp,Path(__file__)]},folds='inherited objective3 folds',ridge_alpha=1),indent=2)+'\n')
 lines=['# 四模型120题试采','','| 模型池 | Oracle | DatasetBest | Ridge | Ridge净质量增益 |','|---|---:|---:|---:|---:|']
 for name,r in results.items():lines.append(f"| {name} | {r['oracle']:.2%} | {r['methods']['DatasetBest']['quality']:.2%} | {r['methods']['Ridge']['quality']:.2%} | {r['methods']['Ridge']['gain_vs_datasetbest']*100:.2f} pp |")
 lines+=['','各模型独有严格获益题数：'+json.dumps(unique),'','这是120题原train的单次生成试采；不据小样本点估计宣称互补性稳定或论文闭环。先比较绝对Gap与净质量收益，再决定模型池。']
 (O/'REPORT.md').write_text('\n'.join(lines)+'\n');save_status('ANALYSIS_COMPLETE',report=str(O/'REPORT.md'))
if __name__=='__main__':
 try:main()
 except Exception as exc:save_status('BLOCKED_ERROR',error=f'{type(exc).__name__}: {exc}');raise
