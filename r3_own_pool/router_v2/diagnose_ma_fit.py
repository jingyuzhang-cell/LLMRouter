import json
from pathlib import Path
import numpy as np
import torch
from .simple_quality_ma import QualityMA
from .mmlu_learnability import validate_pairs,metrics
from .diagnose_rank_signal import load_inputs
ROOT=Path(__file__).resolve().parents[1]
def main():
 torch.set_num_threads(4);p=ROOT/'router_v2/mmlu_utility_panel_400';m,labels=validate_pairs(p,ROOT/'data/mmlu_utility_repeats_400_recovered_b');f,x,_=load_inputs(m['source']);index={q:i for i,q in enumerate(f['ids'])};result={}
 for experiment in ['experiment_B_simple_quality_ma','experiment_C_quality_plus_delta_ma']:
  source=ROOT/'router_v2'/experiment;folds=json.loads((source/'FOLDS.json').read_text());rows=[]
  for fold in folds:
   for seed in (42,43,44):
    net=QualityMA(x.shape[1]);net.load_state_dict(torch.load(source/f"model_fold{fold['fold']}_seed{seed}.pt",map_location='cpu',weights_only=True));net.eval();row=dict(fold=fold['fold'],seed=seed)
    for split,key in [('train','train_ids'),('val','panel_eval_ids')]:
     ids=fold[key];xx=x[[index[q] for q in ids]];y=np.array([labels[q]['target']['delta_quality_empirical'] for q in ids])
     with torch.no_grad():pred=net(torch.tensor(xx,dtype=torch.float32)).numpy()
     row[split]=metrics(pred[:,1]-pred[:,0],y)
    rows.append(row)
  result[experiment]=dict(folds_seeds=rows,mean_train_r2=float(np.mean([r['train']['r2'] for r in rows])),mean_val_r2=float(np.mean([r['val']['r2'] for r in rows])))
 out=ROOT/'router_v2/experiment_D_fit_diagnosis';out.mkdir(exist_ok=False);(out/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:{a:b for a,b in v.items() if a!='folds_seeds'} for k,v in result.items()},indent=2))
if __name__=='__main__':main()
