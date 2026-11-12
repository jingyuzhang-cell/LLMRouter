#!/usr/bin/env python3
"""V4-II-B CONFIRMATORY: Static / NoLearning / Learning on 20 tasks, 171 gold slots.

Frozen design per V4_II_B_FINAL_PREREG.md:
- 3 arms, same task order (frozen seed), independent posteriors per arm
- Extract-layer fault injection (transient/persistent 50/50, gold-bearing branch)
- Primary endpoint: per-task recovery call count (Learning vs NoLearning paired sign test)
- Quality NI gate: Q_terminal paired diff >= -0.05
- UB-1 two-layer delivery contract
- NoLearning = posterior frozen at Beta(1,1); Learning = online update from R outcomes
"""
import os, sys, json, time, re, argparse, hashlib, random
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from ub1_delivery import build_delivery, score_delivery, priority
import qcl_v3_runner as UB
from da_js_v3 import State, Node, BetaPosterior, decide, update_after_action

MT = 8000
random.seed(42)  # frozen task order + fault type assignment

# Load all 5 frozen gold batches → unified 20-task panel
BATCHES = ['GOLD_V4B_BATCH1_FROZEN.json','GOLD_V4B_BATCH2_FROZEN.json',
           'GOLD_V4B_BATCH3_FROZEN.json','GOLD_V4B_BATCH4_FROZEN.json',
           'GOLD_V4B_BATCH5_FROZEN.json']
R = 'independent_case_search/raw/'
PANEL = {}  # task_code -> {docs, gold, doc_files}
for bf in BATCHES:
    f = json.load(open(bf))
    for task in f['tasks']:
        slots = [r for r in f['tasks'][task] if 'SUPERSEDED' not in r.get('verdict_final','')]
        gold = [dict(span=r['span'], value=r.get('desc',''),
                     secondary=r.get('secondary_span')) for r in slots]
        docs = {d: meta['file'] for d, meta in f['source_docs'][task].items()}
        PANEL[task] = dict(docs=docs, gold=gold, n_slots=len(gold))

TASK_ORDER = sorted(PANEL.keys())  # alphabetical for determinism
random.shuffle(TASK_ORDER)  # frozen by seed=42
FAULT_TYPES = {t: ('transient' if random.random()<0.5 else 'persistent') for t in TASK_ORDER}
INJECT_BRANCH = {}  # task -> doc_id with gold-bearing content (first doc with gold hits)

def norm(s): return re.sub(r'[\s,，、；;：:]+','',str(s))

def slot_hits(facts_or_text, task):
    blob = (norm(facts_or_text) if isinstance(facts_or_text,str) else
            norm(' '.join(str(x.get('value',''))+str(x.get('quote',''))
                         for x in facts_or_text if isinstance(x,dict))))
    n=0
    for g in PANEL[task]['gold']:
        gs=norm(g['span']); gv=norm(g['value'])
        if (gs and gs in blob) or (len(gv)>=6 and gv in blob): n+=1
    return n/len(PANEL[task]['gold'])

def extract_prompt(di,dt):
    return f"从该文档中提取各类事实（日期/金额/主体/违法/处罚/风险），每条含fid、value、doc、quote。\n\n文档 [{di}]:\n{dt}\n\n按系统格式输出 JSON。"

NARR=("基于以下已核验事实撰写终端调查报告。事实库由系统逐条携带，你只输出：narrative（综合叙述，"
      "引用事实用 fid），以及 key_facts 数组（最关键 fid）。不得新增事实或改写金额/日期/主体。\n\n"
      "事实库：\n{combined}\n\n输出 JSON：{{\"narrative\":\"...\",\"key_facts\":[\"fid\",...]}}")

def parse_narr(t):
    try:
        j=json.loads(t[t.find('{'):t.rfind('}')+1]); n=str(j.get('narrative',''))
        return (n,j.get('key_facts',[])) if n else ('',[])
    except Exception: return '',[]

