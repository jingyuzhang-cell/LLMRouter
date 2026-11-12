#!/usr/bin/env python3
"""Deadline-Aware Joint Scheduling: 3 strategies × natural+persistent × deadline tight/loose."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,score_node
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget,RunStore

YUAN={'deepseek':0.0129,'qwen':0.02}
ALLOC={'extract':'deepseek','reason':'qwen','verification':'qwen','report':'qwen'}
REPS=3
EV=Path('/root/cap_eval_bench_v1/evidence/texts')
DOCS=[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')]

def truncate(t,n=20): return t[:n]
def get_docs(): return {d:(EV/f).read_text('utf-8') for d,f in DOCS}

def extract_prompt(doc_id,doc_text):
    return f"从该文档中提取以下各类事实：\n1.日期类 2.金额类 3.主体类 4.违法类 5.处罚类 6.风险类\n每条事实必须包含fid、value、doc、quote。\n\n文档 [{doc_id}]:\n{doc_text}\n\n按系统格式输出 JSON。"
def merge_prompt(all_facts):
    return f"合并以下全部事实。保留原始fid/value/doc/quote。\n\n{all_facts}\n\n按系统格式输出 JSON。"
def verify_prompt(up,dt):
    return f"核验以下事实，标注verified/unverified/conflict。不要删除。\n\n{up}\n\n文档：{dt[:2000]}\n\n按系统格式输出 JSON。"
def report_prompt(mf,vs):
    return f"基于以下事实生成终端报告。verified明确陈述，unverified披露。\n\n事实：\n{mf}\n\n核验：{vs}\n\n按系统格式输出 JSON。"

def ds_call(sys_,user,mt):
    import urllib.request
    key=os.environ.get('DEEPSEEK_API_KEY','')
    if not key:
        key=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('DEEPSEEK_API_KEY=')][0]
    body={'model':'deepseek-flash','max_tokens':mt,'messages':[{'role':'system','content':sys_},{'role':'user','content':user}],'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
    req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(body,ensure_ascii=False).encode(),method='POST')
    req.add_header('Content-Type','application/json');req.add_header('Authorization','Bearer '+key)
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r: d=json.loads(r.read().decode())
    c=d['choices'][0]['message'].get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    u=d['usage'];return {'text':c,'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),'stop':d['choices'][0].get('finish_reason',''),'lat':round(time.monotonic()-t0,2)}
def qwen_call(sys_,user,mt):
    import urllib.request
    key=os.environ.get('QWEN_API_KEY','')
    if not key:
        key=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('QWEN_API_KEY=')][0]
    body={'model':'qwen-plus','max_tokens':mt,'messages':[{'role':'system','content':sys_},{'role':'user','content':user}],'response_format':{'type':'json_object'}}
    req=urllib.request.Request('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',data=json.dumps(body,ensure_ascii=False).encode(),method='POST')
    req.add_header('Content-Type','application/json');req.add_header('Authorization','Bearer '+key)
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r: d=json.loads(r.read().decode())
    c=d['choices'][0]['message'].get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    u=d['usage'];return {'text':c,'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),'stop':d['choices'][0].get('finish_reason',''),'lat':round(time.monotonic()-t0,2)}

class DRunner:
    def __init__(self,cfg,out,real):
        self.real=real; self.out=Path(out)
        st=self.out/'state'; st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.ledger=self.out/'ledger.jsonl'; self.outputs=self.out/'outputs.jsonl'
    def call(self,strat,cond,dl,rep,node,role,model,sys_,user,mt,inject=False):
        est=YUAN[model]; self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(min(len(user),12000),mt)
        if self.real:
            fn=ds_call if model=='deepseek' else qwen_call
            r=fn(sys_,user,mt); text=r['text']
            if inject: text=truncate(text)
            tin,tout,stop,lat=r['in'],r['out'],r['stop'],r['lat']
        else:
            text='{"facts":[{"fid":"m","value":"v","doc":"d1","quote":"q"}]}'
            if inject: text=truncate(text)
            tin,tout,stop,lat=len(user),64,'end_turn',0.01
        self.gb.release_reservation(need,tin,tout); self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),strategy=strat,condition=cond,deadline=dl,rep=rep,
                 node=node,role=role,model=model,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat,injected=inject)
        with open(self.ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    def run_exec(self,strat,cond,dl,rep):
        exec_id=f"{strat}|{cond}|{dl}|r{rep}"
        if self.store.completed(exec_id): return None
        self.store.begin(exec_id)
        docs=get_docs(); docs_text='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        upstream={}; actions=[]; t0=time.time()
        # Deadline in seconds (virtual for accounting)
        DL={'loose':120,'tight':30}[dl]
        elapsed=0; estimated_remaining={'qwen':30,'ds':10}  # rough per-call latency

        for doc_id,doc_text in docs.items():
            text=self.call(strat,cond,dl,rep,f'ext_{doc_id}','base',ALLOC['extract'],
                         SYS_COMMON,extract_prompt(doc_id,doc_text),2000)
            ok,facts,_=parse_facts(text); upstream[f'ext_{doc_id}']=facts
            elapsed+=1

        all_facts=[]
        for nid in upstream: all_facts+=[f for f in upstream[nid] if isinstance(f,dict)]
        merge_user=merge_prompt(json.dumps(all_facts,ensure_ascii=False)[:3000])
        mm=ALLOC['reason']
        merge_inject=(cond=='persistent')
        text=self.call(strat,cond,dl,rep,'merge','base',mm,SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
        ok,facts,_=parse_facts(text)
        anomaly=not ok or len(facts)==0
        merge_out=facts

        if anomaly:
            if strat=='Static':
                actions.append('anomaly:no_recovery')
            elif strat=='Proposed':
                # Full R→π ladder
                actions.append('anomaly:R_retry')
                text2=self.call(strat,cond,dl,rep,'merge','reroll',mm,SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
                ok2,f2,_=parse_facts(text2)
                if f2 and len(f2)>0: merge_out=f2; actions.append('R:recovered')
                else:
                    actions.append('R:failed'); actions.append('pi_switch')
                    alt='deepseek' if mm=='qwen' else 'qwen'
                    text3=self.call(strat,cond,dl,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,merge_user,4000)
                    ok3,f3,_=parse_facts(text3)
                    if f3: merge_out=f3; actions.append('pi:recovered')
                    else: actions.append('pi:failed')
            elif strat=='DA-Proposed':
                # Deadline-aware: check remaining time budget
                # Each call estimated ~30s for Qwen, ~10s for DS
                remaining = DL - elapsed * estimated_remaining.get(mm, 30)
                if remaining < 20:
                    # Tight: skip expensive recovery, try cheap R only
                    actions.append(f'anomaly:R_only(tight,remaining~{remaining:.0f}s)')
                    text2=self.call(strat,cond,dl,rep,'merge','reroll',mm,SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
                    ok2,f2,_=parse_facts(text2)
                    if f2 and len(f2)>0: merge_out=f2; actions.append('R:recovered')
                    else: actions.append('R:failed(skip_pi_no_time)')
                else:
                    # Loose: full ladder
                    actions.append(f'anomaly:full_ladder(loose,remaining~{remaining:.0f}s)')
                    text2=self.call(strat,cond,dl,rep,'merge','reroll',mm,SYS_COMMON+D2_CONTRACT,merge_user,4000,inject=merge_inject)
                    ok2,f2,_=parse_facts(text2)
                    if f2 and len(f2)>0: merge_out=f2; actions.append('R:recovered')
                    else:
                        actions.append('R:failed'); actions.append('pi_switch')
                        alt='deepseek' if mm=='qwen' else 'qwen'
                        text3=self.call(strat,cond,dl,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,merge_user,4000)
                        ok3,f3,_=parse_facts(text3)
                        if f3: merge_out=f3; actions.append('pi:recovered')
                        else: actions.append('pi:failed')
        else:
            actions.append('merge:ok')

        upstream['merge']=merge_out
        # Verify
        v_text=self.call(strat,cond,dl,rep,'verify','base',ALLOC['verification'],
                        SYS_COMMON+D2_CONTRACT,verify_prompt(json.dumps(merge_out,ensure_ascii=False)[:2000],docs_text),4000)
        ok_v,vf,_=parse_facts(v_text)
        # Report
        vs={}
        for v in vf:
            if isinstance(v,dict): vs[str(v.get('fid',''))]=v.get('status','unverified')
        combined=[{**mf,'verify_status':vs.get(str(mf.get('fid','')),'unverified')} for mf in merge_out if isinstance(mf,dict)]
        r_text=self.call(strat,cond,dl,rep,'report','base',ALLOC['report'],
                        SYS_COMMON+D2_CONTRACT,
                        report_prompt(json.dumps(combined,ensure_ascii=False)[:3000],json.dumps(vs,ensure_ascii=False)[:500]),4000)
        ok_r,rf,_=parse_facts(r_text)
        span=time.time()-t0
        record=dict(exec_id=exec_id,strategy=strat,condition=cond,deadline=dl,rep=rep,
                    actions=actions,n_merge=len(merge_out),n_report=len(rf),
                    exec_span_s=round(span,1),budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_da_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_da_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip():
                env_key=k.replace('DEEPSEEK','DEEPSEEK').replace('QWEN','QWEN')
                os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith(k+'=')][0]
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else: print('MOCK MODE'); return
    r=DRunner(cfg,a.out,a.real)
    done=0;stop=False
    for cond in ('natural','persistent'):
        for dl in ('loose','tight'):
            for rep in range(1,REPS+1):
                for strat in ('Static','Proposed','DA-Proposed'):
                    eid=f"{strat}|{cond}|{dl}|r{rep}"
                    if r.store.completed(eid): continue
                    if r.gb.left()['calls_left']<10: print(f'STOP'); stop=True; break
                    r.run_exec(strat,cond,dl,rep); done+=1
                    print(f'  {eid} done left={r.gb.left()["calls_left"]}')
                if stop: break
            if stop: break
        if stop: break
    print(f'DONE: {done} budget={r.gb.left()}')

if __name__=='__main__': main()
