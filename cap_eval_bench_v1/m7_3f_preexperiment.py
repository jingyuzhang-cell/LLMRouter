"""M7-3F Pre-experiment: Confirm flash vs glm53 capability gap on reasoning tasks.

6 calls: flash × 3 + glm53 × 3 on numerical/causal reasoning questions.
GO authorized by operator. Uses M7-3E remaining budget (43 calls / 37K).
"""
import json, sys, time
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import Meter, fenced_json

LEDGER = BENCH / 'm7_3e_runs' / 'LEDGER.jsonl'  # same ledger, remaining budget
meter = Meter(ledger_path=str(LEDGER), max_calls=140,
              max_guaranteed_actual=126360)

doc2 = open('evidence/texts/E04-zhuoran_20261009.txt').read()

# Reasoning questions requiring multi-step computation
QUESTIONS = [
    {
        "id": "CALC-1",
        "prompt": f"""基于以下文档内容，计算：2021-2024年虚增利润总额合计是多少万元？

文档关键内容：
{doc2[:1500]}

请逐步列出每年的虚增利润总额，然后计算合计。输出JSON:
{{"y2021": ..., "y2022": ..., "y2023": ..., "y2024": ..., "total": ...}}""",
        "expected_total": 28742.21,
        "check": lambda p: abs(float(p.get('total', 0)) - 28742.21) < 100,
    },
    {
        "id": "CALC-2", 
        "prompt": f"""基于以下文档内容，回答：哪一年度虚增利润总额占当期报告利润总额比例最高？比例是多少？

文档关键内容：
{doc2[:1500]}

输出JSON: {{"highest_year": "...", "highest_ratio_pct": ...}}""",
        "expected": ("2023", 148.33),
        "check": lambda p: '2023' in str(p.get('highest_year','')) and abs(float(p.get('highest_ratio_pct',0)) - 148.33) < 10,
    },
    {
        "id": "INF-1",
        "prompt": f"""基于以下文档内容，从收到立案告知书到收到行政处罚事先告知书间隔了多长时间（天数）？

文档关键内容：
{doc2[:1500]}

注意：收到立案告知书日期是2025年12月19日，收到行政处罚事先告知书日期是2026年9月11日。
计算两个日期之间的天数。输出JSON: {{"start_date": "...", "end_date": "...", "interval_days": ...}}""",
        "expected_days": 266,
        "check": lambda p: abs(int(float(str(p.get('interval_days',0)).replace('天',''))) - 266) < 10,
    },
]

def test_model(model_alias, rep):
    results = []
    for q in QUESTIONS:
        purpose = f'M7-3F-PRE-{model_alias}-r{rep}:{q["id"]}'
        system = "资本市场分析助手。请仔细计算并给出精确答案。"
        rec, text = meter.call(model_alias, system, q['prompt'],
                               max_tokens=400, purpose=purpose, timeout_s=60)
        try:
            parsed = fenced_json(text)
            correct = q['check'](parsed)
        except:
            parsed = {}
            correct = False
        results.append({'id': q['id'], 'correct': correct,
                       'parsed': {k: str(v)[:50] for k, v in parsed.items()}})
        print(f'  {model_alias:12} r{rep} {q["id"]}: {"✓" if correct else "✗"} '
              f'{parsed}')
    return results

def main():
    all_results = {'flash': [], 'glm53': []}
    
    for rep in [1, 2, 3]:
        for model in ['glm53flash', 'glm53']:
            print(f'\n--- {model} rep {rep} ---')
            results = test_model(model, rep)
            key = 'flash' if 'flash' in model else 'glm53'
            all_results[key].extend(results)
    
    # Summary
    print(f'\n{"="*60}')
    print('PRE-EXPERIMENT RESULTS')
    print(f'{"="*60}')
    
    for model in ['flash', 'glm53']:
        runs = all_results[model]
        by_q = {}
        for r in runs:
            by_q.setdefault(r['id'], []).append(r['correct'])
        total_correct = sum(1 for r in runs if r['correct'])
        total = len(runs)
        print(f'\n{model}: {total_correct}/{total} correct ({total_correct/total*100:.0f}%)')
        for qid, scores in sorted(by_q.items()):
            print(f'  {qid}: {sum(scores)}/{len(scores)}')
    
    # Gap assessment
    flash_rate = sum(1 for r in all_results['flash'] if r['correct']) / len(all_results['flash'])
    glm_rate = sum(1 for r in all_results['glm53'] if r['correct']) / len(all_results['glm53'])
    
    print(f'\n=== GAP ASSESSMENT ===')
    print(f'Flash accuracy: {flash_rate:.1%}')
    print(f'GLM53 accuracy: {glm_rate:.1%}')
    print(f'Gap: {glm_rate - flash_rate:.1%}')
    
    if flash_rate < 0.5 and glm_rate > 0.5:
        print('\n✓ CAPABILITY GAP CONFIRMED: flash fails, glm53 succeeds')
        print('  → M7-3F formal experiment can proceed')
    elif glm_rate - flash_rate > 0.3:
        print('\n△ PARTIAL GAP: significant difference but flash not completely failing')
    else:
        print('\n✗ NO SIGNIFICANT GAP: current questions do not differentiate models')
    
    # Save
    output = {
        'batch': 'M7-3F-PRE-EXPERIMENT',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'total_calls': meter.n_calls,
        'total_tokens': meter.actual_tokens,
        'flash_rate': flash_rate, 'glm_rate': glm_rate,
        'results': all_results,
    }
    (BENCH / 'm7_3e_runs' / 'PRE_EXPERIMENT_RESULTS.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
