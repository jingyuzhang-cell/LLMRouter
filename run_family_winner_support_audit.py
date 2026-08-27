#!/usr/bin/env python3
"""Audit within-family winner support before C2 modeling."""
import json, math
from collections import Counter
from pathlib import Path
import numpy as np

ROOT=Path('/root'); EXP=ROOT/'target_support_expansion_v1'; OUT=ROOT/'phase_c2'; OUT.mkdir(exist_ok=True)
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); TIE=.01
def read(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
tasks={x['id']:x for x in read(EXP/'combined_509_tasks_frozen.jsonl')}; rows=read(EXP/'combined_509_task_model_matrix_frozen.jsonl'); outcomes={(x['task_id'],x['model']):x for x in rows}
def family(t):
    x=tasks[t]; return f"{x['dataset']}:{x['risk_level']}"
report={}
for fam in ('TAT-QA:low','TAT-QA:medium','ObliQA:high'):
    ids=sorted(t for t in tasks if family(t)==fam); winners=Counter(); unique=Counter()
    for t in ids:
        ranked=sorted(MODELS,key=lambda m:outcomes[(t,m)]['utility'],reverse=True); winners[ranked[0]]+=1
        if outcomes[(t,ranked[0])]['utility']-outcomes[(t,ranked[1])]['utility']>TIE: unique[ranked[0]]+=1
    means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in ids])) for m in MODELS}; best=max(means,key=means.get); oracle=float(np.mean([max(outcomes[(t,m)]['utility'] for m in MODELS) for t in ids])); rates={m:winners[m]/len(ids) for m in MODELS}; supported=sum(v>.10 for v in rates.values())
    probs=[v/len(ids) for v in winners.values() if v]; entropy=-sum(p*math.log(p) for p in probs)/math.log(len(MODELS))
    report[fam]={'n':len(ids),'winner_counts':dict(winners),'winner_rates':rates,'unique_winner_counts':dict(unique),'models_above_10pct':supported,'winner_support_gate':supported>=2,'best_single_model':best,'best_single_utility':means[best],'oracle_utility':oracle,'oracle_gap':oracle-means[best],'normalized_winner_entropy':entropy}
result={'tie_margin':TIE,'family_gate_definition':'at least two models with oracle-win rate strictly above 10%','families':report,'all_families_pass':all(x['winner_support_gate'] for x in report.values())}
(OUT/'FAMILY_WINNER_SUPPORT_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(result,ensure_ascii=False,indent=2))
