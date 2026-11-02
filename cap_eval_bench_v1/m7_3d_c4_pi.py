"""M7-3D C4: π Capability Gap Experiment (REAL MODEL CALLS).

GO authorized. Tests PI_2' mechanism: parse fault at weak model node →
switch to strong model → does terminal quality improve?

7 arms × 2 tasks (E04+E06) × 2 reps. Uses Extract V2 contract (date_role).
"""
import json, random, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import Meter, BudgetExceeded, fenced_json

LEDGER = BENCH / 'm7_3d_runs' / 'LEDGER.jsonl'
meter = Meter(ledger_path=str(LEDGER), max_calls=434,
              max_guaranteed_actual=340_000)

texts_dir = BENCH / 'evidence' / 'texts'
tasks = {}
for tid in ['E04-zhuoran', 'E06-huanrui']:
    docs = sorted(texts_dir.glob(f'{tid}_*.txt'))
    tasks[tid] = {d.stem: d.read_text() for d in docs}

refs = json.load(open('/root/q_foundation/M7_3D_REFERENCE_FACTS.json'))
refs_by_task = {r['task_id']: r for r in refs}

V2_EXTRACT = """从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实。
每个日期必须标注其语义角色（date_role）。
输出JSON:
{
  "key_facts": [
    {"fact_type": "filing_date", "value": "YYYY-MM-DD", "date_role": "披露日期|收到日期",
     "source_document": "doc_id", "evidence_quote": "原文引用", "confidence_status": "SUPPORTED"}
  ],
  "unknown_facts": []
}
要求：区分披露日期与收到日期；无足够依据返回UNKNOWN；key_facts必须存在。
文档：
{doc}"""

def extract_v2(node_id, doc_id, doc_text, model, purpose, inject_parse_fault=False):
    prompt = V2_EXTRACT.replace('{doc}', doc_text[:1500])
    system = "资本市场文档分析助手。"
    rec, text = meter.call(model, system, prompt, max_tokens=500,
                           purpose=purpose, timeout_s=60)
    if inject_parse_fault:
        return None, rec
    return text, rec

