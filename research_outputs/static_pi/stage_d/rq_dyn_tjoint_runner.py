#!/usr/bin/env python3
"""RQ-DYN-TRANSIENT: merge base truncated, recovery NOT truncated. R vs pi."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,signals,score_node
from rq2_p2r_v3_runner import D2_CONTRACT
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget,RunStore

YUAN={'deepseek':0.0129,'qwen':0.02}
ALLOC_MERGE='qwen'  # from capability matrix
ALLOC_ALT='deepseek'
REPS=3

EVENTS={
 'E04_zhuoran':Path('/root/cap_eval_bench_v1/evidence/texts'),
 'E03_yuandao':Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence'),
}
DOCS={
 'E04_zhuoran':[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')],
 'E03_yuandao':[('D1','D1_E03-yuandao_2026-05-08.txt'),('D2','D2_E03-yuandao_2026-08-29.txt'),('D3','D3_E03-yuandao_2026-08-29.txt')],
}

def truncate(t,n=20): return t[:n]

def get_docs(ev): return {d:(EVENTS[ev]/f).read_text('utf-8') for d,f in DOCS[ev]}

def extract_prompt(doc_id,doc_text):
    return f"从该文档中提取以下各类事实：\n1.日期类 2.金额类 3.主体类（姓名+职务）4.违法类 5.处罚类 6.风险类\n每条事实必须包含fid、value、doc、quote。不要遗漏处罚金额和责任人。\n\n文档 [{doc_id}]:\n{doc_text}\n\n按系统格式输出 JSON。"

def merge_prompt(all_facts):
    return f"合并以下全部事实。保留原始fid/value/doc/quote，同fid去重，不同年份/主体不合并。\n\n{all_facts}\n\n按系统格式输出 JSON。"

def verify_prompt(upstream,docs_text):
    return f"对以下每条事实进行核验，标注verified/unverified/conflict。不要删除任何事实。\n\n事实：{upstream}\n\n原始文档：{docs_text[:2000]}\n\n按系统格式输出 JSON。"

def report_prompt(merge_facts,verify_status):
    return f"基于以下完整事实（含核验状态）生成终端调查报告。对verified明确陈述；对unverified披露状态。不要遗漏事实。\n\n事实集合：\n{merge_facts}\n\n核验状态：{verify_status}\n\n按系统格式输出 JSON。"

def call_model(model,system,user,mt):
    r=cap_transport(model,system,user,mt,180)
    return r

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default=str(HERE/'rq_dyn_transient_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    st=out/'state'; st.mkdir(exist_ok=True)
    gb=GlobalBudget(30,1.0,150000,st)
    ledger=out/'ledger.jsonl'; outputs=out/'outputs.jsonl'
    
    def do_call(arm,ev,rep,node,role,model,system,user,mt,inject=False):
        est=YUAN[model]
        gb.reserve_call(est)
        need=gb.reserve_tokens(min(len(user),12000),mt)
        if a.real:
            r=call_model(model,system,user,mt)
            text=r['text']
            if inject: text=truncate(text)
            tin,tout=r['in'],r['out']; stop=r['stop']; lat=r['lat']
        else:
            text='{"facts":[{"fid":"m","value":"mock","doc":"d1","quote":"q"}]}'
            if inject: text=truncate(text)
            tin=len(user); tout=64; stop='end_turn'; lat=0.01
        gb.release_reservation(need,tin,tout); gb.settle(est,0,0)
        rec=dict(ts=time.time(),arm=arm,event=ev,rep=rep,node=node,role=role,
                 model=model,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat,injected=inject)
        with open(ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    # Reuse extract outputs from previous experiments (load from existing outputs.jsonl)
    cached_extracts={}
    for prev_dir in ['rq_dyn_3arm_v2_runs','rq_dyn_final_runs']:
        p=Path(prev_dir)/'outputs.jsonl'
        if p.exists():
            for line in open(p):
                o=json.loads(line)
                if o.get('role')=='base' and 'ext_' in str(o.get('node','')):
                    key=(o.get('event','E04'),o.get('node',''),o.get('rep'))
                    if key not in cached_extracts:
                        ok,facts,_=parse_facts(o.get('raw_output',''))
                        cached_extracts[key]=facts

    done=0
    for ev in ('E04_zhuoran','E03_yuandao'):
        docs=get_docs(ev)
        docs_text='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        
        for rep in range(1,REPS+1):
            # Get or create extract outputs
            upstream={}
            for doc_id,doc_text in docs.items():
                cache_key=(ev,f'ext_{doc_id}',rep)
                if cache_key in cached_extracts:
                    upstream[f'ext_{doc_id}']=cached_extracts[cache_key]
                else:
                    # Fallback: run extract (shouldn't happen if cache is populated)
                    userp=extract_prompt(doc_id,doc_text)
                    text=do_call('shared',ev,rep,f'ext_{doc_id}','base','deepseek',SYS_COMMON,userp,2000)
                    ok,facts,_=parse_facts(text)
                    upstream[f'ext_{doc_id}']=facts
            
            all_facts=[]
            for nid in upstream:
                all_facts+=[f for f in upstream[nid] if isinstance(f,dict)]
            all_json=json.dumps(all_facts,ensure_ascii=False)[:3000]
            merge_user=merge_prompt(all_json)
            
            for arm in ('Joint',):
                # Merge BASE: truncated (transient fault)
                text=do_call(arm,ev,rep,'merge','base',ALLOC_MERGE,
                            SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=True)
                ok,facts,_=parse_facts(text)
                
                # Joint ladder: R first (cheap), then pi if R fails
                # R: same-model retry (NOT truncated in transient)
                text2=do_call(arm,ev,rep,'merge','reroll',ALLOC_MERGE,
                            SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=False)
                ok2,f2,_=parse_facts(text2)
                if score_node(f2)>score_node(facts):
                    merge_out=f2; actions='R:recovered'
                else:
                    # pi: switch model (also NOT truncated in transient)
                    text3=do_call(arm,ev,rep,'merge','reroll2',ALLOC_ALT,
                                SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=False)
                    ok3,f3,_=parse_facts(text3)
                    if score_node(f3)>score_node(facts):
                        merge_out=f3; actions='pi:recovered'
                    else:
                        merge_out=facts; actions='R+pi:both_failed'
                
                # Verify
                merge_json=json.dumps(merge_out,ensure_ascii=False)[:2000]
                v_text=do_call(arm,ev,rep,'verify','base',ALLOC_MERGE,
                             SYS_COMMON+D2_CONTRACT,verify_prompt(merge_json,docs_text),4000)
                ok_v,vfacts,_=parse_facts(v_text)
                
                # Report
                vstatus={}
                for vf in vfacts:
                    if isinstance(vf,dict): vstatus[str(vf.get('fid',''))]=vf.get('status','unverified')
                combined=[]
                for mf in merge_out:
                    if isinstance(mf,dict):
                        combined.append({**mf,'verify_status':vstatus.get(str(mf.get('fid','')),'unverified')})
                r_text=do_call(arm,ev,rep,'report','base',ALLOC_MERGE,
                             SYS_COMMON+D2_CONTRACT,
                             report_prompt(json.dumps(combined,ensure_ascii=False)[:3000],
                                         json.dumps(vstatus,ensure_ascii=False)[:500]),4000)
                done+=1
                print(f'  {arm} {ev[:12]} r{rep} done actions={actions} ({done}/6) left={gb.left()["calls_left"]}')
    
    print(f'DONE: {done} budget={gb.left()}')

if __name__=='__main__':
    main()
