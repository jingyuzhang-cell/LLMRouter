"""Experiment B: concatenated query/model embeddings, continuous quality MSE."""
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from sklearn.linear_model import Ridge
from .mmlu_learnability import validate_pairs,metrics,group_ci
from .diagnose_rank_signal import load_inputs
from .data import sha
ROOT=Path(__file__).resolve().parents[1]
class QualityMA(nn.Module):
 def __init__(self,dim):
  super().__init__();self.model=nn.Embedding(2,8);self.head=nn.Sequential(nn.Linear(dim+16,64),nn.ReLU(),nn.Linear(64,1))
 def delta(self,x,i,j):
  mi=self.model.weight[i].expand(len(x),-1);mj=self.model.weight[j].expand(len(x),-1)
  # Antisymmetric pair score, no absolute-quality fitting.
  a=self.head(torch.cat([x,mi,mj],dim=1));b=self.head(torch.cat([x,mj,mi],dim=1))
  return torch.tanh((a-b).squeeze(-1))
 def forward(self,x):
  delta=self.delta(x,1,0);return torch.stack([.5-delta/2,.5+delta/2],dim=1)
FIT_DIAGNOSTICS=[]
def fit(x,y,xe,seed):
 torch.manual_seed(seed);net=QualityMA(x.shape[1]);opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.01)
 tx,ty,te=[torch.tensor(a,dtype=torch.float32) for a in [x,y,xe]];rng=np.random.default_rng(seed)
 for epoch in range(50):
  for batch in np.array_split(rng.permutation(len(x)),int(np.ceil(len(x)/32))):
   target=ty[batch,1]-ty[batch,0];pred=net.delta(tx[batch],1,0);loss=(pred-target).square().mean()
   # Ties have zero ranking weight but remain in regression. Fixed temperature .2.
   ranking=(target.abs()*torch.nn.functional.softplus(-target.sign()*pred/.2)).mean()
   loss=loss+0.0*ranking;opt.zero_grad();loss.backward();opt.step()
 with torch.no_grad():
  pred=net(te).numpy();train=net.delta(tx,1,0).numpy();reverse=net.delta(te,0,1).numpy()
 assert np.allclose(pred[:,1]-pred[:,0],-reverse,atol=1e-6)
 FIT_DIAGNOSTICS.append(dict(seed=seed,train=metrics(train,y[:,1]-y[:,0])))
 return pred,net.state_dict()
