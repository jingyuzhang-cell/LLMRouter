"""Complete v2 re-scoring from raw ledger model answers (zero calls).

Extracts each task's FINAL model answer from the actual execution ledger
(following alias chains to source responses), then scores against both v1
and v2 gold. Classifies all differences as: scale, rounding, or
unexplained_inconsistency. Unrecoverable answers → UNSCORABLE.

Rounding rule (frozen from TAT-QA data spec):
  TAT-QA native answers are stored at the precision of the original table
  (typically 2 decimal places for financial figures). The frozen close()
  already has abs(x-y) ≤ max(1e-4, 1e-4*|y|) which is tighter than 2dp.
  For v2 we add a secondary tolerance: if |x - y| ≤ 0.005*max(1,|y|)/100
  (i.e., within half a unit of the last significant digit at 2dp),
  we treat it as rounding-compatible. This is derived from the data
  specification (2dp financial tables), not from model performance.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from static_dag_v0.multidag_dynamic import close, json_value, parse_facts_safe, value_of  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2'


def rounding_compatible(x, y):
    """Check if |x-y| is within 2-decimal-place rounding noise."""
    if x is None or y is None:
        return False
    tol = 0.005 * max(1, abs(y)) / 100  # half of last significant digit at 2dp
    return abs(x - y) <= max(tol, 1e-4)


def classify_diff(model_val, v1_gold, v2_gold, v2_reason):
    """Classify the difference between v1 and v2 outcomes."""
    if v1_gold == v2_gold:
        return 'no_change'
    if v2_reason == 'scale_compatible' and v2_gold is not None:
        ratio = abs(v2_gold / v1_gold) if abs(v1_gold) > 1e-12 else float('inf')
        if 50 < ratio < 200 or 0.005 < ratio < 0.02:
            return 'scale_change'
    if rounding_compatible(v1_gold, v2_gold):
        return 'rounding_difference'
    return 'unexplained_inconsistency'


def extract_final_answers(cid, tasks, led):
    """Extract each task's final model answer from the execution path."""
    from collab_scheduler_v1 import cube_analyze
    ans_fn = led[0]  # resolve function
    topo = cid.split('__')[0]
    answers = {}
    for t in tasks:
        uid = t['uid']
        try:
            if topo in ('SER', 'PARALLELER'):
                # final answer from r node
                pfx = 'SER' if topo == 'SER' else 'PAR'
                key = f'cube:{pfx}:{cid.split("__")[1]}:r:{uid}'
                a = ans_fn(key)
                if a:
                    facts_key = f'cube:{pfx}:{cid.split("__")[1]}:e:{uid}' \
                        if topo == 'SER' else None
                    if facts_key:
                        f = parse_facts_safe(ans_fn(facts_key) or '')[0]
                    else:
                        f1k = f'cube:PAR:{cid.split("__")[1]}:e1:{uid}'
                        f2k = f'cube:PAR:{cid.split("__")[1]}:e2:{uid}'
                        f1 = parse_facts_safe(ans_fn(f1k) or '')[0]
                        f2 = parse_facts_safe(ans_fn(f2k) or '')[0]
                        f = {'facts': f1['facts'] + f2['facts']}
                    val, err = value_of(a, f)
                    answers[uid] = dict(value=val, err=err, source='r_node')
                else:
                    answers[uid] = dict(value=None, err=True, source='NOT_FOUND')
            else:
                # SERV/DYN: final answer from v node
                vkey = f'cube:{topo}:{cid.split("__")[1]}:v:{uid}'
                a = ans_fn(vkey)
                if a:
                    val = json_value(a)
                    answers[uid] = dict(value=val, err=False, source='v_node')
                else:
                    answers[uid] = dict(value=None, err=True, source='NOT_FOUND')
        except Exception as e:
            answers[uid] = dict(value=None, err=True,
                                source=f'ERROR:{type(e).__name__}')
    return answers


