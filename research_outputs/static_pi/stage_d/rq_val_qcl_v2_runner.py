#!/usr/bin/env python3
"""RQ_DYN_VAL_QCL_V2 Phase 1: verify+report with fixed budgets + output saving. 24 calls."""
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
MAXTOK=4000
EV={
 'E03_yuandao':Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence'),
 'E04_zhuoran':Path('/root/cap_eval_bench_v1/evidence/texts'),
}
EV_FILES={
 'E03_yuandao':[('D1','D1_E03-yuandao_2026-05-08.txt'),('D2','D2_E03-yuandao_2026-08-29.txt'),('D3','D3_E03-yuandao_2026-08-29.txt')],
 'E04_zhuoran':[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')],
}
def get_docs(event):
    return {d:(EV[event]/f).read_text('utf-8') for d,f in EV_FILES[event]}

def build_upstream(event,docs):
    # Simulate extract+merge by concatenating all docs as upstream facts
    # (For Q measurement of verify/report, we need representative upstream)
    parts=[]
    for d,t in docs.items():
        parts.append(f'[{d}] {t[:1500]}')
    return '\n\n'.join(parts)

def verify_prompt(event,upstream,docs_text):
    return f"核验以下事实的一致性，检查跨文档日期/金额/主体是否有矛盾或互补：\n\n上游事实：\n{upstream[:2000]}\n\n原始文档：\n{docs_text[:2000]}\n\n按系统格式输出 JSON。"

def report_prompt(event,upstream):
    return f"基于以下事实生成综合调查报告（事件演变、违法事实、监管处置、市场风险）：\n\n{upstream[:3000]}\n\n按系统格式输出 JSON。"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default=str(HERE/'rq_val_qcl_v2_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    gb=GlobalBudget(24,1.5,200000,out)
    ledger=out/'ledger.jsonl'; outputs=out/'outputs.jsonl'
    done=0
    for event in ('E03_yuandao','E04_zhuoran'):
        docs=get_docs(event)
        upstream=build_upstream(event,docs)
        docs_text='\n\n'.join(f'[{d}]\n{t[:1000]}' for d,t in docs.items())
        for rep in range(1,REPS+1):
            for node_type,prompt_fn in [('verify',lambda: verify_prompt(event,upstream,docs_text)),
                                         ('report',lambda: report_prompt(event,upstream))]:
                for model in MODELS:
                    est=YUAN[model]
                    gb.reserve_call(est)
                    need=gb.reserve_tokens(min(len(prompt_fn()),12000),MAXTOK)
                    sysp=SYS_COMMON+D2_CONTRACT
                    if a.real:
                        r=cap_transport(model,sysp,prompt_fn(),MAXTOK,180)
                        text=r['text']; tin=r['in']; tout=r['out']; stop=r['stop']; lat=r['lat']
                    else:
                        text='{"facts":[]}'; tin=len(prompt_fn()); tout=10; stop='end_turn'; lat=0.01
                    gb.release_reservation(need,tin,tout)
                    gb.settle(est,0,0)
                    rec=dict(ts=time.time(),event=event,node_type=node_type,model=model,
                             rep=rep,max_tokens=MAXTOK,tin=tin,tout=tout,yuan=est,
                             stop=stop,lat=lat)
                    out_rec=dict(**rec,raw_output=text)
                    with open(ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                    with open(outputs,'a') as f: f.write(json.dumps(out_rec,ensure_ascii=False)+'\n')
                    done+=1
                    print(f'  {event} {node_type} {model} r{rep} done ({done}/24)')
    print(f'DONE: {done}, budget={gb.left()}')

if __name__=='__main__':
    main()
