"""Stage-C-R6: Minimal paired experiment with downstream-dependent Silver.
20 runs: 2 events × 1 anomaly(transport) × 5 arms × 2 reps.
Four-metric scoring: Q_terminal / Q_prefix / Q_downstream / dQ_recovery.
"""
import json, sys, os, time, re, argparse
from pathlib import Path
from datetime import date

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(B / 'integration'))
sys.path.insert(0, str(P))

from pilot_common import Meter, BudgetExceeded, fenced_json
from stage_c_r1_engine import (
    DAGExecutionState, NodeState, ResourceSlots, FailureType,
    ARM_DECIDERS, execute_dag)

RUNNER = 'stage_c_r6_v1'
SC = B / 'stage_c_evidence'
OUT = B / 'stage_c_r6_runs'

EVENTS = ['E1_zhangzidao', 'E3_chinaship']
TASK_IDS = {'E1_zhangzidao': 'SC-E1', 'E3_chinaship': 'SC-E3'}
# 5 arms (exclude Joint(Z,R,pi) — Z=NOT_TESTED)
ARMS = ['Static-Parallel', 'Simple-Dynamic', 'R-only', 'pi-only', 'Joint(R,pi)']
REPS = 2

SYS = ('你是调查DAG节点。严格执行subtask。只使用给定证据。'
       '无法确认标注UNRESOLVED。输出极其简洁JSON。')

PORT_KEYS = {'index': 'evidence_index', 'extracts': 'doc_extracts', 'timeline': 'timeline',
             'entity': 'entity_facts', 'factcheck': 'verified_facts', 'report': 'report',
             'entity_facts': 'entity_facts', 'factcheck_full': 'verified_facts'}

NODES = [
    ('n1', 'index', '索引证据文档，分类监管/公告线'),
    ('n2', 'extracts', '抽取关键事实片段（引文+doc_id+日期）'),
    ('n3', 'timeline', '梳理事件时间线（日期+事件+doc_id，计算日期间隔）'),
    ('n4', 'entity', '识别涉及主体与处罚/合并结论事实'),
    ('n5', 'factcheck', '交叉核查时间线与事实，比对两份文档，标注UNRESOLVED'),
    ('n6', 'report', '综合调查报告（含日期间隔与跨文档比较结论）'),
]
DEPS = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2', 'n3', 'n4'], 'n6': ['n5']}

model_usage = {'glm53': {'calls': 0, 'tokens': 0}, 'glm53flash': {'calls': 0, 'tokens': 0}}
MODEL_LIMITS = {'glm53': {'calls': 160, 'tokens': 160000},
                'glm53flash': {'calls': 80, 'tokens': 40000}}

def load_event(ev_id):
    task = next(t for t in json.load(open(SC / 'tasks.json')) if t['event'] == ev_id)
    texts = {}
    for did in task['doc_ids']:
        p = SC / 'text' / f'{did}.txt'
        if p.exists(): texts[did] = p.read_text()
    # Load both original and downstream Silver
    silver_orig = json.load(open(SC / f'{ev_id}_silver.json'))['facts']
    dd_all = json.load(open(SC / 'downstream_silver.json'))
    silver_dd = dd_all.get(ev_id, [])
    return task, texts, silver_orig, silver_dd

def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）【】]+', '', str(s))

def score_facts(text, silver):
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
        if hit: covered.append(f.get('fact_id', f.get('id', '?')))
    return covered

