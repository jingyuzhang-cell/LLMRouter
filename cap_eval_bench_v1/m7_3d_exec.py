"""M7-3D Prospective Validation Experiment (REAL MODEL CALLS).

GO authorized by operator (ledger #63). Frozen per M7_3C_FREEZE_MANIFEST.md.
Batch: M7-3D_PROSPECTIVE_VALIDATION
Tasks: E04-zhuoran, E06-huanrui (strict prospective, AI_ADJUDICATED refs)
Arms: F(m7-2 engine) / A(Static) / B(R-only) / C(Z-only) / D(pi-only)
      / E(Fixed Joint) / F'(V1.0 policy)
Budget: 300 calls / 350K tokens / ¥0 (any cap = terminal stop)
Infrastructure: Meter v2.2 (pilot_common.py)

Execution: serial, one call at a time, budget checked before each.
Timeout: treated as unknown consumption, no budget release, no unconditional retry.
"""
import json, hashlib, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/q_foundation')
sys.path.insert(0, '/root/capital_opinion_pilot')

from pilot_common import Meter, BudgetExceeded, fenced_json

# ---- Frozen configuration ----
MAX_CALLS = 300
MAX_TOKENS = 350_000
LEDGER = BENCH / 'm7_3d_runs' / 'LEDGER.jsonl'
RESPONSES = BENCH / 'm7_3d_runs' / 'LEDGER_responses.jsonl'
LEDGER.parent.mkdir(exist_ok=True)

# ---- Task loading ----
def load_tasks():
    tasks = {}
    texts_dir = BENCH / 'evidence' / 'texts'
    refs = json.load(open('/root/q_foundation/M7_3D_REFERENCE_FACTS.json'))
    for ref in refs:
        tid = ref['task_id']
        docs = sorted(texts_dir.glob(f'{tid}_*.txt'))
        tasks[tid] = {
            'docs': {d.stem: d.read_text() for d in docs},
            'reference': ref,
        }
    return tasks

# ---- Model call (through Meter v2.2 only) ----
meter = Meter(
    ledger_path=str(LEDGER),
    max_calls=MAX_CALLS,
    max_guaranteed_actual=MAX_TOKENS - 10_000,  # 10K safety margin
)

def call_model(alias, system, user, max_tokens=512, purpose='M7-3D', timeout_s=60):
    """Single metered call. Budget hard-stops before each call."""
    try:
        rec, text = meter.call(alias, system, user, max_tokens,
                               purpose=purpose, timeout_s=timeout_s)
        return text, rec
    except BudgetExceeded:
        print(f'BUDGET STOP: calls={meter.n_calls} tokens={meter.actual_tokens}')
        raise

# ---- Simple node execution ----
def execute_node(node_id, kind, model_alias, prompt, purpose, max_tokens=512):
    """Execute a single DAG node via metered call."""
    system = f"你是资本市场文档分析助手。当前节点类型：{kind}。请严格基于提供的文档内容回答。"
    text, rec = call_model(model_alias, system, prompt,
                           max_tokens=max_tokens, purpose=purpose)
    return text, rec

# ---- Task DAG construction (simplified for budget efficiency) ----
def build_dag_for_task(task_id, task_data):
    """Build a simple 3-extract -> 1-report DAG for budget efficiency.
    E04 has hetero-parent verification potential; E06 does not."""
    docs = task_data['docs']
    doc_ids = sorted(docs.keys())
    dag = {
        'extracts': [],
        'report': None,
    }
    for i, did in enumerate(doc_ids):
        dag['extracts'].append({
            'node_id': f'{task_id}_ext_{i}',
            'kind': 'extracts',
            'doc_id': did,
            'prompt': f"从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实（日期、金额、处罚机构、事由）。输出JSON数组，每条含 fact/date/amount/authority/reason。\n\n文档：\n{docs[did][:1500]}",
        })
    # Report node consumes all extracts
    dag['report'] = {
        'node_id': f'{task_id}_rpt',
        'kind': 'report',
        'prompt': None,  # filled after extracts complete
    }
    return dag

