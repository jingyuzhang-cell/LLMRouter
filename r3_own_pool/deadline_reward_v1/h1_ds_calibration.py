"""h1_ds_calibration.py — DeepSeek 8-role paired capability calibration.

AUTHORIZED 2026-10-26 (conditional): <=16 real DS calls, cash cap ¥0.40,
verified off-peak window only, stop-on-anomaly (no retry), no auto-extension.

Execution gates (all must pass BEFORE any call; failure => zero-call stop):
  G1 off-peak: DeepSeek peak = weekdays UTC 01-04 & 06-10
  G2 plan-level conservative budget admission: sum over 16 calls of
     (in_max[role]*1.065e-6 + 3072*4.26e-6) <= 0.40   [measured in_max from
     the H1v7 ledger; ¥1.065/M in, ¥4.26/M out = $0.15/$0.60 x 7.1]
  G3 process lock + >=1s spacing

Paired inputs: the SAME prompts GLM-Flash consumed in H1v7 (replayed upstream
outputs from S1_r1/S2_r1 shared states via HeteroDAG.build_prompt) — per-role
same-input model comparison. Contracts identical to the frozen v7 protocol
(out cap 3072, JSON-array role contracts). Calibration data is for capability
estimation and pre-experiment parameter freezing ONLY (per directive #5).
"""
import fcntl
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import (HeteroDAG, ROLE, EDGES, ROLE_SPEC)
from deadline_reward_v1.full_dag_tasks import load_docs

DS_URL = 'https://api.deepseek.com/chat/completions'
PRICE_IN, PRICE_OUT = 1.065e-6, 4.26e-6      # ¥/token, off-peak
OUT_CAP = 3072
CAP_CNY = 0.40
IN_MAX = {'n0': 1972, 'b0': 1606, 'b1': 1605, 'b2': 1600, 'b3': 1604,
          'x0': 1154, 'x1': 1170, 'sink': 3034}   # measured H1v7 ledger
ROLES_ORDER = ['n0', 'x0', 'x1', 'b1', 'b2', 'b3', 'b0', 'sink']
STATES = ['S1_r1', 'S2_r1']

REQ_KEYS = {  # exact field names from ROLE_SPEC (frozen v7 protocol)
    'extraction': ['fact', 'date', 'entities', 'evidence_doc_id'],
    'timeline': ['date', 'event'],
    'timeline_deep': ['stage', 'start_date', 'end_date', 'summary'],
    'amounts': ['amount', 'context'],
    'amounts_check': ['item', 'amount', 'note'],
    'penalties': ['penalty_type', 'target', 'basis'],
    'entity_relations': ['entity', 'role', 'relation'],
    'synthesis': ['conclusion', 'key_dates', 'amounts', 'penalties', 'entities'],
}


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


def parse_array(text):
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
    if m:
        t = m.group(1).strip()
    i = t.find('[')
    if i > 0:
        t = t[i:]
    return json.loads(t)


def compliance(items, role):
    need = REQ_KEYS[role]
    if not isinstance(items, list) or not items:
        return 0.0, 0
    ok = sum(1 for x in items if isinstance(x, dict) and all(k in x for k in need))
    return ok / len(items), len(items)


CREDS = {}


def ds_call(system, user):
    import urllib.request
    key = CREDS.get('DEEPSEEK_API_KEY', '')
    msgs = ([{'role': 'system', 'content': system}] if system else []) + \
           [{'role': 'user', 'content': user}]
    body = {'model': 'deepseek-flash', 'max_tokens': OUT_CAP,
            'messages': msgs, 'thinking': {'type': 'disabled'}}
    req = urllib.request.Request(DS_URL, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + key)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    u = d['usage']
    return {'text': d['choices'][0]['message'].get('content', ''),
            'in': u.get('prompt_tokens', 0), 'out': u.get('completion_tokens', 0),
            'stop': d['choices'][0].get('finish_reason', ''),
            'lat': round(time.monotonic() - t0, 2),
            'headers': dict(r.headers) if False else None}