class R6Adapter:
    def __init__(self, meter):
        self.meter = meter
    def call(self, node_id, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        alias = model if model in ('glm53', 'glm53flash') else 'glm53'
        if model_usage[alias]['calls'] >= MODEL_LIMITS[alias]['calls']:
            return {'success': False, 'failure_type': FailureType.TIMEOUT,
                    'output': None, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.1}
        if node_id == anomaly_node and anomaly_type and attempt == 1:
            if anomaly_type == FailureType.TRANSPORT:
                model_usage[alias]['calls'] += 1
                model_usage[alias]['tokens'] += 100
                return {'success': False, 'failure_type': FailureType.TRANSPORT,
                        'output': None, 'usage': {'in': 100, 'out': 0}, 'latency_s': 0.5}

        pk = PORT_KEYS.get(kind, kind)
        prompt = f'subtask: {NODES_BY_ID[node_id][2] if node_id in NODES_BY_ID else kind}\n'
        prompt += f'输出JSON对象，只有一个顶层键 "{pk}"。\n'
        if kind in ('index', 'extracts'):
            for did, txt in self._texts.items():
                prompt += f'文档 {did}（前500字）: {txt[:500]}\n'
        if kind == 'report':
            prompt += '\n输出JSON：{"investigation_timeline":"含日期间隔","fraud_nature":"含跨文档比较","report":"完整调查报告","unknown_marks":[...]}\n'
        for port, val in self._upstream.items():
            prompt += f'{port}: {json.dumps(val, ensure_ascii=False)[:1500]}\n'

        try:
            rec, txt = self.meter.call(alias, SYS, prompt,
                                       max_tokens=768 if kind == 'report' else 1024,
                                       purpose=f'{self._run_id}:{node_id}:a{attempt}', timeout_s=60)
            model_usage[alias]['calls'] += 1
            model_usage[alias]['tokens'] += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
            try:
                obj = fenced_json(txt)
                if isinstance(obj, dict) and pk in obj:
                    return {'success': True, 'output': {pk: obj[pk]},
                            'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                            'latency_s': rec['latency_s'], 'raw': txt}
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if norm(k) == norm(pk):
                            return {'success': True, 'output': {pk: v},
                                    'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                                    'latency_s': rec['latency_s'], 'raw': txt}
                return {'success': True, 'output': {pk: obj},
                        'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s'], 'raw': txt}
            except Exception:
                return {'success': False, 'failure_type': FailureType.CONTRACT,
                        'output': None, 'usage': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
                        'latency_s': rec['latency_s']}
        except BudgetExceeded:
            return {'success': False, 'failure_type': FailureType.TIMEOUT,
                    'output': None, 'usage': {'in': 0, 'out': 0}, 'latency_s': 0.1}

NODES_BY_ID = {nid: (nid, kind, sub) for nid, kind, sub in NODES}

def run_single(meter, adapter, run_id, arm, ev_id, texts, silver_orig, silver_dd):
    nodes = {nid: NodeState(nid, kind, model='glm53', status='pending') for nid, kind, _ in NODES}
    state = DAGExecutionState(nodes=nodes, deps=DEPS,
                              resource_slots=ResourceSlots({'glm53': 2, 'flash': 2}),
                              budget_remaining=8000, deadline_remaining=120.0,
                              anomaly_node='n3', anomaly_type=FailureType.TRANSPORT)
    adapter._texts = texts
    adapter._upstream = {}
    adapter._run_id = run_id

    orig_call = adapter.call
    def call_with_upstream(node_id, kind, model, **kwargs):
        upstream = {}
        for nid, node in state.nodes.items():
            if node.status == 'done' and node.output:
                pk = PORT_KEYS.get(node.kind, node.kind)
                if pk in node.output: upstream[pk] = node.output[pk]
        adapter._upstream = upstream
        return orig_call(node_id, kind, model, **kwargs)
    adapter.call = call_with_upstream

    t0 = time.time()
    trace = execute_dag(state, arm, adapter)
    wall_s = time.time() - t0

    # Collect outputs for scoring
    all_output_text = ' '.join(r.get('raw', '') for r in trace.get('node_records', []))
    report_output = ''
    for rec in trace.get('node_records', []):
        if rec.get('node_id') == 'n6' and rec.get('status') == 'done':
            report_output = str(rec.get('output', {}))

    # Four-metric scoring
    # Q_terminal: score report output against ALL silver
    all_silver = silver_orig + silver_dd
    terminal_covered = score_facts(report_output, all_silver) if report_output else []
    q_terminal = round(len(terminal_covered) / max(1, len(all_silver)), 4)

    # Q_prefix: score n1-n2 outputs against original silver
    prefix_text = ''
    for rec in trace.get('node_records', []):
        if rec.get('node_id') in ('n1', 'n2') and rec.get('status') == 'done':
            prefix_text += str(rec.get('output', {}))
    prefix_covered = score_facts(prefix_text, silver_orig) if prefix_text else []
    q_prefix = round(len(prefix_covered) / max(1, len(silver_orig)), 4)

    # Q_downstream: score ALL output against downstream silver only
    dd_covered = score_facts(all_output_text, silver_dd) if silver_dd else []
    q_downstream = round(len(dd_covered) / max(1, len(silver_dd)), 4) if silver_dd else 0

    # dQ_recovery: downstream facts in terminal NOT in prefix
    terminal_dd = set(score_facts(report_output, silver_dd)) if report_output else set()
    prefix_dd = set(score_facts(prefix_text, silver_dd)) if prefix_text else set()
    recovery_dd = terminal_dd - prefix_dd
    dq_recovery = round(len(recovery_dd) / max(1, len(silver_dd)), 4) if silver_dd else 0

    # Save artifacts
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str))
    (run_dir / 'scores.json').write_text(json.dumps({
        'Q_terminal': q_terminal, 'Q_prefix': q_prefix,
        'Q_downstream': q_downstream, 'dQ_recovery': dq_recovery,
        'terminal_covered': terminal_covered, 'prefix_covered': prefix_covered,
        'dd_covered': dd_covered, 'recovery_dd_facts': sorted(recovery_dd),
        'wall_s': round(wall_s, 3)
    }, indent=1))

    return {'run_id': run_id, 'arm': arm, 'event': ev_id, 'rep': run_id[-1],
            'status': trace['final_status'], 'wall_s': round(wall_s, 3),
            'Q_terminal': q_terminal, 'Q_prefix': q_prefix,
            'Q_downstream': q_downstream, 'dQ_recovery': dq_recovery,
            'dd_facts_recovered': sorted(recovery_dd)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    args = ap.parse_args()
    if not args.authorize:
        print(json.dumps({'mode': 'PLAN', 'runs': len(EVENTS)*len(ARMS)*REPS}))
        return

    OUT.mkdir(exist_ok=True)
    meter = Meter(ledger_path=OUT / 'ledger.jsonl', max_calls=200, max_guaranteed_actual=200000)
    adapter = R6Adapter(meter)
    results = []

    for ev_id in EVENTS:
        task, texts, silver_orig, silver_dd = load_event(ev_id)
        tid = TASK_IDS[ev_id]
        print(f"\n=== {ev_id} ({tid}) | orig={len(silver_orig)} dd={len(silver_dd)} ===")
        for rep in range(1, REPS + 1):
            for arm in ARMS:
                run_id = f'R6-{arm}-{tid}-r{rep}'
                try:
                    r = run_single(meter, adapter, run_id, arm, ev_id, texts, silver_orig, silver_dd)
                    results.append(r)
                    print(f"  {arm:20s} r{rep}: Qt={r['Q_terminal']:.3f} Qp={r['Q_prefix']:.3f} "
                          f"Qd={r['Q_downstream']:.3f} dQ={r['dQ_recovery']:.3f} {r['status'][:4]}")
                except BudgetExceeded:
                    results.append({'run_id': run_id, 'status': 'BUDGET_STOP'})
                    print(f"  BUDGET STOP")
                    json.dump({'runs': results, 'budget': meter.summary(), 'model_usage': model_usage},
                             open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
                    return

    json.dump({'runner': RUNNER, 'runs': results, 'budget': meter.summary(),
              'model_usage': model_usage},
             open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDone: {len(results)} runs")
    print(f"Calls: {meter.n_calls}/200 | Tokens: {meter.actual_tokens}/200000")
    print(f"GLM: {model_usage['glm53']} | Flash: {model_usage['glm53flash']}")

if __name__ == '__main__':
    main()
