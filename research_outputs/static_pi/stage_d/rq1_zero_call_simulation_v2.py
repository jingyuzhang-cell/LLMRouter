#!/usr/bin/env python3
"""RQ1 V1.5 zero-call simulation (synthetic; no API calls).
Fixes: true H0 equality, correct slot counts, 8/10 task extrapolation, external validation.
"""
import json,random,statistics as st
random.seed(20261102)
base=json.load(open('rq1_tasks/rq1_tasks_materials.json'))
ov=json.load(open('rq1_tasks/rq1_v1_5_overlay.json'))
TYPES=['extract','timeline','merge','reason','verification','report']
TYPE={
 'E04':{'fin_extract':'extract','reg_timeline':'timeline','biz_risk':'extract','anomaly_calc':'reason','cross_verify':'verification','final_report':'report'},
 'E05':{'ext_doc1':'timeline','ext_doc2':'extract','merge':'merge','report':'report'},
 'E06':{'ext_doc1':'extract','ext_doc2':'extract','ext_doc3':'extract','merge':'merge','report':'report'},
 'E07':{'ext_doc1':'extract','ext_doc2':'extract','ext_doc3':'extract','verify':'verification','report':'report'},
 'E08':{'ext_doc1':'extract','ext_doc2':'extract','ext_doc3':'extract','merge':'merge','report':'report'}}
COMPLEX={'E04':'HIGH','E05':'MEDIUM','E06':'MEDIUM','E07':'HIGH','E08':'MEDIUM'}
ORIG={'E04':29,'E05':11,'E06':12,'E07':11,'E08':10}
# node slots = base node fact_ids + derived gold (actual measured output)
NODE={}
for tid,t in base['tasks'].items():
    if tid not in TYPE: continue
    for n in t['nodes']:
        nid=n['node_id']
        derived=len(ov['derived_gold'].get(tid,{}).get(nid,[]))
        NODE[(tid,nid)]=len(n.get('fact_ids',[]))+derived
TASKSLOTS={t:sum(NODE[(t,n)] for n in TYPE[t]) for t in TYPE}

def exact_p_two(diffs):
    nz=[d for d in diffs if d!=0]; m=len(nz)
    if m==0: return 1.0
    order=sorted(range(m),key=lambda i:abs(nz[i])); ranks=[0.0]*m; i=0
    while i<m:
        j=i
        while j+1<m and abs(nz[order[j+1]])==abs(nz[order[i]]): j+=1
        r=(i+j+2)/2.0
        for k in range(i,j+1): ranks[order[k]]=r
        i=j+1
    W=sum(ranks[i] for i in range(m) if nz[i]>0); cg=cl=0
    for mask in range(1<<m):
        s=sum(ranks[i] for i in range(m) if (mask>>i)&1)
        if s>=W: cg+=1
        if s<=W: cl+=1
    return 2.0*min(cg,cl)/(1<<m)

def true_acc(model,typ,comp,cond,h2=False):
    if cond=='H0': return 0.62
    if model=='GLM':
        v=0.62+(0.15 if typ in ('merge','verification','report') else (-0.05 if typ in ('extract','timeline') else 0.0))
        if h2 and comp=='HIGH' and typ in ('merge','verification','report'): v+=0.10
    else:
        v=0.62+(0.15 if typ in ('extract','timeline') else (-0.05 if typ in ('merge','verification','report') else 0.0))
        if h2 and comp=='HIGH' and typ in ('merge','verification','report'): v-=0.05
    return max(0.05,min(0.95,v))

def observe(task_list,cond,h2=False,upstream=False,reps=2):
    obs={}
    for tid in task_list:
        for nid,typ in TYPE[tid].items():
            comp=COMPLEX[tid]
            for m in ('GLM','DS'):
                p=true_acc(m,typ,comp,cond,h2)
                if upstream: p*=0.85
                obs[(tid,nid,m)]=sum(1 for _ in range(reps) if random.random()<p)/float(reps)
    return obs

def strategy_q(obs,tid,strat,bu,tm_mod,rule):
    cov=0; slots=0
    for nid,typ in TYPE[tid].items():
        s=NODE[(tid,nid)]; slots+=s
        if strat=='Unified-GLM': m='GLM'
        elif strat=='Unified-DS': m='DS'
        elif strat=='Best-Unified': m=bu
        elif strat=='Node-Type': m=tm_mod.get(typ) or bu
        else: m=rule(typ,COMPLEX[tid])
        cov+=obs[(tid,nid,m)]*s
    return cov/float(slots)

