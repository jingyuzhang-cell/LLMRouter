"""stage_c_r1_v1 REAL runner: 48 runs (4 events × 2 anomalies × 6 arms × 1 rep).
Uses reconstructed stage_c_r1_engine for scheduling decisions + real GLM API calls.
Per-model quotas enforced in addition to global Meter cap.
"""
import json, sys, os, time, re, hashlib, argparse
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B / 'integration'))
sys.path.insert(0, str(P))

from pilot_common import Meter, BudgetExceeded, fenced_json
from stage_c_r1_engine import (
    DAGExecutionState, NodeState, ResourceSlots, FailureType,
    ARM_DECIDERS, execute_dag)

RUNNER = 'stage_c_r1_v1'
SC = B / 'stage_c_evidence'
OUT = B / 'stage_c_r1_runs'

EVENTS = ['E1_zhangzidao', 'E2_kangmei', 'E3_chinaship', 'E4_leshi']
TASK_IDS = {'E1_zhangzidao': 'SC-E1', 'E2_kangmei': 'SC-E2',
            'E3_chinaship': 'SC-E3', 'E4_leshi': 'SC-E4'}
ANOMALIES = ['transport', 'evidence_fail']
ARMS = list(ARM_DECIDERS.keys())

SYS = ('你是调查DAG节点。严格执行subtask。只使用给定证据。'
       '无法确认标注UNRESOLVED。输出极其简洁JSON——每字段值不超过50字。')

PORT_KEYS = {'index': 'evidence_index', 'extracts': 'doc_extracts', 'timeline': 'timeline',
             'entity': 'entity_facts', 'factcheck': 'verified_facts', 'report': 'report',
             'entity_facts': 'entity_facts', 'factcheck_full': 'verified_facts'}

NODES = [
    ('n1', 'index', '索引证据文档，分类监管/公告线'),
    ('n2', 'extracts', '抽取关键事实片段（引文+doc_id+日期）'),
    ('n3', 'timeline', '梳理事件时间线（日期+事件+doc_id）'),
    ('n4', 'entity', '识别涉及主体与处罚/合并结论事实'),
    ('n5', 'factcheck', '交叉核查时间线与事实，标注UNRESOLVED'),
    ('n6', 'report', '综合调查报告'),
]

DEPS = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2', 'n3', 'n4'], 'n6': ['n5']}

# Per-model quota tracking
model_usage = {'glm53': {'calls': 0, 'tokens': 0}, 'glm53flash': {'calls': 0, 'tokens': 0}}
MODEL_LIMITS = {'glm53': {'calls': 400, 'tokens': 420000},
                'glm53flash': {'calls': 200, 'tokens': 180000}}


def check_model_quota(model_alias):
    """Check per-model quota in addition to global Meter."""
    u = model_usage[model_alias]
    lim = MODEL_LIMITS[model_alias]
    return u['calls'] < lim['calls'] and u['tokens'] < lim['tokens']


def load_event(ev_id):
    task = next(t for t in json.load(open(SC / 'tasks.json')) if t['event'] == ev_id)
    texts = {}
    for did in task['doc_ids']:
        p = SC / 'text' / f'{did}.txt'
        if p.exists():
            texts[did] = p.read_text()
    silver = json.load(open(SC / f'{ev_id}_silver.json'))['facts']
    return task, texts, silver


def score_coverage(text, silver):
    def norm(s):
        return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
    nt = norm(text)
    covered = []
    for f in silver:
        a, typ = f['answer'], f.get('answer_type', 'text')
        na = norm(a)
        hit = na in nt
        if not hit and typ == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                hit = norm(f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日') in nt
        if hit:
            covered.append(f['fact_id'])
    return round(len(covered) / max(1, len(silver)), 4), covered


class RealModelAdapter:
    """Real model adapter that calls GLM API through the Meter."""
    def __init__(self, meter):
        self.meter = meter

    def call(self, node_id, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        alias = model if model in ('glm53', 'glm53flash') else 'glm53'

        # Check per-model quota
        if not check_model_quota(alias):
            return {'success': False, 'failure_type': FailureType.TIMEOUT,
                    'output': None, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.1}

        # Anomaly injection (same as FakeModelAdapter)
        if node_id == anomaly_node and anomaly_type and attempt == 1:
            if anomaly_type == FailureType.TRANSPORT:
                # Simulate transport failure: don't call API, return failure
                model_usage[alias]['calls'] += 1
                model_usage[alias]['tokens'] += 100
                return {'success': False, 'failure_type': FailureType.TRANSPORT,
                        'output': None, 'usage': {'in': 100, 'out': 0}, 'latency_s': 0.5}

        # Build prompt
        pk = PORT_KEYS.get(kind, kind)
        prompt = f'subtask: {NODES_BY_ID[node_id][2] if node_id in NODES_BY_ID else kind}\n'
        prompt += f'输出JSON对象，只有一个顶层键 "{pk}"，值为数组或对象。\n'
        # Add evidence text (limited)
        if kind in ('index', 'extracts') or not hasattr(self, '_texts'):
            for did, txt in self._texts.items():
                prompt += f'文档 {did}（前500字）: {txt[:500]}\n'
        if kind == 'report':
            prompt += '\n输出JSON：{"investigation_timeline":"...","fraud_nature":"...","report":"...","unknown_marks":[...]}\n'
        # Add upstream data
        for port, val in getattr(self, '_upstream', {}).items():
            prompt += f'{port}: {json.dumps(val, ensure_ascii=False)[:1500]}\n'

        # Make real API call
        try:
            rec, txt = self.meter.call(
                alias, SYS, prompt,
                max_tokens=768 if kind == 'report' else 1024,
                purpose=f'{self._run_id}:{node_id}:a{attempt}',
                timeout_s=60)

            # Update model usage
            model_usage[alias]['calls'] += 1
            model_usage[alias]['tokens'] += rec['usage']['input_tokens'] + rec['usage']['output_tokens']

            # Parse response
            try:
                obj = fenced_json(txt)
                if isinstance(obj, dict) and pk in obj:
                    return {'success': True, 'output': obj,
                            'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']}, 'latency_s': rec['latency_s']}
                # Try fuzzy key match
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if norm(k) == norm(pk):
                            return {'success': True, 'output': {pk: v},
                                    'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']}, 'latency_s': rec['latency_s']}
                # If we got JSON but wrong key, still count as success with raw output
                return {'success': True, 'output': {pk: obj},
                        'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']}, 'latency_s': rec['latency_s']}
            except Exception:
                return {'success': False, 'failure_type': FailureType.CONTRACT,
                        'output': None, 'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']}, 'latency_s': rec['latency_s']}

        except BudgetExceeded:
            return {'success': False, 'failure_type': FailureType.TIMEOUT,
                    'output': None, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.1}


