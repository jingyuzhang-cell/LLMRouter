"""M7-3F P2: Five-Arm π Validation with Quality Feedback (REAL MODEL CALLS).

GO authorized: 110 calls / 102,000 tokens / ¥0. New ledger.

Five arms on confirmed-gap reasoning tasks (CALC-1, INF-1):
  A(Static-Flash)  D(Validator-π)  E(FixedBest)  F(PI_2')  G(PI_2'-Q)

Uses P0 quality_verifier + P1 DAG chain framework.
"""
import json, random, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/q_foundation')
from pilot_common import Meter, BudgetExceeded, fenced_json
from m7_3f_p1_dag_chain import run_verifier_node, run_engine_node
import m7_decision_engine as ENGINE

LEDGER = BENCH / 'm7_3f_p2_runs' / 'LEDGER.jsonl'
LEDGER.parent.mkdir(exist_ok=True)
meter = Meter(ledger_path=str(LEDGER), max_calls=110,
              max_guaranteed_actual=102000)

# Source evidence
doc2 = open('evidence/texts/E04-zhuoran_20261009.txt').read()[:1500]

QUESTIONS = [
    {
        "id": "CALC-1",
        "prompt": f"""基于以下文档内容，计算：2021-2024年虚增利润总额合计是多少万元？

文档关键内容：
{doc2}

请逐步列出每年的虚增利润总额，然后计算合计。输出JSON:
{{"y2021": ..., "y2022": ..., "y2023": ..., "y2024": ..., "total": ...}}""",
        "calc_contract": {
            "claim_id": "CALC_001", "required_fields": ["total"],
            "operation": "sum",
            "source_numbers": [
                {"context": "2021 年年度报告虚增利润总额"},
                {"context": "2022 年年度报告虚增利润总额"},
                {"context": "2023 年年度报告虚增营业收入::skip_1"},
                {"context": "2024 年年度报告虚增营业收入::skip_1"},
            ],
            "output_field": "total", "tolerance": 100,
        },
        "correct": 28742.21,
        "check": lambda p: abs(float(p.get('total', 0)) - 28742.21) < 100,
    },
    {
        "id": "INF-1",
        "prompt": f"""基于以下文档内容，从收到立案告知书到收到行政处罚事先告知书间隔了多长时间（天数）？

文档关键内容：
{doc2}

注意：收到立案告知书日期是2025年12月19日，收到行政处罚事先告知书日期是2026年9月11日。
计算两个日期之间的天数。输出JSON: {{"start_date": "...", "end_date": "...", "interval_days": ...}}""",
        "calc_contract": {
            "claim_id": "INF_001",
            "required_fields": ["start_date", "end_date", "interval_days"],
            "operation": "difference_days", "tolerance_days": 2,
        },
        "correct": 266,
        "check": lambda p: abs(int(float(str(p.get('interval_days', 0)).replace('天',''))) - 266) < 10,
    },
]

ARMS = ['A', 'D', 'E', 'F', 'G']
REPS = 5


def reasoning_call(model, q, purpose):
    system = "资本市场分析助手。请仔细计算并给出精确答案。"
    t0 = time.monotonic()
    rec, text = meter.call(model, system, q['prompt'],
                           max_tokens=400, purpose=purpose, timeout_s=60)
    lat = time.monotonic() - t0
    return text, rec, lat


def report_call(reasoning_output, purpose):
    system = "请基于以下计算结果，给出简洁的最终答案。"
    prompt = f"计算结果：{reasoning_output[:300]}\n\n输出JSON摘要。"
    t0 = time.monotonic()
    rec, text = meter.call('glm53', system, prompt, max_tokens=200,
                          purpose=purpose, timeout_s=60)
    return text


def engine_decide(verification, current_model, budget_rem, deadline_rem):
    """Use P1's engine node — real decision engine."""
    return run_engine_node(verification, current_model, budget_rem, deadline_rem)


