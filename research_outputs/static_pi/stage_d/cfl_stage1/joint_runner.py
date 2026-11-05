"""Joint quality+dynamic experiment (JOINT_DESIGN.md). A/B Static + C/D scenarios.
Caps: 21 calls / 70K tokens / 0.12 yuan. Per-call precheck."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD='/root/research_outputs/static_pi/stage_d'
sys.path.insert(0,f'{SD}/quality_phase_v1');sys.path.insert(0,f'{SD}/qp3');sys.path.insert(0,f'{SD}/v2');sys.path.insert(0,SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1, scorer_qp1_v2 as V2
from qp1_prompts import P_SYS, MAXTOK, E_SYS, e_user
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt, j_block, build_j_rows
from ts1_runner import SEL_BLOCK
from stage3_runner import DIRECTED
OUT=f'{SD}/cfl_stage1';LED=f'{OUT}/JOINT_LEDGER.jsonl'
CAPS=dict(calls=21,tokens=70_000,yuan=0.12)
calls=[0];yuan=[0.0];tok=[0]
def contract(t):
    p=[x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]['contract']
    if not os.path.isabs(p):p=f'{SD}/v23a/{p}'
    return json.load(open(p))
def led_load(*fs):
    d={}
    for f in fs:
        p=f if f.startswith('/') or f.startswith('..') else f'{OUT}/{f}'
        if os.path.exists(p):
            for l in open(p):x=json.loads(l);d.setdefault(x['purpose'],x)
    return d
hist=led_load('../qp8/QP8R_STAGE1_LEDGER.jsonl','../qp9/QP9_LEDGER.jsonl','ROUND2B_LEDGER.jsonl','ROUND3_LEDGER.jsonl','ROUND1_LEDGER.jsonl')
def call(alias,system,user,mt,purpose,reuse=True):
    body=build_request(alias,system,user,mt)
    sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if reuse and sha in hist:return extract_any(hist[sha]['text']),0.0,0.0,True
    est=len(system+user)//2
    if calls[0]>=CAPS['calls']:raise RuntimeError('CALLS CAP')
    if tok[0]+est+mt+1500>CAPS['tokens']:raise RuntimeError(f'PRECHECK {tok[0]}+{est+mt}')
    if yuan[0]+0.008>CAPS['yuan']*0.95:raise RuntimeError('YUAN')
    req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
    req.add_header('content-type','application/json')
    req.add_header('authorization','Bearer '+(ds_key() if alias=='deepseek' else glm_key()))
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=240) as r:d=json.loads(r.read().decode())
    ch=d['choices'][0];u=d.get('usage',{});c=ch.get('message',{}).get('content','')
    text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else (c or '')
    tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
    y=round(tin*0.8e-6+tout*2.8e-6,8);lat=round(time.monotonic()-t0,3)
    calls[0]+=1;yuan[0]+=y;tok[0]+=tin+tout
    with open(LED,'a') as f:f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),accounting_yuan=y,latency_s=lat,text=text),ensure_ascii=False)+'\n')
    if tok[0]>=CAPS['tokens']:raise RuntimeError('TOKEN CAP')
    return extract_any(text),lat,y,False
results={}
def score(t,obj):
    ct=contract(t);r=V2.score_task_v2(ct,obj) if obj else None
    if not r:return dict(q=0.0)
    rows=r['rows']
    return dict(q=r['q'],tp=sum(1 for x in rows if x['status']=='TP'),wrong=sum(1 for x in rows if x['status'].startswith('VALUE')),abst=sum(1 for x in rows if x['status']=='ABSENT'))
TASKS=['KANGMEI','ZHANGZIDAO','KDX']
# B pools: correct heterogeneous E + J-v3
for t in TASKS:
    ct=contract(t)
    if t=='KANGMEI':
        ents=[]
        for n in ('e0','e1'):ents+=parse2(extract_any(hist[f'qp8r|KANGMEI|GLM|r1|{n}']['text']) or {})
    else:
        ents=[]
        for n in ('e0','e1'):ents+=parse2(extract_any(hist[f'r2b|{t}|E|{n}']['text']) or {})
    j={fid:b for fid,b in ((fid,joint_bind_v2([pool],[f])[fid]) if False else (fid,None)) for fid in []} if False else {}
    # simple J: use build_j_rows only for KANGMEI; others use clause_bind from ts4
    # use the round2b/round3 J rows where available
    if t=='KANGMEI':
        j3=json.load(open(f'{OUT}/CFL3_MIN_LEDGER.jsonl')) if False else None
        r3=led_load('CFL3_MIN_LEDGER.jsonl')
        ents_min=[]
        for rep in (1,2):
            k=f'cfl3min|KANGMEI|C|r{rep}|e1_reext'
            if k in r3:ents_min+=parse2(extract_any(r3[k]['text']) or {})
        pool=dedup(ents_min,ct)
        try:
            j=build_j_rows(ct,pool,'KANGMEI')
        except:j={}
    prompt=bnew_prompt(ct,pool,sel=True)+'\n\n'+j_block(j)
    qs=[];cost=0
    for rep in (1,2):
        o,la,y,r=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'joint|B|{t}|SINK|r{rep}')
        s=score(t,o);qs.append(s['q'])
        if not r:cost+=y
    results[f'B_{t}']=dict(q=qs,cost=cost,pool=len(pool),J=len(j))
    print(f"B {t}: Q={qs} pool={len(pool)} J={len(j)}")
# Scenario A: KANGMEI E collapse (QP8R DS pool, verify=0)
ct_k=contract('KANGMEI')
qp9=led_load('../qp9/QP9_LEDGER.jsonl')
p9_prompt=None
from qp2_chain import verify_evidence
import qp5a_pure_prep as PP
ents_ds=[]
for n in ('e0','e1'):ents_ds+=parse2(extract_any(hist[f'qp8r|KANGMEI|DS|r1|{n}']['text']) or {})
ver,_=verify_evidence(ents_ds,ct_k)
mf={}
for e in ents_ds:
    k=str(e.get('field') or e.get('bucket') or '')
    if k and e.get('value') not in (None,''):mf.setdefault(k,e.get('value'))
ev=PP.match_evidence(mf,ver,ct_k)
p_empty=PP.render(ct_k,{},mf,ev,with_evidence=True)
# NONE
results['SA_NONE']=score('KANGMEI',{'answers':[],'abstentions':[]})
# R: DS retry on empty-table prompt
o,la,y,r=call('deepseek',P_SYS,p_empty,MAXTOK['p'],'joint|SA|R',reuse=False)
results['SA_R']=dict(score('KANGMEI',o),cost=y,lat=la);print(f"SA R: {results['SA_R']}")
# pi: GLM on same prompt
o,la,y,r=call('glm53flash',P_SYS,p_empty,MAXTOK['p'],'joint|SA|pi',reuse=False)
results['SA_pi']=dict(score('KANGMEI',o),cost=y,lat=la);print(f"SA pi: {results['SA_pi']}")
# Z/Joint: UPSTREAM = directed GLM-E e1 + J-v3 + SINK
docs=sorted(ct_k['source_pages'].keys());h=(len(docs)+1)//2
oE,laE,yE,rE=call('glm53flash',E_SYS,e_user(ct_k,docs[h:] or docs[:1],'E1')+DIRECTED,2000,'joint|SA|Z|e1dir',reuse=False)
pool_z=dedup(parse2(oE) or {},ct_k) if oE else []
if pool_z:
    try:
        j_z=build_j_rows(ct_k,pool_z,'KANGMEI')
    except:j_z={}
    pz=bnew_prompt(ct_k,pool_z,sel=True)+'\n\n'+j_block(j_z)
    o,la,y2,r2=call('deepseek',P_SYS,pz,MAXTOK['p'],'joint|SA|Z|SINK',reuse=False)
    results['SA_Z']=dict(score('KANGMEI',o),cost=yE+y2,lat=laE+la2 if False else laE+la,pool=len(pool_z),J=len(j_z))
else:
    results['SA_Z']=dict(q=0.0,cost=yE)
print(f"SA Z: {results['SA_Z']}")
# Scenario B: E06 J misbinding (frozen wrong state)
ct_e=contract('E06')
s1=led_load('STAGE1_E06_LEDGER.jsonl')
o_old=extract_any(s1['stage1|E06|DS_J|r1|p']['text'])
# Z: UNKNOWN mask H1/H2 (zero-call)
o_mask=json.loads(json.dumps(o_old))
o_mask['answers']=[a for a in o_mask.get('answers',[]) if a.get('fact_id') not in ('H1','H2')]
results['SB_Z']=score('E06',o_mask)
# R (negative): repeat old name-match binding -> same wrong answers
results['SB_R']=score('E06',o_old)
# Joint: mask + SINK re-answer
pool_e=[];seen=set()
for n in ('e0','e1'):
    for e in parse2(extract_any(hist[f'qp8r|E06|GLM|r1|{n}']['text']) or {}):
        if not four_part_check(e,ct_e):continue
        v=e.get('raw') or e.get('value')
        k=(str(e.get('field')),str(e.get('doc')),str(e.get('page')),Q1._norm(e.get('quote') or ''),Q1._norm(str(v)))
        if k in seen:continue
        seen.add(k);pool_e.append(e)
p_e=bnew_prompt(ct_e,pool_e,sel=True)
o,la,y,r=call('deepseek',P_SYS,p_e,MAXTOK['p'],'joint|SB|Joint|SINK',reuse=False)
results['SB_Joint']=dict(score('E06',o),cost=y,lat=la)
print(f"SB Z={results['SB_Z'].get('q')} R={results['SB_R'].get('q')} Joint={results['SB_Joint'].get('q')}")
json.dump(results,open(f'{OUT}/JOINT_RESULTS.json','w'),ensure_ascii=False,indent=1)
print(f"DONE: {calls[0]}/{CAPS['calls']} tok={tok[0]}/{CAPS['tokens']} ¥{yuan[0]:.4f}")