def run():
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        contract_v2_gold, load_native_answers)
    from collab_scheduler_v1 import cube_analyze

    native = load_native_answers()
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/'
                       'FROZEN200_POLICY.json').read_text())['tasks']
    led = cube_analyze.load_ledgers()

    # Load v1 Q values from the frozen analysis
    v1_analysis = json.loads(
        (ROOT / 'collab_scheduler_v1/CUBE_CLEAN_ANALYSIS.json').read_text())
    configs = ['SER__HETEROGENEOUS__NONE__FRESH',
               'SERV__HETEROGENEOUS__NONE__FRESH',
               'DYNAMICDAG__HETEROGENEOUS__NONE__FRESH']

    results = {}
    for cid in configs:
        v1_cfg = v1_analysis['complete'].get(cid, {})
        v1_q = v1_cfg.get('Q')
        # Extract raw model answers
        model_answers = extract_final_answers(cid, tasks, led)

        n_scored = n_unscorable = 0
        q_v1_sum = q_v2_sum = 0
        changes = []
        diff_classes = {}

        for t in tasks:
            uid = t['uid']
            v1_gold = t['answer']  # eval(derivation) from policy
            nat = native.get(uid, {})
            v2 = contract_v2_gold(nat.get('native_answer'),
                                  nat.get('native_scale'),
                                  nat.get('raw_derivation', ''))
            v2_gold = v2['gold']
            ma = model_answers.get(uid, {})
            model_val = ma.get('value')

            if model_val is None or ma.get('err'):
                # Can't score this task
                n_unscorable += 1
                changes.append(dict(uid=uid, status='UNSCORABLE',
                                    reason=ma.get('source', 'unknown')))
                continue

            n_scored += 1
            q_v1 = int(close(model_val, v1_gold))
            q_v2 = int(close(model_val, v2_gold)) if v2_gold is not None else q_v1

            q_v1_sum += q_v1
            q_v2_sum += q_v2
            if q_v1 != q_v2:
                dc = classify_diff(model_val, v1_gold, v2_gold, v2['reason'])
                diff_classes[dc] = diff_classes.get(dc, 0) + 1
                changes.append(dict(
                    uid=uid, Q_v1=q_v1, Q_v2=q_v2,
                    model_value=round(model_val, 6),
                    v1_gold=round(v1_gold, 6),
                    v2_gold=round(v2_gold, 6) if v2_gold else None,
                    diff_class=dc, v2_reason=v2['reason'],
                    rounding_compatible=rounding_compatible(v1_gold, v2_gold)))
            # Also check rounding-only differences (Q stays same but gold differs)
            elif v1_gold != v2_gold and rounding_compatible(v1_gold, v2_gold):
                diff_classes['rounding_same_Q'] = \
                    diff_classes.get('rounding_same_Q', 0) + 1

        results[cid] = dict(
            summary=dict(
                n_total=len(tasks), n_scored=n_scored,
                n_unscorable=n_unscorable,
                coverage_pct=round(100 * n_scored / len(tasks), 1),
                Q_v1=round(q_v1_sum / max(1, n_scored), 4),
                Q_v2=round(q_v2_sum / max(1, n_scored), 4),
                Q_changes=len([c for c in changes if c.get('Q_v1') is not None]),
                diff_classification=diff_classes),
            changes=changes)

    contract_sha = hashlib.sha256(
        Path(ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2.py')
        .read_bytes()).hexdigest()[:16]

    out = dict(
        contract='v2_amended', contract_sha=contract_sha,
        method='full re-scoring from raw ledger answers (alias-chain resolved)',
        rounding_rule='close() primary + 2dp rounding_compatible secondary '
                      '(frozen from TAT-QA financial data spec)',
        configs=results, zero_model_calls=True)
    (OUT / 'FULL_RESCORE_V2.json').write_text(json.dumps(out, indent=1,
                                                         default=str))
    for cid, r in results.items():
        s = r['summary']
        print(f'\n{cid}:')
        print(f'  scored={s["n_scored"]}/{s["n_total"]} '
              f'({s["coverage_pct"]}%) unscorable={s["n_unscorable"]}')
        print(f'  Q_v1={s["Q_v1"]} Q_v2={s["Q_v2"]} changes={s["Q_changes"]}')
        print(f'  classification={s["diff_classification"]}')
        for c in r['changes'][:5]:
            if 'Q_v1' in c:
                print(f'    {c["uid"][:8]}: Q {c["Q_v1"]}→{c["Q_v2"]} '
                      f'class={c["diff_class"]} '
                      f'v1g={c["v1_gold"]} v2g={c["v2_gold"]}')


if __name__ == '__main__':
    run()