def main():
 torch.set_num_threads(4);p=ROOT/'router_v2/mmlu_utility_panel_400';d=ROOT/'data/mmlu_utility_repeats_400_recovered_b';prior=ROOT/'router_v2/mmlu_learnability_400_recovered_b';out=ROOT/'router_v2/experiment_D_pairwise_regression'
 manifest,labels=validate_pairs(p,d);pr=json.loads((prior/'PROTOCOL.json').read_text());assert json.loads((prior/'RESULTS.json').read_text())['signal_gate_pass'];assert all(sha(k)==v for k,v in pr['inputs'].items())
 source=Path(manifest['source']);assert all(sha(source/k)==v for k,v in manifest['source_files'].items())
 f,x,ds=load_inputs(source);ids=f['ids'];fold=f['folds'];y=f['quality'];index={q:i for i,q in enumerate(ids)};panel_ids=np.array(sorted(labels));pi=np.array([index[q] for q in panel_ids]);yp=np.array([[labels[q]['distributions'][s]['empirical_mean'] for s in ('large','reasoning')] for q in panel_ids],dtype=np.float32)
 gp=Path(manifest['groups']);assert sha(gp)==manifest['groups_sha256'];g=json.loads(gp.read_text())['groups'];groups=np.array([g[q] for q in ids]);pg=groups[pi];selection=json.loads((p/'FOLD_SELECTION.json').read_text())
 names=['BestSingle','DatasetBest','RidgeDelta']+[f'MA_seed{s}' for s in (42,43,44)];pc={k:np.zeros(400,dtype=int) for k in names};hc={k:np.zeros(len(ids),dtype=int) for k in names};preds={k:np.zeros((400,2)) for k in names if k.startswith('MA')};ridge_delta=np.zeros(400);trace=[]
 out.mkdir(exist_ok=False)
 protocol=dict(role='development_only_simple_continuous_quality_MA',architecture='direct antisymmetric pair scorer: GTE3584 + ordered model embeddings8+8 -> Linear64 ReLU Linear1; tanh half-difference; utility scores .5 +/- delta/2 are only decision scores',target='empirical repeat delta MSE + 0.0 * abs(delta)-weighted softplus ranking with temperature0.2; ties only regression',epochs=50,batch_size=32,lr=.001,weight_decay=.01,seeds=[42,43,44],ridge_alpha=1,selection='fixed fold-local allowlists; no tuning or early stopping on outer outcomes',decision='argmax mean quality, exact prediction tie -> large',primary='400 selected-panel repeated quality; BestSingle and DatasetBest identical on single-dataset MMLU panel',secondary='2975 historical objective temp0 transfer; replace only MMLU decisions; nonMMLU keep fold DatasetBest for learned routers',limits=['Not an independent test; original test exposed','Historical transfer and repeat panel use different outcomes; do not mix gap denominators','No cost/latency benefit claimed','Fixed3 seeds all reported; no winner seed selection'],inputs={str(t):sha(t) for t in [p/'MANIFEST.json',d/'DISTRIBUTION_STATUS.json',prior/'PROTOCOL.json',prior/'RESULTS.json',Path(__file__)]})
 (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
 for v in sorted(set(fold)):
  tr=np.flatnonzero(fold!=v);va=np.flatnonzero(fold==v);pt=np.array([i for i,q in enumerate(panel_ids) if q in selection[str(v)]]);pv=np.flatnonzero(fold[pi]==v);train=pi[pt]
  assert not set(groups[train])&set(groups[va]);assert not set(train)&set(va)
  best=int(yp[pt].mean(0).argmax())
  for k in ['BestSingle','DatasetBest']:pc[k][pv]=best
  single=int(y[tr].mean(0).argmax());hc['BestSingle'][va]=single
  for task in set(ds[va]):
   ev=va[ds[va]==task];t=tr[ds[tr]==task];b=int(y[t].mean(0).argmax())
   for name in names[1:]:hc[name][ev]=b
  mv=va[ds[va]=='mmlupro'];rv=Ridge(alpha=1).fit(x[train],yp[pt,1]-yp[pt,0]);rd=rv.predict(x[pi[pv]]);ridge_delta[pv]=rd;pc['RidgeDelta'][pv]=(rd>0).astype(int);hc['RidgeDelta'][mv]=2+(rv.predict(x[mv])>0).astype(int)
  for seed in (42,43,44):
   name=f'MA_seed{seed}';pred,state=fit(x[train],yp[pt],x[mv],seed);torch.save(state,out/f'model_fold{v}_seed{seed}.pt');lookup={idx:i for i,idx in enumerate(mv)};pp=pred[[lookup[i] for i in pi[pv]]];preds[name][pv]=pp;pc[name][pv]=pp.argmax(1);hc[name][mv]=2+pred.argmax(1)
  trace.append(dict(fold=int(v),train_ids=panel_ids[pt].tolist(),panel_eval_ids=panel_ids[pv].tolist(),historical_eval_ids=ids[va].tolist()))
  print('finished fold',int(v),flush=True)
 (out/'TRAIN_FIT.json').write_text(json.dumps(FIT_DIAGNOSTICS,indent=2)+'\n')
 def summarize(quality,choices,base,grp):
  b=quality[np.arange(len(quality)),choices[base]];oracle=quality.max(1);gap=float((oracle-b).mean());result={}
  for name,c in choices.items():
   routed=quality[np.arange(len(quality)),c];delta=routed-b;ci=group_ci(delta,grp)
   result[name]=dict(quality=float(routed.mean()),gain_vs_datasetbest=float(delta.mean()),gain_ci95=ci,gap_recovery=float(delta.mean()/gap) if gap>0 else None,gap_recovery_ci95=[z/gap for z in ci] if gap>0 else None,rescued=int((delta>0).sum()),harmed=int((delta<0).sum()),selection_counts=np.bincount(c,minlength=quality.shape[1]).tolist())
  # Average scores across seeds, never pool queries/seeds as independent observations.
  vals=np.array([quality[np.arange(len(quality)),choices[f'MA_seed{s}']] for s in (42,43,44)]).mean(0);delta=vals-b;ci=group_ci(delta,grp)
  result['MA_seed_mean']=dict(quality=float(vals.mean()),gain_vs_datasetbest=float(delta.mean()),gain_ci95=ci,gap_recovery=float(delta.mean()/gap),gap_recovery_ci95=[z/gap for z in ci])
  return dict(n=len(quality),oracle=float(oracle.mean()),gap=gap,methods=result)
 report=dict(panel=summarize(yp,pc,'DatasetBest',pg),historical_transfer=summarize(y,hc,'DatasetBest',groups),delta_prediction={'RidgeDelta':metrics(ridge_delta,yp[:,1]-yp[:,0]),**{k:metrics(v[:,1]-v[:,0],yp[:,1]-yp[:,0]) for k,v in preds.items()}})
 (out/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');(out/'FOLDS.json').write_text(json.dumps(trace,indent=2)+'\n');np.savez_compressed(out/'PREDICTIONS.npz',panel_ids=panel_ids,panel_quality=yp,ids=ids,historical_quality=y,ridge_delta=ridge_delta,**{k+'_quality_prediction':v for k,v in preds.items()},**{'panel_'+k:v for k,v in pc.items()},**{'historical_'+k:v for k,v in hc.items()})
 lines=['# 实验D：Pairwise regression','','固定50epochs、3seeds、无外折调参。直接pairwise差值回归，ranking权重固定0.0；结构及超参数不根据外折结果挑选；两个输出只是等价决策分数，不是校准的绝对质量。']
 for title,section in [('400题重复质量：主分析','panel'),('2975题历史温度0迁移：次分析','historical_transfer')]:
  r=report[section];lines+=['','## '+title,'',f"Oracle={r['oracle']:.6f}; DatasetBest→Oracle gap={r['gap']:.6f}",'','| 方法 | Quality | 净Gap Recovery | Recovery CI95 |','|---|---:|---:|---|']
  for name,v in r['methods'].items():lines.append(f"| {name} | {v['quality']:.6f} | {v['gap_recovery']:.2%} | {v['gap_recovery_ci95']} |")
 lines+=['','400题全为MMLU，因此该面板的BestSingle与DatasetBest相同；两者均只用训练折选择。主分析是富集面板开发诊断，不是总体/独立测试收益。历史迁移保持2975题分母，MA/Ridge只改变MMLU决策。区间条件于拟合模型，不覆盖重训或选题不确定性。未评估成本/延迟。']
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
