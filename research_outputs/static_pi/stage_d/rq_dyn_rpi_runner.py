#!/usr/bin/env python3
"""RQ-DYN-FINAL: StaticHetero vs JointDynamic, E04 卓然, merge fault injection."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,signals,score_node
from rq2_p2r_v3_runner import D2_CONTRACT,DELIVERY_KINDS
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget,RunStore

YUAN={'deepseek':0.0129,'qwen':0.02}
ALLOC={'extract':'deepseek','reason':'qwen','verification':'qwen','report':'qwen'}
REPS=5
EV=Path('/root/cap_eval_bench_v1/evidence/texts')
DOCS=[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')]

def truncate(t,n=20): return t[:n]

def get_docs(): return {d:(EV/f).read_text('utf-8') for d,f in DOCS}

def extract_prompt(doc_id,doc_text):
    return f"从该文档中提取以下各类事实：\n1.日期类 2.金额类 3.主体类（姓名+职务）4.违法类 5.处罚类（按主体分列金额）6.风险类\n每条事实必须包含fid、value、doc、quote。不要遗漏处罚金额和责任人。\n\n文档 [{doc_id}]:\n{doc_text}\n\n按系统格式输出 JSON。"

def merge_prompt(all_facts):
    return f"合并以下全部事实。保留原始fid/value/doc/quote，同fid去重，不同年份/主体不合并。\n\n{all_facts}\n\n按系统格式输出 JSON。"

def verify_prompt(upstream,docs_text):
    return f"对以下每条事实进行核验，标注verified/unverified/conflict。不要删除任何事实。\n\n事实：{upstream}\n\n原始文档：{docs_text[:2000]}\n\n按系统格式输出 JSON。"

def report_prompt(merge_facts,verify_status):
    return f"基于以下完整事实（含核验状态）生成终端调查报告。对verified明确陈述；对unverified披露状态。不要遗漏事实。\n\n事实集合：\n{merge_facts}\n\n核验状态：{verify_status}\n\n按系统格式输出 JSON。"

class Runner:
    def __init__(self,cfg,out,real):
        self.real=real; self.out=Path(out)
        st=self.out/'state'; st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.ledger=self.out/'ledger.jsonl'; self.outputs=self.out/'outputs.jsonl'
    def call(self,arm,rep,node_id,role,model,system,user,mt,inject=False):
        est=YUAN[model]
        self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(min(len(user),12000),mt)
        if self.real:
            r=cap_transport(model,system,user,mt,180)
            text=r['text']
            if inject:
                text=truncate(text)
            tin,tout=r['in'],r['out']; stop=r['stop']; lat=r['lat']
        else:
            text='{"facts":[{"fid":"m","value":"mock","doc":"d1","quote":"q"}]}'
            if inject: text=truncate(text)
            tin=len(user); tout=64; stop='end_turn'; lat=0.01
        self.gb.release_reservation(need,tin,tout); self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),arm=arm,rep=rep,node=node_id,role=role,
                 model=model,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat,
                 injected=inject)
        with open(self.ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    def run_exec(self,arm,rep):
        exec_id=f"{arm}|E04|{arm}|r{rep}"
        if self.store.completed(exec_id): return None
        self.store.begin(exec_id)
        docs=get_docs()
        dyn=arm=='JointDynamic'
        upstream={}; actions=[]

        # Extract nodes (no injection)
        for doc_id,doc_text in docs.items():
            model=ALLOC['extract']
            userp=extract_prompt(doc_id,doc_text)
            text=self.call(arm,rep,f'ext_{doc_id}','base',model,SYS_COMMON,userp,2000)
            ok,facts,unk=parse_facts(text)
            upstream[f'ext_{doc_id}']=facts

        # Merge node (INJECT truncation for both arms - same fault condition)
        all_facts=[]
        for nid in upstream:
            all_facts+= [f for f in upstream[nid] if isinstance(f,dict)]
        all_json=json.dumps(all_facts,ensure_ascii=False)[:3000]
        model=ALLOC['reason']
        userp=merge_prompt(all_json)
        # FAULT: truncate merge base call
        text=self.call(arm,rep,'merge','base',model,SYS_COMMON+D2_CONTRACT,userp,4000,inject=True)
        ok,facts,unk=parse_facts(text)
        sig=signals({'kind':'reason'},ok,facts)

        if sig['exec'] or sig['prod'] or sig['cite']:
            if arm=='pi-only':
                alt='deepseek' if model=='qwen' else 'qwen'
                text3=self.call(arm,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,userp,4000,inject=False)
                ok3,f3,u3=parse_facts(text3)
                if score_node(f3)>score_node(facts):
                    upstream['merge']=f3; actions.append('pi:recovered')
                else:
                    upstream['merge']=facts; actions.append('pi:failed')
            elif arm=='R-only':
                text2=self.call(arm,rep,'merge','reroll',model,SYS_COMMON+D2_CONTRACT,userp,4000,inject=True)
                ok2,f2,u2=parse_facts(text2)
                if score_node(f2)>score_node(facts):
                    upstream['merge']=f2; actions.append('R:recovered')
                else:
                    upstream['merge']=facts; actions.append('R:failed')
            elif not dyn:
                # StaticHetero: try same-model reroll once
                text2=self.call(arm,rep,'merge','reroll',model,SYS_COMMON+D2_CONTRACT,userp,4000,inject=True)
                ok2,f2,u2=parse_facts(text2)
                if score_node(f2)>score_node(facts):
                    upstream['merge']=f2
                    actions.append('R:recovered')
                else:
                    upstream['merge']=facts  # keep whatever we have
                    actions.append('R:failed')
            else:
                # JointDynamic: R (same model) -> pi (switch) -> Z2 (split)
                text2=self.call(arm,rep,'merge','reroll',model,SYS_COMMON+D2_CONTRACT,userp,4000,inject=True)
                ok2,f2,u2=parse_facts(text2)
                if score_node(f2)>score_node(facts):
                    upstream['merge']=f2
                    actions.append('R:recovered')
                else:
                    actions.append('R:failed')
                    # pi: switch to other model (NO injection on pi call)
                    alt='deepseek' if model=='qwen' else 'qwen'
                    text3=self.call(arm,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,userp,4000,inject=False)
                    ok3,f3,u3=parse_facts(text3)
                    if score_node(f3)>score_node(facts):
                        upstream['merge']=f3
                        actions.append('pi:recovered')
                    else:
                        actions.append('pi:failed')
                        # Z2: split per upstream branch
                        bfacts=[]
                        for un in [k for k in upstream if k.startswith('ext_')]:
                            if not upstream[un]: continue
                            sub={un:upstream[un]}
                            sub_json=json.dumps(sub,ensure_ascii=False)[:1500]
                            st_prompt=f"合并以下单一来源事实：\n\n{sub_json}\n\n按系统格式输出 JSON。"
                            bt=self.call(arm,rep,f'split_{un}','split','deepseek',SYS_COMMON,st_prompt,2000,inject=False)
                            bok,bf,bu=parse_facts(bt)
                            if bok: bfacts+= [x for x in bf if isinstance(x,dict)]
                        if bfacts:
                            upstream['merge']=bfacts
                            actions.append(f'Z2:split+join(n={len(bfacts)})')
                        else:
                            upstream['merge']=facts
                            actions.append('Z2:failed')
        else:
            upstream['merge']=facts

        # Verify node (annotate, no injection)
        model=ALLOC['verification']
        merge_json=json.dumps(upstream.get('merge',[]),ensure_ascii=False)[:2000]
        docs_text='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        userp=verify_prompt(merge_json,docs_text)
        text=self.call(arm,rep,'verify','base',model,SYS_COMMON+D2_CONTRACT,userp,4000)
        ok,vfacts,vunk=parse_facts(text)
        upstream['verify']=vfacts

        # Report node (dual input)
        model=ALLOC['report']
        merge_facts=upstream.get('merge',[])
        verify_status={}
        for vf in vfacts:
            if isinstance(vf,dict): verify_status[str(vf.get('fid',''))]=vf.get('status','unverified')
        combined=[]
        for mf in merge_facts:
            if isinstance(mf,dict):
                fid=str(mf.get('fid',''))
                combined.append({**mf,'verify_status':verify_status.get(fid,'unverified')})
        userp=report_prompt(json.dumps(combined,ensure_ascii=False)[:3000],
                           json.dumps(verify_status,ensure_ascii=False)[:500])
        text=self.call(arm,rep,'report','base',model,SYS_COMMON+D2_CONTRACT,userp,4000)
        ok,rfacts,runk=parse_facts(text)

        record=dict(exec_id=exec_id,arm=arm,rep=rep,actions=actions,
                    n_merge_facts=len(upstream.get('merge',[])),
                    n_report_facts=len(rfacts),
                    budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_dyn_final_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_dyn_final_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else: print('MOCK MODE'); return
    r=Runner(cfg,a.out,a.real)
    done=0
    for rep in range(1,REPS+1):
        for arm in ('StaticHetero','R-only','pi-only'):
            eid=f"{arm}|E04|{arm}|r{rep}"
            if r.store.completed(eid): continue
            if r.gb.left()['calls_left']<10: print('STOP'); return
            r.run_exec(arm,rep); done+=1
            print(f'  {arm} r{rep} done left={r.gb.left()["calls_left"]}')
    print(f'DONE: {done} budget={r.gb.left()}')

if __name__=='__main__':
    main()
