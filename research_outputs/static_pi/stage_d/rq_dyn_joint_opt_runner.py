#!/usr/bin/env python3
"""RQ-DYN-3ARM: StaticHetero vs FixedRecovery vs JointDynamic, paired on E03+E04."""
import os,sys,json,time,argparse,hashlib,re,collections
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from rq2_p2r_runner import SYS_COMMON,parse_facts,signals,score_node
from rq2_p2r_v3_runner import D2_CONTRACT,DELIVERY_KINDS,n_upstream_facts,MAXTOK_BASE,D1_PER_FACT,D1_CAP
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget,RunStore

YUAN={'deepseek':0.0129,'qwen':0.02}
REPS=5
# Static allocation from capability matrix
ALLOC={'extract':'deepseek','reason':'qwen','verification':'qwen','report':'qwen'}
MODELS=['deepseek','qwen']
EV={
 'E03_yuandao':Path('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence'),
 'E04_zhuoran':Path('/root/cap_eval_bench_v1/evidence/texts'),
}
EV_FILES={
 'E03_yuandao':[('D1','D1_E03-yuandao_2026-05-08.txt'),('D2','D2_E03-yuandao_2026-08-29.txt'),('D3','D3_E03-yuandao_2026-08-29.txt')],
 'E04_zhuoran':[('doc1','E04-zhuoran_20260910.txt'),('doc2','E04-zhuoran_20261009.txt'),('doc3','E04-zhuoran_20261013.txt')],
}
DAG={
 'E03_yuandao':[
  {'node_id':'ext_D1','kind':'extract','doc':'D1'},
  {'node_id':'ext_D2','kind':'extract','doc':'D2'},
  {'node_id':'ext_D3','kind':'extract','doc':'D3'},
  {'node_id':'merge','kind':'reason','upstream':['ext_D1','ext_D2','ext_D3']},
  {'node_id':'verify','kind':'verification','upstream':['merge']},
  {'node_id':'report','kind':'report','upstream':['merge','verify']},
 ],
 'E04_zhuoran':[
  {'node_id':'ext_doc1','kind':'extract','doc':'doc1'},
  {'node_id':'ext_doc2','kind':'extract','doc':'doc2'},
  {'node_id':'ext_doc3','kind':'extract','doc':'doc3'},
  {'node_id':'merge','kind':'reason','upstream':['ext_doc1','ext_doc2','ext_doc3']},
  {'node_id':'verify','kind':'verification','upstream':['merge']},
  {'node_id':'report','kind':'report','upstream':['merge','verify']},
 ],
}
def get_docs(ev):
    return {d:(EV[ev]/f).read_text('utf-8') for d,f in EV_FILES[ev]}
def node_prompt(ev,node,docs,upstream):
    kind=node['kind']
    if kind=='extract':
        dt=docs[node['doc']]
        return f"从该文档中提取以下各类事实，确保覆盖完整：\n1. 日期类：立案日、告知书日、决定书日、上市日等\n2. 金额类：虚增收入/利润金额、罚款金额、募集资金金额\n3. 主体类：公司名、责任人姓名及职务（如董事长、财务总监、董秘）、违法行为角色\n4. 违法类：违法性质（欺诈发行/信息披露违法）、违法方式、涉及年度\n5. 处罚类：罚款金额（按主体分列）、市场禁入、警告、免予处罚\n6. 风险类：退市风险警示、终止上市、停牌\n\n每条事实必须包含：fid、value（具体值）、doc（来源文档）、quote（原文引用）。\n不要遗漏任何处罚金额和责任人信息。\n\n文档 [{node['doc']}]:\n{dt}\n\n按系统格式输出 JSON。"
    elif kind=='reason':
        all_facts=[]
        for n in node['upstream']:
            for f in upstream.get(n,[]):
                if isinstance(f,dict): all_facts.append(f)
        up=json.dumps(all_facts,ensure_ascii=False)[:3500]
        return f"合并以下多份文档的全部事实。要求：\n1. 保留每条事实的原始fid、value、doc、quote\n2. 相同fid去重（保留最完整版本）\n3. 不同年份、不同主体、不同金额不得合并\n4. 冲突事实保留双方内容\n5. 可新增跨文档关联信息，但不删除原始事实\n\n上游事实集合：\n{up}\n\n按系统格式输出 JSON。"
    elif kind=='verification':
        up='\n'.join(f"{n}: {json.dumps(upstream.get(n,[]),ensure_ascii=False)[:600]}" for n in node['upstream'])
        docs_t='\n\n'.join(f'[{d}]\n{t[:800]}' for d,t in docs.items())
        return f"对以下每条事实进行核验，标注状态。不要删除任何事实，为每条添加核验状态字段。\n输出格式：{{\"facts\":[{{\"fid\":\"...\",\"value\":\"...\",\"doc\":\"...\",\"quote\":\"...\",\"status\":\"verified|unverified|conflict\"}}]}}\n\n事实：{up}\n\n原始文档：{docs_t[:2000]}\n\n按系统格式输出 JSON。"
    else:
        # CRITICAL FIX: report gets ALL merge facts + verify status, not filtered verify output
        merge_facts=upstream.get('merge',[])
        verify_facts=upstream.get('verify',[])
        # Build verify status map
        vstatus={}
        for vf in verify_facts:
            if isinstance(vf,dict):
                vstatus[str(vf.get('fid',''))]=vf.get('status','unverified')
        # Combine: all merge facts annotated with verify status
        combined=[]
        for mf in merge_facts:
            if isinstance(mf,dict):
                fid=str(mf.get('fid',''))
                combined.append({**mf,'verify_status':vstatus.get(fid,'unverified')})
        up=json.dumps(combined,ensure_ascii=False)[:3000]
        return f"基于以下完整事实集合（含核验状态）生成终端调查报告。\n对verified事实明确陈述；对unverified事实披露状态；对conflict事实呈现双方差异。\n不要遗漏任何事实。\n\n事实集合：\n{up}\n\n按系统格式输出 JSON。"

