"""Next-phase round 1: Static baseline on NEW core tasks (ZHANGZIDAO/YJT/KDX).
E fresh (clean prompts, DS) -> J upgraded (subject AND predicate-term AND unique)
-> V four-part -> SINK(DS) x2 reps. Caps: 14 calls / 110K tokens / 0.15 yuan.
Six-metric reporting (Q_all/Q_answerable/coverage/wrong/UNKNOWN/C-L)."""
import json, os, sys, re, time, hashlib, urllib.request, urllib.error
SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1'); sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2'); sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
import qp3_primitives as P3
from qp1_prompts import P_SYS, MAXTOK, E_SYS, e_user
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt, j_block
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/ROUND1_LEDGER.jsonl'
CAPS = dict(calls=14, tokens=110_000, yuan=0.15)
TASKS = ['ZHANGZIDAO', 'YJT', 'KDX']
calls=[0]; yuan=[0.0]; tok=[0]; reserve=[2]

def load_contract_path(t):
    c=[x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]
    p=c['contract']
    if not os.path.isabs(p): p=f'{SD}/v23a/{p}'
    return json.load(open(p))

def call(alias, system, user, mt, purpose):
    for att in (1,2):
        if att==2:
            if reserve[0]<1: raise RuntimeError('NO RESERVE')
            reserve[0]-=1; print(f'  [reserve: {purpose}]')
        if calls[0]>=CAPS['calls']: raise RuntimeError('CALLS CAP')
        if yuan[0]+0.01>CAPS['yuan']*0.95: raise RuntimeError('YUAN CAP')
        body=build_request(alias,system,user,mt)
        sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
        req.add_header('content-type','application/json')
        req.add_header('authorization','Bearer '+ds_key())
        t0=time.monotonic(); d=None
        try:
            for bo in (0,60,120,180):
                if bo: print(f'  [429 backoff {bo}s]'); time.sleep(bo)
                try:
                    with urllib.request.urlopen(req,timeout=240) as r: d=json.loads(r.read().decode())
                    break
                except urllib.error.HTTPError as e:
                    if e.code==429 and bo<180: continue
                    raise
        except Exception:
            if att==1: continue
            raise
        if d is None:
            if att==1: continue
            raise RuntimeError('transport')
        ch=d['choices'][0]; u=d.get('usage',{})
        c=ch.get('message',{}).get('content','')
        text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else (c or '')
        tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
        y=round(tin*0.8e-6+tout*2.8e-6,8); lat=round(time.monotonic()-t0,3)
        calls[0]+=1; yuan[0]+=y; tok[0]+=tin+tout
        with open(LEDGER,'a') as f:
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,
                prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),
                accounting_yuan=y,latency_s=lat,text=text),ensure_ascii=False)+'\n')
        if tok[0]>=CAPS['tokens']: raise RuntimeError('TOKEN CAP')
        obj=extract_any(text)
        if obj is None and att==1: continue
        return obj,lat,y
    raise RuntimeError('unreachable')

def joint_bind(pool, f):
    subj=str(f.get('subject') or ''); pred=str(f.get('predicate') or '')
    terms=[t for t in re.split(r'[（）()/、\s]', pred) if len(t)>=2]
    cands=[]
    for e in pool:
        if not P3.name_matches(e,f): continue
        if (e.get('raw') or e.get('value')) in (None,''): continue
        text=f"{e.get('field') or ''}{e.get('bucket') or ''}{e.get('predicate') or ''}{e.get('quote') or ''}"
        if terms and not any(t in text for t in terms): continue
        cands.append(e)
    uniq={(str(e.get('quote')),str(e.get('raw') or e.get('value'))) for e in cands}
    if len(uniq)==1:
        e=cands[0]
        return dict(value=str(e.get('raw') or e.get('value')),doc=e.get('doc'),page=e.get('page'),quote=e.get('quote'))
    return None

def main():
    results=[]
    for task in TASKS:
        ct=load_contract_path(task)
        facts=[f for f in ct['required_facts'] if f.get('status') not in ('EXCLUDED','NOT_APPLICABLE')]
        pages=[p.get('text','') for d in ct['source_pages'].values() for p in d.get('pages',{}).values()]
        doc_cov=sum(1 for f in facts if any(Q1.value_in_quote(f.get('value'),pg) for pg in pages))
        docs=sorted(ct['source_pages'].keys()); h=(len(docs)+1)//2
        ents=[]
        for node,ed in (('e0',docs[:h]),('e1',docs[h:] or docs[:1])):
            o,la,y=call('deepseek',E_SYS,e_user(ct,ed,'E1'),2000,f'r1|{task}|E|{node}')
            if o is not None: ents+=parse2(o)
        pool=dedup(ents,ct)
        pool_cov=sum(1 for f in facts if any(e.get('quote') and Q1.value_in_quote(f.get('value'),e.get('quote')) for e in pool))
        j={}
        for f in facts:
            b=joint_bind(pool,f)
            if b: j[f['fact_id']]=b
        okj=0
        for fid,r in j.items():
            f=[x for x in facts if x['fact_id']==fid][0]
            okj+=V2.value_equal_v2({'value':r['value'],'value_kind':f.get('value_kind')},dict(f))
        print(f"== {task}: pool={len(pool)} doc_cov={doc_cov}/{len(facts)} pool_cov={pool_cov}/{len(facts)} "
              f"J_bound={len(j)} J_posthoc_ok={okj}")
        prompt=bnew_prompt(ct,pool,sel=True)+'\n\n'+j_block(j)
        for rep in (1,2):
            o,la,y=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'r1|{task}|SINK|r{rep}')
            r=V2.score_task_v2(ct,o)
            rows=r['rows']
            unc=[f2['fact_id'] for f2 in facts if not any(e.get('quote') and Q1.value_in_quote(f2.get('value'),e.get('quote')) for e in pool)]
            tp=[x['fact_id'] for x in rows if x['status']=='TP']
            tp_ans=[t for t in tp if t not in unc]
            n_ans=len(facts)-len(unc)
            row=dict(task=task,rep=rep,q_all=r['q'],
                     q_answerable=round(len(tp_ans)/n_ans,4) if n_ans else None,
                     tp=len(tp),wrong=sum(1 for x in rows if x['status'].startswith('VALUE')),
                     abst=sum(1 for x in rows if x['status']=='ABSENT'),
                     unc_n=len(unc),cost_yuan=round(y,6),lat_s=la,
                     pool_cov=pool_cov,doc_cov=doc_cov,j_bound=len(j),j_ok=okj)
            results.append(row)
            print(f"  SINK r{rep}: Q_all={row['q_all']} Q_ans={row['q_answerable']} TP={row['tp']} "
                  f"wrong={row['wrong']} UNKNOWN={row['abst']} ¥{y:.4f} lat={la}s")
        json.dump(dict(batch='ROUND1',caps=CAPS,results=results),
                  open(f'{OUT}/ROUND1_RESULTS.json','w'),ensure_ascii=False,indent=1)
    print(f"DONE: {calls[0]}/{CAPS['calls']} calls, {tok[0]}/{CAPS['tokens']} tok, ¥{yuan[0]:.4f}, reserve={reserve[0]}")

if __name__=='__main__':
    main()
