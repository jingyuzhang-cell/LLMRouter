#!/usr/bin/env python3
"""DA-JS v1 Final: 3 strategies × 2 anomaly conditions × 3 reps."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget,RunStore
from da_js_v1 import decide

YUAN={'deepseek':0.0129,'qwen':0.02}
ALLOC={'extract':'deepseek','reason':'qwen','verification':'qwen','report':'qwen'}
REPS=3
EV=Path('/root/cap_eval_bench_v1/evidence/texts')
DOCS=[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')]

def truncate(t,n=20): return t[:n]
def get_docs(): return {d:(EV/f).read_text('utf-8') for d,f in DOCS}
def extract_prompt(di,dt):
    return f"从该文档中提取各类事实（日期/金额/主体/违法/处罚/风险），每条含fid、value、doc、quote。\n\n文档 [{di}]:\n{dt}\n\n按系统格式输出 JSON。"
def merge_prompt(af):
    return f"合并以下事实，保留fid/value/doc/quote。\n\n{af}\n\n按系统格式输出 JSON。"
def verify_prompt(up,dt):
    return f"核验以下事实，标注verified/unverified/conflict。不删除。\n\n{up}\n\n文档：{dt[:2000]}\n\n按系统格式输出 JSON。"
def report_prompt(mf,vs):
    return f"基于以下事实生成终端报告。verified明确陈述，unverified披露。\n\n事实：\n{mf}\n\n核验：{vs}\n\n按系统格式输出 JSON。"

def _call(model,sys_,user,mt):
    import urllib.request
    if model=='deepseek':
        key=os.environ.get('DEEPSEEK_API_KEY','')
        body={'model':'deepseek-flash','max_tokens':mt,'messages':[{'role':'system','content':sys_},{'role':'user','content':user}],'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
        url='https://api.deepseek.com/chat/completions'
    else:
        key=os.environ.get('QWEN_API_KEY','')
        body={'model':'qwen-plus','max_tokens':mt,'messages':[{'role':'system','content':sys_},{'role':'user','content':user}],'response_format':{'type':'json_object'}}
        url='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
    req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode(),method='POST')
    req.add_header('Content-Type','application/json');req.add_header('Authorization','Bearer '+key)
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r: d=json.loads(r.read().decode())
    c=d['choices'][0]['message'].get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    u=d['usage']
    return {'text':c,'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),'stop':d['choices'][0].get('finish_reason',''),'lat':round(time.monotonic()-t0,2)}

class FR:
    def __init__(self,cfg,out,real):
        self.real=real;self.out=Path(out)
        st=self.out/'state';st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.deadline=cfg.get('deadline_s',240)
        self.ledger=self.out/'ledger.jsonl';self.outputs=self.out/'outputs.jsonl'
    def call(self,strat,cond,rep,node,role,model,sys_,user,mt,inject=False):
        est=YUAN[model];self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(min(len(user),12000),mt)
        if self.real:
            r=_call(model,sys_,user,mt);text=r['text']
            if inject:text=truncate(text)
            tin,tout,stop,lat=r['in'],r['out'],r['stop'],r['lat']
        else:
            text='{"facts":[{"fid":"m","value":"v","doc":"d1","quote":"q"}]}'
            if inject:text=truncate(text)
            tin,tout,stop,lat=len(user),64,'end_turn',0.01
        self.gb.release_reservation(need,tin,tout);self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),strategy=strat,condition=cond,rep=rep,node=node,role=role,
                 model=model,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat,injected=inject)
        with open(self.ledger,'a') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f:f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    def run_exec(self,strat,cond,rep):
        exec_id=f"{strat}|{cond}|r{rep}"
        if self.store.completed(exec_id):return None
        self.store.begin(exec_id)
        docs=get_docs();docs_text='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        upstream={};actions=[];t0=time.time();merge_inject=(cond!='natural')
        for di,dt in docs.items():
            text=self.call(strat,cond,rep,f'ext_{di}','base',ALLOC['extract'],SYS_COMMON,extract_prompt(di,dt),2000)
            ok,f,_=parse_facts(text);upstream[f'ext_{di}']=f
        af=[]
        for nid in upstream:af+=[f for f in upstream[nid] if isinstance(f,dict)]
        mu=merge_prompt(json.dumps(af,ensure_ascii=False)[:3000]);mm=ALLOC['reason']
        text=self.call(strat,cond,rep,'merge','base',mm,SYS_COMMON+D2_CONTRACT,mu,4000,inject=merge_inject)
        ok,facts,_=parse_facts(text)
        anomaly=(not ok) or len(facts)==0;merge_out=facts
        if anomaly:
            if strat=='Static':
                actions.append('anomaly:no_recovery')
            elif strat=='Proposed':
                # Fixed ladder: R → π
                actions.append('anomaly:R')
                t2=self.call(strat,cond,rep,'merge','reroll',mm,SYS_COMMON+D2_CONTRACT,mu,4000,inject=merge_inject)
                ok2,f2,_=parse_facts(t2)
                if f2 and len(f2)>0:merge_out=f2;actions.append('R:ok')
                else:
                    actions.append('R:fail');actions.append('pi')
                    alt='deepseek' if mm=='qwen' else 'qwen'
                    t3=self.call(strat,cond,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,mu,4000)
                    ok3,f3,_=parse_facts(t3)
                    if f3:merge_out=f3;actions.append('pi:ok')
                    else:actions.append('pi:fail')
            elif strat=='DA-JS-v1':
                # Candidate search using estimation table
                remaining_s=self.deadline-(time.time()-t0)
                remaining_calls=min(self.gb.left()['calls_left'],30)
                # Detect anomaly type: assume transient first (optimistic probe)
                a_type='transient'
                decision=decide(a_type,remaining_s,remaining_calls,mm,'merge')
                actions.append(f'decide:{decision["selected"]}(rem={remaining_s:.0f}s,{remaining_calls}c)')
                sel=decision['selected']
                if sel=='LOCAL_R':
                    t2=self.call(strat,cond,rep,'merge','reroll',mm,SYS_COMMON+D2_CONTRACT,mu,4000,inject=merge_inject)
                    ok2,f2,_=parse_facts(t2)
                    if f2 and len(f2)>0:merge_out=f2;actions.append('R:ok')
                    else:
                        actions.append('R:fail')
                        # Escalate: re-decide as persistent
                        d2=decide('persistent',self.deadline-(time.time()-t0),remaining_calls-1,mm,'merge')
                        actions.append(f'escalate:{d2["selected"]}')
                        if d2['selected']=='LOCAL_pi':
                            alt='deepseek' if mm=='qwen' else 'qwen'
                            t3=self.call(strat,cond,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,mu,4000)
                            ok3,f3,_=parse_facts(t3)
                            if f3:merge_out=f3;actions.append('pi:ok')
                            else:actions.append('pi:fail')
                        elif d2['selected']=='Z2_split_R':
                            bf=[]
                            for un in [k for k in upstream if k.startswith('ext_')]:
                                if not upstream[un]:continue
                                sp=f"合并以下事实：\n\n{json.dumps(upstream[un],ensure_ascii=False)[:1500]}\n\n按系统格式输出 JSON。"
                                bt=self.call(strat,cond,rep,f'split_{un}','split','deepseek',SYS_COMMON,sp,2000)
                                bok,bf2,_=parse_facts(bt)
                                if bok and bf2:bf+=[x for x in bf2 if isinstance(x,dict)]
                            if bf:merge_out=bf;actions.append(f'Z2:ok(n={len(bf)})')
                            else:actions.append('Z2:fail')
                elif sel=='LOCAL_pi':
                    alt='deepseek' if mm=='qwen' else 'qwen'
                    t3=self.call(strat,cond,rep,'merge','reroll2',alt,SYS_COMMON+D2_CONTRACT,mu,4000)
                    ok3,f3,_=parse_facts(t3)
                    if f3:merge_out=f3;actions.append('pi:ok')
                    else:actions.append('pi:fail')
                elif sel=='Z2_split_R':
                    bf=[]
                    for un in [k for k in upstream if k.startswith('ext_')]:
                        if not upstream[un]:continue
                        sp=f"合并以下事实：\n\n{json.dumps(upstream[un],ensure_ascii=False)[:1500]}\n\n按系统格式输出 JSON。"
                        bt=self.call(strat,cond,rep,f'split_{un}','split','deepseek',SYS_COMMON,sp,2000)
                        bok,bf2,_=parse_facts(bt)
                        if bok and bf2:bf+=[x for x in bf2 if isinstance(x,dict)]
                    if bf:merge_out=bf;actions.append(f'Z2:ok(n={len(bf)})')
                    else:actions.append('Z2:fail')
                else:
                    actions.append(f'decide:NONE(no feasible recovery, rem={remaining_s:.0f}s,{remaining_calls}c)')
        else:
            actions.append('merge:ok')
        upstream['merge']=merge_out
        vt=self.call(strat,cond,rep,'verify','base',ALLOC['verification'],SYS_COMMON+D2_CONTRACT,
                    verify_prompt(json.dumps(merge_out,ensure_ascii=False)[:2000],docs_text),4000)
        ok_v,vf,_=parse_facts(vt)
        vs={}
        for v in vf:
            if isinstance(v,dict):vs[str(v.get('fid',''))]=v.get('status','unverified')
        combined=[{**mf,'verify_status':vs.get(str(mf.get('fid','')),'unverified')} for mf in merge_out if isinstance(mf,dict)]
        rt=self.call(strat,cond,rep,'report','base',ALLOC['report'],SYS_COMMON+D2_CONTRACT,
                    report_prompt(json.dumps(combined,ensure_ascii=False)[:3000],json.dumps(vs,ensure_ascii=False)[:500]),4000)
        ok_r,rf,_=parse_facts(rt)
        span=time.time()-t0
        record=dict(exec_id=exec_id,strategy=strat,condition=cond,rep=rep,actions=actions,
                    n_merge=len(merge_out),n_report=len(rf),exec_span_s=round(span,1),
                    deadline_s=self.deadline,deadline_met=bool(span<=self.deadline),
                    budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_dajf_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_dajf_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1':raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip():
                os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith(k+'=')][0]
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else:print('MOCK MODE');return
    r=FR(cfg,a.out,a.real)
    done=skipped=0;stop=False
    for cond in ('natural','persistent'):
        for rep in range(1,REPS+1):
            for strat in ('Static','Proposed','DA-JS-v1'):
                eid=f"{strat}|{cond}|r{rep}"
                if r.store.completed(eid):skipped+=1;continue
                if r.gb.left()['calls_left']<10:print('STOP');stop=True;break
                r.run_exec(strat,cond,rep);done+=1
                print(f'  {eid} done left={r.gb.left()["calls_left"]}')
            if stop:break
        if stop:break
    print(f'DONE: {done} skip={skipped} budget={r.gb.left()}')

if __name__=='__main__':main()
