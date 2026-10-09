"""Node-by-node tracing: Stub dispatch → parse → final scoring (zero calls).

Fixes one NONE config, no faults/recovery, traces every node through the
evaluator to find where Q=0 originates. Steps:
  1. Trace all calls: node, model, prompt head, raw answer, parsed result
  2. Trace final scoring: which answer is used, what close() compares
  3. Build Q=1 positive control (correct verification value)
  4. Build Q=0 negative control (wrong verification value)
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import (JointEvaluator,
    MeteredExecutor, space)
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
from collab_scheduler_v1 import fault30_protocol as fp
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'


def traced_dispatch(model, prompt, trace, verify_value=4.0):
    """Returns format-correct answers; records every call to trace list."""
    time.sleep(0.001)
    ans = 'UNKNOWN'
    if 'extract the quantities' in prompt.lower():
        ans = ('{"facts": [{"value": 1.5, "evidence": "a"}, '
               '{"value": 2.5, "evidence": "b"}]}')
    elif 'arithmetic reasoning' in prompt.lower():
        ans = '{"expression": "v0+v1"}'
    elif 'verifying' in prompt.lower() or 'verification' in prompt.lower():
        ans = '{"value": %s}' % verify_value
    else:
        # Log unknown prompt to diagnose routing
        ans = '{"value": %s}' % verify_value
    trace.append(dict(model=model, prompt_head=prompt[:80], answer=ans))
    return dict(status='delivered', answer=ans,
                usage=dict(prompt_tokens=60, completion_tokens=40,
                           total_tokens=100))


def run_single(config_id, verify_value=4.0, label=''):
    task = make_task()
    led = fp.Ledger()
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name)
    budget = Budget(p, dict(new_request_attempts=100,
                            new_total_tokens=8192000,
                            request_token_reservation=8192,
                            max_output_tokens=512, wall_seconds=60,
                            logical_calls_per_task_config_state=12))
    trace = []
    def dispatch(model, prompt):
        return traced_dispatch(model, prompt, trace, verify_value)
    ex = MeteredExecutor(p, budget, dispatch, lambda model: None,
                         dict(medium='medium', large='large', coder='coder'))
    evaluator = JointEvaluator(ex, led, [task])
    result = evaluator.evaluate(config_id, 'clean', {})
    tmp.cleanup()
    return dict(label=label, config=config_id, trace=trace, result=result,
                gold=task['answer'])


def run():
    # Use a simple NONE config: all medium
    cfg_id = 'medium__medium__medium__coder__NONE'
    configs = space()
    assert cfg_id in {c['id'] for c in configs}, f'{cfg_id} not in space'

    # Positive control: verify returns correct answer
    pos = run_single(cfg_id, verify_value=4.0, label='POSITIVE')
    print('=== POSITIVE CONTROL (verify=4.0, gold=4.0) ===')
    print(f'config: {pos["config"]}')
    print(f'gold: {pos["gold"]}')
    for i, t in enumerate(pos['trace']):
        print(f'  call {i+1}: model={t["model"]} prompt={t["prompt_head"][:50]}...')
        print(f'          answer={t["answer"][:60]}')
    r = pos['result']
    print(f'  result keys: {list(r.keys()) if isinstance(r, dict) else type(r)}')
    if isinstance(r, dict):
        for k, v in r.items():
            if isinstance(v, (int, float, str, bool)):
                print(f'  {k} = {v}')
            elif isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, (int, float, str, bool)):
                        print(f'  {k}.{k2} = {v2}')

    # Negative control: verify returns wrong answer
    neg = run_single(cfg_id, verify_value=99.0, label='NEGATIVE')
    print('\n=== NEGATIVE CONTROL (verify=99.0, gold=4.0) ===')
    for i, t in enumerate(neg['trace']):
        print(f'  call {i+1}: model={t["model"]} answer={t["answer"][:50]}')
    r2 = neg['result']
    if isinstance(r2, dict):
        for k, v in r2.items():
            if isinstance(v, (int, float, str, bool)):
                print(f'  {k} = {v}')

    out = dict(positive=pos, negative=neg)
    (OUT / 'SCORE_CHAIN_TRACE.json').write_text(json.dumps(out, indent=1,
                                                           default=str))
    # Summary
    pos_q = pos['result'].get('Q', pos['result'].get('quality', 'MISSING'))
    neg_q = neg['result'].get('Q', neg['result'].get('quality', 'MISSING'))
    print(f'\nSUMMARY: POS Q={pos_q} | NEG Q={neg_q}')
    print(f'Expected: POS=1, NEG=0')
    if pos_q == 1 and neg_q == 0:
        print('SCORE CHAIN: WORKING')
    elif pos_q == 0:
        print('SCORE CHAIN: BROKEN — Q=0 even with correct verify answer')
        print('Need to inspect evaluator._evaluate internals')
    else:
        print(f'SCORE CHAIN: UNEXPECTED — pos={pos_q} neg={neg_q}')


if __name__ == '__main__':
    run()
