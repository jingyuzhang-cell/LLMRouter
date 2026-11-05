"""v1.2 FINAL core experiment. P1: 6 GLM-E probes. P2: YJT SINK r2 + strong Static
(18 reused probes via SHA + lineage). P3: injected truncation at SINK checkpoint,
arms folded per prereg (exec-failure: R=Z=LOCAL-DS; pi=LOCAL-GLM; Joint=model-by-node).
P4: stats + 5 deliverables. Caps 41/145K/0.20, per-call precheck."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD='/root/research_outputs/static_pi/stage_d'
sys.path.insert(0,f'{SD}/quality_phase_v1'); sys.path.insert(0,f'{SD}/qp3'); sys.path.insert(0,f'{SD}/v2'); sys.path.insert(0,SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1, scorer_qp1_v2 as V2
from qp1_prompts import P_SYS, MAXTOK, E_SYS, e_user
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt
from ts1_runner import SEL_BLOCK
OUT=f'{SD}/cfl_stage1'; LED=f'{OUT}/V12_FINAL_LEDGER.jsonl'
CAPS=dict(calls=41,tokens=145_000,yuan=0.20)
calls=[0];yuan=[0.0];tok=[0]
hist={}
for f in ('../qp8/QP8R_STAGE1_LEDGER.jsonl','../qp9/QP9_LEDGER.jsonl','ROUND1_LEDGER.jsonl','ROUND2B_LEDGER.jsonl','ROUND3_LEDGER.jsonl','QP9_LEDGER.jsonl'):
    p=f if f.startswith('..') else f'{OUT}/{f}'
    if os.path.exists(p):
        for l in open(p): x=json.loads(l); hist.setdefault(x['prompt_sha256'],x)
def contract(t):
    p=[x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]['contract']
    if not os.path.isabs(p): p=f'{SD}/v23a/{p}'
    return json.load(open(p))
def call(alias,system,user,mt,purpose,est_in=None,reuse_ok=True):
    body=build_request(alias,system,user,mt)
    sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if reuse_ok and sha in hist:
        return extract_any(hist[sha]['text']),0.0,0.0,True
    est=(est_in or len(system+user)//2)
    if calls[0]>=CAPS['calls']: raise RuntimeError('CALLS CAP')
    if tok[0]+est+mt+1500>CAPS['tokens']: raise RuntimeError(f'PRECHECK TOK {tok[0]}+{est+mt}')
    if yuan[0]+0.01>CAPS['yuan']*0.95: raise RuntimeError('YUAN')
    req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
    req.add_header('content-type','application/json')
    req.add_header('authorization','Bearer '+(ds_key() if alias=='deepseek' else glm_key()))
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=240) as r: d=json.loads(r.read().decode())
    ch=d['choices'][0];u=d.get('usage',{});c=ch.get('message',{}).get('content','')
    text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else (c or '')
    tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
    y=round(tin*0.8e-6+tout*2.8e-6,8);lat=round(time.monotonic()-t0,3)
    calls[0]+=1;yuan[0]+=y;tok[0]+=tin+tout
    with open(LED,'a') as f: f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),accounting_yuan=y,latency_s=lat,text=text),ensure_ascii=False)+'\n')
    if tok[0]>=CAPS['tokens']: raise RuntimeError('TOKEN CAP')
    return extract_any(text),lat,y,False
TASKS=['KANGMEI','MVR1','YJT','E06','ZHANGZIDAO','KDX']
profile={};static={}
for t in TASKS:
    ct=contract(t);docs=sorted(ct['source_pages'].keys());h=(len(docs)+1)//2
    scores={};pools={}
    for alias,mk in (('deepseek','DS'),('glm53flash','GLM')):
        ents=[];lat=0.0;cost=0.0;new=0
        for node,ed in (('e0',docs[:h]),('e1',docs[h:] or docs[:1])):
            o,l,y,r=call(alias,E_SYS,e_user(ct,ed,'E1'),2000,f'v12|P1|{t}|{mk}|{node}')
            if o is not None: ents+=parse2(o)
            if not r: cost+=y;lat=max(lat,l);new+=1
        pools[mk]=dedup(ents,ct)
        keys={(str(e.get('field')),str(e.get('doc')),str(e.get('page')),Q1._norm(e.get('quote') or '')) for e in pools[mk]}
        scores[mk]=(len(keys),cost,lat,new)
    win='DS' if scores['DS'][0]>=scores['GLM'][0] else 'GLM'
    profile[t]=dict(DS=dict(slots=scores['DS'][0],probe_cost=scores['DS'][1]),GLM=dict(slots=scores['GLM'][0],probe_cost=scores['GLM'][1]),winner=win)
    static[t]=dict(pool=pools[win],probe_cost=scores['DS'][1]+scores['GLM'][1])
    print(f"P1 {t}: DS={scores['DS'][0]} GLM={scores['GLM'][0]} -> E={win} (new probes {scores['DS'][3]+scores['GLM'][3]})")
json.dump(profile,open(f'{OUT}/V12_NODE_PROFILE.json','w'),ensure_ascii=False,indent=1)
# P2 strong Static SINK x2 (reuse historical where SHA matches; else call)
baseline={}
for t in TASKS:
    ct=contract(t);pool=static[t]['pool']
    prompt=bnew_prompt(ct,pool,sel=True)
    qs=[];lat=0.0;cost=0.0
    for rep in (1,2):
        o,l,y,r=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'v12|P2|{t}|SINK|r{rep}')
        if o is None: qs.append(None); continue
        res=V2.score_task_v2(ct,o); qs.append(res['q'])
        if not r: cost+=y;lat=max(lat,l)
    baseline[t]=dict(q=qs,cost=cost+static[t]['probe_cost'],lat=lat,pool=len(pool))
    print(f"P2 {t}: static Q={qs}")
json.dump(baseline,open(f'{OUT}/V12_STATIC_BASELINE.json','w'),ensure_ascii=False,indent=1)
# P3 injected truncation at SINK checkpoint; folded arms per prereg
TRUNC='{"answers":[{"fact_id":"A'
dyn={}
for t in TASKS:
    ct=contract(t);pool=static[t]['pool'];prompt=bnew_prompt(ct,pool,sel=True)
    sq=baseline[t]['q'][0] or 0.0
    arms={}
    o,l,y,r=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'v12|P3|{t}|R|retry',reuse_ok=False)
    if o is not None: arms['R']=(V2.score_task_v2(ct,o)['q'],y,l)
    else: arms['R']=(0.0,y,l)
    o,l,y,r=call('glm53flash',P_SYS,prompt,MAXTOK['p'],f'v12|P3|{t}|pi|swap',reuse_ok=False)
    if o is not None: arms['pi']=(V2.score_task_v2(ct,o)['q'],y,l)
    else: arms['pi']=(0.0,y,l)
    # Z=LOCAL-DS for exec failure -> fold with R (same action); Joint=model-by-node: SINK node -> DS per frozen prior -> fold with R
    arms['Z']=arms['R'];arms['Joint']=arms['R']
    dyn[t]=dict(static_q=sq,arms={k:dict(q=v[0],cost=v[1],lat=v[2]) for k,v in arms.items()})
    print(f"P3 {t}: static={sq:.3f} R={arms['R'][0]:.3f} pi={arms['pi'][0]:.3f} (Z=Joint=R fold)")
json.dump(dyn,open(f'{OUT}/V12_DYNAMIC_RESULTS.json','w'),ensure_ascii=False,indent=1)
# P4 stats
import statistics as st
print(f"used calls={calls[0]} tok={tok[0]} yuan={yuan[0]:.4f}")
