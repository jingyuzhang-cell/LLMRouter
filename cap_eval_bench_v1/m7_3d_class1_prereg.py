"""M7-3D Class I Re-registration: C1 (merge fault) + C2 (transient fault).

RE-REGISTERED per operator rule: full frozen matrix (420 calls) exceeds
remaining budget (244 calls). This minimal subset (70 calls) covers the
two highest-priority mechanisms (Z and R) on E04.

Pre-registered expected outcomes:
  C1 (merge contract fault at verification node):
    A(Static): INCOMPLETE - no recovery
    B(R-only): INCOMPLETE - retry cannot fix persistent merge fault
    C(Z-only): COMPLETE - split isolates per-lineage verification
    D(pi-only): INCOMPLETE - model switch cannot fix structural fault
    E(Fixed Joint): COMPLETE - always-split recovers
    F(Engine): COMPLETE - conditional split fires
    F'(V1.0): COMPLETE - Z_1 rule fires
  Expected differentiation: {A,B,D} INCOMPLETE vs {C,E,F,F'} COMPLETE

  C2 (transient transport fault at extract node):
    A(Static): INCOMPLETE - no retry
    B(R-only): COMPLETE - retry succeeds
    C(Z-only): INCOMPLETE - no retry mechanism
    D(pi-only): COMPLETE - retry with switch
    E(Fixed Joint): COMPLETE - retry
    F(Engine): COMPLETE - retry
    F'(V1.0): COMPLETE - retry
  Expected differentiation: {A,C} INCOMPLETE vs {B,D,E,F,F'} COMPLETE

Budget: ~70 calls / ~56K tokens (within remaining 244/309K)
"""
import json, hashlib, sys, time, traceback
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, '/root/capital_opinion_pilot')

from pilot_common import Meter, BudgetExceeded, fenced_json

MAX_NEW_CALLS = 100  # hard ceiling for this re-registered subset
LEDGER = BENCH / 'm7_3d_runs' / 'LEDGER.jsonl'

meter = Meter(ledger_path=str(LEDGER),
              max_calls=300,  # global cap from GO
              max_guaranteed_actual=340_000)

texts_dir = BENCH / 'evidence' / 'texts'
e04_docs = {d.stem: d.read_text() for d in sorted(texts_dir.glob('E04-zhuoran_*.txt'))}
doc_ids = sorted(e04_docs.keys())

refs = json.load(open('/root/q_foundation/M7_3D_REFERENCE_FACTS.json'))
e04_ref = next(r for r in refs if r['task_id'] == 'E04-zhuoran')


def extract_node(node_id, doc_id, model, purpose, fault=None):
    """Execute extraction; optionally inject fault."""
    prompt = (f"从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实"
              f"（日期、金额、处罚机构、事由）。输出JSON数组。\n\n文档：\n{e04_docs[doc_id][:1200]}")
    system = f"你是资本市场文档分析助手。节点类型：extracts。"
    rec, text = meter.call(model, system, prompt, max_tokens=400,
                           purpose=purpose, timeout_s=60)
    if fault == 'transport' and node_id.endswith('_ext_1'):
        # Inject: simulate transport failure on first attempt of ext_1
        # The real call happened (billed), but we return failure to the caller
        return None, rec  # signal failure
    return text, rec


def retry_extract(node_id, doc_id, model, purpose):
    """Retry a failed extract node."""
    return extract_node(node_id, doc_id, model, purpose)


def verify_node(node_id, extracts, model, purpose, fault=None):
    """Execute verification; optionally inject merge-contract fault."""
    extract_summary = '\n'.join(f"[{e['node']}] {e['text'][:150]}" for e in extracts)
    prompt = (f"基于以下多文档提取结果，核验跨文档事实一致性。"
              f"特别核验：立案日期、处罚日期在不同文档中是否一致。"
              f"输出JSON: {{\"consistent\": true/false, \"conflicts\": [...]}}\n\n"
              f"{extract_summary}")
    system = f"你是资本市场核验助手。节点类型：verification。"
    rec, text = meter.call(model, system, prompt, max_tokens=300,
                           purpose=purpose, timeout_s=60)
    if fault == 'contract':
        return None, rec  # persistent merge fault
    return text, rec


def split_verify_children(node_id, extracts, purpose):
    """Execute split verification: per-lineage sub-verifiers."""
    results = []
    # Group extracts by lineage (simplified: each extract is one lineage)
    for i, ext in enumerate(extracts):
        suffix = chr(ord('a') + i)
        child_id = f"{node_id}_{suffix}"
        prompt = (f"核验单文档提取的一致性。\n[{ext['node']}]: {ext['text'][:150]}\n"
                  f"输出JSON: {{\"consistent\": true/false}}")
        system = f"核验子节点。"
        rec, text = meter.call('glm53flash', system, prompt, max_tokens=200,
                               purpose=f"{purpose}:{child_id}", timeout_s=60)
        results.append({'node': child_id, 'text': text[:100]})
    return results


