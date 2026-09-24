"""Budget curves from frozen summaries, no new calls/statistical estimates.
Question: under what budget does failure robustness translate into completion?
Panels: clean control, moderate faults, high-fault crossover. Python/matplotlib.
"""
from pathlib import Path
import csv,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parent
src=P.parents[1]/'static_dag_v0/adaptive_benchmark/MULTIOBJECTIVE_TRADEOFF.json'
d=json.loads(src.read_text());budgets=d['budgets']
plt.rcParams.update({'font.size':7,'pdf.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'budget4-2','axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(1,3,figsize=(180/25.4,80/25.4),sharey=True)
fig.subplots_adjust(left=.085,right=.98,bottom=.20,top=.77,wspace=.16)
rows=[]
for ax,scene,title in zip(axs,['clean','fault20','fault30'],['a  Clean','b  Fault 20%','c  Fault 30%']):
 for m,name,c,mk in [('router','Single LLM','#0072B2','o'),('static','Static DAG','#777777','s'),('dynamic','Dynamic DAG','#D55E00','D')]:
  vals=d['T2_budget_curves'][scene][m]
  y=[vals[str(b)] if scene=='clean' else vals[str(b)]['mean'] for b in budgets]
  sd=[0 if scene=='clean' else vals[str(b)]['std'] for b in budgets]
  ax.plot(budgets,y,color=c,marker=mk,ms=3,lw=1.2,label=name)
  if scene!='clean': ax.errorbar(budgets,y,yerr=sd,fmt='none',ecolor=c,capsize=2,lw=.8)
  for b,mean,err in zip(budgets,y,sd): rows.append([scene,m,b,mean,'' if scene=='clean' else err])
 ax.set_title(title,loc='left',fontsize=8,pad=8)
 ax.set(xlim=(450,3150),ylim=(0,.60),xticks=[600,1500,3000],xlabel='Budget (tokens)')
 ax.grid(axis='y',alpha=.18)
axs[0].set_ylabel('Budgeted success Q(B)')
fig.legend(*axs[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.52,.98),ncol=3,frameon=False)
fig.canvas.draw()
for ext in ['png','pdf','svg']:
 meta={'CreationDate':None,'ModDate':None} if ext=='pdf' else {'Date':None} if ext=='svg' else None
 fig.savefig(P/f'fig4_2_budget_quality.{ext}',dpi=300,metadata=meta)
with (P/'fig4_2_source.csv').open('w') as f:
 w=csv.writer(f,lineterminator="\n");w.writerow(['scenario','method','budget_tokens','mean','sample_sd']);w.writerows(rows)
layout={'schema_version':1,'row_groups':[['0','1','2']],'figure':{'width_pt':fig.get_figwidth()*72,'height_pt':fig.get_figheight()*72},'panels':[]}
for i,ax in enumerate(axs):
 b=ax.get_position();layout['panels'].append({'id':str(i),'bbox_pt':[b.x0*fig.get_figwidth()*72,b.y0*fig.get_figheight()*72,b.x1*fig.get_figwidth()*72,b.y1*fig.get_figheight()*72],'row':0,'col':i})
(P/'fig4_2_layout.json').write_text(json.dumps(layout,indent=2))

svg=P/"fig4_2_budget_quality.svg"
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines())+"\n")
