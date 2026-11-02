"""Stage-C-R7: Fixed runner with REAL-TIME upstream propagation.

Key fix: upstream data is updated IMMEDIATELY after each node completes,
not after the entire DAG finishes. This ensures downstream nodes always
receive the latest parent outputs in their actual prompts.

Only runs the 12 contaminated SC-E3 + SC-E1-r2 runs within original auth.
"""
import json, sys, time, re, argparse
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
OUT = B / 'stage_c_r7_runs'

SYS = '你是调查DAG节点。严格执行subtask。只使用给定证据。无法确认标注UNRESOLVED。输出极其简洁JSON。'
PK = {'index': 'evidence_index', 'extracts': 'doc_extracts', 'timeline': 'timeline',
      'entity': 'entity_facts', 'factcheck': 'verified_facts', 'report': 'report',
      'entity_facts': 'entity_facts', 'factcheck_full': 'verified_facts'}
NODES = [
    ('n1', 'index', '索引证据文档'),
    ('n2', 'extracts', '抽取关键事实（含所有日期）'),
    ('n3', 'timeline', '时间线（含日期间隔计算，需要上游所有日期）'),
    ('n4', 'entity', '主体事实'),
    ('n5', 'factcheck', '交叉核查（跨文档比较）'),
    ('n6', 'report', '综合报告（含日期间隔与跨文档比较结论）'),
]
DEPS = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2', 'n3', 'n4'], 'n6': ['n5']}
NID = {nid: (nid, k, s) for nid, k, s in NODES}


class FixedAdapter:
    """Adapter with REAL-TIME upstream propagation.
    
    The key fix: upstream is updated by the ENGINE after each node completes,
    not by a post-hoc wrapper. This adapter reads directly from the shared
    state object during execution.
    """
    def __init__(self, meter, state):
        self.meter = meter
        self.state = state  # shared reference to DAGExecutionState
        self.texts = {}
        self.rid = ''
    
    def _get_upstream(self):
        """Read current upstream from shared state - called RIGHT BEFORE building prompt."""
        upstream = {}
        for nid, node in self.state.nodes.items():
            if node.status == 'done' and node.output:
                pk = PK.get(node.kind, node.kind)
                if pk in node.output:
                    upstream[pk] = node.output[pk]
        return upstream
    
    def call(self, nid, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        alias = model if model in ('glm53', 'glm53flash') else 'glm53'
        
        if nid == anomaly_node and anomaly_type and attempt == 1:
            return {'success': False, 'failure_type': FailureType.TRANSPORT,
                    'output': None, 'usage': {'in': 100, 'out': 0}, 'latency_s': 0.5}
        
        pk = PK.get(kind, kind)
        # CRITICAL FIX: get upstream RIGHT NOW, not from a stale cache
        upstream = self._get_upstream()
        
        pr = f'subtask: {NID[nid][2]}\n输出JSON对象，只有一个顶层键 "{pk}"。\n'
        
        if kind in ('index', 'extracts'):
            for did, txt in self.texts.items():
                pr += f'文档 {did}（前500字）: {txt[:500]}\n'
        
        # ALWAYS include upstream data (this is the fix)
        for port, val in upstream.items():
            pr += f'{port}: {json.dumps(val, ensure_ascii=False)[:2000]}\n'
        
        if kind == 'report':
            pr += '\n输出JSON：{"investigation_timeline":"含日期间隔","fraud_nature":"含跨文档比较","report":"完整调查报告","unknown_marks":[...]}\n'
        
        try:
            rec, txt = self.meter.call(alias, SYS, pr,
                                       max_tokens=768 if kind == 'report' else 1024,
                                       purpose=f'R7-{self.rid}:{nid}:a{attempt}', timeout_s=60)
            try:
                obj = fenced_json(txt)
                output = {pk: obj.get(pk, obj)} if isinstance(obj, dict) else {pk: obj}
                return {'success': True, 'output': output,
                        'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s'], 'raw': txt}
            except Exception:
                return {'success': False, 'failure_type': FailureType.CONTRACT, 'output': None,
                        'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s']}
        except BudgetExceeded:
            return {'success': False, 'failure_type': FailureType.TIMEOUT, 'output': None,
                    'usage': {'in': 0, 'out': 0}, 'latency_s': 0.1}


