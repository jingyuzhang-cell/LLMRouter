"""Frozen-panel v2 zero-call re-scoring: Q_v1 vs Q_v2 for executed tasks.

Reads frozen Cube clean results (model answers already recorded), applies
v2 contract gold to the SAME model answers, produces independent Q_v2 file.
No model calls, no prompt changes, no cost/latency changes.

Only re-scores tasks with COMPLETE final answers (incomplete trajectories
remain marked as incomplete).
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from static_dag_v0.multidag_dynamic import close  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2'


def run():
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        contract_v2_gold, load_native_answers)

    native = load_native_answers()

    # Load frozen clean cube results (has per-task final answers)
    # We use the cube_clean RESPONSES to get the actual v-node answers
    from collab_scheduler_v1 import cube_analyze
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/'
                       'FROZEN200_POLICY.json').read_text())['tasks']
    led = cube_analyze.load_ledgers()

    # For each config, re-score every task's final answer against v2 gold
    configs = ['SER__HETEROGENEOUS__NONE__FRESH',  # best clean DAG
               'SERV__HETEROGENEOUS__NONE__FRESH',
               'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH']
    results = {}

    for cid in configs:
        res_v1 = {'n': 0, 'Q_v1_sum': 0, 'Q_v2_sum': 0, 'changes': 0}
        per_task = []
        try:
            eval_results = cube_analyze.evaluate(tasks, led=led)
            rows = eval_results.get(cid, {}).get('per_task', [])
        except Exception:
            rows = []

        for row in rows:
            uid = row['uid']
            v1_ok = row.get('ok', 0)
            # Get v2 gold for this task
            nat = native.get(uid, {})
            v2 = contract_v2_gold(nat.get('native_answer'),
                                  nat.get('native_scale'),
                                  nat.get('raw_derivation', ''))
            gold_v2 = v2['gold']

            # The model's final answer value (from the evaluator's scoring path)
            # For SER/SERV: value_of on r answer; for DYN: json_value on v answer
            # We can get it from the ok field: if ok_v1=1, model matched v1 gold
            # For Q_v2, we need the model's actual answer value
            # The row has 'ok' but not the raw value. We re-derive it:
            model_value = None
            if v1_ok == 1:
                # Model matched v1 gold → model value ≈ v1 gold
                task_obj = next(t for t in tasks if t['uid'] == uid)
                model_value = task_obj['answer']  # v1 gold
            else:
                # Model didn't match v1 gold. We need the actual model output.
                # For zero-call re-scoring, we check if model_value could
                # match v2 gold. Since we don't store the model's raw value,
                # we check if v2 gold == v1 gold (if same, Q_v2 = Q_v1)
                pass

            if gold_v2 is not None and model_value is not None:
                q_v2 = int(close(model_value, gold_v2))
            elif gold_v2 is None:
                q_v2 = v1_ok  # no v2 gold, keep v1
            else:
                # Model value unknown (didn't match v1); can't determine Q_v2
                # without the raw answer. Mark as 'needs_raw_answer'
                q_v2 = None

            changed = (q_v2 is not None) and (q_v2 != v1_ok)
            res_v1['n'] += 1
            res_v1['Q_v1_sum'] += v1_ok
            if q_v2 is not None:
                res_v1['Q_v2_sum'] += q_v2
                if changed:
                    res_v1['changes'] += 1
            per_task.append(dict(
                uid=uid, Q_v1=v1_ok, Q_v2=q_v2, changed=changed,
                v1_gold=next(t for t in tasks if t['uid'] == uid)['answer'],
                v2_gold=gold_v2, v2_source=v2['gold_source'],
                v2_reason=v2['reason'],
                needs_raw_answer=q_v2 is None))

        results[cid] = dict(
            summary=dict(n=res_v1['n'],
                         Q_v1=round(res_v1['Q_v1_sum'] / max(1, res_v1['n']), 4),
                         Q_v2=round(res_v1['Q_v2_sum'] / max(1, res_v1['n']), 4),
                         changes=res_v1['changes']),
            per_task=per_task)

    contract_sha = hashlib.sha256(
        Path(ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2.py')
        .read_bytes()).hexdigest()[:16]

    out = dict(
        contract='v2_amended (unit conversion before conflict check)',
        contract_sha=contract_sha,
        method='zero-call re-scoring of frozen Cube clean results against v2 gold',
        limitation='model raw answer only recoverable when Q_v1=1 (matched v1 gold); '
                   'Q_v1=0 tasks need raw answer from ledger to determine Q_v2',
        configs=results,
        zero_model_calls=True)
    (OUT / 'RESCORE_V2.json').write_text(json.dumps(out, indent=1, default=str))

    for cid, r in results.items():
        s = r['summary']
        print(f'{cid}: Q_v1={s["Q_v1"]} Q_v2={s["Q_v2"]} changes={s["changes"]}/{s["n"]}')


if __name__ == '__main__':
    run()
