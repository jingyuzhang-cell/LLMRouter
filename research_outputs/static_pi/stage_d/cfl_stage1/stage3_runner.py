"""Stage-3 final round (prereg v2): 8 real anomaly events x 5 arms.
Static = frozen historical outcomes (0 calls). R/pi = blind retry (same /
complementary model) at the manifesting node. Z/Joint = type-aware scope
(declared collapses: Joint==Z on A4/A7/A9 executed once, credited to both).
A10 (ZIJING doc-level) is the waste discriminator: R/pi each burn 1 call.
Caps: 31 calls / 110K tokens / 0.20 yuan; reserve 4 (transport/parse only)."""
import json, os, sys, time, hashlib, urllib.request, urllib.error
SD = '/root/research_outputs/static_pi/stage_d'
sys.path.insert(0, f'{SD}/quality_phase_v1'); sys.path.insert(0, f'{SD}/qp3')
sys.path.insert(0, f'{SD}/v2'); sys.path.insert(0, SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
import qp5a_pure_prep as PP
import qp2_chain as CH
import qp1_prompts as P1
from qp4_factorial import VALUE_FORM_RULES
from qp5a_pure_prep import COPY_RULE
from qp1_prompts import P_SYS, MAXTOK, e_user, E_SYS
from stage_d_v2_transport import build_request, ds_key, glm_key, MODEL_CFG
from cfl3_min_runner import four_part_check, load_contract
from ts4_runner import dedup, bnew_prompt, j_block, build_j_rows
from ts1_runner import SEL_BLOCK

OUT = f'{SD}/cfl_stage1'
LEDGER = f'{OUT}/STAGE3_LEDGER.jsonl'
CAPS = dict(calls=31, tokens=110_000, yuan=0.20)
calls=[0]; yuan=[0.0]; tok=[0]; reserve=[4]

def load_any(t):
    p=[x for x in json.load(open(f'{SD}/v23a/TASK_CANDIDATES_V23A.json'))['candidates'] if x['event_key']==t][0]['contract']
    if not os.path.isabs(p): p=f'{SD}/v23a/{p}'
    return json.load(open(p))

def call(alias, system, user, mt, purpose):
    for att in (1,2):
        if att==2:
            if reserve[0]<1: raise RuntimeError('NO RESERVE')
            reserve[0]-=1; print(f'  [reserve: {purpose}]')
        if calls[0]>=CAPS['calls']: raise RuntimeError('CALLS CAP')
        if yuan[0]+0.015>CAPS['yuan']*0.95: raise RuntimeError('YUAN CAP')
        body=build_request(alias,system,user,mt)
        sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        req=urllib.request.Request(MODEL_CFG[alias]['url'],data=json.dumps(body).encode(),method='POST')
        req.add_header('content-type','application/json')
        req.add_header('authorization','Bearer '+(ds_key() if alias=='deepseek' else glm_key()))
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

def led_load(*fs):
    d={}
    for f in fs:
        for l in open(f'{OUT}/{f}'):
            x=json.loads(l); d[x['purpose']]=x
    return d

def qp9_sink_prompt(task, contract, led8, led9):
    """QP9-era SINK prompt from the task's FROZEN E cache (empty/old table state)."""
    ents=[]
    for node in ('e0','e1'):
        r=led8.get(f'qp8r|{task}|DS|r1|{node}') or led9.get(f'qp9|{task}|E|deepseek|{node}')
        ents+=parse2(extract_any(r['text']) or {})
    mf={}
    for e in ents:
        k=str(e.get('field') or e.get('bucket') or '')
        if k and e.get('value') not in (None,''): mf.setdefault(k,e.get('value'))
    ver,_=CH.verify_evidence(ents,contract)
    return PP.render(contract,{},mf,PP.match_evidence(mf,ver,contract),with_evidence=True)

DIRECTED=('\n【重抽要求（本次追加）】上一轮抽取存在"值与引文错配"：部分事实值并未出现在其引用的原文中。'
 '本次抽取必须遵守：每条事实的 value 必须能在该条目给出的 quote 中直接找到（数字、日期、编号允许'
 '千分位/单位换算，但数值本身必须出现在 quote 内）；doc 与 page 必须是 quote 的真实出处；'
 '无法给出含该值的引文时，该条目留空，不要凭记忆填值。')

def directed_e(task, contract, led8, led9, node):
    docs=sorted(contract['source_pages'].keys()); h=(len(docs)+1)//2
    ed=docs[:h] if node=='e0' else (docs[h:] or docs[:1])
    return e_user(contract,ed,'E1')+DIRECTED

def main():
    led8={json.loads(l)['purpose']:json.loads(l) for l in open(f'{SD}/qp8/QP8R_STAGE1_LEDGER.jsonl')}
    led9={json.loads(l)['purpose']:json.loads(l) for l in open(f'{SD}/qp9/QP9_LEDGER.jsonl')}
    ct=led_load('CFL3_CROSSTASK_LEDGER.jsonl','CFL3_MIN_B_LEDGER.jsonl','STAGE1_E06_LEDGER.jsonl','TS4_LEDGER.jsonl')
    r3={json.loads(l)['purpose']:json.loads(l) for l in open(f'{OUT}/CFL3_MIN_LEDGER.jsonl')}
    c_k=load_contract(); c_m=load_any('MVR1'); c_e=load_any('E06'); c_z=load_any('ZEDA'); c_zj=load_any('ZIJING')
    contracts=dict(KANGMEI=c_k,MVR1=c_m,E06=c_e,ZEDA=c_z,ZIJING=c_zj)
    results=[]
    def score(task,obj):
        if obj is None: return dict(q=None,parse_fail=True)
        r=V2.score_task_v2(contracts[task],obj)
        rows=r['rows']
        return dict(q=r['q'],tp=sum(1 for x in rows if x['status']=='TP'),
                    wrong=sum(1 for x in rows if x['status'].startswith('VALUE')),
                    abst=sum(1 for x in rows if x['status']=='ABSENT'))
    def rec(ev,arm,out,c=0.0,l=0.0,note=''):
        row=dict(event=ev,arm=arm,**out,cost_yuan=round(c,6),lat_s=l,note=note)
        results.append(row); print(f"  {ev} {arm:7s} Q={out.get('q')} ¥{c:.4f} {note}")

    # ---- A1: KANGMEI empty-table collapse (org error) ; Static=0.0 measured
    p9=qp9_sink_prompt('KANGMEI',c_k,led8,led9)
    rec('A1','Static',dict(q=0.0),note='QP9 A_static frozen')
    o,la,y=call('deepseek',P_SYS,p9,MAXTOK['p'],'s3|A1|R|sink'); rec('A1','R',score('KANGMEI',o),y,la)
    o,la,y=call('glm53flash',P_SYS,p9,MAXTOK['p'],'s3|A1|pi|sink'); rec('A1','pi',score('KANGMEI',o),y,la)
    o,la,y=call('deepseek',P_SYS,p9,MAXTOK['p'],'s3|A1|Z|sink'); rec('A1','Z',score('KANGMEI',o),y,la,'LOCAL')
    # Joint = UPSTREAM: directed e1 re-extract + SINK on new pool
    oE,laE,yE=call('deepseek',E_SYS,directed_e('KANGMEI',c_k,led8,led9,'e1'),2000,'s3|A1|Joint|e1dir')
    if oE is not None:
        pool=dedup(parse2(oE),c_k)
        if pool:
            pj=bnew_prompt(c_k,pool,sel=True)
            o,la,y=call('deepseek',P_SYS,pj,MAXTOK['p'],'s3|A1|Joint|sink')
            rec('A1','Joint',score('KANGMEI',o),yE+y,laE+la,'UPSTREAM dir-e1+SINK')
        else: rec('A1','Joint',dict(q=0.0),yE,laE,'UPSTREAM e1 empty')
    json.dump(dict(batch='STAGE3',results=results),open(f'{OUT}/STAGE3_PARTIAL.json','w'),ensure_ascii=False,indent=1)
    print(f"[A1 done] calls={calls[0]} tok={tok[0]} ¥{yuan[0]:.4f}")

    # ---- A3: ZEDA SINK collapse (CrossTask B_new r2 state)
    ents_z=[]
    for node in ('e0','e1'):
        ents_z+=parse2(extract_any(led9[f'qp9|ZEDA|E|deepseek|{node}']['text']) or {})
    pool_z=dedup(ents_z,c_z)
    pz=bnew_prompt(c_z,pool_z,sel=False)
    rec('A3','Static',dict(q=0.176),note='CrossTask B_new r2 frozen')
    o,la,y=call('deepseek',P_SYS,pz,MAXTOK['p'],'s3|A3|R|sink'); rec('A3','R',score('ZEDA',o),y,la)
    o,la,y=call('glm53flash',P_SYS,pz,MAXTOK['p'],'s3|A3|pi|sink'); rec('A3','pi',score('ZEDA',o),y,la)
    o,la,y=call('deepseek',P_SYS,pz,MAXTOK['p'],'s3|A3|Z|sink'); rec('A3','Z',score('ZEDA',o),y,la,'LOCAL')
    o,la,y=call('deepseek',P_SYS,pz+SEL_BLOCK,MAXTOK['p'],'s3|A3|Joint|sink'); rec('A3','Joint',score('ZEDA',o),y,la,'LOCAL+SEL')

    # ---- A4: KANGMEI info-collapse; Z==Joint collapse declared
    rec('A4','Static',dict(q=0.0),note='QP9 frozen')
    o,la,y=call('deepseek',P_SYS,p9,MAXTOK['p'],'s3|A4|R|sink'); rec('A4','R',score('KANGMEI',o),y,la)
    o,la,y=call('glm53flash',P_SYS,p9,MAXTOK['p'],'s3|A4|pi|sink'); rec('A4','pi',score('KANGMEI',o),y,la)
    oE,laE,yE=call('deepseek',E_SYS,directed_e('KANGMEI',c_k,led8,led9,'e1'),2000,'s3|A4|ZJoint|e1dir')
    sc= dict(q=0.0)
    if oE is not None:
        pool=dedup(parse2(oE),c_k)
        if pool:
            o,la,y=call('deepseek',P_SYS,bnew_prompt(c_k,pool,sel=True),MAXTOK['p'],'s3|A4|ZJoint|sink')
            sc=score('KANGMEI',o); yE=yE+y; laE=laE+la
    rec('A4','Z',dict(sc),yE,laE,'UPSTREAM collapse'); rec('A4','Joint',dict(sc),yE,laE,'UPSTREAM')

    # ---- A5: E06 J misbinding (frozen Stage-1 prompt incl wrong-date J)
    pool_e=[]; seen_e=set()
    for node in ('e0','e1'):
        for e in parse2(extract_any(led8[f'qp8r|E06|GLM|r1|{node}']['text']) or {}):
            if not four_part_check(e,c_e)[0]: continue
            v=e.get('raw') or e.get('value')
            k=(str(e.get('field')),str(e.get('doc')),str(e.get('page')),Q1._norm(e.get('quote') or ''),Q1._norm(str(v)))
            if k in seen_e: continue
            seen_e.add(k); pool_e.append(e)
    jw=json.load(open(f'{OUT}/E06_PRECHECK.json'))['j_rows']
    pe=bnew_prompt(c_e,pool_e,sel=True)+'\n\n'+j_block(jw)
    rec('A5','Static',dict(q=0.588),note='Stage-1 r1 frozen')
    o,la,y=call('deepseek',P_SYS,pe,MAXTOK['p'],'s3|A5|R|sink'); rec('A5','R',score('E06',o),y,la)
    o,la,y=call('glm53flash',P_SYS,pe,MAXTOK['p'],'s3|A5|pi|sink'); rec('A5','pi',score('E06',o),y,la)
    oS=extract_any(ct['stage1|E06|DS_J|r1|p']['text'])
    if oS:
        oS['answers']=[a for a in oS.get('answers',[]) if a.get('fact_id') not in ('H1','H2')]
        sc=score('E06',oS)
        rec('A5','Z',sc,0.0,0.0,'UNKNOWN-mask 0call'); rec('A5','Joint',dict(sc),0.0,0.0,'UNKNOWN-mask')

    # ---- A6: E06 H3 violation (frozen Stage-1 r2)
    rec('A6','Static',dict(q=0.529),note='Stage-1 r2 frozen')
    o,la,y=call('deepseek',P_SYS,pe,MAXTOK['p'],'s3|A6|R|sink'); rec('A6','R',score('E06',o),y,la)
    o,la,y=call('glm53flash',P_SYS,pe,MAXTOK['p'],'s3|A6|pi|sink'); rec('A6','pi',score('E06',o),y,la)
    oS=extract_any(ct['stage1|E06|DS_J|r2|p']['text'])
    if oS:
        oS['answers']=[a for a in oS.get('answers',[]) if a.get('fact_id') not in ('H3','H1','H2')]
        sc=score('E06',oS)
        rec('A6','Z',sc,0.0,0.0,'mask 0call'); rec('A6','Joint',dict(sc),0.0,0.0,'mask')

    # ---- A7: KANGMEI parse-fail (frozen MIN-B B_new prompt)
    pool_k2=dedup([e for rep in (1,2) for e in parse2(extract_any(r3[f'cfl3min|KANGMEI|C|r{rep}|e1_reext']['text']) or {})],c_k)
    pmb=bnew_prompt(c_k,pool_k2,sel=False)
    rec('A7','Static',dict(q=0.571),note='MIN-B r2_retry frozen')
    o,la,y=call('deepseek',P_SYS,pmb,MAXTOK['p'],'s3|A7|R|sink'); rec('A7','R',score('KANGMEI',o),y,la)
    o,la,y=call('glm53flash',P_SYS,pmb,MAXTOK['p'],'s3|A7|pi|sink'); rec('A7','pi',score('KANGMEI',o),y,la)
    o,la,y=call('deepseek',P_SYS,pmb,MAXTOK['p'],'s3|A7|ZJoint|sink'); sc=score('KANGMEI',o)
    rec('A7','Z',sc,y,la,'LOCAL collapse'); rec('A7','Joint',dict(sc),y,la,'LOCAL')

    # ---- A9: ZEDA coverage gap; Z=Joint UPSTREAM
    rec('A9','Static',dict(q=0.176),note='CrossTask frozen')
    o,la,y=call('deepseek',P_SYS,pz,MAXTOK['p'],'s3|A9|R|sink'); rec('A9','R',score('ZEDA',o),y,la)
    o,la,y=call('glm53flash',P_SYS,pz,MAXTOK['p'],'s3|A9|pi|sink'); rec('A9','pi',score('ZEDA',o),y,la)
    ents_n=[]; yU=0.0; laU=0.0
    for node in ('e0','e1'):
        oE,laE,yE=call('deepseek',E_SYS,directed_e('ZEDA',c_z,led8,led9,node),2000,f's3|A9|ZJoint|{node}dir')
        if oE is not None: ents_n+=parse2(oE); yU+=yE; laU+=laE
    pool_n=dedup(ents_n,c_z); sc=dict(q=0.176)
    if pool_n:
        o,la,y=call('deepseek',P_SYS,bnew_prompt(c_z,pool_n,sel=True),MAXTOK['p'],'s3|A9|ZJoint|sink')
        sc=score('ZEDA',o); yU+=y; laU+=la
    rec('A9','Z',dict(sc),yU,laU,'UPSTREAM collapse'); rec('A9','Joint',dict(sc),yU,laU,'UPSTREAM')

    # ---- A10: ZIJING doc-level (waste discriminator)
    p9z=qp9_sink_prompt('ZIJING',c_zj,led8,led9)
    rec('A10','Static',dict(q=0.05),note='QP9 frozen')
    o,la,y=call('deepseek',P_SYS,p9z,MAXTOK['p'],'s3|A10|R|sink'); rec('A10','R',score('ZIJING',o),y,la,'waste?')
    o,la,y=call('glm53flash',P_SYS,p9z,MAXTOK['p'],'s3|A10|pi|sink'); rec('A10','pi',score('ZIJING',o),y,la,'waste?')
    rec('A10','Z',dict(q=0.05),0.0,0.0,'NONE 0call'); rec('A10','Joint',dict(q=0.05),0.0,0.0,'NONE 0call')

    json.dump(dict(batch='STAGE3',caps=CAPS,
                   used=dict(calls=calls[0],yuan=round(yuan[0],4),tokens=tok[0],reserve_left=reserve[0]),
                   results=results),open(f'{OUT}/STAGE3_RESULTS.json','w'),ensure_ascii=False,indent=1)
    print(f"DONE: {calls[0]}/{CAPS['calls']} calls, {tok[0]}/{CAPS['tokens']} tok, ¥{yuan[0]:.4f}, reserve={reserve[0]}")

if __name__=='__main__':
    main()
