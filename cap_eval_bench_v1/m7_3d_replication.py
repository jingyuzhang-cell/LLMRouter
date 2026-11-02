"""M7-3D C1/C2 Replication with Split Contract V2 (REAL MODEL CALLS).

GO authorized by operator. Per M7_3D_REPLICATION_PROTOCOL.md (SHA c0662c8e...).
Split Contract V2 per M7_3D_SPLIT_CONTRACT_V2.md (SHA 8972bb10...).

5 arms x 2 conditions x 2 reps = 20 runs, ~114 calls.
"""
import json, random, sys, time, traceback
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
refs = json.load(open('/root/q_foundation/M7_3D_REFERENCE_FACTS.json'))
e04_ref = next(r for r in refs if r['task_id'] == 'E04-zhuoran')

ARMS = ['A', 'B', 'C', 'E', 'F']
CONDITIONS = ['C1', 'C2']


def extract(node_id, doc_id, model, purpose):
    prompt = (f"从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实"
              f"（日期、金额、处罚机构、事由）。输出JSON数组。\n\n文档：\n{e04_docs[doc_id][:1200]}")
    system = f"资本市场文档分析助手。节点类型：extracts。"
    rec, text = meter.call(model, system, prompt, max_tokens=400,
                           purpose=purpose, timeout_s=60)
    return text, rec


def extract_with_fault(node_id, doc_id, model, purpose, inject_fault=False):
    """Execute extract; optionally simulate transport fault on first attempt."""
    text, rec = extract(node_id, doc_id, model, purpose)
    if inject_fault:
        return None, rec  # signal failure
    return text, rec


