"""SINK restructuring minimal pair (authorized 4 calls): step1 DS fact->row
selection (1 call/rep), step2 deterministic assembly (0), step3 V gate (0).
Frozen ROUND3 SINK = control. PRE-CALL token check: used+est_in+max_out+margin.
Caps: 4 calls / 20,000 tokens / 0.03 yuan."""
import json, os, sys, time, hashlib, urllib.request, urllib.error, re
SD='/root/research_outputs/static_pi/stage_d'
sys.path.insert(0,f'{SD}/quality_phase_v1'); sys.path.insert(0,f'{SD}/qp3'); sys.path.insert(0,f'{SD}/v2'); sys.path.insert(0,SD)
from real_provider_v22 import extract_any
from parser_v2 import normalize_stage_v2_string_values as parse2
import scorer_qp1 as Q1
import scorer_qp1_v2 as V2
from qp1_prompts import P_SYS
from stage_d_v2_transport import build_request, ds_key, MODEL_CFG
from ts4_runner import dedup
from round2b_runner import load_contract_path
OUT=f'{SD}/cfl_stage1'; LEDGER=f'{OUT}/SINKR_LEDGER.jsonl'
CAPS=dict(calls=4,tokens=20_000,yuan=0.03); MARGIN=1500
NUM=r'(-?\d[\d,，.]*\s*(?:亿元|万元|元|%))'; AMT=('罚款','处罚','虚增','虚减','金额','利润','成本','收入','支出','占','比例')
calls=[0]; yuan=[0.0]; tok=[0]
recs3={json.loads(l)['purpose']:json.loads(l) for l in open(f'{OUT}/ROUND3_LEDGER.jsonl')}
for _f in ('ROUND2B_LEDGER.jsonl',):
    for _l in open(f'{OUT}/{_f}'):
        _x=json.loads(_l); recs3.setdefault(_x['purpose'],_x)
def call(user,mt,purpose,est_in):
    if calls[0]>=CAPS['calls']: raise RuntimeError('CALLS CAP')
    if tok[0]+est_in+mt+MARGIN>CAPS['tokens']:
        raise RuntimeError(f'PRE-CALL TOKEN REFUSED: used={tok[0]} est={est_in+mt+MARGIN}')
    if yuan[0]+0.004>CAPS['yuan']*0.95: raise RuntimeError('YUAN CAP')
    body=build_request('deepseek',P_SYS,user,mt)
    sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    req=urllib.request.Request(MODEL_CFG['deepseek']['url'],data=json.dumps(body).encode(),method='POST')
    req.add_header('content-type','application/json'); req.add_header('authorization','Bearer '+ds_key())
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=240) as r: d=json.loads(r.read().decode())
    ch=d['choices'][0]; u=d.get('usage',{})
    c=ch.get('message',{}).get('content','')
    text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else (c or '')
    tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
    y=round(tin*0.8e-6+tout*2.8e-6,8)
    calls[0]+=1; yuan[0]+=y; tok[0]+=tin+tout
    with open(LEDGER,'a') as f:
        f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias='deepseek',purpose=purpose,
            prompt_sha256=sha,usage=dict(input_tokens=tin,output_tokens=tout),accounting_yuan=y,
            latency_s=round(time.monotonic()-t0,3),text=text),ensure_ascii=False)+'\n')
    if tok[0]>=CAPS['tokens']: raise RuntimeError('TOKEN CAP(post)')
    return extract_any(text)
def canon(v,kind,amt):
    if amt:
        m=re.search(NUM,str(v))
        if m: return re.sub(r'(?<=\d),(?=\d)','',m.group(1))
    return str(v)
for task in ('ZHANGZIDAO','KDX'):
    ct=load_contract_path(task)
    facts=[f for f in ct['required_facts'] if f.get('status') not in ('EXCLUDED','NOT_APPLICABLE')]
    ents=[]
    for n in ('e0','e1'): ents+=parse2(extract_any(recs3[f'r3|{task}|E|{n}']['text'] if f'r3|{task}|E|{n}' in recs3 else recs3[f'r2b|{task}|E|{n}']['text']) or {})
    pool=dedup(ents,ct)
    rows='\n'.join(f"{i}. field={e.get('field') or e.get('bucket')} | value={e.get('raw') or e.get('value')} | doc={e.get('doc')} | page={e.get('page')} | quote={ (e.get('quote') or '')[:60]}" for i,e in enumerate(pool,1))
    slots='\n'.join(f"- {f['fact_id']}: 主体={f.get('subject')}；要求={f.get('predicate')}；类型={f.get('value_kind')}" for f in facts)
    prompt=(f"任务问题：{ct['question']}\n\n证据行（编号）：\n{rows}\n\n事实槽位：\n{slots}\n\n"
      "请为每个槽位从证据行中选出正确对应的一行（判断主体、科目/谓词、年份是否一致），"
      "无法唯一确定时选 UNKNOWN。只输出 JSON：{\"selections\":[{\"fact_id\":...,\"row\":<编号或\"UNKNOWN\">}]}")
    est_in=len(prompt)//2+800
    for rep in (1,2):
        o=call(prompt,1500,f'sinkr|{task}|sel|r{rep}',est_in)
        sel={s.get('fact_id'):s.get('row') for s in (o or {}).get('selections',[]) if isinstance(s,dict)}
        answers=[]; n_unknown=0; n_rejected=0
        for f in facts:
            r=sel.get(f['fact_id'])
            if not isinstance(r,int) or not (1<=r<=len(pool)):
                n_unknown+=1; continue
            e=pool[r-1]
            amt=any(k in str(f.get('predicate'))+str(f.get('subject')) for k in AMT)
            v=canon(e.get('raw') or e.get('value'),f.get('value_kind'),amt)
            doc=ct['source_pages'].get(str(e.get('doc')))
            pg=(doc or {}).get('pages',{}).get(str(e.get('page')))
            okV=pg and e.get('quote') and Q1._norm(e.get('quote')) in Q1._norm(pg.get('text','')) and Q1.value_in_quote(v,e.get('quote'))
            if okV:
                answers.append(dict(fact_id=f['fact_id'],value=v,doc=e.get('doc'),page=e.get('page'),quote=e.get('quote')))
            else: n_rejected+=1
        res=V2.score_task_v2(ct,dict(answers=answers))
        tp=sum(1 for x in res['rows'] if x['status']=='TP')
        wrong=sum(1 for x in res['rows'] if x['status'].startswith('VALUE'))
        print(f"{task} r{rep}: Q={res['q']} TP={tp} wrong={wrong} UNKNOWN_slots={n_unknown} V_rejected={n_rejected} (pool={len(pool)})")
print(f"DONE: {calls[0]}/{CAPS['calls']} tok={tok[0]}/{CAPS['tokens']} ¥{yuan[0]:.4f}")
