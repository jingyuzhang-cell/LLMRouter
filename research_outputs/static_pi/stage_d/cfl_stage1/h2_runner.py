"""H2: H1'v2 controller-driven joint scheduling. 2 tasks(KANGMEI,ZHANGZIDAO)
x anomaly(truncation@SINK) x 4 arms(Static/R/pi/Joint-controller).
Joint uses H1'v2 to decide action. Caps: 12/40K/0.08."""
import json,os,sys,time,hashlib,urllib.request,urllib.error
SD='/root/research_outputs/static_pi/stage_d'
sys.path.insert(0,f'{SD}/quality_phase_v1');sys.path.insert(0,f'{SD}/qp3');sys.path.insert(0,f'{SD}/v2');sys.path.insert(0,SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1,scorer_qp1_v2 as V2
from qp1_prompts import P_SYS,MAXTOK,E_SYS,e_user
from stage_d_v2_transport import build_request,ds_key,glm_key,MODEL_CFG
from cfl3_min_runner import four_part_check
from ts4_runner import dedup,bnew_prompt,j_block,build_j_rows
from ts1_runner import SEL_BLOCK
from stage3_runner import DIRECTED
OUT=SD+'/cfl_stage1';LED=OUT+'/H2_LEDGER.jsonl'
CAPS=dict(calls=12,tokens=40_000,yuan=0.08)
calls=[0];yuan=[0.];tok=[0]
def contract(t):
    p=[x for x in json.load(open(SD+'/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]['contract']
    if not os.path.isabs(p):p=SD+'/v23a/'+p
    return json.load(open(p))
def led_load(*fs):
    d={}
    for f in fs:
        p=f if f.startswith('..') else OUT+'/'+f
        if os.path.exists(p):
            for l in open(p):x=json.loads(l);d.setdefault(x['purpose'],x)
    return d
hist=led_load('../qp8/QP8R_STAGE1_LEDGER.jsonl','../qp9/QP9_LEDGER.jsonl','ROUND2B_LEDGER.jsonl','ROUND3_LEDGER.jsonl','JOINT_LEDGER.jsonl','CFL3_MIN_LEDGER.jsonl')
def call(alias,sys_p,user,mt,purpose):
    body=build_request(alias,sys_p,user,mt)
    sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if sha in hist:return extract_any(hist[sha]['text']),0.,0.
    est=len(sys_p+user)//2
    if calls[0]>=CAPS['calls']:raise RuntimeError('CALLS')
    if tok[0]+est+mt+1500>CAPS['tokens']:raise RuntimeError(f'TOK {tok[0]}')
    if yuan[0]+.008>CAPS['yuan']*.95:raise RuntimeError('YUAN')
    req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
    req.add_header('content-type','application/json')
    req.add_header('authorization','Bearer '+(ds_key() if alias=='deepseek' else glm_key()))
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=240) as r:d=json.loads(r.read().decode())
    ch=d['choices'][0];u=d.get('usage',{});c=ch.get('message',{}).get('content','')
    text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else(c or'')
    tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
    y=round(tin*.8e-6+tout*2.8e-6,8);lat=round(time.monotonic()-t0,3)
    calls[0]+=1;yuan[0]+=y;tok[0]+=tin+tout
    with open(LED,'a') as f:f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias=alias,purpose=purpose,prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),accounting_yuan=y,latency_s=lat,text=text),ensure_ascii=False)+'\n')
    if tok[0]>=CAPS['tokens']:raise RuntimeError('TOK_CAP')
    return extract_any(text),lat,y
# H1'v2 controller (frozen from H1P_V2)
def controller(anomaly,vp):
    if anomaly=='文档级缺失':return 'NONE'
    if vp==0 and anomaly in('SINK弃答','执行失败'):return 'NONE'
    if anomaly in('E坍缩','信息坍缩','覆盖缺口'):return 'Z'
    if anomaly in('J误绑','违纪错答'):return 'Z'
    if anomaly=='SINK弃答' and vp>0:return 'R'
    return 'NONE'
