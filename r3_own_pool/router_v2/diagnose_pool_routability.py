"""Dataset-stratified diagnostics on existing pilot predictions only."""
import json,itertools
from pathlib import Path
import numpy as np
from .data import sha
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'router_v2/pool_routability_diagnosis'

def stats(q,base,slots):
 n,k=q.shape;oracle=q.max(1);unique=q.sum(1)==1;counts=q[unique].sum(0)
 entropy=None
 if counts.sum():
  p=counts[counts>0]/counts.sum();entropy=float(-(p*np.log2(p)).sum()/np.log2(k))
 pairs={};valid=[]
 for i,j in itertools.combinations(range(k),2):
  corr=float(np.corrcoef(q[:,i],q[:,j])[0,1]) if np.std(q[:,i])>0 and np.std(q[:,j])>0 else None
  pairs[slots[i]+' / '+slots[j]]=corr
  if corr is not None:valid.append(corr)
 gain=oracle-base
 return dict(n=n,oracle_accuracy=float(oracle.mean()),datasetbest_oof_accuracy=float(base.mean()),oracle_gap=float(gain.mean()),oracle_gap_count=int(gain.sum()),best_single_in_sample_accuracy=float(q.mean(0).max()),oracle_minus_best_single_in_sample=float(oracle.mean()-q.mean(0).max()),winner_entropy_unique_normalized=entropy,unique_winner_ratio=float(unique.mean()),unique_winner_count=int(unique.sum()),unique_wins=dict(zip(slots,counts.astype(int).tolist())),mean_model_correlation=float(np.mean(valid)) if valid else None,valid_correlation_pairs=len(valid),pair_correlations=pairs,all_correct=int((q.sum(1)==k).sum()),all_wrong=int((q.sum(1)==0).sum()),accuracy=dict(zip(slots,q.mean(0).tolist())))

def main():
 src=ROOT/'router_v2/coder_pilot_results';panel=ROOT/'router_v2/pool4_pilot_120/PANEL.jsonl';gp=ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json'
 for path,h in json.loads((src/'PROVENANCE.json').read_text()).items():assert sha(Path(path))==h
 a=np.load(src/'PREDICTIONS.npz');ids=a['ids'];y=a['quality'];folds=a['folds'];dsmap={r['query_id']:r['dataset'] for r in map(json.loads,panel.read_text().splitlines())};ds=np.array([dsmap[q] for q in ids]);groupsmap=json.loads(gp.read_text())['groups'];groups=np.array([groupsmap[q] for q in ids]);assert len(ids)==120
 specs={'coder_four':([0,1,3,4],['Qwen7B','Large','Coder','R1']),'with_glm_four':([0,1,2,4],['Qwen7B','Large','GLM','R1']),'all_five':([0,1,2,3,4],['Qwen7B','Large','GLM','Coder','R1'])};masks={'代码':np.isin(ds,['mbpp','humaneval']),'数学':ds=='gsm8k','知识':ds=='mmlupro','HumanEval':ds=='humaneval','MBPP':ds=='mbpp'};result={}
 for pool,(cols,slots) in specs.items():
  q=y[:,cols];base=y[np.arange(120),a[pool+'_DatasetBest']]
  # Independently reproduce each held-fold dataset selector.
  for fold in np.unique(folds):
   tr=folds!=fold;va=folds==fold;assert not set(groups[tr])&set(groups[va])
   for task in np.unique(ds):
    choice=q[tr&(ds==task)].mean(0).argmax();at=va&(ds==task);assert np.array_equal(base[at],q[at,choice])
  result[pool]={}
  for name,mask in masks.items():
   st=stats(q[mask],base[mask],slots);g=groups[mask];gain=q[mask].max(1)-base[mask];ug=np.unique(g);rng=np.random.default_rng(20260914);sums=np.array([gain[g==v].sum() for v in ug]);sizes=np.array([(g==v).sum() for v in ug]);draw=rng.integers(0,len(ug),size=(5000,len(ug)));ci=np.quantile(sums[draw].sum(1)/sizes[draw].sum(1),[.025,.975]);st['gap_ci95_conditional_oof']=ci.tolist();result[pool][name]=st
 OUT.mkdir(exist_ok=False);(OUT/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');(OUT/'PROTOCOL.json').write_text(json.dumps({'inputs':{str(p):sha(p) for p in [src/'PREDICTIONS.npz',panel,gp,Path(__file__)]},'main_pool':'coder_four','oracle_gap':'Oracle minus held-fold DatasetBest, original dataset labels retained for code aggregate','winner_entropy':'Shannon entropy of strictly unique winners, divided by log2(number of models); null when no unique winners','unique_ratio':'queries with exactly one correct model / all queries','correlation':'unweighted mean of defined pairwise Pearson correlations of binary correctness (phi); constant columns produce null, never zero','bootstrap':'5000 prompt-group resamples; fixed saved OOF predictions, not full model-refit uncertainty','new_generations':0},ensure_ascii=False,indent=2)+'\n')
 lines=['# 路由可行性诊断','','主模型池：Qwen7B、Large、Coder、R1。现有120题，每大类40题。','','| Dataset | Oracle Gap | Winner entropy | Unique winner ratio | Model correlation |','|---|---:|---:|---:|---:|']
 for name,s in result['coder_four'].items():
  h='N/A' if s['winner_entropy_unique_normalized'] is None else f"{s['winner_entropy_unique_normalized']:.3f}"
  c='N/A' if s['mean_model_correlation'] is None else f"{s['mean_model_correlation']:.3f}"
  lines.append(f"| {name}（{s['n']}题） | {s['oracle_gap']:.2%}（{s['oracle_gap_count']}题） | {h} | {s['unique_winner_ratio']:.2%} | {c}（{s['valid_correlation_pairs']}对） |")
 lines+=['','Gap=Oracle−折外DatasetBest；代码汇总仍分别按MBPP/HumanEval选择基线，避免任务混合制造假gap。','Winner entropy只对独有赢家分布计算并归一化至[0,1]；全对并列不分配winner。没有独有赢家则N/A，熵本身不能证明可路由。','Model correlation为二元正确性两两Pearson/phi的平均；恒定正确性列相关性未定义，不填0。矩阵和各模型独有胜题数见RESULTS.json。','', '## 原GLM四模型池对照']
 for name in ['代码','数学','知识']:
  s=result['with_glm_four'][name];lines.append(f"- {name}：Gap {s['oracle_gap']:.2%}，独有赢家{s['unique_winner_count']}/{s['n']}。")
 lines+=['','## 判断与限制']
 for name in ['代码','数学','知识']:
  s=result['coder_four'][name];ci=s['gap_ci95_conditional_oof'];lines.append(f"- {name}：Oracle {s['oracle_accuracy']:.2%}，DatasetBest {s['datasetbest_oof_accuracy']:.2%}，Gap {s['oracle_gap']:.2%}，条件bootstrap区间[{ci[0]:.2%}, {ci[1]:.2%}]；Oracle−样本内最佳单模型{s['oracle_minus_best_single_in_sample']:.2%}。")
 lines+=['','这是原train小样本探索性诊断，部分旧评分协议与新模型提取不同；子任务筛选后不能把同120题用作确认性论文结果。相关性会受准确率天花板影响。条件bootstrap固定既有预测，不涵盖完整训练/筛选不确定性。']
 (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');print((OUT/'REPORT.md').read_text())
if __name__=='__main__':main()
