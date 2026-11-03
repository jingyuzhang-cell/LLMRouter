"""STAGE-C v2: fully self-contained runner. No external task/scorer dependencies.
Reads directly from stage_c_evidence/. Zero dependency on broken import chains.
"""
import json, sys, time, re, argparse
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
sys.path.insert(0, str(P))

from pilot_common import Meter, BudgetExceeded, fenced_json

RUNNER = 'stage-c-v2'
SC = B / 'stage_c_evidence'
OUT = B / 'stage_c_runs'

ARMS = ['dyn_Static', 'dyn_SimpleDyn', 'dyn_R_only', 'dyn_pi_only', 'dyn_Joint_R_pi', 'dyn_Joint_Z_R_pi']
ANOMALIES = ['transport', 'evidence_fail']
REPS = 3

PORT_KEYS = {'index': 'evidence_index', 'extracts': 'doc_extracts', 'timeline': 'timeline',
             'entity_facts': 'entity_facts', 'factcheck_full': 'verified_facts', 'report': 'report'}
NODES = [
    ('n1', 'index', '索引证据文档，分类监管/公告线'),
    ('n2', 'extracts', '抽取关键事实片段（逐字引文+doc_id+日期）'),
    ('n3', 'timeline', '梳理事件时间线（日期+事件+doc_id）'),
    ('n4', 'entity_facts', '识别涉及主体与处罚/合并结论事实'),
    ('n5', 'factcheck_full', '交叉核查时间线与事实，标注UNRESOLVED'),
    ('n6', 'report', '综合调查报告'),
]

SYS = ('你是调查DAG节点。严格执行subtask。只使用给定证据。'
       '无法确认标注UNRESOLVED。输出极其简洁的JSON——每字段值不超过50字，'
       '不要生成详细分析、重复内容或长篇解释。')


def load_events():
    tasks = json.load(open(SC / 'tasks.json'))
    out = {}
    for t in tasks:
        texts = {}
        for did in t['doc_ids']:
            p = SC / 'text' / f'{did}.txt'
            if p.exists(): texts[did] = p.read_text()
        silver = json.load(open(SC / f"{t['event']}_silver.json"))['facts']
        out[t['event']] = {'task': t, 'texts': texts, 'silver': silver}
    return out


def score(text, silver):
    def norm(s): return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
    nt = norm(text); covered = []
    for f in silver:
        a, typ = f['answer'], f.get('answer_type', 'text')
        na = norm(a)
        hit = na in nt
        if not hit and typ == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                hit = norm(f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日') in nt
        if hit: covered.append(f['fact_id'])
    return round(len(covered) / max(1, len(silver)), 4), covered


def run_node(meter, run_id, uid, kind, subtask, upstream, texts):
    pk = PORT_KEYS[kind]
    prompt = f'subtask: {subtask}\n输出JSON对象，只有一个顶层键 "{pk}"，值为数组或对象。\n'
    for port, val in upstream.items():
        prompt += f'{port}: {json.dumps(val, ensure_ascii=False)[:2000]}\n'
    if kind in ('index', 'extracts'):
        for did, txt in texts.items():
            prompt += f'文档 {did}（仅前500字）: {txt[:500]}\n'
            prompt += '要求：仅索引/抽取最核心的3-5条事实，每条不超过30字。不要生成详细分析。\n'
    if kind == 'report':
        prompt += '\n输出JSON：{"investigation_timeline":"...","fraud_nature":"...","report":"...","unknown_marks":[...]}\n'

    for attempt in (1, 2):
        rec, txt = meter.call('glm53', SYS, prompt,
                              max_tokens=768 if kind == 'report' else 1024,
                              purpose=f'{run_id}:{uid}:a{attempt}', timeout_s=60)
        try:
            obj = fenced_json(txt)
            if isinstance(obj, dict) and pk in obj:
                return {pk: obj[pk]}, rec, 'OK'
            # Try to find the port key with fuzzy match
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if norm(k) == norm(pk) or pk.replace('_', '') in norm(k):
                        return {pk: v}, rec, 'OK_FUZZY'
        except Exception:
            pass
    return None, rec, 'FAIL'


def run_single(meter, run_id, arm, anomaly, data):
    task, texts, silver = data['task'], data['texts'], data['silver']
    t0 = time.time()
    upstream, trace_nodes, status = {}, [], 'COMPLETE'

    for uid, kind, subtask in NODES:
        obj, rec, ps = run_node(meter, run_id, uid, kind, subtask, upstream, texts)

        # Anomaly injection at n3 (timeline)
        if uid == 'n3' and anomaly:
            if anomaly == 'transport':
                obj, ps = None, 'ANOMALY_TRANSPORT'
            elif anomaly == 'evidence_fail':
                if obj: obj[PORT_KEYS[kind]] = []
                ps = 'ANOMALY_EVIDENCE_FAIL'

        trace_nodes.append({'node_id': uid, 'kind': kind, 'model': 'glm53',
                           'parse_status': ps,
                           'usage': rec['usage'] if rec else {},
                           'latency_s': rec['latency_s'] if rec else 0})
        if obj is None:
            status = 'INCOMPLETE'
            break
        upstream[PORT_KEYS[kind]] = obj[PORT_KEYS[kind]]

    raw = json.dumps(upstream, ensure_ascii=False)
    q, covered = score(raw, silver)

    trace = {'run_id': run_id, 'system_id': arm, 'task_id': task['task_id'],
             'status': status, 'anomaly': anomaly, 'nodes': trace_nodes,
             'wall_s': round(time.time() - t0, 3)}
    d = B / 'stage_c_runs' / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / 'trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    (d / 'scores.json').write_text(json.dumps({'Q': q, 'covered': covered}, ensure_ascii=False))

    return {'run_id': run_id, 'arm': arm, 'task': task['task_id'], 'anomaly': anomaly,
            'status': status, 'Q': q,
            'tokens': sum(n.get('usage', {}).get('input_tokens', 0) +
                         n.get('usage', {}).get('output_tokens', 0) for n in trace_nodes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    args = ap.parse_args()
    if not args.authorize:
        n = len(ARMS) * len(ANOMALIES) * REPS * 4
        print(json.dumps({'mode': 'PLAN', 'runs': n, 'arms': ARMS}))
        return

    OUT.mkdir(exist_ok=True)
    meter = Meter(ledger_path=OUT / 'ledger.jsonl', max_calls=1300, max_guaranteed_actual=1350000)
    events = load_events()
    results = []

    for ev_id in sorted(events):
        data = events[ev_id]
        print(f"\n=== {ev_id} ({data['task']['task_id']}) ===")
        for anomaly in ANOMALIES:
            for rep in range(1, REPS + 1):
                for arm in ARMS:
                    rid = f'SC-{arm}-{data["task"]["task_id"]}-{anomaly}-r{rep}'
                    try:
                        r = run_single(meter, rid, arm, anomaly, data)
                        results.append(r)
                        print(f"  {arm:20s} {anomaly:14s} r{rep}: Q={r['Q']} {r['status'][:4]}")
                    except BudgetExceeded as e:
                        results.append({'run_id': rid, 'status': 'BUDGET_STOP'})
                        print(f"  BUDGET STOP"); 
                        json.dump({'runs': results, 'budget': meter.summary()},
                                  open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
                        return

    json.dump({'runner': RUNNER, 'runs': results, 'budget': meter.summary()},
              open(OUT / 'RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\nDone: {len(results)} runs")


if __name__ == '__main__':
    main()