results={}
for task in ('KANGMEI','ZHANGZIDAO'):
    ct=contract(task)
    # pool from best available source
    if task=='KANGMEI':
        r3=led_load('CFL3_MIN_LEDGER.jsonl');ents=[]
        for rep in(1,2):
            k=f'cfl3min|KANGMEI|C|r{rep}|e1_reext'
            if k in r3:ents+=parse2(extract_any(r3[k]['text'])or{})
    else:
        r2b=led_load('ROUND2B_LEDGER.jsonl');ents=[]
        for n in('e0','e1'):
            k=f'r2b|{task}|E|{n}'
            if k in r2b:ents+=parse2(extract_any(r2b[k]['text'])or{})
    pool=dedup(ents,ct)
    try:j=build_j_rows(ct,pool,task)
    except:j={}
    prompt=bnew_prompt(ct,pool,sel=True)+'\n\n'+j_block(j)
    # verify pass count (signal for controller)
    ver_count=len(pool)
    # anomaly: SINK truncation (simulated by executing SINK then treating result as checkpoint)
    o,la,y=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'h2|{task}|checkpoint|SINK')
    if o is None:
        # truncation occurred -> anomaly = 执行失败, vp=pool_size
        anomaly='执行失败';vp=ver_count
    else:
        r=V2.score_task_v2(ct,o)
        if r['q']<0.3:anomaly='SINK弃答' if ver_count<5 else 'E坍缩'
        else:anomaly='none'
        vp=ver_count
    sq=V2.score_task_v2(ct,o)['q'] if o else 0.0
    # controller decision
    ctrl=controller(anomaly,vp)
    print(f"{task}: pool={len(pool)} J={len(j)} anomaly={anomaly} vp={vp} ctrl={ctrl} static_Q={sq:.3f}")
    arms={'Static':dict(q=sq,cost=0,lat=0)}
    if ctrl!='NONE':
        if ctrl=='R':
            o2,la2,y2=call('deepseek',P_SYS,prompt,MAXTOK['p'],f'h2|{task}|R|retry')
            q2=V2.score_task_v2(ct,o2)['q'] if o2 else 0
            arms['R']=dict(q=q2,cost=y2,lat=la2)
            arms['Joint']=dict(q=q2,cost=y2,lat=la2)  # same action
        elif ctrl=='Z':
            docs=sorted(ct['source_pages'].keys());h=(len(docs)+1)//2
            oE,laE,yE=call('glm53flash',E_SYS,e_user(ct,docs[h:]or docs[:1],'E1')+DIRECTED,2000,f'h2|{task}|Z|e1dir')
            pool2=dedup(parse2(oE)or{},ct) if oE else []
            if pool2:
                try:
                    j2=build_j_rows(ct,pool2,task)
                except:
                    j2={}
                p2=bnew_prompt(ct,pool2,sel=True)+'\n\n'+j_block(j2)
                o2,la2,y2=call('deepseek',P_SYS,p2,MAXTOK['p'],f'h2|{task}|Z|SINK')
                q2=V2.score_task_v2(ct,o2)['q'] if o2 else 0
                arms['Z']=dict(q=q2,cost=yE+y2,lat=laE+la2)
                arms['Joint']=dict(q=q2,cost=yE+y2,lat=laE+la2)
    else:
        arms['Z']=dict(q=sq,cost=0,lat=0,note='controller NONE')
        arms['Joint']=dict(q=sq,cost=0,lat=0,note='controller NONE')
    results[task]=dict(anomaly=anomaly,vp=vp,ctrl=ctrl,arms=arms)
    print(f"  {task}: {json.dumps({a:dict(q=v['q'],cost=v['cost']) for a,v in arms.items()})}")
json.dump(results,open(OUT+'/H2_RESULTS.json','w'),ensure_ascii=False,indent=1)
print(f"\nDONE: {calls[0]}/{CAPS['calls']} tok={tok[0]}/{CAPS['tokens']} Y{yuan[0]:.4f}")
