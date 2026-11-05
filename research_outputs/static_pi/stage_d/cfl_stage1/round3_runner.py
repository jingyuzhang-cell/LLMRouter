"""Round 3 (authorized 10/45K/0.08): YJT GLM-E x2 (+cond SINK x2),
ZHANGZIDAO SINK x2 (J-v3 block 7/7), KDX SINK x2 (no J), reserve 2.
Layer attribution: J binding/echo/TP tracked separately."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD='/root/research_outputs/static_pi/stage_d'
sys.path.insert(0,f'{SD}/quality_phase_v1'); sys.path.insert(0,f'{SD}/qp3'); sys.path.insert(0,f'{SD}/v2'); sys.path.insert(0,SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
from qp1_prompts import P_SYS, MAXTOK, E_SYS, e_user
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup, bnew_prompt, j_block
from stage3_runner import DIRECTED
OUT=f'{SD}/cfl_stage1'; LEDGER=f'{OUT}/ROUND3_LEDGER.jsonl'
CAPS=dict(calls=10,tokens=45_000,yuan=0.08)
calls=[0]; yuan=[0.0]; tok=[0]; reserve=[2]
def load_contract_path(t):
    c=[x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]
    p=c['contract']
    if not os.path.isabs(p): p=f'{SD}/v23a/{p}'
    return json.load(open(p))
def call(alias,system,user,mt,purpose):
    for att in (1,2):
        if att==2:
            if reserve[0]<1: raise RuntimeError('NO RESERVE')
            reserve[0]-=1; print(f'  [reserve: {purpose}]')
        if calls[0]>=CAPS['calls']: raise RuntimeError('CALLS CAP')
        if yuan[0]+0.008>CAPS['yuan']*0.95: raise RuntimeError('YUAN CAP')
        body=build_request(alias,system,user,mt)
        sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
        req.add_header('content-type','application/json')
        req.add_header('authorization','Bearer '+(ds_key() if alias=='deepseek' else glm_key()))
        t0=time.monotonic(); d=None
        try:
            for bo in (0,60,120,180):
                if bo: print(f'  [429 {bo}s]'); time.sleep(bo)
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
            f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,prompt_sha256=sha,
                usage=dict(input_tokens=tin,output_tokens=tout),accounting_yuan=y,latency_s=lat,text=text),ensure_ascii=False)+'\n')
        print(f"  [{purpose}] in={tin} out={tout} tok={tok[0]}/{CAPS['tokens']} ¥{yuan[0]:.4f}")
        if tok[0]>=CAPS['tokens']: raise RuntimeError('TOKEN CAP')
        obj=extract_any(text)
        if obj is None and att==1: continue
        return obj,lat,y
    raise RuntimeError('unreachable')
def sink_cells(task,ct,pool,j,tag):
    prompt=bnew_prompt(ct,pool,sel=True)+(('\n\n'+j_block(j)) if j else '')
    facts={f['fact_id']:f for f in ct['required_facts'] if f.get('status') not in ('EXCLUDED','NOT_APPLICABLE')}
    for rep in (1,2):
        o,la,y=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'r3|{task}|{tag}SINK|r{rep}')
        r=V2.score_task_v2(ct,o); rows=r['rows']
        tp={x['fact_id'] for x in rows if x['status']=='TP'}
        wrong=sum(1 for x in rows if x['status'].startswith('VALUE'))
        abst=sum(1 for x in rows if x['status']=='ABSENT')
        j_tp=sorted(tp&set(j)) if j else []
        print(f"  {task} {tag} r{rep}: Q={r['q']} TP={len(tp)} wrong={wrong} UNKNOWN={abst} Jslot_TP={len(j_tp)}/{len(j)} {j_tp}")
def main():
    jv3=json.load(open(f'{OUT}/JV3_PRECHECK.json'))
    recs={json.loads(l)['purpose']:json.loads(l) for l in open(f'{OUT}/ROUND2B_LEDGER.jsonl')}
    # ZHANGZIDAO: frozen pool + J-v3 block
    ct=load_contract_path('ZHANGZIDAO'); ents=[]
    for n in ('e0','e1'): ents+=parse2(extract_any(recs[f'r2b|ZHANGZIDAO|E|{n}']['text']) or {})
    pool=dedup(ents,ct); j=jv3['ZHANGZIDAO']['j']
    print(f"ZHANGZIDAO pool={len(pool)} J={len(j)}")
    sink_cells('ZHANGZIDAO',ct,pool,j,'J')
    # KDX: frozen pool, no J
    ct=load_contract_path('KDX'); ents=[]
    for n in ('e0','e1'): ents+=parse2(extract_any(recs[f'r2b|KDX|E|{n}']['text']) or {})
    pool=dedup(ents,ct); print(f"KDX pool={len(pool)} J=0")
    sink_cells('KDX',ct,pool,{},'noJ')
    # YJT GLM-E
    ct=load_contract_path('YJT'); docs=sorted(ct['source_pages'].keys()); h=(len(docs)+1)//2
    ents=[]
    for node,ed in (('e0',docs[:h]),('e1',docs[h:] or docs[:1])):
        o,la,y=call('glm53flash',E_SYS,e_user(ct,ed,'E1')+DIRECTED,2000,f'r3|YJT|GLME|{node}')
        if o is not None: ents+=parse2(o)
    pool=dedup(ents,ct)
    print(f"YJT GLM-E pool={len(pool)}")
    if pool:
        sink_cells('YJT',ct,pool,{},'GLME')
    else:
        print('YJT GLM-E still zero -> line closed honestly')
    print(f"DONE: {calls[0]}/{CAPS['calls']} tok={tok[0]}/{CAPS['tokens']} ¥{yuan[0]:.4f} reserve={reserve[0]}")
if __name__=='__main__': main()
