import json,fcntl,hashlib,datetime,re
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
ROOT=Path('/root/r3_own_pool');p=ROOT/'router_v2/mmlu_utility_panel_400';d=ROOT/'data/mmlu_utility_repeats_400';out=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())
m=read(p/'MANIFEST.json');split=read(ROOT/'data/cohort_full_v2/split.json');cohort={r['query_id']:r for r in map(json.loads,(ROOT/'data/cohort_full_v2/queries.jsonl').read_text().strip().split('\n'))};panel={r['query_id']:r for r in map(json.loads,(p/'PANEL.jsonl').read_text().strip().split('\n'))};selection=read(p/'FOLD_SELECTION.json');g=read(m['groups'])['groups'];protocol=read(d/'COLLECTION_PROTOCOL.json')
checks={str(p/n):sha(p/n)==h for n,h in m['files'].items()}
checks.update({str(Path(m['source'])/n):sha(Path(m['source'])/n)==h for n,h in m['source_files'].items()})
checks[m['groups']]=sha(m['groups'])==m['groups_sha256'];checks['selector']=sha(ROOT/'router_v2/prepare_mmlu_utility_panel.py')==m['selector_sha256'];checks['engine']=sha(ROOT/'router_v2/run_repeat_stability.py')==protocol['engine_sha256']
source_protocol=read(Path(m['source'])/'PROTOCOL.json')
checks.update({k:sha(k)==h for k,h in source_protocol['input_sha256'].items()})
f=np.load(Path(m['source'])/'OOF.npz',allow_pickle=False);folds=dict(zip(f['ids'].tolist(),f['folds'].tolist()));fold_checks={}
for fold,chosen in selection.items():
 held={q for q,v in folds.items() if v==int(fold)}
 fold_checks[fold]={'train_count':len(chosen),'held_id_overlap':len(set(chosen)&held),'held_group_overlap':len({g[q] for q in chosen}&{g[q] for q in held})}
norm=lambda x:re.sub(r'\s+',' ',x.casefold()).strip()
text_index=defaultdict(list)
for q,r in cohort.items():text_index[norm(r['query'])].append(q)
summary={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hash_checks':checks,'panel_split_counts':{s:len(set(panel)&set(v)) for s,v in split.items() if isinstance(v,list)},'query_mismatch':sum(r['query']!=cohort[q]['query'] for q,r in panel.items()),'fold_checks':fold_checks,'cross_split_exact_prompt_matches':[(q,k) for q in panel for k in text_index[norm(panel[q]['query'])] if k not in split['train']],'cross_split_known_group_matches':[(q,k) for q in panel for k in split['validation']+split['test'] if g.get(q)==g.get(k)],'slots':{}}
validkeys={}
for slot in ('large','reasoning'):
 with (d/(slot+'.jsonl')).open() as stream:
  fcntl.flock(stream,fcntl.LOCK_SH);rows=[json.loads(line) for line in stream if line.strip()]
 keys=Counter((r['query_id'],r['repeat_index']) for r in rows);valid=[r for r in rows if r.get('status')!='failed' and not r.get('error') and r.get('quality') in (0,1)];validkeys[slot]={(r['query_id'],r['repeat_index']) for r in valid};per=Counter(q for q,k in validkeys[slot]);failed=[r for r in rows if r['status']=='failed' or r.get('error')]
 bad_provenance=sum(r.get('panel_sha256')!=protocol['panel_sha256'] or r.get('cohort_sha256')!=protocol['cohort_sha256'] or r['query_id'] not in panel or r.get('temperature')!=.7 or r.get('top_p')!=1 or r.get('slot')!=slot for r in rows)
 summary['slots'][slot]={'records':len(rows),'valid':len(validkeys[slot]),'statuses':dict(Counter(r['status'] for r in rows)),'failed_rows_with_numeric_quality':sum(r.get('quality') is not None for r in failed),'failed_keys':[{'query_id':r['query_id'],'repeat_index':r['repeat_index']} for r in failed],'duplicate_keys':sum(n>1 for n in keys.values()),'provenance_mismatch':bad_provenance,'complete_queries':sum(n==5 for n in per.values()),'models':dict(Counter(r.get('model') for r in rows)),'valid_missing_resources':sum(r.get('cost',{}).get('tokens_input') is None or r.get('cost',{}).get('tokens_output') is None or r.get('latency',{}).get('total_ms') is None for r in valid)}
summary['complete_pairs']=sum(all((q,k) in validkeys[s] for s in validkeys for k in range(5)) for q in panel)
summary['limits']=['Original test previously exposed; not an independent confirmation set.','Selected panel is opportunity-enriched, not representative of population.','Concurrency amendments confound observed latency; no matched-load latency claim.','Public benchmark pretraining contamination cannot be checked from these artifacts.','Current raw snapshot only; running collector may append after this audit.']
(out/'AUDIT.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(summary,indent=2,ensure_ascii=False))
