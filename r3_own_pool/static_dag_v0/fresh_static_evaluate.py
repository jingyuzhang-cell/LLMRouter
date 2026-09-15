"""Five-arm scoring of a fully frozen conditional fresh node table."""
import json,time
from pathlib import Path
import numpy as np
from . import core,node_router_compare as old
from .node_gap_audit_full import score
from .fresh_static_confirmation import OUT,POOL,verify
ARMS=['AlwaysLarge','QueryRouter','StaticCapability','FrozenNodeRouter','NodeOracle']

def dedup_cost(nodes,indices,picks,lookup,task_index):
 c=np.zeros(len(task_index));l=c.copy();calls=c.copy();seen=set()
 for i in indices:
  node=nodes[i];slot=POOL[int(picks[i])];r=lookup[slot][node['node_id']];key=(slot,r['call_key'])
  if key in seen:continue
  seen.add(key);tid=task_index[node['task_uid']];c[tid]+=r['usage']['total_tokens'];l[tid]+=r['latency_s'];calls[tid]+=1
 return c,l,calls

def bootstrap_quality(Q,picks,mask,task_of,boot):
 ids=np.flatnonzero(mask);nt=boot.shape[1];counts=np.bincount(task_of[ids],minlength=nt).astype(float)
 selected={a:Q[np.arange(len(Q)),p][ids] for a,p in picks.items()}
 sums={a:np.bincount(task_of[ids],weights=val,minlength=nt) for a,val in selected.items()}
 den=counts[boot].sum(1)
 samples={a:np.divide(val[boot].sum(1),den,out=np.full(len(boot),np.nan),where=den>0) for a,val in sums.items()}
 fixed=np.column_stack([np.bincount(task_of[ids],weights=Q[ids,j],minlength=nt)[boot].sum(1)/den for j in range(3)])
 return samples,np.max(fixed,axis=1)

def ci(x):
 x=np.asarray(x);finite=x[np.isfinite(x)]
 return np.quantile(finite,[.025,.975]).tolist() if len(finite) else None