class VB:
    def __init__(self,cfg,out,real):
        self.real=real; self.out=Path(out)
        st=self.out/'state'; st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.posteriors={'NoLearning':{},'Learning':{}}
        # Resume: restore Learning posterior from completed tasks 1-2 (600781, 002490)
        # Both had persistent faults where R failed -> Beta(alpha=1, beta=3)
        from da_js_v3 import BetaPosterior as _BP
        for _nid in ('D1','D2','D3','D4'):
            self.posteriors['Learning'][(_nid,'deepseek')]=_BP(1,3)
        self.ledger=self.out/'ledger.jsonl'; self.outputs=self.out/'outputs.jsonl'
        self.decisions=self.out/'decisions.jsonl'; self.results=self.out/'results.jsonl'

    def call(self,unit,arm,node,model,user,inject=False):
        est=YUAN[model]; self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(len(user)+100,MT)
        if self.real:
            for a,d in enumerate((0,20,45),1):
                if d: time.sleep(d)
                try: r=_call(model,SYS_COMMON,user,MT); break
                except Exception as e:
                    print(f'  [retry {a}] {type(e).__name__}',flush=True)
                    if a==3: raise
            text,tin,tout,lat=r['text'],r['in'],r['out'],r['lat']
            if inject: text=truncate(text)
        else:
            text='{"facts":[{"fid":"f1","value":"v","doc":"D1","quote":"q"}]}'
            if inject: text=truncate(text)
            tin,tout,lat=len(user),64,0.01
        self.gb.release_reservation(need,tin,tout); self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),unit=unit,arm=arm,node=node,model=model,
                 tin=tin,tout=tout,yuan=est,lat=lat,injected=inject,user_chars=len(user))
        with open(self.ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text

    def extracts(self,task,docs,arm='Shared'):
        facts=[]
        for di,fn in sorted(docs.items()):
            dt=open(R+fn,encoding='utf-8').read()
            t=self.call(task,arm,f'ext_{di}','deepseek',extract_prompt(di,dt))
            _,f2,_=parse_facts(t)
            facts+=[{'fid':f"{di}::{x.get('fid','')}",'value':x.get('value',''),
                     'doc':x.get('doc',di),'quote':x.get('quote','')} for x in f2 if isinstance(x,dict)]
        return facts

    def verify(self,unit,arm,store):
        slim=json.dumps([{'fid':f['fid'],'value':f.get('value','')} for f in store],ensure_ascii=False)
        user=("逐条核验以下事实与已知文档一致性。只输出 fid 和 status，不要复述 value。\n\n"
              f"事实：\n{slim}\n\n输出 JSON：{{\"facts\":[{{\"fid\":\"...\",\"status\":\"verified|unverified|conflict\"}}]}}")
        t=self.call(unit,arm,'verify','qwen',user)
        _,vf,_=parse_facts(t)
        return {str(x.get('fid','')):x.get('status','unverified') for x in vf if isinstance(x,dict)}

    def narr_report(self,unit,arm,store,vs,model='qwen',inject=False):
        combined=[{**f,'verify_status':vs.get(str(f['fid']),'unverified')} for f in store]
        user=NARR.format(combined=json.dumps(combined,ensure_ascii=False))
        for f in combined:
            assert json.dumps(f,ensure_ascii=False)[:120] in user, f'TRUNCATED {f["fid"]}'
        try:
            t=self.call(unit,arm,'report',model,user,inject=inject)
            return parse_narr(t)
        except Exception as e:
            print(f'  REPORT FALLBACK: {type(e).__name__} on {unit}/{arm}; using empty narrative',flush=True)
            return '',[]

    def score(self,task,store,vs,narr,kf):
        art,qb,qa=build_delivery(store,vs,narr,kf)
        sc=score_delivery(qb,qa,[dict(span=g['span'],value=g['value']) for g in PANEL[task]['gold']])
        return sc

    def run_task(self,idx,task):
        try:
            self._run_task_inner(idx,task)
        except Exception as e:
            print(f'  TASK ERROR: {task} {type(e).__name__}: {e}',flush=True)
            # record error but don't block subsequent tasks
            eid=f'ERROR|{task}'
            try:
                self.store.begin(eid)
                self.store.commit(dict(exec_id=eid,unit=task,error=str(e)[:200],
                    budget_left=self.gb.left()))
            except Exception: pass

    def _run_task_inner(self,idx,task):
        docs=PANEL[task]['docs']
        fault=FAULT_TYPES[task]
        print(f'\n===== [{idx+1}/20] {task} (fault={fault}) =====',flush=True)

        # 1) Shared base execution (extract → store → verify → report)
        eid=f'BASE|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            facts=self.extracts(task,docs)
            store=UB.det_merge(facts)
            vs=self.verify(task,'Shared',store)
            narr,kf=self.narr_report(task,'Shared',store,vs)
            sc=self.score(task,store,vs,narr,kf)
            qtransport=slot_hits(store,task)
            # find gold-bearing branch for injection
            branch_hits={}
            for di,fn in sorted(docs.items()):
                bf=[f for f in facts if f['fid'].startswith(di+'::')]
                if bf: branch_hits[di]=slot_hits(bf,task)
            best_branch=max(branch_hits,key=branch_hits.get) if branch_hits else sorted(docs)[0]
            INJECT_BRANCH[task]=best_branch
            self.store.commit(dict(exec_id=eid,unit=task,n_store=len(store),
                Q_transport=round(qtransport,3),**sc,inject_branch=best_branch,
                branch_hits=branch_hits,budget_left=self.gb.left()))
            print(f'  BASE: store={len(store)} Qt={sc["Q_terminal"]} inject_branch={best_branch}',flush=True)

        base_rec=json.loads((self.out/f'BASE__{task}.json').read_text())
        inject_di=base_rec.get('inject_branch',sorted(docs)[0])

        # 2) Fault recovery (NoLearning + Learning arms)
        for arm in ('NoLearning','Learning'):
            eid=f'FAULT|{task}|{arm}'
            if self.store.completed(eid): continue
            self.store.begin(eid)
            acts=[]; recovery_calls=0
            # build faulted state: inject branch output truncated
            base_facts=self._cached_ext(task)
            branch_facts=[f for f in base_facts if f['fid'].startswith(inject_di+'::')]
            other=[f for f in base_facts if not f['fid'].startswith(inject_di+'::')]

            # decision
            st=State(task=task,G={inject_di:Node(inject_di,'extract','deepseek')},
                     H=self.posteriors[arm],faulted=(inject_di,'unknown'),
                     B=dict(calls=self.gb.left()['calls_left'],
                            tokens=self.gb.left()['tokens_left'] or 10**9,
                            yuan=self.gb.left()['yuan_left']),
                     D=2400.0,task_profile=dict(zx_comparable=False))
            d1=decide(st)
            with open(self.decisions,'a') as f:
                f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|fault',arm=arm,**d1),ensure_ascii=False)+'\n')
            acts.append(f'decide1:{d1["selected"]}')
            sel=d1['selected']; new_branch=[]

            if sel=='R':
                dt=open(R+docs[inject_di],encoding='utf-8').read()
                t=self.call(f'{task}|FAULT',arm,f'ext_{inject_di}','deepseek',
                           extract_prompt(inject_di,dt),inject=(fault=='persistent'))
                recovery_calls+=1
                _,f2,_=parse_facts(t)
                new_branch=[{'fid':f"{inject_di}::{x.get('fid','')}",'value':x.get('value',''),
                            'doc':x.get('doc',inject_di),'quote':x.get('quote','')}
                           for x in f2 if isinstance(x,dict)]
                ok=bool(new_branch)
                acts.append(f'R:{"ok" if ok else "fail"}')
                if not ok:
                    if arm=='Learning':
                        st=update_after_action(st,'R',dict(restored=False))
                        d2=decide(st)
                        acts.append(f'decide2:{d2["selected"]}')
                        escalate=(d2['selected']=='pi')
                    else:
                        acts.append('ladder:pi')
                        escalate=True
                    if escalate:
                        t=self.call(f'{task}|FAULT',arm,f'ext_{inject_di}','qwen',
                                   extract_prompt(inject_di,open(R+docs[inject_di]).read()))
                        recovery_calls+=1
                        _,f3,_=parse_facts(t)
                        new_branch=[{'fid':f"{inject_di}::pi::{x.get('fid','')}",'value':x.get('value',''),
                                    'doc':x.get('doc',inject_di),'quote':x.get('quote','')}
                                   for x in f3 if isinstance(x,dict)]
                        acts.append('pi:ok' if new_branch else 'pi:fail')
            elif sel=='pi':
                t=self.call(f'{task}|FAULT',arm,f'ext_{inject_di}','qwen',
                           extract_prompt(inject_di,open(R+docs[inject_di]).read()))
                recovery_calls+=1
                _,f3,_=parse_facts(t)
                new_branch=[{'fid':f"{inject_di}::pi::{x.get('fid','')}",'value':x.get('value',''),
                            'doc':x.get('doc',inject_di),'quote':x.get('quote','')}
                           for x in f3 if isinstance(x,dict)]
                acts.append('pi:ok' if new_branch else 'pi:fail')

            # rebuild store with recovered branch + downstream
            store2=UB.det_merge(other+new_branch)
            vs2=self.verify(f'{task}|FAULT',arm,store2)
            narr2,kf2=self.narr_report(f'{task}|FAULT',arm,store2,vs2)
            sc2=self.score(task,store2,vs2,narr2,kf2)

            # record
            self.store.commit(dict(exec_id=eid,unit=f'{task}|FAULT',arm=arm,
                actions=acts,recovery_calls=recovery_calls,fault_type=fault,
                **sc2,budget_left=self.gb.left()))
            with open(self.results,'a') as f:
                f.write(json.dumps(dict(task=task,arm=arm,fault=fault,
                    calls=recovery_calls,Q_terminal=sc2['Q_terminal'],
                    actions=acts),ensure_ascii=False)+'\n')
            print(f'  {arm}: {acts} calls={recovery_calls} Qt={sc2["Q_terminal"]}',flush=True)

        # 3) Static arm: accept degraded (zero calls, computed from base minus injected branch)
        eid=f'FAULT|{task}|Static'
        if not self.store.completed(eid):
            base_facts=self._cached_ext(task)
            degraded=[f for f in base_facts if not f['fid'].startswith(inject_di+'::')]
            store_s=UB.det_merge(degraded)
            sc_s=self.score(task,store_s,{},'',[])
            self.store.commit(dict(exec_id=eid,unit=f'{task}|FAULT',arm='Static',
                actions=['accept-degraded'],recovery_calls=0,fault_type=fault,
                **sc_s,budget_left=self.gb.left(),zero_calls=True))
            print(f'  Static: accept-degraded Qt={sc_s["Q_terminal"]}',flush=True)

    def _cached_ext(self,task):
        outs=[json.loads(l) for l in open(self.outputs)]
        facts=[]
        for o in outs:
            if o.get('unit')==task and o.get('arm')=='Shared' and o.get('node','').startswith('ext_') \
               and '_s' not in o['node'] and not o.get('injected'):
                _,f2,_=parse_facts(o['raw_output'])
                di=o['node'].replace('ext_','')
                facts+=[{'fid':f"{di}::{x.get('fid','')}",'value':x.get('value',''),
                        'doc':x.get('doc',''),'quote':x.get('quote','')} for x in f2 if isinstance(x,dict)]
        return facts

    def run(self):
        for i,task in enumerate(TASK_ORDER):
            self.run_task(i,task)
        print(f'\nV4-II-B DONE budget={self.gb.left()}',flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'v4b_config.json'))
    ap.add_argument('--out',default=str(HERE/'v4b_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip():
                os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith(k+'=')][0]
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'],flush=True)
    else: print('MOCK MODE')
    VB(cfg,a.out,a.real).run()

if __name__=='__main__':
    main()