def run_arm(arm, q, rep):
    run_id = f'M7-3F-P2-{arm}-{q["id"]}-r{rep}'
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens
    start_time = time.monotonic()

    # N2: Reasoning (model depends on arm)
    if arm == 'E':
        model = 'glm53'
    else:
        model = 'glm53flash'

    text1, rec1, lat1 = reasoning_call(model, q, f'{run_id}:reasoning')

    # N3: Verify (programmatic, zero cost)
    verification = run_verifier_node(text1, doc2, q['calc_contract'])

    # N4: Engine decision
    decision = engine_decide(verification, model,
                            102000 - meter.actual_tokens, 300 - (time.monotonic() - start_time))

    # π Switch logic (arm-dependent)
    switch_executed = False
    final_model = model
    final_text = text1

    if verification.verdict == "INVALID":
        if arm == 'D':
            # Validator-π: always switch on INVALID
            switch_executed = True
        elif arm == 'G' and verification.failure_type == "quality_silent":
            # PI_2'-Q: switch on quality_silent INVALID
            switch_executed = decision.action == "PI_SWITCH"
        elif arm == 'F':
            # Original PI_2': only switch on systematic failure + attempts≥2
            # (with verifier feedback mapping, this rarely fires for quality_silent)
            switch_executed = False  # Original PI_2' doesn't detect silent errors
    elif verification.verdict == "UNKNOWN" and arm in ('D', 'G'):
        # For UNKNOWN, D switches conservatively, G follows engine
        switch_executed = (arm == 'D')  # D: always retry; G: engine decides (default NO)

    if switch_executed:
        final_model = 'glm53'
        text2, rec2, lat2 = reasoning_call('glm53', q, f'{run_id}:switch')
        final_text = text2
        # Re-verify
        verification2 = run_verifier_node(text2, doc2, q['calc_contract'])
        final_verdict = verification2.verdict
    else:
        final_verdict = verification.verdict

    # N5: Report (always glm53 for fairness)
    report_text = report_call(final_text, f'{run_id}:report')

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
        'status': 'COMPLETE', 'correct': correct,
        'final_model': final_model, 'switch_executed': switch_executed,
        'verify_verdict': final_verdict,
        'verify_reason': verification.reason if not switch_executed else 're-verified',
        'engine_action': decision.action,
        'engine_rationale': decision.rationale[:80],
        'calls': calls, 'tokens': tokens, 'makespan_s': round(makespan, 2),
        'parsed': {k: str(v)[:50] for k, v in parsed.items()},
    }
    print(f'  {arm:3} {q["id"]:8} r{rep} {"✓" if correct else "✗"} '
          f'model={final_model:12} switch={switch_executed} '
          f'verify={final_verdict:8} {calls}c {tokens}t {makespan:.1f}s')
    return record


def main():
    all_runs = []
    plan = [(a, q, r) for a in ARMS for q in QUESTIONS for r in range(1, REPS+1)]
    random.seed(77)
    random.shuffle(plan)

    print(f'M7-3F P2 Five-Arm: {len(plan)} runs')
    print(f'Budget: {meter.n_calls}/110 calls, {meter.actual_tokens}/102000 tokens')
    print(f'Ledger: {LEDGER}')

    try:
        for arm, q, rep in plan:
            if meter.n_calls >= 108:
                print(f'SAFETY STOP: {meter.n_calls} calls')
                break
            print(f'\n--- {arm}-{q["id"]}-r{rep} ---')
            run = run_arm(arm, q, rep)
            all_runs.append(run)
    except BudgetExceeded as e:
        print(f'BUDGET STOP: {e}')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3F-P2-FIVE-ARM',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls,
            'total_tokens': meter.actual_tokens,
            'runs': all_runs,
        }
        (BENCH / 'm7_3f_p2_runs' / 'RESULTS.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=1))

        print(f'\n{"="*70}')
        print(f'M7-3F P2: {meter.n_calls}/110 calls, {meter.actual_tokens}/102000 tokens')
        print(f'Runs: {len(all_runs)}/{len(plan)}')
        print(f'{"="*70}')

        # Summary by arm × question
        print(f'\n{"Arm":5} {"Question":10} {"Correct":8} {"Switch":8} {"Verify":10} {"Avg Tok":8} {"Avg Sec":8}')
        print('-' * 65)
        for arm in ARMS:
            for q in QUESTIONS:
                runs = [r for r in all_runs if r['arm']==arm and r['question']==q['id']]
                if not runs: continue
                correct = sum(1 for r in runs if r['correct'])
                switches = sum(1 for r in runs if r['switch_executed'])
                avg_tok = sum(r['tokens'] for r in runs) / len(runs)
                avg_mk = sum(r['makespan_s'] for r in runs) / len(runs)
                print(f'{arm:5} {q["id"]:10} {correct}/{len(runs):6} '
                      f'{switches}/{len(runs):6} '
                      f'{runs[0]["verify_verdict"][:8]:10} '
                      f'{avg_tok:6.0f} {avg_mk:6.1f}')

        # Key comparisons
        print('\n=== KEY COMPARISONS ===')
        for q in QUESTIONS:
            qid = q['id']
            print(f'\n{qid}:')
            for arm in ARMS:
                runs = [r for r in all_runs if r['arm']==arm and r['question']==qid]
                if runs:
                    c = sum(1 for r in runs if r['correct'])
                    s = sum(1 for r in runs if r['switch_executed'])
                    t = sum(r['tokens'] for r in runs) / len(runs)
                    m = sum(r['makespan_s'] for r in runs) / len(runs)
                    print(f'  {arm}: Q={c}/{len(runs)} switch={s}/{len(runs)} '
                          f'avg_tok={t:.0f} avg_mk={m:.1f}s')

        # Overall
        print('\n=== OVERALL (both questions) ===')
        for arm in ARMS:
            runs = [r for r in all_runs if r['arm']==arm]
            if runs:
                c = sum(1 for r in runs if r['correct'])
                s = sum(1 for r in runs if r['switch_executed'])
                t = sum(r['tokens'] for r in runs) / len(runs)
                m = sum(r['makespan_s'] for r in runs) / len(runs)
                print(f'  {arm}: Q={c}/{len(runs)} ({c/len(runs)*100:.0f}%) '
                      f'switch={s}/{len(runs)} avg_tok={t:.0f} avg_mk={m:.1f}s')


if __name__ == '__main__':
    main()
