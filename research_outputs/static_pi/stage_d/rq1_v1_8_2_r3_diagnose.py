#!/usr/bin/env python3
"""R3 failure decomposition (zero API; low-compute: N=300 per scenario).
Read-only w.r.t. existing results; writes new diagnostic JSON."""
import numpy as np, json, time, sys
import rq1_v1_8_2_r3_mechanism as M
import rq1_v1_8_2_r3_calibrate as C

def diagnose(n,delta,N,up=1.0,extra_parse=0.0,flip=False,partial=False,seed=1,label=''):
    tasks=M.make_tasks(n); M.make_u(tasks)
    if flip:
        for i,t in enumerate(tasks):
            if i%2: t['sign']=-t['sign']
    rng=np.random.default_rng(seed)
    acc={'bu_glm':0,'nt_true_agree':[], 'type_pick':{ty:{0:0,1:0} for ty in M.TYPES},
         'local':{'BU':[],'NT':[],'TRUE':[]},'term':{'BU':[],'NT':[],'TRUE':[]},
         'q':{'BU':[],'NT':[],'TRUE':[]},'slot':{s:{'BU':[],'NT':[],'TRUE':[]} for s in ('v0','v1','p0')},
         'ctp':{'BU':[],'NT':[]},'cfp':{'BU':[],'NT':[]},'cfn':{'BU':[],'NT':[]},
         'unk':{'BU':[],'NT':[]},'loc':{'BU':[],'NT':[]},'sup':{'BU':[],'NT':[]},
         'cost':{'BU':[],'NT':[],'TRUE':[]},'mk':{'BU':[],'NT':[],'TRUE':[]},
         'costpass':0,'mkpass':0,'parsepass':0,'contractpass':0,
         'local_gain_term_not':0,'ties':0,'strict_win':0,'strict_lose':0,
         'upstream_err':[],'inh':[],'corr_rate':[],
         'cf_gain':{k:[] for k in (5,10,20)}}
    for b in range(N):
        idx=rng.permutation(n); tr=[tasks[i] for i in idx[:n//2]]; te=[tasks[i] for i in idx[n//2:]]
        S=C.build_strats(tr,delta,partial)
        bu=int(S['BU'](te[0])[0]); acc['bu_glm']+= (bu==0)
        nt_vec=S['NT'](te[0]); true_vec=S['TRUE'](te[0])
        acc['nt_true_agree'].append(float(np.mean(nt_vec==true_vec)))
        for ni,ty in enumerate(M.TYPES): acc['type_pick'][ty][int(nt_vec[ni])]+=1
        outs={}
        for name in ('BU','NT','TRUE'):
            R=M.evaluate(te,S[name],delta,up,extra_parse,partial)
            outs[name]=R
            acc['local'][name].append(float(R['local'].mean()))
            acc['term'][name].append(float(R['term'].mean()))
            acc['cost'][name].append(float(R['cost'].mean())); acc['mk'][name].append(float(R['mk'].mean()))
        B,T=outs['BU'],outs['NT']
        # q/slot decomposition on first eval structure: rerun one task to inspect internals
        t0=te[0]
        for name,fn in (('BU',S['BU']),('NT',S['NT']),('TRUE',S['TRUE'])):
            out,lo,su=M.run_task(t0,fn(t0),delta,up,extra_parse,partial=partial)
            qv=[]
            for ni in (3,4,5,6):
                cons=M.FACT_PARENTS[ni][0]
                qv.append(float(np.mean([out[pn,pf]==0 for pn,pf in cons])) if cons else 1.0)
            acc['q'][name].append(float(np.mean(qv)))
            acc['slot']['v0'][name].append(out[5,0]==0); acc['slot']['v1'][name].append(out[5,1]==0); acc['slot']['p0'][name].append(out[6,0]==0)
        for k in ('ctp','cfp','cfn','unk'):
            acc[k]['BU'].append(float(B[k].mean())); acc[k]['NT'].append(float(T[k].mean()))
        acc['loc']['BU'].append(float(B['local'].mean()))  # proxy replaced below
        # loc/sup per strategy via direct run on te
        lv=[];sv=[];lvb=[];svb=[]
        for t in te[:10]:
            oN,lN,sN_=M.run_task(t,S['NT'](t),delta,up,extra_parse,partial=partial)
            oB,lB,sB_=M.run_task(t,S['BU'](t),delta,up,extra_parse,partial=partial)
            lv.append(lN.mean()); sv.append(sN_.mean()); lvb.append(lB.mean()); svb.append(sB_.mean())
        acc['loc']['NT'].append(float(np.mean(lv))); acc['loc']['BU'].append(float(np.mean(lvb)))
        acc['sup']['NT'].append(float(np.mean(sv))); acc['sup']['BU'].append(float(np.mean(svb)))
        dc=float(np.mean(T['cost']/B['cost']-1)); dm=float(np.mean(T['mk']/B['mk']-1))
        acc['costpass']+= dc<=0.10; acc['mkpass']+= dm<=0.10
        acc['parsepass']+= float(T['parse'].mean()>=B['parse'].mean()-0.02)
        acc['contractpass']+= float(T['contract'].mean()>=B['contract'].mean()-0.02)
        lg=T['local']>B['local']; tn=T['term']<=B['term']
        acc['local_gain_term_not']+=float(np.mean(lg&tn))
        d=T['term']-B['term']; acc['ties']+=float(np.mean(d==0)); acc['strict_win']+=float(np.mean(d>0)); acc['strict_lose']+=float(np.mean(d<0))
        # upstream error & inheritance/correction on NT run of te[0]
        out,_,_=M.run_task(t0,S['NT'](t0),delta,up,extra_parse,partial=partial)
        acc['upstream_err'].append(float(np.mean(out[0,:]!=0)+np.mean(out[1,:]!=0))/2)
        m_err = out[3,0]!=0
        if m_err: acc['inh'].append(float(out[6,0]!=0))
        vp = M.run_task(t0,S['NT'](t0),delta,up,extra_parse,corr=0.0,partial=partial)[0]
        vq = out
        acc['corr_rate'].append(float((vq[5,0]==0))-float((vp[5,0]==0)))
        # CF oracle at train sizes 5/10/20 (subset of tr)
        for k in (5,10,20):
            sub=tr[:k]
            S2=C.build_strats(sub,delta,partial)
            RC=M.evaluate(te,S2['NT'],delta,up,extra_parse,partial)
            acc['cf_gain'][k].append(float((RC['term']-B['term']).mean()))
    R={'label':label,'n':n,'N':N,
       'P(BU=GLM)':acc['bu_glm']/N,
       'NT_TRUE_agree':float(np.mean(acc['nt_true_agree'])),
       'type_pick':{ty:{'GLM':v[0]/N,'DS':v[1]/N} for ty,v in acc['type_pick'].items()},
       'local':{k:float(np.mean(v)) for k,v in acc['local'].items()},
       'term':{k:float(np.mean(v)) for k,v in acc['term'].items()},
       'q':{k:float(np.mean(v)) for k,v in acc['q'].items()},
       'slot':{s:{k:float(np.mean(v)) for k,v in d.items()} for s,d in acc['slot'].items()},
       'ctp':{k:float(np.mean(v)) for k,v in acc['ctp'].items()},
       'cfp':{k:float(np.mean(v)) for k,v in acc['cfp'].items()},
       'cfn':{k:float(np.mean(v)) for k,v in acc['cfn'].items()},
       'unk':{k:float(np.mean(v)) for k,v in acc['unk'].items()},
       'loc':{k:float(np.mean(v)) for k,v in acc['loc'].items()},
       'sup':{k:float(np.mean(v)) for k,v in acc['sup'].items()},
       'cost':{k:float(np.mean(v)) for k,v in acc['cost'].items()},
       'mk':{k:float(np.mean(v)) for k,v in acc['mk'].items()},
       'GR_parts':{'cost':acc['costpass']/N,'mk':acc['mkpass']/N,'parseNI':acc['parsepass']/N,'contractNI':acc['contractpass']/N},
       'local_gain_term_not':float(np.mean(acc['local_gain_term_not'])),
       'term_ties':float(np.mean(acc['ties'])),'strict_win':float(np.mean(acc['strict_win'])),'strict_lose':float(np.mean(acc['strict_lose'])),
       'upstream_err':float(np.mean(acc['upstream_err'])),
       'inh_given_merge_err':float(np.mean(acc['inh'])) if acc['inh'] else None,
       'corr_gain':float(np.mean(acc['corr_rate'])),
       'cf_gain':{k:{'mean':float(np.mean(v)),'sd':float(np.std(v))} for k,v in acc['cf_gain'].items()}}
    return R

if __name__=='__main__':
    t0=time.time()
    out={}
    for label,kw in [('H0',dict(n=40,delta=0.0,N=300,seed=301)),
                     ('H1 .15',dict(n=40,delta=0.15,N=300,seed=302)),
                     ('H1 .20',dict(n=40,delta=0.20,N=300,seed=303)),
                     ('up+parse',dict(n=40,delta=0.15,N=200,up=0.85,extra_parse=0.10,seed=306))]:
        out[label]=diagnose(**kw,label=label)
        print(f'[{label}] done {time.time()-t0:.0f}s',flush=True)
    json.dump(out,open('RQ1_V1_8_2_R3_DIAGNOSIS.json','w'),indent=1)
    for lab,r in out.items():
        print(f'\n=== {lab} ===')
        print('P(BU=GLM)=',round(r['P(BU=GLM)'],3),' NT==TRUE agree=',round(r['NT_TRUE_agree'],3))
        print('type_pick:',{ty:(round(v['GLM'],2),round(v['DS'],2)) for ty,v in r['type_pick'].items()})
        print('local:',{k:round(v,3) for k,v in r['local'].items()})
        print('term:',{k:round(v,3) for k,v in r['term'].items()})
        print('q:',{k:round(v,3) for k,v in r['q'].items()})
        print('slot v0/v1/p0 NT:',{s:round(r['slot'][s]['NT'],3) for s in ('v0','v1','p0')})
        print('cost:',{k:round(v,3) for k,v in r['cost'].items()},' mk:',{k:round(v,3) for k,v in r['mk'].items()})
        print('GR parts:',{k:round(v,3) for k,v in r['GR_parts'].items()})
        print('ctp/cfp/cfn BU vs NT:',r['ctp'],r['cfp'],r['cfn'])
        print('unk:',r['unk'],' loc:',r['loc'],' sup:',r['sup'])
        print('local_gain_term_not=',round(r['local_gain_term_not'],3),' ties=',round(r['term_ties'],3),
              ' win=',round(r['strict_win'],3),' lose=',round(r['strict_lose'],3))
        print('upstream_err=',round(r['upstream_err'],3),' inh|merge_err=',r['inh_given_merge_err'],' corr_gain=',round(r['corr_gain'],4))
        print('cf_gain:',{k:(round(v['mean'],4),round(v['sd'],4)) for k,v in r['cf_gain'].items()})
    print(f'\ntotal {time.time()-t0:.0f}s; SYNTHETIC only.')