def select(obs,tr):
    gm={m:st.mean([obs[(t,n,m)] for t in tr for n in TYPE[t]]) for m in ('GLM','DS')}
    bu='GLM' if gm['GLM']>=gm['DS'] else 'DS'
    tm_mod={}
    for typ in TYPES:
        vals={m:[obs[(t,n,m)] for t in tr for n,ty in TYPE[t].items() if ty==typ] for m in ('GLM','DS')}
        tm_mod[typ]=('GLM' if st.mean(vals['GLM'])>=st.mean(vals['DS']) else 'DS') if vals['GLM'] else None
    return bu,tm_mod

def rule(typ,comp):
    if comp=='HIGH' and typ in ('merge','verification','report'): return 'GLM'
    if typ in ('extract','timeline'): return 'DS'
    return 'GLM'

def one(cond,tasks,h2=False,upstream=False,external=False):
    obs=observe(tasks,cond,h2,upstream)
    # LOTO over tasks; for external, train on first 5, evaluate last 3
    if external:
        train,helds=tasks[:5],tasks[5:]
        bu,tm=select(obs,train)
        return {strat:[strategy_q(obs,h,strat,bu,tm,rule) for h in helds] for strat in ('Unified-GLM','Unified-DS','Node-Type','Task-Conditioned','Best-Unified')}
    out={s:[] for s in ('Unified-GLM','Unified-DS','Node-Type','Task-Conditioned','Best-Unified')}
    for held in tasks:
        tr=[t for t in tasks if t!=held]
        bu,tm=select(obs,tr)
        for s in out: out[s].append(strategy_q(obs,held,s,bu,tm,rule))
    return out

def fmt(d): return f'{d:+.4f}'

def run(cond,tasks,N=500,h2=False,upstream=False,external=False):
    dNT=[]; dTC=[]; pNT=[]; pTC=[]; q=[]
    for _ in range(N):
        r=one(cond,tasks,h2,upstream,external)
        kk=len(r['Node-Type'])
        a=[r['Node-Type'][i]-r['Best-Unified'][i] for i in range(kk)]
        b=[r['Task-Conditioned'][i]-r['Best-Unified'][i] for i in range(kk)]
        dNT.append(st.mean(a)); dTC.append(st.mean(b))
        pNT.append(exact_p_two(a)); pTC.append(exact_p_two(b))
        q.append(st.mean(r['Best-Unified']))
    n=len(dNT)
    def ci(x):
        if n<2: return (0,0)
        se=st.stdev(x)/n**0.5; mu=st.mean(x); return (mu-1.96*se,mu+1.96*se)
    return {'dNT':st.mean(dNT),'dTC':st.mean(dTC),'fpNT':sum(p<=0.05 for p in pNT)/n,'fpTC':sum(p<=0.05 for p in pTC)/n,
            'p0625_NT':sum(p<=0.0625 for p in pNT)/n,'p0625_TC':sum(p<=0.0625 for p in pTC)/n,
            'ciNT':ci(dNT),'ciTC':ci(dTC),'baseQ':st.mean(q)}

print('RQ1 V1.5 zero-call simulation v2 (synthetic)')
print('task node slots:',{t:NODE[(t,n)] for t in TYPE for n in TYPE[t]})
print('task slots:',TASKSLOTS,'sum',sum(TASKSLOTS.values()))
print('5-task exact two-sided min p (no zeros) = 2/32 = 0.0625; 8 = 2/256 =',2/256,'; 10 =',2/1024)
print('\n=== 5 tasks (E04-E08) ===')
for cond,h2,up in [('H0',False,False),('H1',False,False),('H2',True,False),('H1+upstream',False,True)]:
    r=run(cond,['E04','E05','E06','E07','E08'],N=400,h2=h2,upstream=up)
    print(f'{cond}: dNT={fmt(r["dNT"])} dTC={fmt(r["dTC"])} FP@.05={r["fpNT"]:.3f}/{r["fpTC"]:.3f} P(min<=.0625)={r["p0625_NT"]:.3f}/{r["p0625_TC"]:.3f} CI_NT=[{fmt(r["ciNT"][0])},{fmt(r["ciNT"][1])}]')
print('\n=== task-count sensitivity (H1) ===')
for k in (5,8,10):
    tasks=['E04','E05','E06','E07','E08'][:k] if k<=5 else ['E04','E05','E06','E07','E08']+[f'S{i}' for i in range(k-5)]
    if k>5:
        for t in tasks[5:]:
            TYPE[t]=dict(TYPE['E04']); COMPLEX[t]='HIGH'
            for nid in TYPE[t]: NODE[(t,nid)]=NODE[('E04',nid)]
    r=run('H1',tasks,N=250)
    print(f'N={k}: dNT={fmt(r["dNT"])} dTC={fmt(r["dTC"])} FP@.05={r["fpNT"]:.3f}/{r["fpTC"]:.3f} P(min<=.0625)={r["p0625_NT"]:.3f}/{r["p0625_TC"]:.3f}')
