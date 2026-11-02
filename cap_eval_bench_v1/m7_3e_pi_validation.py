"""M7-3E: π Model Reassignment Validation (REAL MODEL CALLS).

GO authorized: 140 calls / 126,360 tokens / ¥0. New ledger, hard stops.

Fixes ALL four C4 deficiencies:
  1. Real capability gap: flash genuinely produces lower-quality reports
     (PROFILE_Q gap=0.25 on report kind) — no artificial fault injection.
  2. Real engine decisions: Arm F uses m7_decision_engine.pi_switch_legal()
     to evaluate switching; other arms use simpler policies.
  3. Fair comparison: same tasks, same extracts, same report prompt,
     same scoring. Only the report model policy differs.
  4. Terminal evaluation: Q + completion + tokens + latency per run.

4 arms × 2 tasks × 3 reps = 24 runs.
"""
import json, random, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/q_foundation')
from pilot_common import Meter, BudgetExceeded, fenced_json

# NEW separate ledger for M7-3E
LEDGER = BENCH / 'm7_3e_runs' / 'LEDGER.jsonl'
LEDGER.parent.mkdir(exist_ok=True)
meter = Meter(ledger_path=str(LEDGER), max_calls=140,
              max_guaranteed_actual=126360)

texts_dir = BENCH / 'evidence' / 'texts'
tasks = {}
for tid in ['E04-zhuoran', 'E06-huanrui']:
    docs = sorted(texts_dir.glob(f'{tid}_*.txt'))
    tasks[tid] = {d.stem: d.read_text() for d in docs}

refs = json.load(open('/root/q_foundation/M7_3D_REFERENCE_FACTS.json'))
refs_by_task = {r['task_id']: r for r in refs}

# Import decision engine for Arm F
import m7_decision_engine as ENGINE

PROFILE_Q = {
    'extracts':  {'glm53': 0.85, 'glm53flash': 0.62},
    'report':    {'glm53': 0.85, 'glm53flash': 0.60},
}
PERSISTENCE = (('contract','persistent'),('parse','transient'),('transport','transient'))

V2_EXTRACT = """从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实。
每个日期必须标注其语义角色（date_role）。
输出JSON:
{"key_facts": [{"fact_type": "filing_date", "value": "YYYY-MM-DD",
  "date_role": "披露日期|收到日期", "source_document": "doc_id",
  "evidence_quote": "原文引用", "confidence_status": "SUPPORTED"}],
 "unknown_facts": []}
要求：区分披露日期与收到日期；无足够依据返回UNKNOWN；key_facts必须存在。
文档：
"""

REPORT_PROMPT = """基于以下多文档提取结果，综合回答：
1. 立案告知书披露日期（在交易所网站发布公告的日期）？
2. 行政处罚告知书收到日期？
3. 主要风险是什么？（要求综合所有文档信息，100字以内）

{extracts}

JSON: {{"filing_date": "YYYY-MM-DD或null", "penalty_date": "YYYY-MM-DD或null", "main_risk": "..."}}"""


def extract_node(node_id, doc_id, doc_text, purpose):
    """Extract facts using flash (same for ALL arms — no capability gap here)."""
    prompt = V2_EXTRACT + doc_text[:1500]
    system = "资本市场文档分析助手。"
    rec, text = meter.call('glm53flash', system, prompt, max_tokens=500,
                           purpose=purpose, timeout_s=60)
    return text