# Global mapping for NODES_BY_ID
NODES_BY_ID = {nid: (nid, kind, sub) for nid, kind, sub in NODES}


def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))


def run_single(meter, adapter, run_id, arm, anomaly_type_str, ev_id, texts, silver):
    """Execute one run using the real engine."""
    anomaly_type = FailureType.TRANSPORT if anomaly_type_str == 'transport' else FailureType.EVIDENCE
    anomaly_node = 'n3'  # timeline node for all events (consistent)

    nodes = {}
    for nid, kind, sub in NODES:
        nodes[nid] = NodeState(nid, kind, model='glm53', status='pending')

    state = DAGExecutionState(
        nodes=nodes, deps=DEPS,
        resource_slots=ResourceSlots({'glm53': 2, 'flash': 2}),
        budget_remaining=50000, deadline_remaining=120.0,
        anomaly_node=anomaly_node, anomaly_type=anomaly_type)

    # Set up adapter context
    adapter._texts = texts
    adapter._upstream = {}
    adapter._run_id = run_id

    # Override the adapter's call to include upstream data
    original_call = adapter.call
    def call_with_upstream(node_id, kind, model, **kwargs):
        # Get upstream outputs from state
        upstream = {}
        for nid, node in state.nodes.items():
            if node.status == 'done' and node.output:
                pk = PORT_KEYS.get(node.kind, node.kind)
                if pk in node.output:
                    upstream[pk] = node.output[pk]
        adapter._upstream = upstream
        return original_call(node_id, kind, model, **kwargs)
    adapter.call = call_with_upstream

    t0 = time.time()
    trace = execute_dag(state, arm, adapter)
    wall_s = time.time() - t0

    # Score
    raw_output = json.dumps({nid: n.output for nid, n in state.nodes.items() if n.output},
                            ensure_ascii=False)
    q, covered = score_coverage(raw_output, silver)

    # Save per-run artifacts
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1,
                                                  default=str))
    (run_dir / 'scores.json').write_text(json.dumps(
        {'Q': q, 'covered': covered, 'wall_s': wall_s}, indent=1))

    return {'run_id': run_id, 'arm': arm, 'event': ev_id,
            'anomaly': anomaly_type_str, 'status': trace['final_status'],
            'Q': q, 'wall_s': round(wall_s, 3),
            'makespan': trace['makespan'], 'cache_hits': trace['cache_hits'],
            'n_decisions': len(trace['decisions']),
            'z_ops': [d['z_op'] for d in trace['decisions']]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    args = ap.parse_args()
    if not args.authorize:
        print(json.dumps({'mode': 'PLAN', 'runs': len(EVENTS)*len(ANOMALIES)*len(ARMS)}))
        return

    OUT.mkdir(exist_ok=True)
    meter = Meter(ledger_path=OUT / 'ledger.jsonl',
                  max_calls=550, max_guaranteed_actual=600000)
    adapter = RealModelAdapter(meter)
    results = []

    for ev_id in EVENTS:
        task, texts, silver = load_event(ev_id)
        tid = TASK_IDS[ev_id]
        print(f"\n=== {ev_id} ({tid}) ===")

        for anomaly in ANOMALIES:
            for arm in ARMS:
                run_id = f'R1-{arm}-{tid}-{anomaly}'
                try:
                    r = run_single(meter, adapter, run_id, arm, anomaly, ev_id, texts, silver)
                    results.append(r)
                    print(f"  {arm:20s} {anomaly:14s}: Q={r['Q']} {r['status'][:4]} wall={r['wall_s']}s")
                except BudgetExceeded as e:
                    results.append({'run_id': run_id, 'status': 'BUDGET_STOP'})
                    print(f"  BUDGET STOP")
                    # Write partial results
                    json.dump({'runs': results, 'budget': meter.summary(),
                              'model_usage': model_usage},
                             open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
                    return

    # Write final results
    json.dump({
        'runner': RUNNER,
        'runs': results,
        'budget': meter.summary(),
        'model_usage': model_usage,
    }, open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDone: {len(results)} runs")
    print(f"Calls: {meter.n_calls}/550")
    print(f"Tokens: {meter.actual_tokens}/{600000}")
    print(f"GLM: {model_usage['glm53']['calls']} calls / {model_usage['glm53']['tokens']} tokens")
    print(f"Flash: {model_usage['glm53flash']['calls']} calls / {model_usage['glm53flash']['tokens']} tokens")


if __name__ == '__main__':
    main()
