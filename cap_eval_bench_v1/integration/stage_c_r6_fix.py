import json, sys, os, time, re
from pathlib import Path
B = Path('/root/cap_eval_bench_v1'); P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B/'integration')); sys.path.insert(0, str(P))
from pilot_common import Meter, BudgetExceeded, fenced_json
from stage_c_r1_engine import DAGExecutionState, NodeState, ResourceSlots, FailureType, ARM_DECIDERS, execute_dag

SC = B/'stage_c_evidence'; OUT = B/'stage_c_r6_runs'
ARMS = ['Static-Parallel','Simple-Dynamic','R-only','pi-only','Joint(R,pi)']
EVENT = 'E3_chinaship'; TASK_ID = 'SC-E3'
SYS = '你是调查DAG节点。严格执行subtask。只使用给定证据。无法确认标注UNRESOLVED。输出极其简洁JSON。'
PK = {'index':'evidence_index','extracts':'doc_extracts','timeline':'timeline','entity':'entity_facts','factcheck':'verified_facts','report':'report','entity_facts':'entity_facts','factcheck_full':'verified_facts'}
NODES = [('n1','index','索引证据文档'),('n2','extracts','抽取关键事实'),
          ('n3','timeline','时间线（含日期间隔计算）'),('n4','entity','主体事实'),
          ('n5','factcheck','交叉核查（跨文档比较）'),('n6','report','综合报告')]
DEPS = {'n2':['n1'],'n3':['n2'],'n4':['n2'],'n5':['n2','n3','n4'],'n6':['n5']}
NID = {nid:(nid,k,s) for nid,k,s in NODES}

task = next(t for t in json.load(open(SC/'tasks.json')) if t['event']==EVENT)
texts = {did:(SC/'text'/f'{did}.txt').read_text() for did in task['doc_ids'] if (SC/'text'/f'{did}.txt').exists()}

class Ad:
    def __init__(self, meter): self.m = meter
    def call(self, nid, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        if nid == anomaly_node and anomaly_type and attempt == 1:
            return {'success':False,'failure_type':FailureType.TRANSPORT,'output':None,
                    'usage':{'in':100,'out':0},'latency_s':0.5}
        pk = PK.get(kind,kind)
        pr = f'subtask: {NID[nid][2]}\n输出JSON对象，只有一个顶层键 "{pk}"。\n'
        if kind in ('index','extracts'):
            for did,txt in self.texts.items(): pr += f'文档 {did}（前500字）: {txt[:500]}\n'
        if kind == 'report':
            pr += '\n输出JSON：{"investigation_timeline":"含日期间隔","fraud_nature":"含跨文档比较","report":"完整调查报告","unknown_marks":[...]}\n'
        for port,val in self.upstream.items(): pr += f'{port}: {json.dumps(val,ensure_ascii=False)[:1500]}\n'
        try:
            rec,txt = self.m.call('glm53',SYS,pr,max_tokens=768 if kind=='report' else 1024,
                                  purpose=f'{self.rid}:{nid}:a{attempt}',timeout_s=60)
            try:
                obj = fenced_json(txt)
                return {'success':True,'output':{pk:obj.get(pk,obj)} if isinstance(obj,dict) else {pk:obj},
                        'usage':{'in':rec['usage']['input_tokens'],'out':rec['usage']['output_tokens']},
                        'latency_s':rec['latency_s'],'raw':txt}
            except: return {'success':False,'failure_type':FailureType.CONTRACT,'output':None,
                        'usage':{'in':rec['usage']['input_tokens'],'out':rec['usage']['output_tokens']},
                        'latency_s':rec['latency_s']}
        except BudgetExceeded: return {'success':False,'failure_type':FailureType.TIMEOUT,'output':None,
                'usage':{'in':0,'out':0},'latency_s':0.1}

meter = Meter(ledger_path=OUT/'ledger.jsonl', max_calls=200, max_guaranteed_actual=200000)
ad = Ad(meter)
n_done = 0
for rep in [1,2]:
    for arm in ARMS:
        rid = f'R6-{arm}-{TASK_ID}-r{rep}'
        print(f'  {arm:20s} r{rep}: ',end='',flush=True)
        nodes = {nid:NodeState(nid,k,model='glm53',status='pending') for nid,k,_ in NODES}
        state = DAGExecutionState(nodes=nodes,deps=DEPS,resource_slots=ResourceSlots({'glm53':2,'flash':2}),
                                  budget_remaining=8000,deadline_remaining=120.0,
                                  anomaly_node='n3',anomaly_type=FailureType.TRANSPORT)
        ad.texts = texts; ad.upstream = {}; ad.rid = rid
        t0 = time.time()
        trace = execute_dag(state,arm,ad)
        wall = time.time()-t0
        # Update upstream after each node
        for rec in trace.get('node_records',[]):
            if rec['status']=='done':
                for nid2,node in state.nodes.items():
                    if node.output:
                        pk2 = PK.get(node.kind,node.kind)
                        if pk2 in node.output: ad.upstream[pk2] = node.output[pk2]
        print(f'{trace["final_status"][:4]} wall={wall:.1f}s')
        rd = OUT/rid; rd.mkdir(parents=True,exist_ok=True)
        (rd/'trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=1,default=str))
        n_done += 1
print(f'\nDone: +{n_done} runs | Ledger: {meter.n_calls}/200, {meter.actual_tokens:,} tok')