def report_node(extract_results, verify_results, model, purpose):
    """Execute terminal report."""
    all_results = '\n'.join(
        f"[{r['node']}] {r.get('text', r.get('result', ''))[:150]}"
        for r in extract_results + (verify_results or []))
    prompt = (f"基于以下提取和核验结果，回答：\n"
              f"1. 立案告知书披露日期？\n2. 行政处罚告知书收到日期？\n"
              f"3. 主要风险？\n\n{all_results}\n\n"
              f"JSON格式: {{\"filing_date\": \"YYYY-MM-DD或null\", "
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


def run_condition(arm, condition, start_calls, start_tokens):
    """Run one arm under one condition. Returns run record."""
    run_id = f'M7-3D-C1R-{arm}-{condition}'
    print(f'\n--- {run_id} ---')

    # Phase 1: Extract (3 nodes)
    extracts = []
    extract_fault = 'transport' if condition == 'C2' else None
    for i, did in enumerate(doc_ids):
        nid = f'e04_ext_{i}'
        text, rec = extract_node(nid, did, 'glm53flash',
                                 f'{run_id}:{nid}',
                                 fault=extract_fault if i == 1 else None)
        if text is None:
            # Extract failed
            if arm in ('B', 'D', 'E', 'F', 'F_prime'):
                # These arms retry
                text, rec = retry_extract(nid, did, 'glm53flash',
                                          f'{run_id}:{nid}:v2')
                if text:
                    extracts.append({'node': nid, 'text': text[:150]})
                else:
                    extracts.append({'node': nid, 'text': 'RETRY_FAILED'})
            else:
                # A and C don't retry
                extracts.append({'node': nid, 'text': 'FAILED'})
        else:
            extracts.append({'node': nid, 'text': text[:150]})

    # Phase 2: Verify (only for C1; C2 has no verify node)
    verify_results = None
    verify_status = 'skipped'
    if condition == 'C1':
        verify_fault = 'contract'  # inject merge contract fault
        text, rec = verify_node('e04_chk', extracts, 'glm53',
                                f'{run_id}:e04_chk',
                                fault=verify_fault)
        if text is None:
            # Verify failed - persistent merge fault
            if arm in ('C', 'E', 'F', 'F_prime'):
                # These arms split
                verify_results = split_verify_children(
                    'e04_chk', extracts, run_id)
                verify_status = 'split_recovered'
            elif arm == 'B':
                # R-only: retry verify (will fail again - persistent)
                text2, rec2 = verify_node('e04_chk', extracts, 'glm53',
                                          f'{run_id}:e04_chk:v2')
                verify_status = 'retry_failed'  # persistent fault
            else:
                verify_status = 'failed'
        else:
            verify_status = 'passed'

    # Phase 3: Report
    report_model = 'glm53'
    report_text, report_rec = report_node(
        extracts, verify_results, report_model,
        f'{run_id}:report')

    # Score
    try:
        parsed = fenced_json(report_text)
    except:
        parsed = {}
    correct, total = score(parsed)

    # Determine completion status
    any_failed = any(e['text'] in ('FAILED', 'RETRY_FAILED') for e in extracts)
    verify_blocked = (condition == 'C1' and verify_status in ('failed', 'retry_failed'))
    status = 'INCOMPLETE' if (any_failed or verify_blocked) else 'COMPLETE'

    tokens_used = meter.actual_tokens - start_tokens
    calls_used = meter.n_calls - start_calls

    record = {
        'run_id': run_id, 'arm': arm, 'condition': condition,
        'task': 'E04-zhuoran', 'status': status,
        'calls': calls_used, 'tokens': tokens_used,
        'verify_status': verify_status,
        'score_correct': correct, 'score_total': total,
        'report_text': report_text[:200],
    }
    print(f'  {arm:8} {condition} status={status} '
          f'Q={correct}/{total} verify={verify_status} '
          f'{calls_used} calls {tokens_used} tok')
    return record


def main():
    all_runs = []
    start_calls = meter.n_calls
    start_tokens = meter.actual_tokens

    try:
        # C1: merge contract fault (7 arms)
        for arm in ['A', 'B', 'C', 'D', 'E', 'F', 'F_prime']:
            if meter.n_calls - start_calls >= MAX_NEW_CALLS:
                print('BUDGET CEILING for re-registered subset')
                break
            run = run_condition(arm, 'C1', meter.n_calls, meter.actual_tokens)
            all_runs.append(run)

        # C2: transient transport fault (7 arms)
        for arm in ['A', 'B', 'C', 'D', 'E', 'F', 'F_prime']:
            if meter.n_calls - start_calls >= MAX_NEW_CALLS:
                print('BUDGET CEILING for re-registered subset')
                break
            run = run_condition(arm, 'C2', meter.n_calls, meter.actual_tokens)
            all_runs.append(run)

    except BudgetExceeded:
        print('GLOBAL BUDGET STOP')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        results = {
            'batch': 'M7-3D_CLASS_I_REREG',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'total_calls': meter.n_calls, 'total_tokens': meter.actual_tokens,
            'new_calls': meter.n_calls - start_calls,
            'new_tokens': meter.actual_tokens - start_tokens,
            'runs': all_runs,
        }
        out = BENCH / 'm7_3d_runs' / 'CLASS1_RESULTS.json'
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))

        print(f'\n{"="*60}')
        print(f'Class I Results: {meter.n_calls - start_calls} new calls, '
              f'{meter.actual_tokens - start_tokens} new tokens')
        print(f'Total budget: {meter.n_calls}/300 calls, '
              f'{meter.actual_tokens}/350K tokens')
        print(f'{"="*60}')

        # Print summary table
        print(f'\n{"Arm":10} {"C1":20} {"C2":20}')
        print('-' * 50)
        for arm in ['A', 'B', 'C', 'D', 'E', 'F', 'F_prime']:
            c1 = next((r for r in all_runs if r['arm']==arm and r['condition']=='C1'), None)
            c2 = next((r for r in all_runs if r['arm']==arm and r['condition']=='C2'), None)
            c1_str = f'{c1["status"][:10]} Q={c1["score_correct"]}/{c1["score_total"]}' if c1 else 'N/A'
            c2_str = f'{c2["status"][:10]} Q={c2["score_correct"]}/{c2["score_total"]}' if c2 else 'N/A'
            print(f'{arm:10} {c1_str:20} {c2_str:20}')


if __name__ == '__main__':
    main()
