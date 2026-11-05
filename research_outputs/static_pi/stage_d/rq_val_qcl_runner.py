#!/usr/bin/env python3
"""RQ_DYN_VAL_QCL: node-level Q/C/L/Reliability measurement, 72 calls."""
import os,sys,json,time,argparse,hashlib,re
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,signals,score_node
from rq2_p2r_v3_runner import D2_CONTRACT,DELIVERY_KINDS,n_upstream_facts,MAXTOK_BASE,D1_PER_FACT,D1_CAP
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget

YUAN={'deepseek':0.0129,'qwen':0.02}
REPS=3
MODELS=['deepseek','qwen']

# Evidence paths
EV={
 'E03_yuandao':Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence'),
 'E04_zhuoran':Path('/root/cap_eval_bench_v1/evidence/texts'),
}
EV_FILES={
 'E03_yuandao':[('D1','D1_E03-yuandao_2026-05-08.txt'),('D2','D2_E03-yuandao_2026-08-29.txt'),('D3','D3_E03-yuandao_2026-08-29.txt')],
 'E04_zhuoran':[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')],
}
GOLD={
 'E03_yuandao':json.load(open(HERE/'E03_GOLD_CANDIDATES.json')),
 'E04_zhuoran':json.load(open(Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/e04_candidates_atomic_facts.json')))['candidates'],
}

def get_docs(event):
    docs={}
    for doc_id,fname in EV_FILES[event]:
        p=EV[event]/fname
        docs[doc_id]=p.read_text('utf-8') if p.exists() else ''
    return docs

def extract_prompt(event,doc_id,doc_text):
    task_desc={
     'E03_yuandao':'提取该文档中的关键事实：日期、金额、主体、违法事实、处罚措施',
     'E04_zhuoran':'提取该文档中的关键事实：日期、金额、主体、违法事实、处罚措施',
    }
    return f"调查问题：{task_desc[event]}\n\n文档 [{doc_id}]:\n{doc_text}\n\n按系统格式输出 JSON。"

def merge_prompt(event,upstream_json):
    return f"合并以下多份文档的事实，建立事件时间线：\n\n{upstream_json}\n\n按系统格式输出 JSON。"

def verify_prompt(event,upstream_json,docs_text):
    return f"核验以下事实的一致性，检查是否有矛盾或互补关系：\n\n事实：{upstream_json}\n\n原始文档：\n{docs_text[:3000]}\n\n按系统格式输出 JSON。"

def report_prompt(event,upstream_json):
    return f"基于以下已核验的事实，生成终端调查报告：\n\n{upstream_json}\n\n按系统格式输出 JSON。"

def call_model(model,system,user,mt):
    est=YUAN[model]
    r=cap_transport(model,system,user,mt,180)
    return r

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_val_qcl_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_val_qcl_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else:
        print('MOCK MODE'); return
    
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),out)
    ledger=out/'ledger.jsonl'; results=out/'results.jsonl'
    
    def do_call(event,node_type,node_id,model,system,user,mt,rep):
        est=YUAN[model]
        gb.reserve_call(est)
        need=gb.reserve_tokens(min(len(user),12000),mt)
        r=call_model(model,system,user,mt)
        gb.release_reservation(need,r['in'],r['out'])
        gb.settle(est,0,0)
        rec=dict(ts=time.time(),event=event,node_type=node_type,node_id=node_id,
                 model=model,rep=rep,tin=r['in'],tout=r['out'],yuan=est,
                 stop=r['stop'],lat=r['lat'],model_resp=r.get('model'),
                 prompt_sha=hashlib.sha256((system+'||'+user[:200]).encode()).hexdigest()[:16])
        with open(ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        return r['text'],rec
    
    done=0
    for event in ['E03_yuandao','E04_zhuoran']:
        docs=get_docs(event)
        for rep in range(1,REPS+1):
            # Extract nodes
            upstream={}
            for doc_id,doc_text in docs.items():
                for model in MODELS:
                    sysp=SYS_COMMON
                    userp=extract_prompt(event,doc_id,doc_text)
                    text,rec=do_call(event,'extract',f'ext_{doc_id}',model,sysp,userp,MAXTOK_BASE,rep)
                    ok,facts,unk=parse_facts(text)
                    if doc_id not in upstream or len(facts)>len(upstream.get(doc_id,[])):
                        upstream[doc_id]=facts
                    done+=1
                    print(f'  {event} ext_{doc_id} {model} r{rep} done ({done}/72)')
            
            upstream_json=json.dumps(upstream,ensure_ascii=False)
            docs_text='\n\n'.join(f'[{d}]\n{t[:1000]}' for d,t in docs.items())
            
            # Merge
            for model in MODELS:
                sysp=SYS_COMMON+D2_CONTRACT
                mt=min(D1_CAP,MAXTOK_BASE+D1_PER_FACT*sum(len(v) for v in upstream.values()))
                text,rec=do_call(event,'merge','merge',model,sysp,merge_prompt(event,upstream_json),mt,rep)
                done+=1
                print(f'  {event} merge {model} r{rep} done ({done}/72)')
            
            # Verify
            for model in MODELS:
                sysp=SYS_COMMON+D2_CONTRACT
                text,rec=do_call(event,'verify','verify',model,sysp,verify_prompt(event,upstream_json,docs_text),MAXTOK_BASE,rep)
                done+=1
                print(f'  {event} verify {model} r{rep} done ({done}/72)')
            
            # Report
            for model in MODELS:
                sysp=SYS_COMMON+D2_CONTRACT
                text,rec=do_call(event,'report','report',model,sysp,report_prompt(event,upstream_json),MAXTOK_BASE,rep)
                done+=1
                print(f'  {event} report {model} r{rep} done ({done}/72)')
    
    print(f'BATCH DONE: {done} calls, budget={gb.left()}')

if __name__=='__main__':
    main()
