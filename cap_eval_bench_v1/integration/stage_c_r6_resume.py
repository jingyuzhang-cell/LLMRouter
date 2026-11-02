"""Resume Stage-C-R6: SC-E3 only (10 runs × 5 arms × 2 reps)."""
import json, sys, os, time, re, argparse
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B / 'integration'))
sys.path.insert(0, str(P))

from pilot_common import Meter, BudgetExceeded, fenced_json
from stage_c_r1_engine import (
    DAGExecutionState, NodeState, ResourceSlots, FailureType,
    ARM_DECIDERS, execute_dag)

SC = B / 'stage_c_evidence'
OUT = B / 'stage_c_r6_runs'
ARMS = ['Static-Parallel', 'Simple-Dynamic', 'R-only', 'pi-only', 'Joint(R,pi)']
EVENT = 'E3_chinaship'
TASK_ID = 'SC-E3'

SYS = ('你是调查DAG节点。严格执行subtask。只使用给定证据。'
       '无法确认标注UNRESOLVED。输出极其简洁JSON。')
PORT_KEYS = {'index': 'evidence_index', 'extracts': 'doc_extracts', 'timeline': 'timeline',
             'entity': 'entity_facts', 'factcheck': 'verified_facts', 'report': 'report',
             'entity_facts': 'entity_facts', 'factcheck_full': 'verified_facts'}
NODES = [
    ('n1', 'index', '索引证据文档'),
    ('n2', 'extracts', '抽取关键事实'),
    ('n3', 'timeline', '时间线（含日期间隔计算）'),
    ('n4', 'entity', '主体事实'),
    ('n5', 'factcheck', '交叉核查（跨文档比较）'),
    ('n6', 'report', '综合报告'),
]
DEPS = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2', 'n3', 'n4'], 'n6': ['n5']}
NODES_BY_ID = {nid: (nid, k, s) for nid, k, s in NODES}

model_usage = {'glm53': {'calls': 0, 'tokens': 0}, 'glm53flash': {'calls': 0, 'tokens': 0}}

class Adapter:
    def __init__(self, meter): self.meter = meter
    def call(self, node_id, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        alias = model if model in ('glm53','glm53flash') else 'glm53'
        if node_id == anomaly_node and anomaly_type and attempt == 1:
            model_usage[alias]['calls'] += 1
            model_usage[alias]['tokens'] += 100
            return {'success': False, 'failure_type': FailureType.TRANSPORT,
                    'output': None, 'usage': {'in': 100, 'out': 0}, 'latency_s': 0.5}
        pk = PORT_KEYS.get(kind, kind)
        prompt = f'subtask: {NODES_BY_ID[node_id][2]}\n输出JSON对象，只有一个顶层键 "{pk}"。\n'
        if kind in ('index','extracts'):
            for did, txt in self._texts.items():
                prompt += f'文档 {did}（前500字）: {txt[:500]}\n'
        if kind == 'report':
            prompt += '\n输出JSON：{"investigation_timeline":"含日期间隔","fraud_nature":"含跨文档比较","report":"完整调查报告","unknown_marks":[...]}\n'
        for port, val in self._upstream.items():
            prompt += f'{port}: {json.dumps(val, ensure_ascii=False)[:1500]}\n'
        try:
            rec, txt = self.meter.call(alias, SYS, prompt,
                                       max_tokens=768 if kind=='report' else 1024,
                                       purpose=f'{self._run_id}:{node_id}:a{attempt}', timeout_s=60)
            model_usage[alias]['calls'] += 1
            model_usage[alias]['tokens'] += rec['usage']['input_tokens']+rec['usage']['output_tokens']
            try:
                obj = fenced_json(txt)
                if isinstance(obj, dict) and pk in obj:
                    return {'success': True, 'output': {pk: obj[pk]},
                            'usage': {'in': rec['usage']['input_tokens'],'out': rec['usage']['output_tokens']},
                            'latency_s': rec['latency_s'], 'raw': txt}
                return {'success': True, 'output': {pk: obj},
                        'usage': {'in': rec['usage']['input_tokens'],'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s'], 'raw': txt}
            except Exception:
                return {'success': False, 'failure_type': FailureType.CONTRACT, 'output': None,
                        'usage': {'in': rec['usage']['input_tokens'],'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s']}
        except BudgetExceeded:
            return {'success': False, 'failure_type': FailureType.TIMEOUT, 'output': None,
                    'usage': {'in':0,'out':0}, 'latency_s': 0.1}

def load_event():
    task = next(t for t in json.load(open(SC/'tasks.json')) if t['event']==EVENT)
    texts = {did: (SC/'text'/f'{did}.txt').read_text() for did in task['doc_ids'] if (SC/'text'/f'{did}.txt').exists()}
    silver_orig = json.load(open(SC/f'{EVENT}_silver.json'))['facts']
    dd_all = json.load(open(SC/'downstream_silver.json'))
    silver_dd = dd_all.get(EVENT, [])
    return task, texts, silver_orig, silver_dd

def main():
    task, texts, silver_orig, silver_dd = load_event()
    meter = Meter(ledger_path=OUT/'ledger.jsonl', max_calls=200, max_guaranteed_actual=200000)
    adapter = Adapter(meter)
    results = []

    for rep in [1, 2]:
        for arm in ARMS:
            run_id = f'R6-{arm}-{TASK_ID}-r{rep}'
            print(f"  {arm:20s} r{rep}: ", end='', flush=True)
            nodes = {nid: NodeState(nid, k, model='glm53', status='pending') for nid,k,_ in NODES}
            state = DAGExecutionState(nodes=nodes, deps=DEPS,
                                      resource_slots=ResourceSlots({'glm53':2,'flash':2}),
                                      budget_remaining=8000, deadline_remaining=120.0,
                                      anomaly_node='n3', anomaly_type=FailureType.TRANSPORT)
            adapter._texts = texts; adapter._upstream = {}; adapter._run_id = run_id
            orig = adapter.call
            def cwa(nid, kind, model, **kw):
                upstream = {}
                for n2, node in state.nodes.items():
                    if node.status=='done' and node.output:
                        pk = PORT_KEYS.get(node.kind, node.kind)
                        if pk in node.output: upstream[pk] = node.output[pk]
                adapter._upstream = upstream
                return orig(nid, kind, model, **kw)
            adapter.call = cwa
            t0 = time.time()
            trace = execute_dag(state, arm, adapter)
            wall = time.time()-t0
            print(f"{trace['final_status'][:4]} wall={wall:.1f}s")

            rd = OUT/run_id; rd.mkdir(parents=True, exist_ok=True)
            (rd/'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str))
            results.append({'run_id': run_id, 'arm': arm, 'status': trace['final_status'], 'wall_s': round(wall,3)})

    print(f"\nDone: +{len(results)} SC-E3 runs")
    print(f"Total ledger: {meter.n_calls}/200, {meter.actual_tokens:,}/200,000")

if __name__ == '__main__':
    main()
