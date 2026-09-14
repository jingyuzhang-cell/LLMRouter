"""One-shot transport rescue under AMENDMENT_001: third attempt, 30-minute wait.

Reads the frozen amendment, recomputes eligible R1 positions (two prior
attempts, no scorable answer), enforces the unchanged 2060-attempt cap and the
few-percent stop condition, then issues exactly one rescue request per
eligible position with identical generation parameters. Results are written to
separate rescue files; the running collector's outputs are never touched.
"""
import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .collect_label_repair import read, request_once, score
from .data import load_cohort, sha
from .label_repair_plan import MODELS, OUT, ROOT
from . import run_repeat_stability as engine

AMENDMENT = OUT / 'AMENDMENT_001_TRANSPORT_RESCUE.json'
RESCUE = OUT / 'raw/reasoning_RESCUE.jsonl'
RESCUE_ATTEMPTS = OUT / 'raw/reasoning_ATTEMPTS_RESCUE.jsonl'
RESCUE_TIMEOUT = 1800
ELIGIBLE_FRACTION_CAP = 0.05
BUDGET_CAP = 2060


def run():
    amendment = json.loads(AMENDMENT.read_text())
    if not amendment['rule']['rescue_counts_inside_cap'] or amendment['rule']['rescue_attempts'] != 1:
        raise ValueError('Amendment rule mismatch')
    if amendment['adopted_unix_time'] is not None:
        raise FileExistsError('Rescue already executed under this amendment')
    failed = [r for r in read(OUT / 'raw/reasoning.jsonl') if r.get('quality') is None]
    attempts = read(OUT / 'raw/reasoning_ATTEMPTS.jsonl')
    spent = {(r['query_id'], r['repeat_index']): 0 for r in attempts}
    for r in attempts:
        spent[(r['query_id'], r['repeat_index'])] += 1
    eligible = []
    for row in failed:
        key = (row['query_id'], row['repeat_index'])
        if spent.get(key) != 2:
            raise ValueError(f'Eligibility violation: {key} has {spent.get(key)} attempts, expected exactly 2')
        eligible.append(row)
    target = read(OUT / 'PANEL.jsonl')
    if len(eligible) > ELIGIBLE_FRACTION_CAP * len(target) * 10:
        raise RuntimeError('Stop condition: rescue-eligible fraction exceeds cap; pause and reassess service')
    if len(attempts) + len(eligible) > BUDGET_CAP:
        raise RuntimeError('Global R1 transport budget cap would be exceeded')
    if amendment['rule']['max_wait_seconds'] != RESCUE_TIMEOUT:
        raise ValueError('Rescue timeout does not match the frozen amendment')
    amendment['adopted_unix_time'] = time.time()
    AMENDMENT.write_text(json.dumps(amendment, ensure_ascii=False, indent=2) + '\n')
    amendment_sha = sha(AMENDMENT)
    AMENDMENT.write_text(json.dumps(amendment, ensure_ascii=False, indent=2) + '\n')
    cohort, _ = load_cohort(ROOT / 'data/cohort_full_v2')
    panel = {r['query_id']: {**r, 'ground_truth': cohort[r['query_id']]['ground_truth']} for r in target}
    client = engine.api_client()
    client['timeout'] = RESCUE_TIMEOUT
    guard = threading.Lock()
    outcomes = []
    with RESCUE_ATTEMPTS.open('a') as ledger, RESCUE.open('a') as output:
        def rescue(row):
            key = (row['query_id'], row['repeat_index'])
            prompt_row = panel[row['query_id']]
            intent = dict(query_id=key[0], repeat_index=key[1], slot='reasoning', attempt=3,
                          unix_time=time.time(), model=MODELS['reasoning']['served'], max_tokens=2048,
                          protocol_sha256=sha(OUT / 'PROTOCOL.json'), amendment=amendment['amendment_id'],
                          amendment_sha256=amendment_sha, timeout_seconds=RESCUE_TIMEOUT)
            with guard:
                ledger.write(json.dumps(intent) + '\n')
                ledger.flush()
                os.fsync(ledger.fileno())
            raw = request_once(client, MODELS['reasoning']['served'], prompt_row)
            scored = score(prompt_row, raw)
            result = dict(**raw, **scored, query_id=key[0], repeat_index=key[1], slot='reasoning',
                          model=MODELS['reasoning']['model'], revision=MODELS['reasoning']['revision'],
                          temperature=.7, top_p=1., max_tokens=2048, attempts_used=3,
                          unix_time=time.time(), panel_sha256=sha(OUT / 'PANEL.jsonl'),
                          protocol_sha256=sha(OUT / 'PROTOCOL.json'),
                          cohort_sha256=sha(ROOT / 'data/cohort_full_v2/queries.jsonl'),
                          scorer_sha256=sha(ROOT / 'router_v2/rescore_glm_pilot.py'),
                          amendment=amendment['amendment_id'], amendment_sha256=amendment_sha)
            with guard:
                output.write(json.dumps(result, ensure_ascii=False) + '\n')
                output.flush()
                os.fsync(output.fileno())
            return result
        with ThreadPoolExecutor(max_workers=min(4, len(eligible))) as pool:
            outcomes = list(pool.map(rescue, eligible))
    summary = dict(positions=[dict(query_id=r['query_id'], repeat_index=r['repeat_index'],
                                   status=r['status'], finish_reason=r.get('finish_reason'),
                                   quality=r.get('quality'), evaluation_status=r.get('evaluation_status'),
                                   extracted_option=r.get('extracted_option'),
                                   latency_ms=r['latency']['total_ms'],
                                   tokens_output=(r.get('cost') or {}).get('tokens_output'))
                          for r in outcomes],
                   still_missing=sum(r.get('quality') is None for r in outcomes),
                   total_attempts_after=len(attempts) + len(eligible), budget_cap=BUDGET_CAP)
    write_summary = OUT / 'raw/reasoning_RESCUE_SUMMARY.json'
    write_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['run'])
    ap.parse_args()
    run()


if __name__ == '__main__':
    main()
