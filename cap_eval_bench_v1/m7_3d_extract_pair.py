"""M7-3D Extract V1/V2 Paired Experiment (REAL MODEL CALLS).

GO authorized. Per M7_3D_EXTRACT_PAIREX_PROTOCOL.md (SHA cf84ce1f...).
V1 (original) vs V2 (date_role disambiguation) on E04-zhuoran, 3 reps each.
"""
import json, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import Meter, BudgetExceeded, fenced_json

LEDGER = BENCH / 'm7_3d_runs' / 'LEDGER.jsonl'
meter = Meter(ledger_path=str(LEDGER), max_calls=300,
              max_guaranteed_actual=340_000)

texts_dir = BENCH / 'evidence' / 'texts'
e04_docs = {d.stem: d.read_text() for d in sorted(texts_dir.glob('E04-zhuoran_*.txt'))}
doc_ids = sorted(e04_docs.keys())

MAX_NEW = 40  # hard ceiling for this experiment

# V1 extract prompt (original - no date_role)
V1_PROMPT = ("从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实"
             "（日期、金额、处罚机构、事由）。输出JSON数组。\n\n文档：\n{doc}")

# V2 extract prompt (date_role disambiguation + evidence anchoring)
V2_PROMPT = """从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实。
每个日期必须标注其语义角色（date_role）。

输出JSON:
{
  "key_facts": [
    {
      "fact_type": "filing_date" | "penalty_date" | "risk_warning_date" | "other_date" | "amount" | "authority" | "reason",
      "value": "具体值",
      "date_role": "披露日期|收到日期|落款日期|处罚日期|其他",
      "source_document": "文档标识",
      "evidence_quote": "原文证据引用（截取关键句，含日期上下文）",
      "confidence_status": "SUPPORTED" | "UNKNOWN"
    }
  ],
  "unknown_facts": []
}

要求：
1. 区分"披露日期"（在交易所网站发布公告的日期）与"收到日期"（收到监管机构文书的日期）。
2. 如果文档中同时出现两个日期，必须分别提取并标注各自的 date_role。
3. 没有足够原文依据时，confidence_status 必须为 UNKNOWN，不得猜测。
4. 事实必须附带原文证据引用。
5. key_facts 必须存在（可为空数组），不得省略字段。

文档：
{doc}"""

REPORT_PROMPT = """基于以下提取结果，回答：
1. 立案告知书披露日期（在交易所网站发布公告的日期）？
2. 行政处罚告知书收到日期？
3. 主要风险？

{extracts}

JSON格式: {{"filing_date": "YYYY-MM-DD或null", "penalty_date": "YYYY-MM-DD或null", "main_risk": "..."}}"""


def run_extract(contract_version, doc_id, doc_text, purpose):
    if contract_version == 'V1':
        prompt = V1_PROMPT.replace('{doc}', doc_text[:1200])
    else:
        prompt = V2_PROMPT.replace('{doc}', doc_text[:1500])
    system = "资本市场文档分析助手。"
    rec, text = meter.call('glm53flash', system, prompt, max_tokens=500,
                           purpose=purpose, timeout_s=60)
    return text, rec


