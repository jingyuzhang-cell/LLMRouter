"""Render frozen summary only; no model calls or new statistical analysis.
Overall stress response (a) and task-difficulty qualification (b).
180 mm wide; population SD; clean points have no replicate error bars.
"""
from pathlib import Path
import json, csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parent
src=P.parents[1]/'static_dag_v0/adaptive_benchmark/MULTI_SEED_RESULTS.json'
d=json.loads(src.read_text())
plt.rcParams.update({'font.size':8,'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(1,2,figsize=(180/25.4,85/25.4),sharey=True)
fig.subplots_adjust(left=.085,right=.98,bottom=.19,top=.77,wspace=.22)
rows=[]
for ax,key,title,clean in zip(axs,['per_rate','hard'],['a  Overall (120 tasks)','b  Hard subset (46 tasks)'],[[.55,.35,.4],[.3043,.2174,.3043]]):
 for i,(m,name,c,mark) in enumerate([('router','Single LLM (retry)','#0072B2','o'),('static','Static DAG','#777777','s'),('dynamic','Dynamic DAG','#D55E00','D')]):
  y=[clean[i]]+[d[key][str(r)][m]['mean'] for r in [.1,.2,.3]]
  sd=[0]+[d[key][str(r)][m]['std'] for r in [.1,.2,.3]]
  ax.plot([0,10,20,30],[v*100 for v in y],color=c,marker=mark,ms=4,lw=1.4,label=name)
  ax.errorbar([10,20,30],[v*100 for v in y[1:]],yerr=[v*100 for v in sd[1:]],fmt='none',ecolor=c,capsize=3,lw=1)
  for x,mean,std in zip([0,10,20,30],y,sd): rows.append([key,m,x,mean,'' if x==0 else std])
 ax.set_title(title,loc='left',fontsize=9,pad=9)
 ax.set(xlim=(-1.5,31.5),ylim=(0,60),xticks=[0,10,20,30],xlabel='Injected failure rate (%)')
 ax.grid(axis='y',alpha=.18)
axs[0].set_ylabel('Accuracy (%)')
fig.legend(*axs[0].get_legend_handles_labels(),loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.52,.98))
fig.canvas.draw()
for ext in ['png','pdf','svg']: fig.savefig(P/f'fig4_1_robustness.{ext}',dpi=300)
with (P/'fig4_1_source.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['panel','method','failure_rate_percent','mean','population_sd']);w.writerows(rows)
layout={'schema_version':1,'row_groups':[['0','1']],'figure':{'width_pt':fig.get_figwidth()*72,'height_pt':fig.get_figheight()*72},'panels':[]}
for i,ax in enumerate(axs):
 b=ax.get_position();layout['panels'].append({'id':str(i),'bbox_pt':[b.x0*fig.get_figwidth()*72,b.y0*fig.get_figheight()*72,b.x1*fig.get_figwidth()*72,b.y1*fig.get_figheight()*72],'row':0,'col':i})
(P/'fig4_1_layout.json').write_text(json.dumps(layout,indent=2))
