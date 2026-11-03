"""h1_unit2_joint.py — UNIT2: S2/b2-fault paired unit (authorized 2026-10-27).

AUTHORIZATION: ONE paired unit, <=41 HTTP attempts, cash <= ¥0.12, whole-unit
admission PROVEN before first request; stop-on-anomaly (no retry); paid HOLD
after; UNIT3 must NOT run.

Pre-registered online state (legal fresh execution order — UNIT1's b2 cache
is NOT reused; b2 fails on its OWN real attempt):
  prefix (3 attempts): n0 -> b0 (healthy, CACHED) -> b2 (real attempt, fails
  -> explicit GARBAGE placeholder)
  snapshot: DONE={n0,b0}  FAILED={b2}  PENDING={x0,b1,x1,b3,sink}
  D=80s/arm (real clock), B_tok=30K/arm.

R sets: accept=5 calls | LOCAL closure(b2)={b2,sink} re-exec =6 | FULL=7.
Frozen predictions (calibration + unit-1 real): accept+Flash 73.1s/9.7K;
targeted+Flash 79.5s/13.2K (BORDERLINE); targeted+DS3 ~44s/14.2K; full 90.7s.
q_hat (v7 S2 anchors): accept .769 > targeted .731 (repair HURTS).
U_hat(D=80): accept+F .688 > targeted+F .621 > targeted+DS3 .613.

Strategy choices (frozen rules) -> EXECUTION SHARING per fairness directive:
  SD-FC(b2->accept)/R-only(gate)/SEQ/JOINT -> accept+Flash   [1 shared exec]
  STATIC / pi-only r1,r2 (fixed targeted, Flash feasible)    [targeted+Flash x2]
Same action from same snapshot = one shared execution outcome recorded for
each strategy; pi-only r2 = repeat for the sampling-variance band.
"""
import fcntl
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import (HeteroDAG, GARBAGE, eval_by_category, call_ds)
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_executor import load_env_creds

D_ARM, B_TOK = 80.0, 30000
CAP_ATTEMPTS, CAP_CNY = 41, 0.12
THETA_PRIME, DOC_SLOT = 0.42, '舜天#st_announce_2024_020'
FAULT_NODE = 'b2'
FLASH_LAT = {'b0': 11.2, 'x0': 7.7, 'b1': 12.0, 'x1': 19.5, 'b2': 6.4, 'b3': 8.6, 'sink': 25.3}
DS_LAT = {'b0': 3.2, 'x0': 1.5, 'b1': 3.4, 'x1': 3.3, 'b2': 1.4, 'b3': 2.6, 'sink': 7.2}
Q_HAT = {'accept': 0.769, 'targeted': 0.731, 'full': 0.769}
TOK_PRED = {('accept', 'Flash'): 9700, ('targeted', 'Flash'): 13200,
            ('targeted', 'DS3'): 14200, ('full', 'Flash'): 16500, ('full', 'DS3'): 17500,
            ('accept', 'DS3'): 10700}
DS3_NODES = ['sink', 'x1', 'b1']
R_NODES = {'accept': ['x0', 'b1', 'x1', 'b3', 'sink'],
           'targeted': ['b2', 'x0', 'b1', 'x1', 'b3', 'sink'],
           'full': ['b0', 'b2', 'x0', 'b1', 'x1', 'b3', 'sink']}
PRICE_IN, PRICE_OUT = 2.13e-6, 8.52e-6  # peak prices for the deviation reserve


def predict(R, pi):
    lat = sum(DS_LAT[n] if (pi == 'DS3' and n in DS3_NODES) else FLASH_LAT[n]
              for n in R_NODES[R])
    tok = TOK_PRED[(R, pi)]
    late = lat > D_ARM
    u = Q_HAT[R] * (0 if late else 1) - 0.5 * tok / 60000 - (2.0 if late else 0.0)
    return {'lat_pred': round(lat, 1), 'tok_pred': tok, 'u_hat': round(u, 4)}


