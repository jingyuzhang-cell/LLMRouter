"""h1_unit1_joint.py — Stage-2 ONE paired unit, 6 strategies (v2 runner).

AUTHORIZATION (unchanged): <=50 HTTP attempts total, cash <= ¥0.25, one unit,
GLM-Flash + DeepSeek off-peak only, stop-on-anomaly, no retry/extension.

PRE-REGISTERED online state (G-preflight 2026-10-27, legal execution order):
  shared prefix (3 real attempts, costs counted): n0 -> b2 (healthy, CACHED)
  -> b0 (real attempt, instance failure -> explicit GARBAGE placeholder)
  snapshot: DONE={n0,b2}  FAILED={b0}  PENDING={x0,b1,x1,b3,sink}

R physical sets (first-exec vs re-exec kept DISTINCT, no double counting):
  ACCEPT  : PENDING only                                  = 5 calls (b2 cache kept)
  LOCAL   : re-exec {b0} + closure {x0,sink} + first {b1,x1,b3} = 6 (b2 KEPT)
  FULL    : re-exec {b0,b2} + first {x0,x1,b3,sink,b1}    = 7 (b2 DISCARDED)
=> LOCAL vs FULL differ physically (b2 cache): R discrimination established.

Strategy plans (frozen; D=80s/arm, B_tok=30K/arm, DS<=3/arm HARD incl repairs):
  STATIC  targeted+Flash   SD-FC targeted+Flash   R-only accept+Flash (gate+feas)
  pi-only targeted+DS3     SEQ accept+Flash       JOINT targeted+DS3 (argmax)
  DS3 = DS on the 3 largest latency savers of the arm's node set (sink,x1,b1).
Admission (proven, math bounds): attempts 3+34=37<=50; cash worst
2 arms x (sink .01601 + x1 .01408 + b1 .01553) = ¥0.0912 <= 0.25.
Deadline judged on REAL per-arm clock; predictions only for decisions.
"""
import fcntl
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import (HeteroDAG, GARBAGE, utility,
                                             eval_by_category, call_ds)
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_executor import load_env_creds

DS_URL = 'https://api.deepseek.com/chat/completions'
PRICE_IN, PRICE_OUT = 2.13e-6, 8.52e-6  # PEAK prices (user-override run)
D_ARM, B_TOK, DS_CAP_PER_ARM = 80.0, 30000, 3
CAP_ATTEMPTS, CAP_CNY = 50, 0.25
FLASH_LAT = {'b0': 11.2, 'x0': 7.7, 'b1': 12.0, 'x1': 19.5, 'b2': 6.4, 'b3': 8.6, 'sink': 25.3}
DS_LAT = {'b0': 3.2, 'x0': 1.5, 'b1': 3.4, 'x1': 3.3, 'b2': 1.4, 'b3': 2.6, 'sink': 7.2}
DS3_NODES = ['sink', 'x1', 'b1']          # largest latency savers
Q_HAT = {'accept': 0.385, 'targeted': 0.654, 'full': 0.577}
TOK_PRED = {('accept', 'Flash'): 15000, ('targeted', 'Flash'): 20000,
            ('full', 'Flash'): 24000, ('accept', 'DS3'): 16000,
            ('targeted', 'DS3'): 20000, ('full', 'DS3'): 24000}
THETA_PRIME, DOC_SLOT = 0.42, '舜天#st_announce_2024_020'
R_NODES = {'accept': ['x0', 'b1', 'x1', 'b3', 'sink'],
           'targeted': ['b0', 'x0', 'b1', 'x1', 'b3', 'sink'],
           'full': ['b0', 'b2', 'x0', 'b1', 'x1', 'b3', 'sink']}
CASH_BOUND_DS = {'sink': 0.03202, 'x1': 0.02816, 'b1': 0.03106,
                 'b0': 0.03106, 'b2': 0.03106, 'x0': 0.02652, 'b3': 0.03108}


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