def report(extract_texts, model, purpose):
    extracts = '\n'.join(f'[ext_{i}] {t[:250]}' for i, t in enumerate(extract_texts))
    prompt = (f"基于以下提取结果回答：\n1. 立案告知书披露日期？\n2. 行政处罚告知书收到日期？\n"
              f"3. 主要风险？\n\n{extracts}\n\n"
              f"JSON: {{\"filing_date\":\"YYYY-MM-DD或null\",\"penalty_date\":\"YYYY-MM-DD或null\",\"main_risk\":\"...\"}}")
    system = "资本市场分析助手。"
    rec, text = meter.call(model, system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    return text, rec

def score(parsed, task_ref):
    correct = 0
    for fact in task_ref['facts']:
        got = None
        if '立案' in fact['claim'] and '披露' in fact['claim']:
            got = str(parsed.get('filing_date', ''))
        elif '处罚' in fact['claim']:
            got = str(parsed.get('penalty_date', ''))
        if got and fact['answer'] in got:
            correct += 1
    return correct, len(task_ref['facts'])

def run_c4(arm, task_id, rep):
    run_id = f'M7-3D-C4-{arm}-{task_id}-r{rep}'
    task_docs = tasks[task_id]
    task_ref = refs_by_task[task_id]
    doc_ids = sorted(task_docs.keys())
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens
    
    # Phase 1: Extract with V2 contract
    # Fault injection: parse fault on doc 1's first attempt (weak model = flash)
    extracts = []
    for i, did in enumerate(doc_ids):
        nid = f'{task_id[:3].lower()}_ext_{i}'
        inject = (i == 1)  # inject at second extract node
        text, rec = extract_v2(nid, did, task_docs[did], 'glm53flash',
                               f'{run_id}:{nid}', inject_parse_fault=inject)
        if text is None:
            # Parse fault occurred — arms respond differently
            if arm in ('B', 'E', 'F'):
                # Retry same model (R mechanism)
                text, rec = extract_v2(nid, did, task_docs[did], 'glm53flash',
                                       f'{run_id}:{nid}:v2')
                extracts.append(text[:250] if text else 'RETRY_FAIL')
            elif arm == 'D':
                # π-only: switch to strong model
                text, rec = extract_v2(nid, did, task_docs[did], 'glm53',
                                       f'{run_id}:{nid}:switch')
                extracts.append(text[:250] if text else 'SWITCH_FAIL')
            elif arm == 'F_prime':
                # V1.0: switch on any fault + gap
                text, rec = extract_v2(nid, did, task_docs[did], 'glm53',
                                       f'{run_id}:{nid}:switch')
                extracts.append(text[:250] if text else 'SWITCH_FAIL')
            else:
                # A (Static) and C (Z-only): no retry, no switch
                extracts.append('FAILED')
        else:
            extracts.append(text[:250])

    # Phase 2: Report (strong model for dynamic arms)
    report_model = 'glm53' if arm != 'A' else 'glm53flash'
    report_text, _ = report(extracts, report_model, f'{run_id}:report')
    
    try:
        parsed = fenced_json(report_text)
    except:
        parsed = {}
    
    correct, total = score(parsed, task_ref)
    any_failed = any(e in ('FAILED', 'RETRY_FAIL', 'SWITCH_FAIL') for e in extracts)
    status = 'INCOMPLETE' if any_failed else 'COMPLETE'
    tokens = meter.actual_tokens - start_tokens
    calls = meter.n_calls - start_calls
    
    record = {
        'run_id': run_id, 'arm': arm, 'condition': 'C4', 'task': task_id,
        'rep': rep, 'status': status, 'calls': calls, 'tokens': tokens,
        'score_correct': correct, 'score_total': total,
        'parsed': parsed, 'report_text': report_text[:200],
    }
    print(f'  {arm:8} {task_id[:10]:12} r{rep} {status:10} Q={correct}/{total} '
          f'{calls}c {tokens}t')
    return record

def main():
    all_runs = []
    ARMS = ['A', 'B', 'C', 'D', 'E', 'F', 'F_prime']
    TASKS = ['E04-zhuoran', 'E06-huanrui']
    
    # Randomize order
    plan = [(a, t, r) for a in ARMS for t in TASKS for r in [1, 2]]
    random.seed(44)
    random.shuffle(plan)
    
    try:
        for arm, task_id, rep in plan:
            run = run_c4(arm, task_id, rep)
            all_runs.append(run)
    except BudgetExceeded:
        print('BUDGET STOP')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3D-C4-PI', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls, 'total_tokens': meter.actual_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3d_runs' / 'C4_RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        
        print(f'\n{"="*60}')
        print(f'C4 Results: {meter.n_calls}/300 calls, {meter.actual_tokens}/350K tokens')
        print(f'Runs: {len(all_runs)}')
        print(f'{"="*60}')
        
        print(f'\n{"Arm":8} {"E04-r1":10} {"E04-r2":10} {"E06-r1":10} {"E06-r2":10}')
        print('-' * 55)
        for arm in ARMS:
            cells = []
            for task in TASKS:
                for rep in [1, 2]:
                    r = next((x for x in all_runs if x['arm']==arm and x['task']==task and x['rep']==rep), None)
                    if r:
                        cells.append(f'{r["status"][:4]}:{r["score_correct"]}/{r["score_total"]}')
                    else:
                        cells.append('N/A')
            print(f'{arm:8} {cells[0]:10} {cells[1]:10} {cells[2]:10} {cells[3]:10}')
        
        # Key comparison: D (π-only switches) vs A (Static no switch)
        print('\n=== KEY: π switch benefit (D vs A) ===')
        for task in TASKS:
            for rep in [1, 2]:
                d = next((x for x in all_runs if x['arm']=='D' and x['task']==task and x['rep']==rep), None)
                a = next((x for x in all_runs if x['arm']=='A' and x['task']==task and x['rep']==rep), None)
                if d and a:
                    print(f'{task} r{rep}: D={d["status"][:4]} Q={d["score_correct"]}/{d["score_total"]} '
                          f'vs A={a["status"][:4]} Q={a["score_correct"]}/{a["score_total"]}')

if __name__ == '__main__':
    main()
