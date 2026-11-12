#!/usr/bin/env python3
"""RQ-DYN-JOINT-FINAL: 3-arm × 5-rep joint scheduling with full R→π→Z2 recovery."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,signals,score_node
from rq2_p2r_v3_runner import D2_CONTRACT,DELIVERY_KINDS
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

def ds_call(system,user,mt):
    import urllib.request,os
    key=os.environ.get('DEEPSEEK_API_KEY','')
    if not key:
        key=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('DEEPSEEK_API_KEY=')][0]
    body={'model':'deepseek-flash','max_tokens':mt,
          'messages':[{'role':'system','content':system},{'role':'user','content':user}],
          'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
    req=urllib.request.Request('https://api.deepseek.com/chat/completions',
        data=json.dumps(body,ensure_ascii=False).encode(),method='POST')
    req.add_header('Content-Type','application/json')
    req.add_header('Authorization','Bearer '+key)
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r:
        d=json.loads(r.read().decode())
    c=d['choices'][0]['message'].get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    u=d['usage']
    return {'text':c,'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),
            'stop':d['choices'][0].get('finish_reason',''),'lat':round(time.monotonic()-t0,2),
            'model':d.get('model','deepseek-flash')}

def qwen_call(system,user,mt):
    import urllib.request,os
    key=os.environ.get('QWEN_API_KEY','')
    if not key:
        key=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('QWEN_API_KEY=')][0]
    body={'model':'qwen-plus','max_tokens':mt,
          'messages':[{'role':'system','content':system},{'role':'user','content':user}],
          'response_format':{'type':'json_object'}}
    req=urllib.request.Request('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
        data=json.dumps(body,ensure_ascii=False).encode(),method='POST')
    req.add_header('Content-Type','application/json')
    req.add_header('Authorization','Bearer '+key)
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r:
        d=json.loads(r.read().decode())
    c=d['choices'][0]['message'].get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    u=d['usage']
    return {'text':c,'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),
            'stop':d['choices'][0].get('finish_reason',''),'lat':round(time.monotonic()-t0,2),
            'model':d.get('model','qwen-plus')}

class Runner:
    def __init__(self,cfg,out,real,inject_persistent=False):
        self.real=real; self.inject_persistent=inject_persistent
        self.out=Path(out)
        st=self.out/'state'; st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.ledger=self.out/'ledger.jsonl'; self.outputs=self.out/'outputs.jsonl'

    def call(self,arm,cond,rep,node,role,model,system,user,mt,inject=False):
        est=YUAN[model]
        self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(min(len(user),12000),mt)
        if self.real:
            fn=ds_call if model=='deepseek' else qwen_call
            r=fn(system,user,mt)
            text=r['text']
            if inject: text=truncate(text)
            tin,tout=r['in'],r['out']; stop=r['stop']; lat=r['lat']; mr=r['model']
        else:
            text='{"facts":[{"fid":"m","value":"mock","doc":"d1","quote":"q"}]}'
            if inject: text=truncate(text)
            tin=len(user); tout=64; stop='end_turn'; lat=0.01; mr='mock'
        self.gb.release_reservation(need,tin,tout); self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),arm=arm,condition=cond,rep=rep,node=node,role=role,
                 model=model,model_resp=mr,max_tokens=mt,tin=tin,tout=tout,
                 yuan=est,stop=stop,lat=lat,injected=inject)
        with open(self.ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    def run_exec(self,arm,cond,rep):
        exec_id=f"{arm}|{cond}|r{rep}"
        if self.store.completed(exec_id): return None
        self.store.begin(exec_id)
        docs=get_docs()
        docs_text='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        upstream={}; actions=[]; timeline=[]  # timeline = list of (ts, node, action)
        t_exec_start=time.time()
        dyn=arm=='Joint-Dynamic'

        # Extract nodes
        for doc_id,doc_text in docs.items():
            model=ALLOC['extract']
            userp=extract_prompt(doc_id,doc_text)
            text=self.call(arm,cond,rep,f'ext_{doc_id}','base',model,SYS_COMMON,userp,2000)
            ok,facts,_=parse_facts(text)
            upstream[f'ext_{doc_id}']=facts
            timeline.append((time.time()-t_exec_start,f'ext_{doc_id}','executed'))

        # Merge node
        all_facts=[]
        for nid in upstream:
            all_facts+=[f for f in upstream[nid] if isinstance(f,dict)]
        all_json=json.dumps(all_facts,ensure_ascii=False)[:3000]
        merge_user=merge_prompt(all_json)
        merge_model=ALLOC['reason']

        # FAULT INJECTION: persistent merge truncation for 'persistent' condition
        merge_inject = (cond=='persistent')

        text=self.call(arm,cond,rep,'merge','base',merge_model,
                      SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
        ok,facts,_=parse_facts(text)
        merge_anomaly = not ok or len(facts)==0
        merge_out=facts

        if merge_anomaly:
            timeline.append((time.time()-t_exec_start,'merge','anomaly_detected'))
            if arm=='Static':
                actions.append('merge_anomaly:NO_RECOVERY')
                timeline.append((time.time()-t_exec_start,'merge','static_no_recovery'))
            elif arm in ('Fixed-Recovery','Joint-Dynamic'):
                # R: same-model retry
                actions.append('merge_anomaly:R_retry')
                if self.inject_persistent and cond=='persistent':
                    text2=truncate(text)  # simulated persistent failure
                    ok2,f2,_=parse_facts(text2)
                else:
                    text2=self.call(arm,cond,rep,'merge','reroll',merge_model,
                                  SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
                    ok2,f2,_=parse_facts(text2)
                if f2 and len(f2)>0:
                    merge_out=f2
                    actions.append('R:recovered')
                    timeline.append((time.time()-t_exec_start,'merge','R_recovered'))
                else:
                    actions.append('R:failed')
                    timeline.append((time.time()-t_exec_start,'merge','R_failed'))
                    if dyn:
                        # π: switch model
                        alt='deepseek' if merge_model=='qwen' else 'qwen'
                        actions.append(f'pi_model_switch:{alt}')
                        text3=self.call(arm,cond,rep,'merge','reroll2',alt,
                                      SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=False)
                        ok3,f3,_=parse_facts(text3)
                        if f3 and len(f3)>0:
                            merge_out=f3
                            actions.append('pi:recovered')
                            timeline.append((time.time()-t_exec_start,'merge','pi_recovered'))
                        else:
                            actions.append('pi:failed')
                            # Z2: split merge per upstream branch
                            bfacts=[]
                            for un in [k for k in upstream if k.startswith('ext_')]:
                                if not upstream[un]: continue
                                sub={un:upstream[un]}
                                sub_json=json.dumps(sub,ensure_ascii=False)[:1500]
                                st_p=f"合并以下单一来源事实：\n\n{sub_json}\n\n按系统格式输出 JSON。"
                                bt=self.call(arm,cond,rep,f'split_{un}','split','deepseek',
                                           SYS_COMMON,st_p,2000,inject=False)
                                bok,bf,_=parse_facts(bt)
                                if bok and bf: bfacts+= [x for x in bf if isinstance(x,dict)]
                            if bfacts:
                                merge_out=bfacts
                                actions.append(f'Z2:split_recovered(n={len(bfacts)})')
                                timeline.append((time.time()-t_exec_start,'merge','Z2_recovered'))
                            else:
                                actions.append('Z2:failed')
        else:
            timeline.append((time.time()-t_exec_start,'merge','executed'))

        upstream['merge']=merge_out

        # Verify
        v_model=ALLOC['verification']
        merge_json=json.dumps(merge_out,ensure_ascii=False)[:2000]
        v_text=self.call(arm,cond,rep,'verify','base',v_model,
                       SYS_COMMON+D2_CONTRACT,verify_prompt(merge_json,docs_text),4000)
        ok_v,vfacts,_=parse_facts(v_text)
        upstream['verify']=vfacts

        # Report
        r_model=ALLOC['report']
        vstatus={}
        for vf in vfacts:
            if isinstance(vf,dict): vstatus[str(vf.get('fid',''))]=vf.get('status','unverified')
        combined=[]
        for mf in merge_out:
            if isinstance(mf,dict):
                combined.append({**mf,'verify_status':vstatus.get(str(mf.get('fid','')),'unverified')})
        r_text=self.call(arm,cond,rep,'report','base',r_model,
                       SYS_COMMON+D2_CONTRACT,
                       report_prompt(json.dumps(combined,ensure_ascii=False)[:3000],
                                    json.dumps(vstatus,ensure_ascii=False)[:500]),4000)
        ok_r,rfacts,_=parse_facts(r_text)

        exec_span=time.time()-t_exec_start
        record=dict(exec_id=exec_id,arm=arm,condition=cond,rep=rep,actions=actions,
                    timeline=[(round(t,2),n,a) for t,n,a in timeline],
                    n_merge_facts=len(merge_out),n_report_facts=len(rfacts),
                    exec_span_s=round(exec_span,1),
                    budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_dyn_jf_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_dyn_jf_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip():
                if k=='DEEPSEEK_API_KEY':
                    os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('DEEPSEEK_API_KEY=')][0]
                else:
                    os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('QWEN_API_KEY=')][0]
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else: print('MOCK MODE'); return
    r=Runner(cfg,a.out,a.real)
    done=skipped=0; stop=False
    for cond in ('natural','persistent'):
        for rep in range(1,REPS+1):
            for arm in ('Static','Fixed-Recovery','Joint-Dynamic'):
                eid=f"{arm}|{cond}|r{rep}"
                if r.store.completed(eid): skipped+=1; continue
                if r.gb.left()['calls_left']<10:
                    print(f'STOP {eid}'); stop=True; break
                r.run_exec(arm,cond,rep); done+=1
                print(f'  {eid} done left={r.gb.left()["calls_left"]}')
            if stop: break
        if stop: break
    print(f'DONE: {done} skip={skipped} stop={stop} budget={r.gb.left()}')

if __name__=='__main__':
    main()
