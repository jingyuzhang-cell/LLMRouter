import json,csv,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,'/root/.agents/skills/nature-figure/scripts')
from audit_panel_alignment import require_matplotlib_panel_alignment
out=Path(__file__).parent
root=Path('/root/research_outputs')
nd=json.load(open(root/'static_pi/stage_d/damjs_r2/v03/ND_CONFIRM_ANALYSIS.json'))
base=root/'QP5C_RECOVERY_MECHANISMS_20261103/LOCAL_FULL_RUN_20261104_R2'
r=json.load(open(base/'RESULTS.json'))
ledger=[json.loads(l) for l in open(base/'LEDGER.jsonl')]
pairs=[(k,v['R2']['calibers']['strict_norm_canon'],v['ND']['calibers']['strict_norm_canon'],v['d_strict']) for k,v in nd['pairs'].items()]
res={}
for arm in ['Full','Local']:
 rows=[x for x in ledger if x['event']=='RESPONSE' and '_'+arm+'_' in x['id']]
 res[arm]=[len(rows),sum(x['estimate_cny'] for x in rows),sum(x['recovery_wall_s'] for x in r['results'] if x['result']['arm']==arm)]
with open(out/'panel_a.csv','w') as f:
 w=csv.writer(f);w.writerow(['pair','overwrite_TP','protected_TP','difference']);w.writerows(pairs)
with open(out/'panel_b.csv','w') as f:
 w=csv.writer(f);w.writerow(['metric','Full','Local','Local_percent_of_Full']);w.writerows((m,res['Full'][i],res['Local'][i],100*res['Local'][i]/res['Full'][i]) for i,m in enumerate(['calls','estimated_CNY','recovery_wall_s']))
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['DejaVu Sans'],'font.size':8,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'svg.fonttype':'none'})
fig,ax=plt.subplots(1,2,figsize=(7.2,2.65))
fig.subplots_adjust(left=.085,right=.98,bottom=.24,top=.79,wspace=.42)
# Deterministic horizontal offsets distinguish equal paired observations; y values unchanged.
for i,(_,a,b,d) in enumerate(pairs):
 off=(i-3)*.035
 ax[0].plot([off,1+off],[a,b],color='#aab2b9',lw=.85,zorder=1)
 ax[0].scatter([off],[a],color='#6c7884',s=20,zorder=3)
 ax[0].scatter([1+off],[b],color='#2279a7',s=20,zorder=3)
ax[0].set(xlim=(-.28,1.28),ylim=(0,15),xticks=[0,1],xticklabels=['Overwrite','Protect valid snapshot'],ylabel='Terminal factual-match score (TP)')
ax[0].set_yticks([0,3,6,9,12,15])
ax[0].text(.5,1.07,'7 completed pairs; p = 0.015625',transform=ax[0].transAxes,ha='center',fontsize=8)
rat=np.array(res['Local'])/np.array(res['Full'])*100
x=np.arange(3)
ax[1].bar(x-.17,[100]*3,.32,color='#bbc3ca',label='Full')
ax[1].bar(x+.17,rat,.32,color='#2279a7',label='Local')
for i,v in enumerate(rat):ax[1].text(i+.17,v+3,f'{v:.1f}',ha='center',fontsize=7)
ax[1].set(ylim=(0,132),xticks=x,xticklabels=['Calls','Estimated\ncost','Recovery\nwall time'],ylabel='Resource use (% of Full)')
ax[1].set_yticks([0,25,50,75,100,125])
ax[1].legend(loc='upper center',ncol=2,frameon=False,fontsize=7)
for a,l,t in zip(ax,['a','b'],['Protection under recovery failure','Resource use by recovery scope']):
 a.text(-.16,1.22,l,transform=a.transAxes,fontweight='bold',fontsize=10)
 a.set_title(t,fontsize=8,pad=30)
 a.set_axisbelow(True);a.grid(axis='y',color='#e4e8eb',lw=.5)
fig.canvas.draw()
require_matplotlib_panel_alignment(fig,json_out=str(out/'alignment.json'),strict=True)
fig.savefig(out/'figure53.pdf')
fig.savefig(out/'figure53.svg')
fig.savefig(out/'figure53.png',dpi=600)
print(res)
