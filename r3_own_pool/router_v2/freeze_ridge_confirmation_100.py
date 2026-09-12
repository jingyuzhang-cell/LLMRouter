"""Freeze an outcome-blind 100-query prospective panel and Ridge decisions."""
import json
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from .data import load_cohort,read_rows,sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'router_v2/ridge_confirmation_100'
TRAIN_PANEL=ROOT/'router_v2/mmlu_utility_panel_400/PANEL.jsonl'
LABELS=ROOT/'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
EMBEDDINGS=ROOT/'data/embeddings_full_v2_recovery1/EMBEDDINGS.npz'
SLOTS=['medium','large','coder','reasoning']
USED=[ROOT/'router_v2/pool4_pilot_120/PANEL.jsonl',ROOT/'router_v2/knowledge_validation_400/PANEL.jsonl',TRAIN_PANEL]

def main():
 if OUT.exists():raise FileExistsError(OUT)
 cohort,split=load_cohort(ROOT/'data/cohort_full_v2');used=set()
 for path in USED:
  used|={r['query_id'] for r in read_rows(path)}
 candidate=sorted(q for q in split['train'] if cohort[q]['dataset']=='mmlupro' and q not in used)
 if len(candidate)!=100:raise ValueError(f'Expected exhaustive 100 unused queries, got {len(candidate)}')
 training=read_rows(TRAIN_PANEL);labels={r['query_id']:r for r in read_rows(LABELS)};train_ids=[r['query_id'] for r in training]
 if set(train_ids)!=set(labels):raise ValueError('Training panel/labels mismatch')
 with np.load(EMBEDDINGS,allow_pickle=False) as saved:
  index={q:i for i,q in enumerate(saved['ids'].tolist())};x=saved['vectors'].astype('float32');train_x=x[[index[q] for q in train_ids]];test_x=x[[index[q] for q in candidate]]
 y=np.array([[labels[q]['models'][s]['mean'] for s in SLOTS] for q in train_ids],dtype='float32')
 model=Ridge(alpha=1.0).fit(train_x,y);prediction=model.predict(test_x);choice=prediction.argmax(1)
 OUT.mkdir(parents=True)
 rows=[]
 for i,q in enumerate(candidate):
  c=cohort[q];rows.append({**{k:c[k] for k in ['query_id','query','dataset','task_type']},'panel_index':i,'planned_repeats':5})
 panel=OUT/'PANEL.jsonl';panel.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 decisions=[]
 for i,q in enumerate(candidate):decisions.append({'query_id':q,'panel_index':i,'choice_index':int(choice[i]),'choice_slot':SLOTS[choice[i]],'predicted_utility':dict(zip(SLOTS,map(float,prediction[i])))})
 decision_path=OUT/'FROZEN_DECISIONS.jsonl';decision_path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in decisions))
 np.savez_compressed(OUT/'RIDGE_MODEL_AND_PREDICTIONS.npz',coef=model.coef_,intercept=model.intercept_,train_ids=np.array(train_ids),test_ids=np.array(candidate),prediction=prediction,choice=choice)
 protocol={'role':'prospective confirmation of frozen Query-only Ridge','selection':'exhaustive set of train MMLU-Pro queries absent from pilot120, uniform knowledge400, and utility400; no outcome filtering','n':100,'primary_estimand':'paired mean expected-quality gain of frozen Ridge route versus R1 baseline under five temperature-.7 draws','primary_method':'Ridge(alpha=1) fit once on all corrected four-model utility400 repeat means; argmax fixed before confirmation generation','secondary':'selection distribution and per-subject paired gain; no oracle claim unless all four models are later collected','slots':SLOTS,'repeats':5,'temperature':.7,'top_p':1.0,'source_sha256':{'train_panel':sha(TRAIN_PANEL),'labels':sha(LABELS),'embeddings':sha(EMBEDDINGS),'panel':sha(panel),'decisions':sha(decision_path),'freezer':sha(Path(__file__))},'limits':['All queries belong to original train split; prospective outcomes are new, but this is not a public benchmark test split.','Only 100 unused train MMLU-Pro queries remain, limiting power.','Primary evaluation must include every frozen query and may not tune alpha, features, choices, or thresholds.']}
 (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
 print(json.dumps({'n':100,'selection_counts':dict(zip(SLOTS,np.bincount(choice,minlength=4).tolist())),'panel_sha256':sha(panel),'decisions_sha256':sha(decision_path)},indent=2))
if __name__=='__main__':main()