class ArmRunner:
    def __init__(self,cfg,out,real):
        self.real=real; self.out=Path(out)
        st=self.out/'state'; st.mkdir(parents=True,exist_ok=True)
        self.gb=GlobalBudget(cfg['calls'],cfg['yuan'],cfg.get('tokens'),st)
        self.store=RunStore(st,self.out)
        self.ledger=self.out/'ledger.jsonl'; self.outputs=self.out/'outputs.jsonl'
    def call(self,arm,ev,rep,node_id,role,model,system,user,mt):
        est=YUAN[model]
        self.gb.reserve_call(est)
        need=self.gb.reserve_tokens(min(len(user),12000),mt)
        if self.real:
            r=cap_transport(model,system,user,mt,180)
            text=r['text']; tin=r['in']; tout=r['out']; stop=r['stop']; lat=r['lat']
        else:
            text='{"facts":[{"fid":"mock","value":"mock","doc":"doc1","quote":"mock"}]}'
            tin=len(user); tout=64; stop='end_turn'; lat=0.01
        self.gb.release_reservation(need,tin,tout); self.gb.settle(est,0,0)
        rec=dict(ts=time.time(),arm=arm,event=ev,rep=rep,node=node_id,role=role,
                 model=model,tin=tin,tout=tout,yuan=est,stop=stop,lat=lat,
                 prompt_sha=hashlib.sha256((system+'||'+user[:200]).encode()).hexdigest()[:16])
        with open(self.ledger,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
        with open(self.outputs,'a') as f: f.write(json.dumps({**rec,'raw_output':text},ensure_ascii=False)+'\n')
        return text
    def run_exec(self,arm,ev,rep):
        exec_id=f"{arm}|{ev}|r{rep}"
        if self.store.completed(exec_id): return None
        self.store.begin(exec_id)
        docs=get_docs(ev); upstream={}; actions=[]
        dyn = arm=='JointDynamic'
        for node in DAG[ev]:
            kind=node['kind']; nid=node['node_id']
            model=ALLOC.get(kind,'deepseek')
            delivery=kind in DELIVERY_KINDS
            sysp=SYS_COMMON+(D2_CONTRACT if delivery else '')
            userp=node_prompt(ev,node,docs,upstream)
            mt=4000 if delivery else 2000
            text=self.call(arm,ev,rep,nid,'base',model,sysp,userp,mt)
            ok,facts,unk=parse_facts(text)
            sig=signals({'kind':kind},ok,facts)
            chosen=dict(model=model,facts=facts,unknown=unk,rerolled=False)
            if (sig['exec'] or sig['prod'] or sig['cite']):
                if arm=='StaticHetero':
                    actions.append(dict(action='SIGNAL_SUPPRESSED',node=nid))
                else:
                    # R: same-model reroll (FixedRecovery + JointDynamic)
                    text2=self.call(arm,ev,rep,nid,'reroll',model,sysp,userp,mt)
                    ok2,f2,u2=parse_facts(text2)
                    if score_node(f2)>score_node(facts):
                        chosen=dict(model=model,facts=f2,unknown=u2,rerolled=True)
                        actions.append(dict(action='R',node=nid,outcome='recovered'))
                    else:
                        actions.append(dict(action='R',node=nid,outcome='failed'))
                        if dyn and delivery and not ok2:
                            # pi: switch model (JointDynamic only)
                            alt='qwen' if model=='deepseek' else 'deepseek'
                            text3=self.call(arm,ev,rep,nid,'reroll2',alt,sysp,userp,mt)
                            ok3,f3,u3=parse_facts(text3)
                            if score_node(f3)>score_node(facts):
                                chosen=dict(model=alt,facts=f3,unknown=u3,rerolled=True)
                                actions.append(dict(action='pi',node=nid,model=alt,outcome='recovered'))
                            else:
                                actions.append(dict(action='pi',node=nid,model=alt,outcome='failed'))
            upstream[nid]=chosen.get('facts',[])
        record=dict(exec_id=exec_id,arm=arm,event=ev,rep=rep,actions=actions,
                    budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(HERE/'rq_dyn_3arm_config.json'))
    ap.add_argument('--out',default=str(HERE/'rq_dyn_3arm_runs'))
    ap.add_argument('--real',action='store_true')
    a=ap.parse_args()
    cfg=json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED')!='1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip(): raise SystemExit(f'REFUSED:{k}')
        print('REAL MODE',cfg['calls'],cfg['tokens'],cfg['yuan'])
    else: print('MOCK MODE'); return
    r=ArmRunner(cfg,a.out,a.real)
    done=skipped=0; stop=False
    for ev in ('E03_yuandao','E04_zhuoran'):
        for rep in range(1,REPS+1):
            for arm in ('StaticHetero','FixedRecovery','JointDynamic'):
                eid=f"{arm}|{ev}|r{rep}"
                if r.store.completed(eid): skipped+=1; continue
                if r.gb.left()['calls_left']<12:
                    print(f'STOP {eid}'); stop=True; break
                r.run_exec(arm,ev,rep); done+=1
                print(f'  {eid} done left={r.gb.left()["calls_left"]}')
            if stop: break
        if stop: break
    print(f'DONE: {done} skip={skipped} stop={stop} budget={r.gb.left()}')

if __name__=='__main__':
    main()
