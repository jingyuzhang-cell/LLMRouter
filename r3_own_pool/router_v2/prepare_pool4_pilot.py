import json
from pathlib import Path
import numpy as np
from .data import load_cohort,read_rows,sha
from .integrity import require_valid_quality
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'router_v2/pool4_pilot_120';out.mkdir(exist_ok=True);cohort,split=load_cohort(ROOT/'data/cohort_full_v2');rng=np.random.default_rng(20260912);ids=[]
 # Fixed dataset-stratified random choice before reading quality outcomes.
 for ds,n in [('mmlupro',40),('gsm8k',40),('mbpp',20),('humaneval',20)]:
  candidates=sorted(q for q in split['train'] if cohort[q]['dataset']==ds);ids+=rng.choice(candidates,n,replace=False).tolist()
 panel=[{k:cohort[q][k] for k in ['query_id','query','dataset','task_type']} for q in sorted(ids)]
 target=out/'PANEL.jsonl'
 if target.exists():raise RuntimeError('Panel already frozen')
 target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in panel))
 matrix=ROOT/'data/clean_splits_verified_20260910b/TRAIN_MATRIX.jsonl';by={r['query_id']:r for r in read_rows(matrix)};rows=[]
 for q in sorted(ids):
  r=by[q];responses=[x for x in r['responses'] if x['slot'] in ['medium','large','reasoning']]
  assert len(responses)==3
  for x in responses:require_valid_quality(x)
  rows.append(dict(query_id=q,query=r['query'],dataset=r['dataset'],task_type=r['task_type'],responses=responses))
 (out/'EXISTING_3MODEL_MATRIX.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 plan=dict(seed=20260912,n=120,strata={'mmlupro':40,'gsm8k':40,'mbpp':20,'humaneval':20},selection='uniform within datasets, train only; never filter by old model errors',slots=['medium','large','glm','reasoning'],existing_reused_cells=360,new_glm_generations=120,max_glm_transport_requests=240,glm_checkpoint='zai-org/glm-4-9b-chat-hf',glm_revision='8599336fc6c125203efb2360bfaf4c80eef1d1bf',new_generation_temperature=0,new_generation_top_p=1.,stage='single-generation compatibility pilot; repeat only after screening',panel_sha256=sha(target),matrix_source_sha256=sha(matrix),cohort_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),split_sha256=sha(ROOT/'data/cohort_full_v2/split.json'),limits=['Existing answers keep historical deployment and resource metadata; compare quality first, no matched-load latency claim','No independent test use; final confirmation requires new data','Full GLM weights require18.80GB; current model disk free~13GB; download blocked on capacity'])
 (out/'PROTOCOL.json').write_text(json.dumps(plan,indent=2)+'\n');print(json.dumps(plan,indent=2))
if __name__=='__main__':main()
