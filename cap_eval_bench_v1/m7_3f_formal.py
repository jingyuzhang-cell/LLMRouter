"""M7-3F Formal: π Model Reassignment on Confirmed-Gap Reasoning Tasks.

GO authorized. Uses CALC-1 (numerical aggregation) + INF-1 (date reasoning)
where pre-experiment confirmed flash 44% vs glm53 89%.

4 arms × 2 questions × 3 reps = 24 runs (shared extracts reduce calls).
Real engine decisions for Arm F. Same extracts, same scoring, fair comparison.
"""
import json, random, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/q_foundation')
from pilot_common import Meter, BudgetExceeded, fenced_json
import m7_decision_engine as ENGINE

LEDGER = BENCH / 'm7_3e_runs' / 'LEDGER.jsonl'
meter = Meter(ledger_path=str(LEDGER), max_calls=140,
              max_guaranteed_actual=126360)

doc2 = open('evidence/texts/E04-zhuoran_20261009.txt').read()[:1500]

# Use ONLY the confirmed-gap questions
QUESTIONS = [
    {
        "id": "CALC-1",
        "kind": "reasoning",
        "prompt": f"""基于以下文档内容，计算：2021-2024年虚增利润总额合计是多少万元？

文档关键内容：
{doc2}

请逐步列出每年的虚增利润总额，然后计算合计。输出JSON:
{{"y2021": ..., "y2022": ..., "y2023": ..., "y2024": ..., "total": ...}}""",
        "check": lambda p: abs(float(p.get('total', 0)) - 28742.21) < 100,
    },
    {
        "id": "INF-1",
        "kind": "reasoning",
        "prompt": f"""基于以下文档内容，从收到立案告知书到收到行政处罚事先告知书间隔了多长时间（天数）？

文档关键内容：
{doc2}

注意：收到立案告知书日期是2025年12月19日，收到行政处罚事先告知书日期是2026年9月11日。
计算两个日期之间的天数。输出JSON: {{"start_date": "...", "end_date": "...", "interval_days": ...}}""",
        "check": lambda p: abs(int(float(str(p.get('interval_days',0)).replace('天',''))) - 266) < 10,
    },
]

PROFILE_Q = {'reasoning': {'glm53': 0.80, 'glm53flash': 0.58}}
PERSISTENCE = (('contract','persistent'),('parse','transient'),('transport','transient'))


def call_reasoning(model, q, purpose):
    system = "资本市场分析助手。请仔细计算并给出精确答案。"
    t0 = time.monotonic()
    rec, text = meter.call(model, system, q['prompt'],
                           max_tokens=400, purpose=purpose, timeout_s=60)
    lat = time.monotonic() - t0
    return text, rec, lat


def engine_decides(text, q):
    """Arm F: Real engine evaluates whether to switch."""
    try:
        parsed = fenced_json(text)
        correct = q['check'](parsed)
    except:
        correct = False
    
    # Build EngineState from actual result
    node = ENGINE.Node(
        node_id=q['id'], kind='reasoning',
        parents=(), model='glm53flash',
        status='done' if correct else 'failed',
        attempts=1,
        last_failure_type=None if correct else 'parse',
        failure_signature_seen=not correct,
    )
    state = ENGINE.EngineState(
        task_id='M7-3F', dag_version=1,
        nodes=(node,), edges=(),
        budget_remaining=126360 - meter.actual_tokens,
        deadline_remaining_s=600.0,
        slots_total=(('glm53', 2), ('glm53flash', 2)),
        slots_in_use=(),
        persistence_table=PERSISTENCE,
        profile_q=tuple((k, tuple(v.items())) for k, v in PROFILE_Q.items()),
    )
    can_switch, reasons = ENGINE.pi_switch_legal(node, state)
    return can_switch, reasons, correct


