#!/usr/bin/env python3
"""P2-0: node-level failure structure and rebuildability (zero-call, existing data only).
M1 reason failure records; M2 co-recovery potential (analytic fresh-draw expectations,
CRN-swap correlated bound); M3 per-node DS/GLM capability; M4 rebuild cost/latency
feasibility arithmetic under frozen caps. No new mechanism, no parameters changed.
"""
import os, json, numpy as np
from rq1_v1_8_2_r5_core import (FACT_PARENTS, DEC, RATES, PRICE, LAT, BASE_LAT,
    prep_all, run_fast, mask_to_assign, FP_RATE)
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool

OUT = os.path.dirname(os.path.abspath(__file__))
cfg = SCENARIOS[2]
N = 800
ts = task_pool(N, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
P = prep_all(ts, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
NODES = ['e0','e1','t','m','r','v','p']
DS, GLM = mask_to_assign(127), mask_to_assign(0)

def states(assign):
    out=[]; loc=[]; sup=[]; eok=[]; qexec=[]
    for p in P:
        o,l,s,e = run_fast(p, assign)
        out.append(o); loc.append(l); sup.append(s); eok.append(e)
        qn={}
        for ni in range(7):
            vals=[o[pn][pf]==0 for fi in (0,1) for (pn,pf) in FACT_PARENTS[ni][fi]]
            qn[ni]=1.0 if not vals else float(np.mean(vals))
        qexec.append(qn)
    return out, loc, sup, eok, qexec

oD,lD,sD,eD,qD = states(DS)
oG,lG,sG,eG,qG = states(GLM)

# ---- M1: reason failure records (all-DS base)
rbad_tasks=0; r_bad_facts=0; r_fn=0; r_fp=0; r_execfail=0; both_bad=0; r0_bad=0; r1_bad=0
q_when_rbad=[]
for i in range(N):
    b0 = not (oD[i][4][0]==0 and lD[i][4][0] and sD[i][4][0])
    b1 = not (oD[i][4][1]==0 and lD[i][4][1] and sD[i][4][1])
    if not (b0 or b1): continue
    rbad_tasks+=1
    if b0: r0_bad+=1
    if b1: r1_bad+=1
    if b0 and b1: both_bad+=1
    for bi,f_ in ((b0,0),(b1,1)):
        if not bi: continue
        r_bad_facts+=1
        if oD[i][4][f_]==2: r_fn+=1
        elif oD[i][4][f_]==1: r_fp+=1
        if not eD[i][4]: r_execfail+=1
    q_when_rbad.append(qD[i][4])
M1={'tasks_with_r_bad':rbad_tasks,'share':rbad_tasks/N,
    'r_bad_facts':r_bad_facts,'FN':r_fn,'FP':r_fp,'exec_fail_node':r_execfail,
    'r0_bad':r0_bad,'r1_bad':r1_bad,'both_bad':both_bad,
    'P(both|>=1 bad)':both_bad/max(1,rbad_tasks),
    'mean_parent_q_when_bad':float(np.mean(q_when_rbad)),
    'parent_q_lt_0.5_share':float(np.mean([q<0.5 for q in q_when_rbad]))}

# ---- M3: per-node capability DS vs GLM (own slots, no gate)
cap={}
for ni in range(7):
    slots=[fi for fi in (0,1) if (ni,fi) in DEC]
    pd_=np.mean([oD[i][ni][fi]==0 and lD[i][ni][fi] and sD[i][ni][fi] for i in range(N) for fi in slots])
    pg_=np.mean([oG[i][ni][fi]==0 and lG[i][ni][fi] and sG[i][ni][fi] for i in range(N) for fi in slots])
    td=np.mean([oD[i][ni][fi]==0 for i in range(N) for fi in slots])
    tg=np.mean([oG[i][ni][fi]==0 for i in range(N) for fi in slots])
    cap[NODES[ni]]={'DS_slot_pass':float(pd_),'GLM_slot_pass':float(pg_),
                    'DS_TP':float(td),'GLM_TP':float(tg)}

# ---- M2: analytic fresh-draw rebuild expectations, conditioned on node bad
def pp_model(p, ni, m, q):
    b=p['base'][m][ni]
    v=b*(0.35+0.65*q)
    if ni==5: v=v+0.30*(1-q)*(1-b)
    return max(0.02,min(0.98,v))
Rloc={0:RATES['loc'][0],1:RATES['loc'][1]}
Rsup={0:RATES['sup'][0],1:RATES['sup'][1]}
Rexec={0:RATES['parse'][0]*RATES['contract'][0],1:RATES['parse'][1]*RATES['contract'][1]}
def node_bad(i,ni):
    return any(not(oD[i][ni][fi]==0 and lD[i][ni][fi] and sD[i][ni][fi]) for fi in (0,1) if (ni,fi) in DEC) or (ni==6 and not eD[i][6])
rebuild={}
for ni in range(7):
    bad_idx=[i for i in range(N) if node_bad(i,ni)]
    entry={'bad_tasks':len(bad_idx),'share':len(bad_idx)/N}
    for m,mn in ((1,'DS'),(0,'GLM')):
        own=0.0; conv=0.0; bothfix=0.0; at_least1=0.0
        for i in bad_idx:
            q=qD[i][ni]
            pe=Rexec[m]
            ps=[pp_model(P[i],ni,m,q)*Rloc[m]*Rsup[m]*pe for fi in (0,1) if (ni,fi) in DEC]
            own+=sum(ps)
            bads=[fi for fi in (0,1) if (ni,fi) in DEC and not(oD[i][ni][fi]==0 and lD[i][ni][fi] and sD[i][ni][fi])]
            conv+=sum(ps[fi] for fi in bads) if len(ps)==2 else 0
            # careful indexing: ps built over DEC facts of the node in order
            # recompute mapping
        # redo with explicit mapping
        conv=0.0; bothfix=0.0
        for i in bad_idx:
            q=qD[i][ni]; pe=Rexec[m]
            slot_fis=[fi for fi in (0,1) if (ni,fi) in DEC]
            ppass={fi: pp_model(P[i],ni,m,q)*Rloc[m]*Rsup[m]*pe for fi in slot_fis}
            bads=[fi for fi in slot_fis if not(oD[i][ni][fi]==0 and lD[i][ni][fi] and sD[i][ni][fi])]
            conv+=sum(ppass[fi] for fi in bads)
            if bads and all(ppass[fi]>0 for fi in bads):
                bothfix+=float(np.prod([ppass[fi] for fi in bads]))
        nb=len(bad_idx)
        entry[mn]={'own_expected_pass_per_rebuild':own/nb,
                   'expected_new_conversions_per_rebuild':conv/nb,
                   'P(all_bad_facts_recoverable)':bothfix/nb}
    # downstream first-order: p0 q change for r rebuild
    rebuild[NODES[ni]]=entry
# downstream effect of rebuilding r (first-order, expected q)
down={}
for m,mn in ((1,'DS'),(0,'GLM')):
    dq=0.0; conv_p0=0.0
    for i in range(N):
        if not node_bad(i,4): continue
        q=qD[i][4]; pe=Rexec[m]
        p_r0=pp_model(P[i],4,m,q)*Rloc[m]*Rsup[m]*pe
        # p0 parents: (4,0) rebuilt, (5,0) unchanged
        tp_r0 = p_r0  # expectation of indicator
        tp_v0 = 1.0 if oD[i][5][0]==0 else 0.0
        q_new=(tp_r0+tp_v0)/2.0; q_old=(tp_r0*0+ (1.0 if oD[i][4][0]==0 else 0.0)+tp_v0)/2.0
        pp_old=pp_model(P[i],6,1,q_old); pp_new=pp_model(P[i],6,1,q_new)
        conv_p0 += max(0.0, pp_new*Rloc[1]*Rsup[1]*Rexec[1] - pp_old*Rloc[1]*Rsup[1]*Rexec[1]) * (0.0 if (oD[i][6][0]==0 and lD[i][6][0] and sD[i][6][0]) else 1.0)
        dq += q_new-q_old
    n_rbad=M1['tasks_with_r_bad']
    down[mn]={'expected_dq_p0':dq/n_rbad,'expected_extra_p0_conversions_per_task':conv_p0/n_rbad}

# ---- M4: cost/latency arithmetic
base_cost=float(np.mean(PRICE[DS])); base_mk=2.85
crit=[0,1,3,4,6]
# node finish times under all-DS (unlimited workers)
lat={ni:BASE_LAT[ni]*LAT[DS[ni]] for ni in range(7)}
F={0:lat[0],1:lat[1],2:lat[0]+lat[2],3:max(lat[0],lat[1])+lat[3],4:0}
F[3]=max(lat[0],lat[1])+lat[3]; F[4]=F[3]+lat[4]; F[5]=max(F[3],F[2])+lat[5]
F[6]=max(F[4],F[5])+lat[6]; MK=F[6]
feas={}
for ni in range(7):
    row={}
    for m,mn in ((1,'DS'),(0,'GLM')):
        c_add=PRICE[m]/7.0
        l_node=BASE_LAT[ni]*LAT[m]
        # post-hoc sequential rebuild (critical if node on any longest path)
        post_mk=MK+l_node  # worst-case: node on critical chain
        on_crit=ni in crit
        # speculative parallel rebuild started with original
        spec_finish=({0:lat[0],1:lat[1],2:lat[0],3:max(lat[0],lat[1])}[ni] if ni in (0,1,2,3) else F[ni]-lat[ni])+l_node
        slack=MK-F[ni]  # slack after node's original finish
        spec_mk=MK+max(0.0, l_node-lat[ni]) if ni not in (6,) else MK+max(0.0,l_node-lat[ni])
        row[mn]={'cost_add':c_add,'latency_add_node':l_node,'on_critical_path':on_crit,
                 'posthoc_mk':post_mk,'posthoc_pct':post_mk/MK-1,
                 'speculative_mk':spec_mk,'speculative_pct':spec_mk/MK-1,
                 'fits_10':c_add<=0.06+1e-9,'fits_15':c_add<=0.09+1e-9,'fits_20':c_add<=0.12+1e-9}
    feas[NODES[ni]]=row
caps={'10':base_cost*1.10,'15':base_cost*1.15,'20m':base_cost*1.20}

res={'M1_reason':M1,'M3_capability':cap,'M2_rebuild':rebuild,'M2_downstream_r':down,
     'M4_feasibility':feas,'caps':{'10':caps['10'],'15':caps['15'],'20m':caps['20m']},
     'N':N,'scenario':'stable .20','note':'analytic fresh-draw expectations; CRN bias avoided'}
def _clean(o):
    if isinstance(o,dict): return {k:_clean(v) for k,v in o.items()}
    if isinstance(o,(list,tuple)): return [_clean(v) for v in o]
    if isinstance(o,(np.bool_,)): return bool(o)
    if isinstance(o,(np.floating,)): return float(o)
    if isinstance(o,(np.integer,)): return int(o)
    return o
json.dump(_clean(res),open(os.path.join(OUT,'P2_0_ANALYSIS.json'),'w'),indent=1)
print('M1 reason:',json.dumps(M1,indent=1))
print('\nM3 capability (slot pass, no gate):')
for k,v in cap.items(): print(f"  {k}: DS {v['DS_slot_pass']:.3f} GLM {v['GLM_slot_pass']:.3f} (TP {v['DS_TP']:.3f}->{v['GLM_TP']:.3f})")
print('\nM2 rebuild expectations (per bad-node rebuild):')
for k,v in rebuild.items():
    print(f"  {k}: bad {v['share']:.2f} | DS conv {v['DS']['expected_new_conversions_per_rebuild']:.3f} both {v['DS']['P(all_bad_facts_recoverable)']:.3f} | GLM conv {v['GLM']['expected_new_conversions_per_rebuild']:.3f} both {v['GLM']['P(all_bad_facts_recoverable)']:.3f}")
print('\nM2 downstream r:',json.dumps(down,indent=1))
print('\nM4 caps:',caps)
print('M4 feasibility:')
for k,v in feas.items():
    print(f"  {k}: crit={v['DS']['on_critical_path']} | DS c+{v['DS']['cost_add']:.3f} post%+{v['DS']['posthoc_pct']*100:.1f} spec%+{v['DS']['speculative_pct']*100:.1f} | GLM c+{v['GLM']['cost_add']:.3f} post%+{v['GLM']['posthoc_pct']*100:.1f} spec%+{v['GLM']['speculative_pct']*100:.1f} fits10/15/20(DS)={v['DS']['fits_10']}/{v['DS']['fits_15']}/{v['DS']['fits_20']}")