def verify(extracts, model, purpose, inject_contract_fault=False):
    """Execute verification node."""
    extract_summary = '\n'.join(f"[{e['node']}] {e['text'][:150]}" for e in extracts)
    prompt = (f"基于以下多文档提取结果，核验跨文档事实一致性。"
              f"特别核验：立案日期、处罚日期在不同文档中是否一致。"
              f"输出JSON: {{\"consistent\": true/false, \"conflicts\": [...]}}\n\n{extract_summary}")
    system = "资本市场核验助手。节点类型：verification。"
    rec, text = meter.call(model, system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    if inject_contract_fault:
        return None, rec
    return text, rec


def split_verify_v2(node_id, extracts, purpose):
    """Execute split verification children with CONTRACT V2 (info preservation)."""
    results = []
    for i, ext in enumerate(extracts):
        suffix = chr(ord('a') + i)
        child_id = f"{node_id}_{suffix}"
        prompt = (
            f"核验单文档提取的一致性，并回显核验过程中识别到的关键事实。\n\n"
            f"要求：\n"
            f"1. 逐条核验提取内容中的日期、金额、主体、事由是否与原文一致。\n"
            f"2. 将核验到的每条关键事实完整回显（保留原值、来源、证据）。\n"
            f"3. 不得自行补充、推测或修改事实——仅传递和核验上游提取的内容。\n"
            f"4. 如果未发现关键事实，返回空数组 \"key_facts\": []，不得省略字段。\n\n"
            f"输出JSON:\n"
            f"{{\"consistent\": true/false, \"key_facts\": [\n"
            f"  {{\"fact\": \"事实描述\", \"value\": \"具体值\", \"source_node\": \"来源节点\",\n"
            f"   \"source_document\": \"来源文档\", \"evidence\": \"原文证据引用\"}}\n"
            f"]}}\n\n待核验内容：\n[{ext['node']}]: {ext['text'][:200]}")
        system = "资本市场核验子节点（V2合同）。"
        rec, text = meter.call('glm53flash', system, prompt, max_tokens=400,
                               purpose=f"{purpose}:{child_id}", timeout_s=60)
        results.append({'node': child_id, 'text': text[:300]})
    return results


def report(extract_results, verify_results, model, purpose):
    all_content = '\n'.join(
        f"[{r['node']}] {r.get('text', '')[:200]}"
        for r in extract_results + (verify_results or []))
    prompt = (f"基于以下提取和核验结果，回答：\n"
              f"1. 立案告知书披露日期？\n2. 行政处罚告知书收到日期？\n"
              f"3. 主要风险？\n\n{all_content}\n\n"
              f"JSON: {{\"filing_date\": \"YYYY-MM-DD或null\", "
              f"\"penalty_date\": \"YYYY-MM-DD或null\", \"main_risk\": \"...\"}}")
    system = "资本市场分析助手。"
    rec, text = meter.call(model, system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    return text, rec


def score(parsed):
    correct = 0
    for fact in e04_ref['facts']:
        got = None
        if '立案' in fact['claim']:
            got = parsed.get('filing_date')
        elif '处罚' in fact['claim']:
            got = parsed.get('penalty_date')
        if got and fact['answer'] in str(got):
            correct += 1
    return correct, len(e04_ref['facts'])


def run_one(arm, condition, rep):
    run_id = f'M7-3D-REPL-V2-{arm}-{condition}-r{rep}'
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens

    extracts = []
    inject_transport = (condition == 'C2')
    for i, did in enumerate(doc_ids):
        nid = f'e04_ext_{i}'
        text, rec = extract_with_fault(nid, did, 'glm53flash',
                                       f'{run_id}:{nid}',
                                       inject_fault=(inject_transport and i == 1))
        if text is None:
            if arm in ('B', 'E', 'F'):
                text, rec = extract(nid, did, 'glm53flash', f'{run_id}:{nid}:v2')
                extracts.append({'node': nid, 'text': text[:150] if text else 'RETRY_FAIL'})
            else:
                extracts.append({'node': nid, 'text': 'FAILED'})
        else:
            extracts.append({'node': nid, 'text': text[:150]})

    verify_results = None
    verify_status = 'skipped'
    if condition == 'C1':
        text, rec = verify(extracts, 'glm53', f'{run_id}:e04_chk',
                           inject_contract_fault=True)
        if text is None:
            if arm in ('C', 'E', 'F'):
                verify_results = split_verify_v2('e04_chk', extracts, run_id)
                verify_status = 'split_recovered'
            elif arm == 'B':
                verify(extracts, 'glm53', f'{run_id}:e04_chk:v2',
                       inject_contract_fault=True)
                verify_status = 'retry_failed'
            else:
                verify_status = 'failed'
        else:
            verify_status = 'passed'

    report_model = 'glm53'
    report_text, report_rec = report(extracts, verify_results, report_model,
                                     f'{run_id}:report')
    try:
        parsed = fenced_json(report_text)
    except:
        parsed = {}
    correct, total = score(parsed)

    any_failed = any(e['text'] in ('FAILED', 'RETRY_FAIL') for e in extracts)
    verify_blocked = (condition == 'C1' and verify_status in ('failed', 'retry_failed'))
    status = 'INCOMPLETE' if (any_failed or verify_blocked) else 'COMPLETE'

    tokens_used = meter.actual_tokens - start_tokens
    calls_used = meter.n_calls - start_calls
    record = {
        'run_id': run_id, 'arm': arm, 'condition': condition, 'rep': rep,
        'contract': 'V2', 'status': status,
        'calls': calls_used, 'tokens': tokens_used,
        'verify_status': verify_status,
        'score_correct': correct, 'score_total': total,
        'parsed': parsed,
        'report_text': report_text[:200],
    }
    print(f'  {arm:3} {condition} r{rep} {status:10} Q={correct}/{total} '
          f'verify={verify_status:16} {calls_used}c {tokens_used}t')
    return record


def main():
    all_runs = []
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens

    # Build randomized run order
    run_plan = [(arm, cond, rep) for arm in ARMS for cond in CONDITIONS
                for rep in [1, 2]]
    random.seed(42)
    random.shuffle(run_plan)

    print(f'Replication plan: {len(run_plan)} runs (randomized)')
    print(f'Budget: {meter.n_calls}/300 used, {meter.actual_tokens}/350K used')

    try:
        for arm, cond, rep in run_plan:
            if meter.n_calls >= 295:  # safety margin
                print(f'SAFETY STOP: {meter.n_calls} calls')
                break
            print(f'\n--- {arm}-{cond}-r{rep} ---')
            run = run_one(arm, cond, rep)
            all_runs.append(run)
    except BudgetExceeded as e:
        print(f'BUDGET STOP: {e}')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3D_REPLICATION_V2',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls_global': meter.n_calls,
            'total_tokens_global': meter.actual_tokens,
            'new_calls': meter.n_calls - start_calls,
            'new_tokens': meter.actual_tokens - start_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3d_runs' / 'REPLICATION_RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))

        print(f'\n{"="*60}')
        print(f'Replication V2 complete: {meter.n_calls - start_calls} new calls, '
              f'{meter.actual_tokens - start_tokens} new tokens')
        print(f'Global: {meter.n_calls}/300 calls, {meter.actual_tokens}/350K tokens')
        print(f'{"=" * 60}')

        # Summary
        print(f'\n{"Arm":5} {"Cond":5} {"Rep":4} {"Status":12} {"Q":6} {"Verify":16}')
        print('-' * 55)
        for r in all_runs:
            print(f'{r["arm"]:5} {r["condition"]:5} r{r["rep"]} '
                  f'{r["status"]:12} {r["score_correct"]}/{r["score_total"]:4} '
                  f'{r["verify_status"]:16}')

        # Key comparison: Q improvement
        print(f'\n=== V2 Contract Quality Check ===')
        for arm in ARMS:
            for cond in CONDITIONS:
                runs = [r for r in all_runs if r['arm']==arm and r['condition']==cond]
                qs = [f'{r["score_correct"]}/{r["score_total"]}' for r in runs]
                statuses = [r['status'][:4] for r in runs]
                print(f'  {arm:3} {cond} Q: {qs} status: {statuses}')


if __name__ == '__main__':
    main()
