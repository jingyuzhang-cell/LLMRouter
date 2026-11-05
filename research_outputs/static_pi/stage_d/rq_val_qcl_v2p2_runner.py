#!/usr/bin/env python3
"""RQ_DYN_VAL_QCL_V2P2: extract+merge with output saving + Q scoring. 48 calls."""
import os,sys,json,time,argparse,hashlib,re
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget

YUAN={'deepseek':0.0129,'qwen':0.02}
MODELS=['deepseek','qwen']
REPS=3
EV={
 'E03_yuandao':Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence'),
 'E04_zhuoran':Path('/root/cap_eval_bench_v1/evidence/texts'),
}
EV_FILES={
 'E03_yuandao':[('D1','D1_E03-yuandao_2026-05-08.txt'),('D2','D2_E03-yuandao_2026-08-29.txt'),('D3','D3_E03-yuandao_2026-08-29.txt')],
 'E04_zhuoran':[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')],
}
def get_docs(ev):
    return {d:(EV[ev]/f).read_text('utf-8') for d,f in EV_FILES[ev]}
def extract_prompt(ev,doc_id,doc_text):
    return f"提取该文档中的关键事实（日期、金额、主体、违法事实、处罚措施）：\n\n文档 [{doc_id}]:\n{doc_text}\n\n按系统格式输出 JSON。"
def merge_prompt(ev,upstream_json):
    return f"合并以下多份文档的事实，建立事件时间线：\n\n{upstream_json}\n\n按系统格式输出 JSON。"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default=str(HERE/'rq_val_qcl_v2p2_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    gb=GlobalBudget(48,2.0,400000,out)
    ledger=out/'ledger.jsonl'; outputs=out/'outputs.jsonl'
    done=0
    for event in ('E03_yuandao','E04_zhuoran'):
        docs=get_docs(event)
        for rep in range(1,REPS+1):
            upstream={}
            for doc_id,doc_text in docs.items():
                userp=extract_prompt(event,doc_id,doc_text)
                for model in MODELS:
                    est=YUAN[model]; mt=2000
                    sysp=SYS_COMMON
                    gb.reserve_call(est)
                    need=gb.reserve_tokens(min(len(userp),12000),mt)
                    if a.real:
                        r=cap_transport(model,sysp,userp,mt,180)
                        text=r['text']; tin=r['in']; tout=r['out']; stop=r['stop']; lat=r['lat']
                    else:
                        text='{"facts":[]}'; tin=len(userp); tout=10; stop='end_turn'; lat=0.01
                    gb.release_reservation(need,tin,tout); gb.settle(est,0,0)
                    rec=dict(ts=time.time(),event=event,node_type='extract',node_id=f'ext_{doc_id}',
                             model=model,rep=rep,max_tokens=mt,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat)
                    with open(ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                    with open(outputs,'a') as f: f.write(json.dumps({**rec,"raw_output":text},ensure_ascii=False)+'\n')
                    ok,facts,unk=parse_facts(text)
                    if doc_id not in upstream or len(facts)>len(upstream.get(doc_id,[])):
                        upstream[doc_id]=facts
                    done+=1
                    print(f'  {event} ext_{doc_id} {model} r{rep} ({done}/48)')
            upstream_json=json.dumps(upstream,ensure_ascii=False)[:4000]
            mt_merge=4000
            for model in MODELS:
                est=YUAN[model]
                sysp=SYS_COMMON+D2_CONTRACT
                userp=merge_prompt(event,upstream_json)
                gb.reserve_call(est)
                need=gb.reserve_tokens(min(len(userp),12000),mt_merge)
                if a.real:
                    r=cap_transport(model,sysp,userp,mt_merge,180)
                    text=r['text']; tin=r['in']; tout=r['out']; stop=r['stop']; lat=r['lat']
                else:
                    text='{"facts":[]}'; tin=len(userp); tout=10; stop='end_turn'; lat=0.01
                gb.release_reservation(need,tin,tout); gb.settle(est,0,0)
                rec=dict(ts=time.time(),event=event,node_type='merge',node_id='merge',
                         model=model,rep=rep,max_tokens=mt_merge,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat)
                with open(ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                with open(outputs,'a') as f: f.write(json.dumps({**rec,"raw_output":text},ensure_ascii=False)+'\n')
                done+=1
                print(f'  {event} merge {model} r{rep} ({done}/48)')
    print(f'DONE: {done}, budget={gb.left()}')

if __name__=='__main__':
    main()