def load_event(ev_id):
    task = next(t for t in json.load(open(SC / 'tasks.json')) if t['event'] == ev_id)
    texts = {did: (SC / 'text' / f'{did}.txt').read_text()
             for did in task['doc_ids'] if (SC / 'text' / f'{did}.txt').exists()}
    silver_orig = json.load(open(SC / f'{ev_id}_silver.json'))['facts']
    dd_all = json.load(open(SC / 'downstream_silver.json'))
    silver_dd = dd_all.get(ev_id, [])
    return task, texts, silver_orig, silver_dd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    args = ap.parse_args()
    if not args.authorize:
        print(json.dumps({'mode': 'PLAN'}))
        return
    
    OUT.mkdir(exist_ok=True)
    meter = Meter(ledger_path=B / 'stage_c_r6_runs' / 'ledger.jsonl',
                  max_calls=200, max_guaranteed_actual=200000)
    
    # Rerun list
    rerun = json.load(open(B / 'stage_c_r6_runs' / 'CONTAMINATED_RERUN_LIST.json'))
    
    # Load events
    events_data = {}
    for ev_id in ['E1_zhangzidao', 'E3_chinaship']:
        events_data[ev_id] = load_event(ev_id)
    
    ARMS = ['Static-Parallel', 'Simple-Dynamic', 'R-only', 'pi-only', 'Joint(R,pi)']
    results = []
    
    for run_id_old in rerun:
        # Parse: R6-{arm}-{task}-{anomaly?}-r{rep}
        # Actually format is: R6-{arm}-{SC-Ex}-r{rep}
        arm = None
        for a in ARMS:
            if run_id_old.startswith(f'R6-{a}-'): arm = a; break
        if not arm: continue
        
        ev_tid = None
        for tid in ['SC-E1', 'SC-E3']:
            if tid in run_id_old: ev_tid = tid; break
        if not ev_tid: continue
        
        ev_id = 'E1_zhangzidao' if ev_tid == 'SC-E1' else 'E3_chinaship'
        rep = run_id_old[-1]
        new_rid = f'R7-{arm}-{ev_tid}-r{rep}'
        
        task, texts, silver_orig, silver_dd = events_data[ev_id]
        
        print(f'\n  {arm:20s} {ev_tid} r{rep}: ', end='', flush=True)
        
        nodes = {nid: NodeState(nid, k, model='glm53', status='pending') for nid, k, _ in NODES}
        state = DAGExecutionState(nodes=nodes, deps=DEPS,
                                  resource_slots=ResourceSlots({'glm53': 2, 'flash': 2}),
                                  budget_remaining=8000, deadline_remaining=120.0,
                                  anomaly_node='n3', anomaly_type=FailureType.TRANSPORT)
        
        adapter = FixedAdapter(meter, state)  # Pass state directly
        adapter.texts = texts
        adapter.rid = f'{arm}-{ev_tid}-r{rep}'
        
        t0 = time.time()
        trace = execute_dag(state, arm, adapter)
        wall = time.time() - t0
        print(f'{trace["final_status"][:4]} wall={wall:.1f}s')
        
        rd = OUT / new_rid
        rd.mkdir(parents=True, exist_ok=True)
        (rd / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str))
        
        results.append({'run_id': new_rid, 'arm': arm, 'event': ev_tid, 'rep': rep,
                        'status': trace['final_status'], 'wall_s': round(wall, 3),
                        'original_contaminated': run_id_old})
    
    json.dump({'runner': 'stage_c_r7_v1', 'runs': results, 'budget': meter.summary()},
              open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nDone: {len(results)} runs')
    print(f'Ledger: {meter.n_calls}/200, {meter.actual_tokens:,}/200,000')


if __name__ == '__main__':
    main()