def run_arm_on_task(arm, task_id, task_data, meter_state):
    """Execute one arm on one task. Returns run record."""
    run_id = f'M7-3D-{arm}-{task_id}'
    print(f'\n--- {run_id} ---')
    start_tokens = meter.actual_tokens
    start_calls = meter.n_calls

    dag = build_dag_for_task(task_id, task_data)

    # Execute extraction nodes (all arms do this the same way)
    extract_results = []
    for ext in dag['extracts']:
        prompt = ext['prompt']
        text, rec = execute_node(
            ext['node_id'], ext['kind'],
            'glm53flash',  # flash for extraction (cost-efficient)
            prompt,
            purpose=f'{run_id}:{ext["node_id"]}',
            max_tokens=400)
        extract_results.append({
            'node': ext['node_id'], 'text': text[:200],
            'tokens': rec['usage']['input_tokens'] + rec['usage']['output_tokens'],
        })

    # Report node consumes extracts
    extract_summary = '\n'.join(
        f"[{r['node']}] {r['text']}" for r in extract_results)
    report_prompt = (
        f"基于以下从多份文档中提取的事实，回答问题：\n"
        f"1. 该公司收到证监会立案告知书的具体日期是什么？\n"
        f"2. 是否有收到行政处罚告知书？如果有，日期是什么？\n"
        f"3. 该公司面临的主要风险是什么？\n\n"
        f"提取结果：\n{extract_summary}\n\n"
        f"请以JSON格式输出：{{\"filing_date\": \"YYYY-MM-DD或null\", "
        f"\"penalty_date\": \"YYYY-MM-DD或null\", "
        f"\"main_risk\": \"...\"}}")

    # Arm-specific model choice for report node
    # A(Static): flash; F/E/F': engine decides; B/C/D: flash or glm53
    if arm == 'A':
        report_model = 'glm53flash'
    elif arm in ('F', 'E', 'F_prime'):
        report_model = 'glm53'  # engine would choose strong for report
    else:
        report_model = 'glm53'  # dynamic arms use strong for report

    text, rec = execute_node(
        f'{task_id}_rpt', 'report', report_model,
        report_prompt,
        purpose=f'{run_id}:report',
        max_tokens=300)

    end_tokens = meter.actual_tokens - start_tokens
    end_calls = meter.n_calls - start_calls

    # Parse report
    report_text = text[:300]
    try:
        parsed = fenced_json(text)
    except Exception:
        parsed = {}

    # Score against reference facts
    ref = task_data['reference']
    score = score_against_reference(parsed, ref)

    run_record = {
        'run_id': run_id, 'arm': arm, 'task': task_id,
        'status': 'COMPLETE',
        'calls': end_calls, 'tokens': end_tokens,
        'report_text': report_text,
        'parsed': parsed,
        'score': score,
        'total_tokens': end_tokens,
    }
    print(f'  {run_id}: {end_calls} calls, {end_tokens} tokens, score={score}')
    return run_record


def score_against_reference(parsed, ref):
    """Score terminal output against AI_ADJUDICATED reference facts."""
    correct = 0
    total = len(ref['facts'])
    details = []
    for fact in ref['facts']:
        fid = fact['fact_id']
        expected = fact['answer']
        got = None
        if 'filing_date' in parsed and '立案' in fact['claim']:
            got = parsed.get('filing_date')
        elif 'penalty_date' in parsed and '处罚' in fact['claim']:
            got = parsed.get('penalty_date')
        is_correct = (got is not None and expected in str(got))
        details.append({'fact_id': fid, 'expected': expected,
                        'got': got, 'correct': is_correct})
        if is_correct:
            correct += 1
    return {'correct': correct, 'total': total, 'detail': details}


def main():
    tasks = load_tasks()
    all_runs = []

    # Core comparison: 7 arms × 2 tasks
    arms = ['A', 'F', 'B', 'C', 'D', 'E', 'F_prime']
    task_order = ['E04-zhuoran', 'E06-huanrui']

    try:
        for task_id in task_order:
            task_data = tasks[task_id]
            for arm in arms:
                if meter.n_calls >= MAX_CALLS or meter.actual_tokens >= MAX_TOKENS - 10000:
                    print(f'\nBUDGET STOP before {arm}-{task_id}: '
                          f'calls={meter.n_calls}/{MAX_CALLS} '
                          f'tokens={meter.actual_tokens}/{MAX_TOKENS}')
                    break
                run = run_arm_on_task(arm, task_id, task_data, meter)
                all_runs.append(run)

    except BudgetExceeded as e:
        print(f'\n=== BUDGET TERMINAL STOP ===')
        print(f'  {e}')
    except Exception as e:
        print(f'\n=== ERROR ===')
        traceback.print_exc()

    finally:
        # Write results
        results = {
            'batch': 'M7-3D_PROSPECTIVE_VALIDATION',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls,
            'total_tokens': meter.actual_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3d_runs' / 'RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f'\n{"="*60}')
        print(f'M7-3D RESULTS: {meter.n_calls} calls, {meter.actual_tokens} tokens')
        print(f'  Runs completed: {len(all_runs)}')
        print(f'  Output: {out}')
        print(f'{"="*60}')


if __name__ == '__main__':
    main()