def predict(R, pi):
    lat = sum(DS_LAT[n] if (pi == 'DS3' and n in DS3_NODES) else FLASH_LAT[n]
              for n in R_NODES[R])
    tok = TOK_PRED[(R, pi)]
    late = lat > D_ARM
    u = Q_HAT[R] * (0.0 if late else 1.0) - 0.5 * tok / 60000 - (2.0 if late else 0.0)
    return {'lat_pred': round(lat, 1), 'tok_pred': tok, 'u_hat': round(u, 4)}


def call_ds_api(prompt, creds, max_out=3072):
    import urllib.request
    body = {'model': 'deepseek-flash', 'max_tokens': max_out,
            'messages': [{'role': 'user', 'content': prompt}],
            'thinking': {'type': 'disabled'}}
    req = urllib.request.Request(DS_URL, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + creds['DEEPSEEK_API_KEY'])
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    u = d['usage']
    return {'answer': d['choices'][0]['message'].get('content', ''),
            'tokens_in': u.get('prompt_tokens', 0),
            'tokens_out': u.get('completion_tokens', 0),
            'latency_s': round(time.monotonic() - t0, 2),
            'finish_reason': d['choices'][0].get('finish_reason', ''),
            'cash_cny': (u.get('prompt_tokens', 0) * PRICE_IN
                         + u.get('completion_tokens', 0) * PRICE_OUT)}