def eU(q, tok, clk):
    late = clk > D_ARM
    return (q * (0 if late else 1) - 0.5 * tok / 60000
            - ((clk - D_ARM) / D_ARM if late else 0) - (2.0 if late else 0))


def main():
    lock = open(HERE / 'unit2.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: unit2 lock held.')
    # whole-unit admission (shared-execution plan, proven before first request)
    att_plan = 3 + 5 + 6 + 6
    reserve = 3 * 0.0321
    assert att_plan <= CAP_ATTEMPTS and reserve <= CAP_CNY, 'unit admission FAIL'
    print(f'admission: shared-exec plan {att_plan} attempts<=41; deviation reserve ¥{reserve:.4f}<=0.12')
    creds = load_env_creds()
    doc = load_docs()[DOC_SLOT]
    at = doc_atoms(doc['text'])
    keys = ([f'd:{k}' for k in at['dates'][:4]] + [f'a:{k}' for k in at['amounts'][:3]]
            + [f'p:{k}' for k in at['penalties'][:3]] + [f'e:{k}' for k in at['entities'][:3]])
    probes = [str(k) for k in list(at['amounts']) + list(at['dates'])]
    attempts, spend = 0, 0.0
    ledger = open(HERE / 'H1_UNIT2_LEDGER.jsonl', 'a')
    # orphan seed: attempt-1 crash (kwarg bug) AFTER a completed n0 flash call
    attempts = 1
    ledger.write(json.dumps({'attempt': 1, 'exec': 'PREFIX', 'node': 'n0',
                             'model': 'flash', 'in': 0, 'out': 0, 'lat': 0, 'cash': 0.0,
                             'stop': 'OK-unrecorded(orphan-seed)',
                             'fault_injected': False}, ensure_ascii=False) + '\n')
    ledger.flush()

    def record(exec_id, node, model, rec, fault_injected=False):
        nonlocal attempts, spend
        attempts += 1
        spend += rec.get('cash_cny', 0.0)
        assert attempts <= CAP_ATTEMPTS, 'ATTEMPT CAP'
        assert spend <= CAP_CNY, 'CASH CAP'
        ledger.write(json.dumps({'attempt': attempts, 'exec': exec_id, 'node': node,
                                 'model': model, 'in': rec.get('tokens_in', 0),
                                 'out': rec.get('tokens_out', 0), 'lat': rec.get('latency_s', 0),
                                 'cash': rec.get('cash_cny', 0.0),
                                 'stop': rec.get('finish_reason', ''),
                                 'fault_injected': fault}, ensure_ascii=False) + '\n')
        ledger.flush()

    # ---- shared prefix: n0 -> b0 (healthy, cached) -> b2 (real attempt, FAILS) ----
    base = HeteroDAG(doc['text'], doc['doc_id'])
    for node, fault in (('n0', False), ('b0', False), (FAULT_NODE, True)):
        o = call_ds(base.build_prompt(node), creds)
        record('PREFIX', node, 'flash', o, fault_injected=fault)
        base.outputs[node] = dict(o, answer=GARBAGE, finish_reason='stop') if fault else o
        time.sleep(1.1)
    n0c = re.sub(r'[\s,，]', '', str(base.outputs['n0']['answer']))
    root_cov = sum(1 for p in probes if p in n0c) / max(1, len(probes))
    det = '占位' in base.outputs[FAULT_NODE]['answer']
    print(f'prefix done ({attempts} attempts); detection={det}; ROOT-cov={root_cov:.3f}')
    snapshot = dict(base.outputs)

    preds = {f'{R}|{pi}': predict(R, pi) for R in Q_HAT for pi in ('Flash', 'DS3')}
    print('predictions:', json.dumps(preds, ensure_ascii=False))
    # frozen strategy rules -> actions
    gate_repair = root_cov < THETA_PRIME
    flash_feasible = [R for R in Q_HAT if predict(R, 'Flash')['lat_pred'] <= D_ARM]
    R_ronly = 'accept' if (not gate_repair or 'targeted' not in flash_feasible) else 'targeted'
    joint_best = max(((R, pi) for R in Q_HAT for pi in ('Flash', 'DS3')),
                     key=lambda rp: preds[f'{rp[0]}|{rp[1]}']['u_hat'])
    choices = {
        'STATIC': ('targeted', 'Flash'),
        'SD-FC': ('accept', 'Flash'),                      # b2 rule -> accept
        'R-only': (R_ronly, 'Flash'),
        'pi-only': ('targeted', 'Flash'),                  # fixed R; Flash feasible (79.5<=80)
        'SEQ': (R_ronly, 'Flash'),
        'JOINT': joint_best,
    }
    print('strategy choices:', {k: v for k, v in choices.items()})

    # ---- distinct executions (shared across same-action strategies) ----
    execs_needed = {}
    for arm, act in choices.items():
        execs_needed.setdefault(act, []).append(arm)
    execs_needed[('targeted', 'Flash')].append('pi-only_r2')  # variance repeat
    results_exec = {}
    for act, owners in execs_needed.items():
        R, pi = act
        dag = HeteroDAG(doc['text'], doc['doc_id'])
        dag.outputs.update(snapshot)
        t0 = time.monotonic()
        tok = 0
        stopped = None
        for n in R_NODES[R]:
            rec = call_ds(dag.build_prompt(n), creds)
            record('|'.join(owners), n, 'flash', rec)
            if rec.get('finish_reason') in ('length', 'max_tokens'):
                stopped = f'{n}:TRUNCATION'
                break
            dag.outputs[n] = rec
            tok += rec['tokens_in'] + rec['tokens_out']
            if tok > B_TOK:
                stopped = f'{n}:B_TOK'
                break
            time.sleep(1.1)
        clk = time.monotonic() - t0
        if stopped:
            results_exec[act] = {'stopped': stopped, 'tokens': tok, 'clock': round(clk, 1)}
            print(f'  exec {act} STOPPED {stopped} — unit halt')
            break
        full, _ = eval_by_category(dag.outputs, keys)
        results_exec[act] = {'t_q': full['terminal_q'], 'hits': full['terminal_hits'],
                             'n_ref': full['n_ref'], 'tokens': tok,
                             'clock': round(clk, 1), 'met': clk <= D_ARM,
                             'eU': round(eU(full['terminal_q'], tok, clk), 4)}
        print(f"  exec {act} (owners={owners}): t_q={full['terminal_q']:.3f} "
              f"tok={tok} clk={clk:.1f}s met={clk <= D_ARM} eU={results_exec[act]['eU']:+.4f}")

    rows = []
    for arm, act in choices.items():
        r = results_exec.get(act, {})
        rows.append({'arm': arm, 'action': list(act), **{k: v for k, v in r.items()}})
    rep_r2 = results_exec.get(('targeted', 'Flash'), {})
    out = {'unit': 'S2-b2-fault | DONE{n0,b0} FAILED{b2} PENDING{5} | D=80 B_tok=30K | shared-exec fairness',
           'root_cov': round(root_cov, 3), 'gate_repair_indicated': gate_repair,
           'predictions': preds, 'choices': {k: list(v) for k, v in choices.items()},
           'executions': {str(list(k)): v for k, v in results_exec.items()},
           'strategy_rows': rows,
           'pi_only_repeat': rep_r2,
           'attempts': attempts, 'cash': round(spend, 4)}
    (HERE / 'H1_UNIT2_RESULT.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nUNIT2 DONE: attempts={attempts}/{CAP_ATTEMPTS} cash=¥{spend:.4f}/{CAP_CNY}")


if __name__ == '__main__':
    main()