print('\n=== external validation (train 5, external 3) ===')
for xt in ('X1','X2','X3'):
    TYPE[xt]=dict(TYPE['E04']); COMPLEX[xt]='HIGH'
    for nid in TYPE[xt]: NODE[(xt,nid)]=NODE[('E04',nid)]
for cond in ('H0','H1','H2'):
    r=run(cond,['E04','E05','E06','E07','E08','X1','X2','X3'],N=300,h2=(cond=='H2'),external=True)
    print(f'{cond}: dNT={fmt(r["dNT"])} dTC={fmt(r["dTC"])} FP@.05={r["fpNT"]:.3f}/{r["fpTC"]:.3f}')
print('\nSynthetic only; no real model calls.')

# === supplementary: true-effect bias, CI coverage, fact-equal, coverage, cost (fixed seed) ===
def true_q(tid,strat,true_bu,true_tm,true_rule):
    cov=0; slots=0
    for nid,typ in TYPE[tid].items():
        s=NODE[(tid,nid)]; slots+=s
        comp=COMPLEX[tid]
        if strat=='Unified-GLM': m='GLM'
        elif strat=='Unified-DS': m='DS'
        elif strat=='Best-Unified': m=true_bu
        elif strat=='Node-Type': m=true_tm.get(typ) or true_bu
        else: m=true_rule(typ,comp)
        cov+=true_acc(m,typ,comp,'H1')*s
    return cov/float(slots)

def true_effects(cond='H1',h2=False):
    T5=['E04','E05','E06','E07','E08']
    # true model ranking by type is deterministic
    tbu='GLM'  # overall GLM wins on 3 of 6 types
    ttm={t:('GLM' if t in ('merge','verification','report') else 'DS') for t in TYPES}
    vals={s:[] for s in ('Node-Type','Task-Conditioned','Best-Unified')}
    for tid in T5:
        for s in vals: vals[s].append(true_q(tid,s,tbu,ttm,rule))
    dNT=[vals['Node-Type'][i]-vals['Best-Unified'][i] for i in range(len(T5))]
    dTC=[vals['Task-Conditioned'][i]-vals['Best-Unified'][i] for i in range(len(T5))]
    return sum(dNT)/len(dNT),sum(dTC)/len(dTC),vals

print('\n=== true effect and bias (synthetic) ===')
tnt,ttc,_=true_effects()
print(f'true dNT={tnt:+.4f} true dTC={ttc:+.4f}')
# fact-equal on the same 5-task draws
def one_diffs(cond='H1',h2=False):
    obs=observe(['E04','E05','E06','E07','E08'],cond,h2)
    bu,tm=select(obs,['E05','E06','E07','E08'])  # proxy fold: hold E04
    q={s:strategy_q(obs,'E04',s,bu,tm,rule) for s in ('Node-Type','Task-Conditioned','Best-Unified')}
    return q
# fact-equal across tasks: use per-task strategy TP counts; report mean ratio
fe_nt=[]; fe_tc=[]
for _ in range(300):
    obs=observe(['E04','E05','E06','E07','E08'],'H1',False)
    for held in ['E04','E05','E06','E07','E08']:
        tr=[t for t in ['E04','E05','E06','E07','E08'] if t!=held]; bu,tm=select(obs,tr)
        a=strategy_q(obs,held,'Node-Type',bu,tm,rule); b=strategy_q(obs,held,'Task-Conditioned',bu,tm,rule); c=strategy_q(obs,held,'Best-Unified',bu,tm,rule)
        w=TASKSLOTS[held]
        fe_nt.append((a-c,w)); fe_tc.append((b-c,w))
def wmean(v): return sum(x*w for x,w in v)/sum(w for x,w in v)
print(f'fact-equal dNT={wmean(fe_nt):+.4f} dTC={wmean(fe_tc):+.4f} (task-equal means above)')
print('\n=== coverage insufficiency: reason only in E04 ===')
tr=[t for t in ['E04','E05','E06','E07','E08'] if t!='E04']
has=any('reason' in TYPE[t].values() for t in tr)
print('held-out E04: training has reason?',has,'-> fallback to global training baseline (pre-registered), not a type estimate')
print('\n=== cost / calls (per strategy, 25 nodes x 2 reps) ===')
for s in ('Unified-GLM','Unified-DS','Node-Type','Task-Conditioned','Best-Unified'):
    print(f'{s}: 50 calls (Best-Unified reuses an arm; 0 incremental)')
print('Layer-1 fixed input: 100 calls; total matrix: 300 calls. No hidden calls in simulation.')
print('\nSynthetic only; no real model calls.')
