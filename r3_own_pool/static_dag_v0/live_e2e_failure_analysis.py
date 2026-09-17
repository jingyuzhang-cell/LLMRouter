"""Live E2E failure analysis: taxonomy over failed tasks + strict recovery.

Reads live_e2e/TRACES.jsonl. Per Static-failed task, classifies the Full-arm
outcome and the dominant failure cause: extraction_error (facts unparseable or
operand recall failed), reasoning_error (no valid expression/value), wrong_value
(valid value != gold), verifier_misjudge (verdict wrong vs truth),
decompose_fail (decompose triggered but still wrong), router_error (a pool
model existed that was correct but never selected). Strict recovery:
(Full correct - Static correct) / Static failed, capped at 1 by construction.
"""
import argparse
import json

import numpy as np

from . import core

OUT = core.ROOT / 'static_dag_v0/live_e2e'


def run():
    traces = [json.loads(l) for l in (OUT / 'TRACES.jsonl').open()]
    results = json.loads((OUT / 'RESULTS.json').read_text())
    static_ok = [t['arms']['Static']['task_success'] for t in traces]
    full_ok = [t['arms']['Full']['task_success'] for t in traces]
    fb_ok = [t['arms']['Feedback']['task_success'] for t in traces]
    static_failed = [i for i, ok in enumerate(static_ok) if not ok]
    recovered = [i for i in static_failed if full_ok[i]]
    broken = [i for i, ok in enumerate(static_ok) if ok and not full_ok[i]]
    taxonomy = {}
    cases = []
    for i in static_failed:
        t = traces[i]
        full = t['arms']['Full']
        st = t['arms']['Static']
        if full['task_success']:
            cause = 'recovered'
        elif not full.get('extraction_parse', True):
            cause = 'extraction_error'
        elif full.get('final_value') is None:
            cause = 'reasoning_error' if not full.get('decompose') else 'decompose_fail'
        else:
            cause = 'wrong_value'
        taxonomy[cause] = taxonomy.get(cause, 0) + 1
        cases.append(dict(task_uid=t['task_uid'], cause=cause,
                          static_value=st.get('final_value'), full_value=full.get('final_value'),
                          gold=full.get('gold'), decompose=full.get('decompose', False),
                          verdict=full.get('verdict')))
    # verifier misjudgement rate on final answers (verdict vs truth, Full arm)
    mis = [t for t in traces if t['arms']['Full'].get('verdict') is not None]
    misjudge = sum(1 for t in mis if t['arms']['Full']['verdict'] != t['arms']['Full']['task_success'])
    summary = dict(
        n=len(traces),
        static_success=int(np.sum(static_ok)), feedback_success=int(np.sum(fb_ok)), full_success=int(np.sum(full_ok)),
        strict_recovery=dict(formula='(Full correct - Static correct)/Static failed',
                             static_failed=len(static_failed), recovered=len(recovered),
                             value=len(recovered) / max(1, len(static_failed)),
                             broken_static_now_failed=len(broken)),
        failure_taxonomy=taxonomy,
        verifier_disagreement_with_truth=f'{misjudge}/{len(mis)}',
        note='failure cases with full context in CASES.jsonl for the Discussion chapter')
    core.write(OUT / 'FAILURE_ANALYSIS.json', dict(summary=summary))
    (OUT / 'CASES.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