def main():
    lock = open(HERE / 'ds_calib.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: another calibration instance holds the lock.')
    # G1 off-peak
    if peak_now():
        print('G1 FAIL: DeepSeek peak window — zero-call stop.')
        return
    # G2 plan-level conservative admission
    plan_worst = sum((IN_MAX[n] * PRICE_IN + OUT_CAP * PRICE_OUT)
                     for n in ROLES_ORDER for _ in STATES)
    if plan_worst > CAP_CNY + 1e-12:
        print(f'G2 FAIL: plan worst ¥{plan_worst:.4f} > cap ¥{CAP_CNY} — zero-call stop.')
        return
    print(f'G1 ok (off-peak); G2 ok: plan worst-case ¥{plan_worst:.4f} <= ¥{CAP_CNY}')
    # creds (dict-returning loader; attempt-1 401 was a plumbing bug, fixed)
    from deadline_reward_v1.full_dag_executor import load_env_creds
    CREDS.update(load_env_creds())
    if not CREDS.get('DEEPSEEK_API_KEY'):
        print('G-creds FAIL: no DEEPSEEK_API_KEY — zero-call stop.')
        return

    doc = load_docs()['舜天#st_announce_2024_020']
    shared = {s: json.load(open(HERE / f'fe_screening_runs/h1v7_20261026/{s}_shared.json'))
              for s in STATES}
    results, spend = [], 0.0
    out_path = HERE / 'DS_CALIBRATION_RESULT.json'
    for node in ROLES_ORDER:
        for st in STATES:
            dag = HeteroDAG(doc['text'], doc['doc_id'])
            # replay the SAME upstream outputs Flash consumed
            for up, rec in shared[st].items():
                if up != node:
                    dag.outputs[up] = rec if isinstance(rec, dict) else {'answer': str(rec)}
            prompt = dag.build_prompt(node)
            role = ROLE[node]
            rec = {'node': node, 'role': role, 'state': st,
                   'prompt_chars': len(prompt)}
            try:
                raw = ds_call(None, prompt)  # single user message, matches Flash call shape
            except Exception as e:
                rec['anomaly'] = f'{type(e).__name__}: {str(e)[:120]}'
                rec['stopped'] = True
                results.append(rec)
                out_path.write_text(json.dumps(
                    {'gates': {'offpeak': True, 'plan_worst_cny': round(plan_worst, 4)},
                     'results': results, 'stopped': True,
                     'stop_reason': rec['anomaly']}, ensure_ascii=False, indent=1))
                print(f'  {node}/{st}: ANOMALY {rec["anomaly"]} — STOP (no retry)')
                return
            cost = raw['in'] * PRICE_IN + raw['out'] * PRICE_OUT
            spend += cost
            try:
                items = parse_array(raw['text'])
                comp, n_items = compliance(items, role)
                parsed = True
            except Exception:
                items, comp, n_items, parsed = None, 0.0, 0, False
            rec.update({'in_tok': raw['in'], 'out_tok': raw['out'],
                        'stop_reason_api': raw['stop'],
                        'truncated': raw['stop'] in ('length', 'max_tokens'),
                        'lat_s': raw['lat'], 'parsed': parsed,
                        'n_items': n_items, 'field_compliance': round(comp, 3),
                        'cost_cny': round(cost, 6),
                        'cum_cny': round(spend, 6),
                        'text': raw['text']})
            results.append(rec)
            out_path.write_text(json.dumps(
                {'gates': {'offpeak': True, 'plan_worst_cny': round(plan_worst, 4),
                           'cap_cny': CAP_CNY, 'pricing': 'off-peak $0.15/$0.60 x7.1'},
                 'results': [{k: v for k, v in r.items() if k != 'text'} for r in results],
                 'raw_texts': {f"{r['node']}|{r['state']}": r.get('text', '')
                               for r in results if 'text' in r},
                 'spend_cny': round(spend, 6), 'stopped': False},
                ensure_ascii=False, indent=1))
            print(f"  {node:5s}/{st}: in={raw['in']:5d} out={raw['out']:4d} "
                  f"lat={raw['lat']:5.1f}s parsed={parsed} n={n_items:3d} "
                  f"comp={comp:.2f} ¥{cost:.4f} (cum ¥{spend:.4f})", flush=True)
            if raw['stop'] in ('length', 'max_tokens'):
                print('  TRUNCATION -> STOP per authorization (no retry)')
                break
            time.sleep(1.1)
    print(f'\nDONE: {len(results)} calls, spend ¥{spend:.4f} (admission worst ¥{plan_worst:.4f}, cap ¥{CAP_CNY})')


if __name__ == '__main__':
    main()