def evaluate():
 protocol=verify();frozen=json.loads((OUT/'PREDICTIONS_FROZEN.json').read_text());assert core.sha(OUT/'PREDICTIONS.json')==frozen['predictions_sha256']
 if (OUT/'EVALUATION_STARTED.json').exists():raise RuntimeError('No implicit repeated evaluation')
 core.write(OUT/'EVALUATION_STARTED.json',dict(unix_time=time.time(),predictions_sha256=frozen['predictions_sha256']))
 nodes=json.loads((OUT/'NODES.json').read_text());pred=json.loads((OUT/'PREDICTIONS.json').read_text());assert [n['node_id'] for n in nodes]==[n['node_id'] for n in pred]
 lookup={};missing=[];physical={}
 for slot in POOL:
  rows=core.lines(OUT/(slot+'_RESPONSES.jsonl'));lookup[slot]={nid:r for r in rows for nid in r['node_ids']};physical[slot]=dict(requests=len(rows),known_tokens=sum((r.get('usage') or {}).get('total_tokens',0) for r in rows))
  for n in nodes:
   r=lookup[slot].get(n['node_id'])
   if r is None or r['status']!='delivered' or not r.get('answer') or not r.get('usage'):missing.append(dict(node_id=n['node_id'],model=slot,status=r.get('status') if r else 'absent'))
 if missing:
  core.write(OUT/'RESULTS.json',dict(phase='INCONCLUSIVE_MISSING',missing=missing,physical=physical,gates=dict(F1=None,F2=None,F3=None)));core.write(OUT/'STATUS.json',dict(phase='INCONCLUSIVE_MISSING',next_experiment_started=False));return
 Q=np.array([[score(n,lookup[s][n['node_id']]['answer']) for s in POOL] for n in nodes]);C=np.array([[lookup[s][n['node_id']]['usage']['total_tokens'] for s in POOL] for n in nodes]);L=np.array([[lookup[s][n['node_id']]['latency_s'] for s in POOL] for n in nodes]);picks={a:np.array([POOL.index(p['arms'][a]) for p in pred]) for a in ARMS[:-1]}
 utility=old.utility(Q,C,L);picks['NodeOracle']=np.array([max(range(3),key=lambda j:(Q[i,j],utility[i,j],-j)) for i in range(len(nodes))])
 tasks=sorted({n['task_uid'] for n in nodes});ti={t:i for i,t in enumerate(tasks)};task_of=np.array([ti[n['task_uid']] for n in nodes]);main=np.array([n['node_type']!='transformation' for n in nodes]);rng=np.random.default_rng(20260915);boot=rng.integers(0,len(tasks),(10000,len(tasks)));samples,bs_best=bootstrap_quality(Q,picks,main,task_of,boot)
 arms={};per_tasks={a:[] for a in ARMS};costs={};latencies={}
 for a,choice in picks.items():
  values=Q[np.arange(len(nodes)),choice];c,l,nc=dedup_cost(nodes,np.flatnonzero(main),choice,lookup,ti);costs[a]=c;latencies[a]=l
  arms[a]=dict(Q=float(values[main].mean()),tokens_total=float(c.sum()),tokens_per_task=float(c.mean()),deduplicated_calls=int(nc.sum()),mean_task_service_seconds=float(l.mean()),legacy_mean_per_node_tokens=float(C[np.flatnonzero(main),choice[main]].mean()),legacy_mean_per_node_latency=float(L[np.flatnonzero(main),choice[main]].mean()),legacy_mean_per_node_utility=float(old.utility(values[main],C[np.flatnonzero(main),choice[main]],L[np.flatnonzero(main),choice[main]]).mean()),selection_counts={s:int(sum(choice[main]==j)) for j,s in enumerate(POOL)})
  for i,t in enumerate(tasks):
   mask=main&(task_of==i);per_tasks[a].append(dict(task_uid=t,node_count=int(sum(mask)),Q_sum=float(values[mask].sum()),Q_mean=float(values[mask].mean()),tokens=float(c[i]),service_seconds=float(l[i]),calls=int(nc[i])))
 contrasts={}
 for b in ['QueryRouter','AlwaysLarge','StaticCapability']:
  contrasts['FrozenNodeRouter_minus_'+b]=dict(Q_delta=arms['FrozenNodeRouter']['Q']-arms[b]['Q'],Q_ci95=ci(samples['FrozenNodeRouter']-samples[b]),tokens_per_task_delta=float((costs['FrozenNodeRouter']-costs[b]).mean()),tokens_ci95=ci((costs['FrozenNodeRouter']-costs[b])[boot].mean(1)),service_seconds_delta=float((latencies['FrozenNodeRouter']-latencies[b]).mean()),service_ci95=ci((latencies['FrozenNodeRouter']-latencies[b])[boot].mean(1)))
 by_type={}
 for typ in old.TYPES:
  mask=np.array([n['node_type']==typ for n in nodes]);ns=int(sum(mask))
  if not ns:by_type[typ]=dict(n=0);continue
  fixed=Q[mask].mean(0);bestj=int(np.argmax(fixed));qualities={a:float(Q[np.flatnonzero(mask),p[mask]].mean()) for a,p in picks.items()};gap=qualities['NodeOracle']-float(fixed[bestj]);gain=Q[mask].max(1)-Q[mask,bestj]
  ts,bf=bootstrap_quality(Q,picks,mask,task_of,boot);den=ts['NodeOracle']-bf;rec=np.divide(ts['FrozenNodeRouter']-bf,den,out=np.full(len(den),np.nan),where=den>0)
  by_type[typ]=dict(n=ns,tasks=len(set(task_of[mask])),exploratory=typ=='transformation',per_fixed_model={s:float(fixed[j]) for j,s in enumerate(POOL)},best_fixed_model=POOL[bestj],Q_best_fixed=float(fixed[bestj]),arms_Q=qualities,oracle_gap=gap,oracle_gap_ci95=ci(ts['NodeOracle']-bf),positive_advantage_nodes=int(sum(gain>0)),positive_advantage_tasks=len(set(task_of[mask][gain>0])),quality_recovery=(qualities['FrozenNodeRouter']-float(fixed[bestj]))/gap if gap>0 else None,recovery_ci95=ci(rec),bootstrap_undefined_recovery=int(sum(~np.isfinite(rec))))
 fixed=Q[main].mean(0);bestj=int(np.argmax(fixed));best=float(fixed[bestj]);gap=arms['NodeOracle']['Q']-best;recovery=(arms['FrozenNodeRouter']['Q']-best)/gap if gap>0 else None;den=samples['NodeOracle']-bs_best;bs_rec=np.divide(samples['FrozenNodeRouter']-bs_best,den,out=np.full(len(den),np.nan),where=den>0)
 nq=arms['FrozenNodeRouter']['Q'];qq=arms['QueryRouter']['Q'];lq=arms['AlwaysLarge']['Q'];F1=any(by_type[t]['oracle_gap']>0 for t in ['extraction','reasoning']);quality_path=nq>qq and nq>=lq;efficiency_path=nq>qq and abs(nq-lq)<=.01 and arms['FrozenNodeRouter']['tokens_total']<arms['AlwaysLarge']['tokens_total'];F2=quality_path or efficiency_path;F3=recovery is not None and recovery>0;cq=contrasts['FrozenNodeRouter_minus_QueryRouter'];cl=contrasts['FrozenNodeRouter_minus_AlwaysLarge'];query_confirm=cq['Q_ci95'][0]>0;eff_confirm=efficiency_path and cl['Q_ci95'][0]>=-.01 and cl['Q_ci95'][1]<=.01 and cl['tokens_ci95'][1]<0;F2confirm=query_confirm and (quality_path or eff_confirm)
 results=dict(tasks=len(tasks),primary_nodes=int(sum(main)),exploratory_nodes=int(sum(~main)),arms=arms,contrasts=contrasts,by_type=by_type,quality_recovery=dict(best_fixed_model=POOL[bestj],Q_best_fixed=best,oracle_gap=gap,recovery=recovery,ci95=ci(bs_rec),undefined_bootstrap_samples=int(sum(~np.isfinite(bs_rec)))),gates=dict(F1=bool(F1),F2_directional=bool(F2),F2_quality_path=bool(quality_path),F2_efficiency_path=bool(efficiency_path),F2_statistically_supported=bool(F2confirm),F3=bool(F3),Static_stage_confirmed=bool(F1 and F2 and F3 and F2confirm)),physical=physical,limitations=['This is a conditional node-table benchmark: gold facts for reasoning and gold/perturbed verification inputs; not deployed end-to-end DAG quality.','Fresh holdout is audited unused labelled train, not official test; audit covers two workspace roots, not pretraining or unknown external use.','Full-dev heads refit/exported with original alpha/features before fresh inference; original CV reproduced.','StaticCapability follows implemented global profile, not a per-node-type profile.','Question-length feature and quality scoring unchanged, including their limitations.','Primary transformation excluded; old46.2% was utility recovery, fresh number is quality recovery.','Per-call latency/service sum and deduplicated tokens are measured; end-to-end latency and dollar billing not established.'])
 core.write(OUT/'RESULTS.json',results);core.write(OUT/'PER_TASK.json',per_tasks);np.savez_compressed(OUT/'SCORED_MATRIX.npz',Q=Q,C=C,L=L,main=main,task_of=task_of,**{a:p for a,p in picks.items()})
 with (OUT/'PER_NODE.jsonl').open('w') as f:
  for i,n in enumerate(nodes):f.write(json.dumps(dict(node_id=n['node_id'],task_uid=n['task_uid'],node_type=n['node_type'],Q={s:float(Q[i,j]) for j,s in enumerate(POOL)},choices={a:POOL[int(p[i])] for a,p in picks.items()}))+'\n')
 lines=['# Fresh Static DAG Confirmation','', '使用经审计未参与开发的MultiHiertt train独立holdout，100题；不称为官方test。原dev模型、特征、GTE、节点定义、评分与utility固定。','',f"主评估 {int(sum(main))} 个节点，Transformation {int(sum(~main))} 个仅探索性报告。所有三个候选模型各节点均有真实响应。",'', '| 方法 | 主节点质量 Q | 去重总 tokens | 去重调用 | 每任务服务时长 s |','|---|---:|---:|---:|---:|']
 for a,r in arms.items():lines.append(f"| {a} | {r['Q']:.4f} | {r['tokens_total']:.0f} | {r['deduplicated_calls']} | {r['mean_task_service_seconds']:.3f} |")
 lines+=['','## 配对比较（task-cluster bootstrap，10000次）','']
 for b in ['QueryRouter','AlwaysLarge','StaticCapability']:
  c=contrasts['FrozenNodeRouter_minus_'+b];lines.append(f"Node Router − {b}：ΔQ={c['Q_delta']*100:+.2f}pp，95% CI [{c['Q_ci95'][0]*100:.2f}, {c['Q_ci95'][1]*100:.2f}]pp；每题tokens差={c['tokens_per_task_delta']:+.1f}，CI {c['tokens_ci95']}。")
 lines+=['','## F1–F3','',f"F1（至少一个主要类型Node GAP>0）：{F1}。",f"F2（泛化方向）：{F2}；统计支持：{F2confirm}。",f"F3（quality recovery>0）：{F3}；Recovery={recovery}，CI {ci(bs_rec)}。BestFixed={POOL[bestj]}，quality oracle gap={gap:.6f}。",f"Static阶段最终确认：{results['gates']['Static_stage_confirmed']}。",'', '| Node Type | 节点 | BestFixed Q | Oracle Q | GAP | NodeRouter Q | Recovery |','|---|---:|---:|---:|---:|---:|---|']
 for typ,r in by_type.items():
  if r['n']:lines.append(f"| {typ}{' (exploratory)' if typ=='transformation' else ''} | {r['n']} | {r['Q_best_fixed']:.4f} | {r['arms_Q']['NodeOracle']:.4f} | {r['oracle_gap']:.4f} | {r['arms_Q']['FrozenNodeRouter']:.4f} | {r['quality_recovery']} |")
 lines+=['','## 冻结与边界','']+['- '+x for x in results['limitations']]+['','本轮完成后停止。不依据fresh结果修改参数或阈值，不重选模型，不启动Feedback、Dynamic DAG或Graph Forest，不推GitHub。']
 (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');core.write(OUT/'STATUS.json',dict(phase='COMPLETE',gates=results['gates'],next_experiment_started=False));print(json.dumps(dict(arms=arms,gates=results['gates'],quality_recovery=results['quality_recovery'])))

if __name__=='__main__':evaluate()
