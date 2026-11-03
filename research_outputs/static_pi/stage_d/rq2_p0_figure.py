import json, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=json.load(open('RQ2_P0_TERMINAL_ANATOMY.json'))
names=['Static','MGC-m','MGC-mv','Node-Type','V-CR-m']
labels=['Static\n(DS)','MGC\n(m)','MGC\n(m+v)','Node-Type','V-CR\n(conservative)']
cats=['pass','fact_FN','fact_FP','loc','sup','gate']
colors=['#4c72b0','#c44e52','#dd8452','#55a868','#8172b3','#937860']
vals={c:[] for c in cats}
for n in names:
    d=R[n]['cat_gate_first']
    for c in cats: vals[c].append(d[c]*100)
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(15,5.6),dpi=150)
bottom=np.zeros(len(names))
for c,col,lab in zip(cats,colors,['pass (Q)','FN','FP','loc','sup','gate']):
    ax1.bar(labels,vals[c],bottom=bottom,color=col,label=lab,width=0.62)
    bottom+=np.array(vals[c])
for i,n in enumerate(names):
    ax1.text(i,101.5,f"Q={R[n]['Q']*100:.1f}%",ha='center',fontsize=9,fontweight='bold')
ax1.set_ylim(0,108); ax1.set_ylabel('share of 13 terminal slots (%)')
ax1.set_title('Terminal-Q loss decomposition (stable .20, 800 tasks)',fontsize=10)
ax1.legend(fontsize=7,ncol=3,loc='lower center',bbox_to_anchor=(0.5,-0.23),frameon=False)
ax1.grid(axis='y',alpha=.2)
# upper bounds
b=R['V-CR-m']['bounds']
order=[('fact_only','fact only'),('loc_only','loc only'),('sup_only','sup only'),
       ('gate_only','gate only'),('loc_sup','loc+sup'),('fact_loc_sup','fact+loc+sup')]
ys=np.arange(len(order))[::-1]
for y,(k,lab) in zip(ys,order):
    v=b[k]*100
    ax2.barh(y,v,color='#4c72b0' if v<70 else '#55a868',height=.55)
    ax2.text(v+1,y,f'{v:.1f}%',va='center',fontsize=8)
ax2.axvline(70,color='#c44e52',ls='--',lw=1.2)
ax2.text(70.5,ys[0]+.4,'70% target',color='#c44e52',fontsize=8)
ax2.set_yticks(ys); ax2.set_yticklabels([l for _,l in order],fontsize=8)
ax2.set_xlim(0,105); ax2.set_xlabel('perfect-repair upper bound (%)')
ax2.set_title('V-CR quality upper bounds (non-deployable)',fontsize=10)
ax2.grid(axis='x',alpha=.2)
fig.suptitle('RQ2 P0: where terminal Q is lost, and which repair scope crosses 70%',fontsize=12)
fig.tight_layout()
fig.savefig('RQ2_P0_TERMINAL_ANATOMY.png',dpi=300,bbox_inches='tight')
print('wrote RQ2_P0_TERMINAL_ANATOMY.png')
