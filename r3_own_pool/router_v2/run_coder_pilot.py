"""Frozen 120-query Coder screening; download wait, collection, then analysis."""
import json,time,fcntl,subprocess,ast
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from . import run_repeat_stability as engine
from . import score_code,score_available
from .rescore_glm_pilot import extract_code,extract_option
from .analyze_pool4_pilot import quality_value
from .diagnose_rank_signal import load_inputs
from .mmlu_learnability import group_ci
from .data import sha
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'router_v2/pool4_pilot_120';D=ROOT/'data/coder_pilot_120';O=ROOT/'router_v2/coder_pilot_results';MODEL=Path('/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct');REPO='Qwen/Qwen2.5-Coder-7B-Instruct';REV='c03e6d358207e414f1eca0bb1891e29f1db0e242'
def state(phase,**kw):
 D.mkdir(exist_ok=True);p=D/'STATUS.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(dict(phase=phase,ts=time.time(),**kw),indent=2)+'\n');t.replace(p)
def score(row,raw):
 if raw['status']=='failed':return {'quality':None,'evaluation_status':'infrastructure_failure_missing'}
 if row['dataset'] in ('humaneval','mbpp'):
  return score_code.score(row,dict(answer='```python\n'+extract_code(raw.get('answer') or '')+'\n```',status=raw['status']))
 if row['dataset']=='mmlupro':
  v=extract_option(raw.get('answer') or '');return dict(quality=float(v==str(row['ground_truth']).strip().upper()[-1]) if v else 0.,evaluation_status='scored' if v else 'answer_parse_failed',parse_succeeded=v is not None)
 return score_available.score(row,raw)