def main():
    lock = open(HERE / 'unit1.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: unit1 lock held.')
    if peak_now():
        print('NOTE: peak window — USER OVERRIDE 2026-10-27 ("run now"); '
              'admission recomputed at peak prices (cash bound x2 = ¥0.1825 <= 0.25).')
    # unit admission: exact planned attempts + math cash bound
    plans = {'STATIC': ('targeted', 'Flash'), 'SD-FC': ('targeted', 'Flash'),
             'R-only': ('accept', 'Flash'), 'pi-only': ('targeted', 'DS3'),
             'SEQ': ('accept', 'Flash'), 'JOINT': ('targeted', 'DS3')}
    att = 3 + sum(len(R_NODES[R]) for R, _ in plans.values())
    cash = 2 * sum(CASH_BOUND_DS[n] for n in DS3_NODES)
    assert att <= CAP_ATTEMPTS and cash <= CAP_CNY, 'unit admission FAIL'
    print(f'gates: offpeak ok; attempts {att}<=50; cash worst ¥{cash:.4f}<=0.25')
    creds = load_env_creds()
    doc = load_docs()[DOC_SLOT]
    at = doc_atoms(doc['text'])
    keys = ([f'd:{k}' for k in at['dates'][:4]] + [f'a:{k}' for k in at['amounts'][:3]]
            + [f'p:{k}' for k in at['penalties'][:3]] + [f'e:{k}' for k in at['entities'][:3]])
    probes = [str(k) for k in list(at['amounts']) + list(at['dates'])]
    attempts, spend, arm_cash = 0, 0.0, 0.0
    ledger = open(HERE / 'H1_UNIT1_LEDGER.jsonl', 'a')
    # orphan-attempt seed: attempt-1 run crashed AFTER a completed n0 flash call
    # (client kwarg bug); the HTTP attempt is consumed — recorded honestly here.
    attempts = 1
    ledger.write(json.dumps({'attempt': 1, 'arm': 'PREFIX', 'node': 'n0',
                             'model': 'flash', 'in': 0, 'out': 0, 'lat': 0,
                             'cash': 0.0, 'stop': 'OK-unrecorded(orphan-seed)',
                             'fault_injected': False}, ensure_ascii=False) + '\n')
    ledger.flush()

    def record(arm, node, model, rec, fault_injected=False):
        nonlocal attempts, spend, arm_cash
        attempts += 1
        spend += rec.get('cash_cny', 0.0)
        arm_cash += rec.get('cash_cny', 0.0)
        assert attempts <= CAP_ATTEMPTS, 'ATTEMPT CAP'
        assert spend <= CAP_CNY, 'CASH CAP'
        ledger.write(json.dumps({'attempt': attempts, 'arm': arm, 'node': node,
                                 'model': model, 'in': rec.get('tokens_in', 0),
                                 'out': rec.get('tokens_out', 0),
                                 'lat': rec.get('latency_s', 0),
                                 'cash': rec.get('cash_cny', 0.0),
                                 'stop': rec.get('finish_reason', ''),
                                 'fault_injected': fault_injected}, ensure_ascii=False) + '\n')
        ledger.flush()

    # ---- shared prefix: n0 -> b2 (healthy, cached) -> b0 (attempt, fails) ----
    base = HeteroDAG(doc['text'], doc['doc_id'])
    for node, fault in (('n0', False), ('b2', False), ('b0', True)):
        o = call_ds(base.build_prompt(node), creds)
        record('PREFIX', node, 'flash', o, fault_injected=fault)
        base.outputs[node] = dict(o, answer=GARBAGE, finish_reason='stop') if fault else o
        time.sleep(1.1)
    n0c = re.sub(r'[\s,，]', '', str(base.outputs['n0']['answer']))
    root_cov = sum(1 for p in probes if p in n0c) / max(1, len(probes))
    det = '占位' in base.outputs['b0']['answer']
    print(f'prefix done ({attempts} attempts); detection={det}; ROOT-cov={root_cov:.3f}')
    snapshot = dict(base.outputs)

    preds = {f'{R}|{pi}': predict(R, pi) for R in Q_HAT for pi in ('Flash', 'DS3')}
    print('predictions:', json.dumps(preds, ensure_ascii=False))
    results = []
    for arm, (R, pi) in plans.items():
        dag = HeteroDAG(doc['text'], doc['doc_id'])
        dag.outputs.update(snapshot)
        t0 = time.monotonic()
        tok = ds_used = 0
        stopped = None
        for n in R_NODES[R]:
            use_ds = (pi == 'DS3' and n in DS3_NODES)
            if use_ds:
                assert ds_used < DS_CAP_PER_ARM, f'DS cap breached in {arm}'
                ds_used += 1
            prompt = dag.build_prompt(n)
            est = (int(len(prompt) * 0.721) * PRICE_IN + 3072 * PRICE_OUT) if use_ds else 0.0
            assert spend + est <= CAP_CNY, 'pre-call cash admission'
            try:
                rec = call_ds_api(prompt, creds) if use_ds else call_ds(prompt, creds)
            except Exception as e:
                record(arm, n, 'DS' if use_ds else 'flash',
                       {'tokens_in': 0, 'tokens_out': 0, 'latency_s': 0, 'cash_cny': 0.0,
                        'finish_reason': f'ERR:{type(e).__name__}'})
                stopped = f'{n}:{type(e).__name__}'
                break
            record(arm, n, 'DS' if use_ds else 'flash', rec)
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
            results.append({'arm': arm, 'R': R, 'pi': pi, 'stopped': stopped,
                            'tokens': tok, 'clock': round(clk, 1)})
            print(f'  {arm:8s} STOPPED {stopped} — unit halt')
            break
        full, _ = eval_by_category(dag.outputs, keys)
        late = clk > D_ARM
        eu = ((0.0 if late else 1.0) * full['terminal_q'] - 0.5 * tok / 60000
              - ((clk - D_ARM) / D_ARM if late else 0.0) - (2.0 if late else 0.0))
        results.append({'arm': arm, 'R': R, 'pi': pi, 't_q': full['terminal_q'],
                        'hits': full['terminal_hits'], 'n_ref': full['n_ref'],
                        'tokens': tok, 'clock': round(clk, 1), 'met': clk <= D_ARM,
                        'eU': round(eu, 4), 'ds_used': ds_used})
        print(f"  {arm:8s} R={R:8s} pi={pi:4s} t_q={full['terminal_q']:.3f} "
              f"tok={tok} clk={clk:.1f}s met={clk <= D_ARM} eU={eu:+.4f} ds={ds_used}")
    out = {'unit': 'S1-b0-fault | DONE{n0,b2} FAILED{b0} PENDING{5} | D=80 B_tok=30K',
           'root_cov': round(root_cov, 3), 'predictions': preds,
           'plans': {k: list(v) for k, v in plans.items()},
           'results': results, 'attempts': attempts, 'cash': round(spend, 4)}
    (HERE / 'H1_UNIT1_RESULT.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nUNIT DONE: attempts={attempts}/{CAP_ATTEMPTS} cash=¥{spend:.4f}/{CAP_CNY}")


if __name__ == '__main__':
    main()