def run_arm(arm, q, rep):
    run_id = f'M7-3F-{arm}-{q["id"]}-r{rep}'
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens
    start_time = time.monotonic()
    
    final_model = 'glm53flash'  # default weak
    final_text = None
    engine_decision = None
    switch_reasons = None
    flash_correct = None
    
    if arm == 'A':
        # Static: always flash
        final_text, rec, lat = call_reasoning('glm53flash', q, f'{run_id}:flash')
        
    elif arm == 'D':
        # π-only: try flash, if wrong switch to glm53
        flash_text, frec, flat = call_reasoning('glm53flash', q, f'{run_id}:flash')
        try:
            fp = fenced_json(flash_text)
            flash_correct = q['check'](fp)
        except:
            flash_correct = False
        if not flash_correct:
            final_model = 'glm53'
            final_text, rec, lat = call_reasoning('glm53', q, f'{run_id}:switch')
        else:
            final_text = flash_text
            
    elif arm == 'E':
        # Fixed Best: always glm53
        final_model = 'glm53'
        final_text, rec, lat = call_reasoning('glm53', q, f'{run_id}:glm53')
        
    elif arm == 'F':
        # Engine: try flash, then let engine decide
        flash_text, frec, flat = call_reasoning('glm53flash', q, f'{run_id}:flash')
        can_switch, reasons, flash_correct = engine_decides(flash_text, q)
        engine_decision = can_switch
        switch_reasons = reasons
        if can_switch:
            final_model = 'glm53'
            final_text, rec, lat = call_reasoning('glm53', q, f'{run_id}:switch')
        else:
            final_text = flash_text
    
    # Score
    try:
        parsed = fenced_json(final_text)
        correct = q['check'](parsed)
    except:
        parsed = {}
        correct = False
    
    tokens = meter.actual_tokens - start_tokens
    calls = meter.n_calls - start_calls
    makespan = time.monotonic() - start_time
    
    record = {
        'run_id': run_id, 'arm': arm, 'question': q['id'], 'rep': rep,
        'status': 'COMPLETE',
        'final_model': final_model, 'correct': correct,
        'engine_decision': engine_decision, 'switch_reasons': switch_reasons,
        'flash_correct': flash_correct,
        'calls': calls, 'tokens': tokens, 'makespan_s': round(makespan, 2),
        'parsed': {k: str(v)[:50] for k, v in parsed.items()},
    }
    print(f'  {arm:4} {q["id"]:8} r{rep} {"✓" if correct else "✗"} '
          f'model={final_model:12} {calls}c {tokens}t {makespan:.1f}s'
          + (f' engine={"SWITCH" if engine_decision else "KEEP"}' if engine_decision is not None else ''))
    return record


def main():
    all_runs = []
    ARMS = ['A', 'D', 'E', 'F']
    
    plan = [(a, q, r) for a in ARMS for q in QUESTIONS for r in [1, 2, 3]]
    random.seed(66)
    random.shuffle(plan)
    
    print(f'M7-3F Formal: {len(plan)} runs')
    print(f'Budget: {meter.n_calls}/140 used, {meter.actual_tokens}/126360 used')
    
    try:
        for arm, q, rep in plan:
            if meter.n_calls >= 138:
                print(f'SAFETY STOP')
                break
            print(f'\n--- {arm}-{q["id"]}-r{rep} ---')
            run = run_arm(arm, q, rep)
            all_runs.append(run)
    except BudgetExceeded:
        print('BUDGET STOP')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3F-FORMAL',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls,
            'total_tokens': meter.actual_tokens,
            'runs': all_runs,
        }
        (BENCH / 'm7_3e_runs' / 'M7_3F_RESULTS.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=1))
        
        print(f'\n{"="*60}')
        print(f'M7-3F: {meter.n_calls}/140 calls, {meter.actual_tokens}/126360 tokens')
        print(f'Runs: {len(all_runs)}/{len(plan)}')
        print(f'{"="*60}')
        
        # Summary
        print(f'\n{"Arm":5} {"Q":8} {"Rep":4} {"✓/✗":4} {"Model":12} {"Engine":8} {"Tok":6} {"Sec":5}')
        print('-' * 58)
        for r in all_runs:
            print(f'{r["arm"]:5} {r["question"]:8} r{r["rep"]} '
                  f'{"✓" if r["correct"] else "✗":4} '
                  f'{r["final_model"]:12} '
                  f'{str(r["engine_decision"])[:5]:8} '
                  f'{r["tokens"]:4}  {r["makespan_s"]:4.1f}')
        
        # Key comparisons
        print('\n=== KEY COMPARISONS ===')
        for q in QUESTIONS:
            qid = q['id']
            print(f'\n{qid}:')
            for arm in ARMS:
                runs = [r for r in all_runs if r['arm']==arm and r['question']==qid]
                if runs:
                    correct = sum(1 for r in runs if r['correct'])
                    avg_tok = sum(r['tokens'] for r in runs) / len(runs)
                    avg_mk = sum(r['makespan_s'] for r in runs) / len(runs)
                    switches = sum(1 for r in runs if r['final_model']=='glm53')
                    print(f'  {arm}: {correct}/{len(runs)} correct '
                          f'avg_tok={avg_tok:.0f} avg_mk={avg_mk:.1f}s '
                          f'switched={switches}/{len(runs)}')


if __name__ == '__main__':
    main()