def run_report(extract_texts, purpose):
    extracts = '\n'.join(f'[extract_{i}] {t[:200]}' for i, t in enumerate(extract_texts))
    prompt = REPORT_PROMPT.format(extracts=extracts)
    system = "资本市场分析助手。"
    rec, text = meter.call('glm53', system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    return text, rec


def score(parsed):
    f1 = str(parsed.get('filing_date', ''))
    f2 = str(parsed.get('penalty_date', ''))
    f1_ok = '2025-12-20' in f1
    f2_ok = '2026-09-11' in f2
    return f1_ok, f2_ok


def run_one(contract, rep):
    run_id = f'M7-3D-EXT-{contract}-r{rep}'
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens
    print(f'\n--- {run_id} ---')

    # Phase 1: Extract all 3 docs
    extract_texts = []
    for i, did in enumerate(doc_ids):
        text, rec = run_extract(contract, did, e04_docs[did],
                                f'{run_id}:ext_{i}')
        extract_texts.append(text[:300])

    # Phase 2: Report
    report_text, _ = run_report(extract_texts, f'{run_id}:report')
    try:
        parsed = fenced_json(report_text)
    except:
        parsed = {}

    f1_ok, f2_ok = score(parsed)
    tokens = meter.actual_tokens - start_tokens
    calls = meter.n_calls - start_calls

    # Also check extract-level date_role presence
    extract_dates = []
    for i, t in enumerate(extract_texts):
        has_1220 = '2025-12-20' in t or '12月20' in t or '12-20' in t
        has_1219 = '2025-12-19' in t or '12月19' in t or '12-19' in t
        has_0911 = '2026-09-11' in t or '9月11' in t or '09-11' in t
        has_role = 'date_role' in t or '披露' in t or '收到' in t
        extract_dates.append({'doc': doc_ids[i], 'has_1220': has_1220,
                              'has_1219': has_1219, 'has_0911': has_0911,
                              'has_role': has_role})

    record = {
        'run_id': run_id, 'contract': contract, 'rep': rep,
        'status': 'COMPLETE', 'calls': calls, 'tokens': tokens,
        'f1_filing_date': f1_ok, 'f2_penalty_date': f2_ok,
        'parsed': parsed,
        'extract_dates': extract_dates,
        'report_text': report_text[:200],
    }
    print(f'  {contract} r{rep}: F1={"✓" if f1_ok else "✗"} F2={"✓" if f2_ok else "✗"} '
          f'{calls}c {tokens}t')
    if extract_dates:
        for ed in extract_dates:
            print(f'    {ed["doc"][:20]:22} 12-20={ed["has_1220"]} 12-19={ed["has_1219"]} '
                  f'09-11={ed["has_0911"]} role={ed["has_role"]}')
    return record


def main():
    all_runs = []
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens

    try:
        # Alternating execution: V1-r1, V2-r1, V1-r2, V2-r2, V1-r3, V2-r3
        for rep in [1, 2, 3]:
            for contract in ['V1', 'V2']:
                if meter.n_calls - start_calls >= MAX_NEW:
                    print(f'BUDGET CEILING: {meter.n_calls - start_calls} new calls')
                    break
                run = run_one(contract, rep)
                all_runs.append(run)
    except BudgetExceeded:
        print('GLOBAL BUDGET STOP')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3D-EXTRACT-V2-PAIR',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls_global': meter.n_calls,
            'total_tokens_global': meter.actual_tokens,
            'new_calls': meter.n_calls - start_calls,
            'new_tokens': meter.actual_tokens - start_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3d_runs' / 'EXTRACT_PAIR_RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))

        print(f'\n{"="*60}')
        print(f'Extract Paired Results: {meter.n_calls - start_calls} new calls, '
              f'{meter.actual_tokens - start_tokens} new tokens')
        print(f'Global: {meter.n_calls}/300 calls, {meter.actual_tokens}/350K tokens')
        print(f'{"="*60}')

        # Summary
        print(f'\n{"Contract":10} {"Rep":4} {"F1":4} {"F2":4} {"12-20":6} {"12-19":6} {"09-11":6} {"role":5}')
        print('-' * 50)
        for r in all_runs:
            has1220 = any(e['has_1220'] for e in r['extract_dates'])
            has1219 = any(e['has_1219'] for e in r['extract_dates'])
            has0911 = any(e['has_0911'] for e in r['extract_dates'])
            hasrole = any(e['has_role'] for e in r['extract_dates'])
            print(f'{r["contract"]:10} r{r["rep"]} '
                  f'{"✓" if r["f1_filing_date"] else "✗":4} '
                  f'{"✓" if r["f2_penalty_date"] else "✗":4} '
                  f'{"Y" if has1220 else "N":6} {"Y" if has1219 else "N":6} '
                  f'{"Y" if has0911 else "N":6} {"Y" if hasrole else "N":5}')

        # Summary stats
        for contract in ['V1', 'V2']:
            runs = [r for r in all_runs if r['contract'] == contract]
            f1_rate = sum(1 for r in runs if r['f1_filing_date']) / len(runs)
            f2_rate = sum(1 for r in runs if r['f2_penalty_date']) / len(runs)
            print(f'\n{contract}: F1 accuracy={f1_rate:.1%} F2 accuracy={f2_rate:.1%} '
                  f'({len(runs)} reps)')


if __name__ == '__main__':
    main()