def report_node(extracts, model, purpose):
    """Generate report. Model choice is the KEY DIFFERENCE between arms."""
    extract_text = '\n'.join(f'[ext_{i}] {t[:250]}' for i, t in enumerate(extracts))
    prompt = REPORT_PROMPT.format(extracts=extract_text)
    system = "资本市场分析助手。请综合多文档信息回答。"
    t0 = time.monotonic()
    rec, text = meter.call(model, system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    latency = time.monotonic() - t0
    return text, rec, latency


def engine_decides_switch(report_text, task_id, arm):
    """Arm F: Use the REAL decision engine to evaluate switching.
    
    Constructs an EngineState from actual execution results and calls
    pi_switch_legal() — no hardcoded decisions.
    """
    # Parse the flash report to check quality
    try:
        parsed = fenced_json(report_text)
        has_filing = parsed.get('filing_date') is not None
        has_penalty = parsed.get('penalty_date') is not None
        has_risk = bool(parsed.get('main_risk'))
        quality_score = sum([has_filing, has_penalty, has_risk])
    except Exception:
        quality_score = 0  # parse failure = worst quality
    
    # Build a Node representing the report node's actual state
    # The report was attempted with flash (weak model)
    node = ENGINE.Node(
        node_id='report', kind='report',
        parents=('ext_0', 'ext_1', 'ext_2'),
        model='glm53flash', status='failed' if quality_score < 2 else 'done',
        attempts=1,
        last_failure_type='parse' if quality_score == 0 else None,
        failure_signature_seen=quality_score == 0,
    )
    
    # Build EngineState
    state = ENGINE.EngineState(
        task_id=task_id, dag_version=1,
        nodes=(node,),
        edges=(),
        budget_remaining=126360 - meter.actual_tokens,
        deadline_remaining_s=600.0,
        slots_total=(('glm53', 2), ('glm53flash', 2)),
        slots_in_use=(),
        persistence_table=PERSISTENCE,
        profile_q=tuple((k, tuple(v.items())) for k, v in PROFILE_Q.items()),
    )
    
    # Call the REAL engine's pi_switch_legal
    can_switch, reasons = ENGINE.pi_switch_legal(node, state)
    return can_switch, reasons, quality_score


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


def run_experiment(arm, task_id, rep):
    """Execute one arm on one task. Returns complete run record."""
    run_id = f'M7-3E-{arm}-{task_id}-r{rep}'
    task_docs = tasks[task_id]
    task_ref = refs_by_task[task_id]
    doc_ids = sorted(task_docs.keys())
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens
    start_time = time.monotonic()
    
    # Phase 1: Extract (ALL arms use flash — same, fair)
    extracts = []
    for i, did in enumerate(doc_ids):
        text = extract_node(f'ext_{i}', did, task_docs[did],
                           f'{run_id}:ext_{i}')
        extracts.append(text[:300])
    
    # Phase 2: Report (THE KEY DIFFERENCE)
    report_model = 'glm53flash'  # default: weak model
    report_reason = 'default: flash'
    engine_decision = None
    switch_reasons = None
    flash_quality = None
    
    if arm == 'A':
        # Static: always flash, never switch
        report_model = 'glm53flash'
        report_reason = 'A(Static): keep flash'
        
    elif arm == 'D':
        # π-only: always try flash first, then switch to glm53
        # (simple policy: if flash quality < 2/3, switch)
        flash_text, flash_rec, flash_lat = report_node(
            extracts, 'glm53flash', f'{run_id}:report_flash')
        try:
            fp = fenced_json(flash_text)
            flash_quality = sum([fp.get('filing_date') is not None,
                                fp.get('penalty_date') is not None,
                                bool(fp.get('main_risk'))])
        except:
            flash_quality = 0
        
        if flash_quality < 2:
            report_model = 'glm53'
            report_reason = f'D(π-only): flash quality={flash_quality}/3, switch to glm53'
        else:
            report_model = 'glm53flash'
            report_reason = f'D(π-only): flash quality={flash_quality}/3, keep flash'
            
    elif arm == 'E':
        # Fixed Best: always glm53 from start
        report_model = 'glm53'
        report_reason = 'E(FixedBest): always glm53'
        
    elif arm == 'F':
        # Engine: try flash first, then let the REAL engine decide
        flash_text, flash_rec, flash_lat = report_node(
            extracts, 'glm53flash', f'{run_id}:report_flash')
        try:
            fp = fenced_json(flash_text)
            flash_quality = sum([fp.get('filing_date') is not None,
                                fp.get('penalty_date') is not None,
                                bool(fp.get('main_risk'))])
        except:
            flash_quality = 0
        
        # Call the REAL decision engine
        can_switch, reasons, quality = engine_decides_switch(
            flash_text, task_id, arm)
        engine_decision = can_switch
        switch_reasons = reasons
        
        if can_switch:
            report_model = 'glm53'
            report_reason = f'F(Engine): engine says switch ({"; ".join(reasons[:2])})'
        else:
            report_model = 'glm53flash'
            report_reason = f'F(Engine): engine says keep ({"; ".join(reasons[:2])})'
    
    # Execute the decided report model
    # (For arms A/E: this is the first report call)
    # (For arms D/F: this may be a second call after flash attempt)
    if arm in ('D', 'F'):
        # If switching, use glm53; if keeping, reuse flash result
        if report_model == 'glm53flash' and flash_quality is not None:
            # Engine/D decided to keep flash — reuse the flash result
            final_text = flash_text
            final_rec = flash_rec
            final_lat = flash_lat
        else:
            # Switch to glm53
            final_text, final_rec, final_lat = report_node(
                extracts, report_model, f'{run_id}:report_final')
    else:
        # Arms A/E: single report call
        final_text, final_rec, final_lat = report_node(
            extracts, report_model, f'{run_id}:report')
    
    # Score
    try:
        parsed = fenced_json(final_text)
    except:
        parsed = {}
    correct, total = score(parsed, task_ref)
    
    end_time = time.monotonic()
    tokens = meter.actual_tokens - start_tokens
    calls = meter.n_calls - start_calls
    makespan = end_time - start_time
    
    record = {
        'run_id': run_id, 'arm': arm, 'task': task_id, 'rep': rep,
        'status': 'COMPLETE',
        'report_model': report_model, 'report_reason': report_reason,
        'engine_decision': engine_decision, 'switch_reasons': switch_reasons,
        'flash_quality': flash_quality,
        'Q': correct, 'Q_total': total,
        'calls': calls, 'tokens': tokens, 'makespan_s': round(makespan, 2),
        'parsed': parsed,
    }
    print(f'  {arm:4} {task_id[:10]:12} r{rep} Q={correct}/{total} '
          f'model={report_model:12} {calls}c {tokens}t {makespan:.1f}s')
    if engine_decision is not None:
        print(f'       engine_switch={engine_decision} reasons={switch_reasons}')
    return record


def main():
    all_runs = []
    ARMS = ['A', 'D', 'E', 'F']
    TASKS = ['E04-zhuoran', 'E06-huanrui']
    
    plan = [(a, t, r) for a in ARMS for t in TASKS for r in [1, 2, 3]]
    random.seed(55)
    random.shuffle(plan)
    
    print(f'M7-3E: {len(plan)} runs, budget 140 calls / 126,360 tokens')
    print(f'Ledger: {LEDGER}')
    
    try:
        for arm, task_id, rep in plan:
            if meter.n_calls >= 138:  # safety margin
                print(f'SAFETY STOP: {meter.n_calls} calls')
                break
            print(f'\n--- {arm}-{task_id}-r{rep} ---')
            run = run_experiment(arm, task_id, rep)
            all_runs.append(run)
    except BudgetExceeded as e:
        print(f'BUDGET STOP: {e}')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3E-PI-VALIDATION',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls,
            'total_tokens': meter.actual_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3e_runs' / 'RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        
        print(f'\n{"="*60}')
        print(f'M7-3E Results: {meter.n_calls}/140 calls, '
              f'{meter.actual_tokens}/126,360 tokens')
        print(f'Runs: {len(all_runs)}/{len(plan)}')
        print(f'{"="*60}')
        
        # Summary table
        print(f'\n{"Arm":5} {"Task":12} {"Rep":4} {"Q":5} {"Model":12} '
              f'{"Engine":7} {"Calls":6} {"Tokens":7} {"Make(s)":8}')
        print('-' * 70)
        for r in all_runs:
            print(f'{r["arm"]:5} {r["task"][:10]:12} r{r["rep"]} '
                  f'{r["Q"]}/{r["Q_total"]:3} {r["report_model"]:12} '
                  f'{str(r["engine_decision"])[:5]:7} '
                  f'{r["calls"]:4}   {r["tokens"]:5}   {r["makespan_s"]:6.1f}')
        
        # Key comparisons
        print('\n=== KEY COMPARISONS ===')
        for task in TASKS:
            task_runs = [r for r in all_runs if r['task'] == task]
            for arm in ARMS:
                arm_runs = [r for r in task_runs if r['arm'] == arm]
                if arm_runs:
                    avg_q = sum(r['Q'] for r in arm_runs) / len(arm_runs)
                    avg_tok = sum(r['tokens'] for r in arm_runs) / len(arm_runs)
                    avg_mk = sum(r['makespan_s'] for r in arm_runs) / len(arm_runs)
                    switches = sum(1 for r in arm_runs if r['report_model'] == 'glm53')
                    print(f'  {task[:10]} {arm}: avg_Q={avg_q:.2f}/{arm_runs[0]["Q_total"]} '
                          f'avg_tok={avg_tok:.0f} avg_mk={avg_mk:.1f}s '
                          f'switched={switches}/{len(arm_runs)}')


if __name__ == '__main__':
    main()