def analyze():
 old=engine.read_jsonl(P/'EXISTING_3MODEL_MATRIX.jsonl');glm={r['query_id']:r for r in engine.read_jsonl(ROOT/'data/pool4_glm_rescore_v1/glm.jsonl')};coder={r['query_id']:r for r in engine.read_jsonl(D/'coder.jsonl')};ids=np.array([r['query_id'] for r in old]);assert len(coder)==120 and set(ids)==set(coder)==set(glm)
 slots=['medium','large','glm','coder','reasoning'];y=[]
 for row in old:
  rr={x['slot']:x for x in row['responses']};rr.update(glm=glm[row['query_id']],coder=coder[row['query_id']]);y.append([quality_value(rr[s]) for s in slots])
 y=np.array(y);f,x,ds=load_inputs(ROOT/'router_v2/objective_verified_20260910');index={q:i for i,q in enumerate(f['ids'])};ii=np.array([index[q] for q in ids]);x=x[ii];ds=ds[ii];folds=f['folds'][ii];gp=ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json';groups_data=json.loads(gp.read_text())['groups'];groups=np.array([groups_data[q] for q in ids]);pools={'old_pair':[1,4],'historical_three':[0,1,4],'with_glm_four':[0,1,2,4],'coder_three':[0,3,4],'coder_four':[0,1,3,4],'all_five':[0,1,2,3,4]};results={};pred={}
 for name,cols in pools.items():
  q=y[:,cols];choices={m:np.zeros(120,dtype=int) for m in ['BestSingle','DatasetBest','Ridge']}
  for fold in sorted(set(folds)):
   tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold);assert not set(groups[tr])&set(groups[va]);choices['BestSingle'][va]=q[tr].mean(0).argmax()
   for task in sorted(set(ds[va])):
    t=tr[ds[tr]==task];assert len(t);choices['DatasetBest'][va[ds[va]==task]]=q[t].mean(0).argmax()
   choices['Ridge'][va]=Ridge(alpha=1.).fit(x[tr],q[tr]).predict(x[va]).argmax(1)
  base=q[np.arange(120),choices['DatasetBest']];oracle=q.max(1);gap=float((oracle-base).mean());methods={}
  for m,ch in choices.items():
   routed=q[np.arange(120),ch];gain=routed-base;pred[name+'_'+m]=np.array(cols)[ch];methods[m]=dict(accuracy=float(routed.mean()),gain=float(gain.mean()),gain_ci95=group_ci(gain,groups),gap_recovery=float(gain.mean()/gap) if gap else None,selected=dict(zip([slots[c] for c in cols],np.bincount(ch,minlength=len(cols)).tolist())))
  unique={slots[c]:int(((q[:,j]==1)&(np.delete(q,j,axis=1).max(1)==0)).sum()) for j,c in enumerate(cols)}
  results[name]=dict(oracle_accuracy=float(oracle.mean()),oracle_gap=gap,unique_wins=unique,methods=methods)
 distributions={}
 for i,row in enumerate(y):
  winners='+'.join(slots[j] for j in range(5) if row[j]==1) or 'none_correct';distributions[winners]=distributions.get(winners,0)+1
 accuracy={s:float(y[:,j].mean()) for j,s in enumerate(slots)};per_dataset={str(task):{s:float(y[ds==task,j].mean()) for j,s in enumerate(slots)} for task in sorted(set(ds))}
 exclusive=results['all_five']['unique_wins']['coder'];recommendation='Coder passes >10% strict unique-win screening; consider retaining for utility panel.' if exclusive/120>.1 else 'Coder does not pass >10% strict unique-win screening; inspect per-task gains and absolute routing quality before choosing a pool.'
 O.mkdir(exist_ok=False);np.savez_compressed(O/'PREDICTIONS.npz',ids=ids,quality=y,folds=folds,**pred)
 report=dict(n=120,slots=slots,accuracy=accuracy,per_dataset_accuracy=per_dataset,pools=results,winner_distribution=distributions,winner_definition='set of models correct on a query; none_correct is separate; strict unique wins exclude all ties',decision=recommendation,limits=['Original-train exploratory pilot, no independent test or stability claim','Old Qwen/R1 labels reused; GLM/Coder use corrected extraction; historical-score protocol difference remains','Report all fixed pools; no significance claim from selecting best observed pool','400-query panel and MA follow a separate frozen protocol after pool review'])
 (O/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');(O/'PROVENANCE.json').write_text(json.dumps({str(p):sha(p) for p in [D/'PROTOCOL.json',D/'coder.jsonl',D/'RAW.jsonl',P/'EXISTING_3MODEL_MATRIX.jsonl',ROOT/'data/pool4_glm_rescore_v1/glm.jsonl',gp,Path(__file__)]},indent=2)+'\n')
 lines=['# Coder 120题模型池筛查','','| 模型 | Accuracy | 全五模型独有正确 |','|---|---:|---:|']
 for s in slots:lines.append(f"| {s} | {accuracy[s]:.2%} | {results['all_five']['unique_wins'][s]}/120 |")
 lines+=['','| 模型池 | Oracle | DatasetBest | Ridge | Oracle gap |','|---|---:|---:|---:|---:|']
 for name,v in results.items():lines.append(f"| {name} | {v['oracle_accuracy']:.2%} | {v['methods']['DatasetBest']['accuracy']:.2%} | {v['methods']['Ridge']['accuracy']:.2%} | {v['oracle_gap']:.2%} |")
 lines+=['',recommendation,'','赢家组合分布、分任务准确率和区间见RESULTS.json。没有自动扩大样本或启动MA；先根据筛查结果冻结模型池及400题协议。'];(O/'REPORT.md').write_text('\n'.join(lines)+'\n');state('SCREENING_COMPLETE',records=120,report=str(O/'REPORT.md'))
def main():
 D.mkdir(exist_ok=True)
 with (D/'RUN.lock').open('a+') as runlock:
  fcntl.flock(runlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  panel=engine.bind_panel(engine.read_jsonl(P/'PANEL.jsonl'),ROOT/'data/cohort_full_v2');assert len(panel)==120
  protocol=dict(repo=REPO,revision=REV,panel_sha256=sha(P/'PANEL.jsonl'),cohort_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),split_sha256=sha(ROOT/'data/cohort_full_v2/split.json'),temperature=0.,top_p=1.,max_tokens=engine.MAX_TOKENS,max_requests_per_query=2,scorer_sha256=sha(ROOT/'router_v2/rescore_glm_pilot.py'),engine_sha256=sha(engine.__file__),analysis='fixed inherited folds, Ridge alpha=1, six pools reported',selection_gate='strict unique correct >10%; inclusive winner rate reported separately')
  pp=D/'PROTOCOL.json'
  if pp.exists():assert json.loads(pp.read_text())==protocol
  else:pp.write_text(json.dumps(protocol,indent=2)+'\n')
  while not (MODEL/'DOWNLOAD_COMPLETE.json').exists():state('WAITING_FOR_DOWNLOAD');time.sleep(15)
  assert json.loads((MODEL/'DOWNLOAD_COMPLETE.json').read_text())==dict(repo=REPO,revision=REV)
  from safetensors import safe_open
  ix=json.loads((MODEL/'model.safetensors.index.json').read_text());keys=set()
  for file in set(ix['weight_map'].values()):
   with safe_open(str(MODEL/file),framework='pt',device='cpu') as f:keys.update(f.keys())
  assert set(ix['weight_map'])<=keys
  runtime=score_code.verify_runtime();probe=json.loads((ROOT/'router_v2/CODE_SANDBOX_PROBE_V3.json').read_text());assert probe['status']=='PASS' and probe['runtime_manifest_sha256']==runtime
  with (ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with (D/'VLLM.log').open('a') as log:
    proc=subprocess.Popen(['/root/autodl-tmp/r3_venv/bin/vllm','serve',str(MODEL),'--served-model-name',REPO,'--port','8127','--max-model-len','8192','--max-num-seqs','2','--gpu-memory-utilization','.92','--generation-config','vllm'],stdout=log,stderr=subprocess.STDOUT)
    try:
     state('LOADING');engine.wait_healthy(proc);client=dict(base_url='http://127.0.0.1:8127/v1',api_key='local',local=True,timeout=600)
     raw={r['query_id']:r for r in engine.read_jsonl(D/'RAW.jsonl')};scored={r['query_id']:r for r in engine.read_jsonl(D/'coder.jsonl')};spent={r['query_id'] for r in engine.read_jsonl(D/'ATTEMPTS.jsonl')}
     for row in panel:
      q=row['query_id']
      if q in scored:continue
      if q not in raw:
       if q in spent:raise RuntimeError('Interrupted request budget requires audit: '+q)
       with (D/'ATTEMPTS.jsonl').open('a') as f:f.write(json.dumps(dict(query_id=q,max_requests=2,ts=time.time()))+'\n')
       response=engine.generate(client,REPO,row,0.,1.,2);response.update(query_id=q,slot='coder',model=REPO,revision=REV,temperature=0.,top_p=1.,panel_sha256=protocol['panel_sha256'],ts=time.time());raw[q]=response
       with (D/'RAW.jsonl').open('a') as f:f.write(json.dumps(response,ensure_ascii=False)+'\n')
      result=score(row,raw[q])
      if result.get('quality') is None:raise RuntimeError('Scoring/generation failure: '+q+' '+str(result))
      record={**raw[q],**result};scored[q]=record
      with (D/'coder.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
      state('COLLECTING',records=len(scored),target=120)
    finally:
     proc.terminate()
     try:proc.wait(timeout=60)
     except subprocess.TimeoutExpired:proc.kill();proc.wait()
  state('ANALYZING',records=120);analyze()
if __name__=='__main__':
 try:main()
 except Exception as e:state('BLOCKED_ERROR',error=f'{type(e).__name__}: {e}');raise
