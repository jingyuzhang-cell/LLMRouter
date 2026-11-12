#!/usr/bin/env python3
"""J2 dual-model probe (operator GO 2026-11-06): DS and GLM, 3 frozen J2 inputs x 2 replicates each = 12 calls.

Inputs are the three Stage A' J2 requests, byte for byte (each checked against the ledger hash). The J2 system
prompt is the frozen one. DS: deepseek-flash, thinking disabled, temperature 0, max_tokens 4000. GLM: GLM-5.3-Flash
on the subscription endpoint, reasoning_effort low, no thinking field, max_tokens 8000. Models run serially, DS
first. A model whose call fails (transport error or contract-guard fault) is stopped; the other model continues;
nothing is retried, no prompt or cap changes, no other model substituted. Missing results are never scored as zero.
Caps: 12 calls / 100K tokens / ¥0.30 (accounting price for both models).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC_DIR = HERE.parent / 'sc_e1_1'
sys.path[:0] = [str(SC_DIR), str(HERE.parent)]
import sc_e1_1_runner as R  # noqa: E402

OUT = HERE / 'run'
MODELS = ('ds', 'glm')
INPUT_ARMS = ('Static', 'Fixed-Recovery', 'Joint-Dynamic')
REPS = 2
CAPS = dict(calls=12, tokens=100_000, yuan=0.30)
MAX_TOKENS = {'ds': 4000, 'glm': 8000}


def inputs():
    done = [r for r in R.read_ledger(SC_DIR / 'canary_A2/LEDGER.jsonl') if r['phase'] == 'done' and r['node'] == 'J2']
    out = []
    for i, arm in enumerate(INPUT_ARMS, 1):
        row = next(r for r in done if r['arm'] == arm)
        user = row['request_body']['messages'][-1]['content']
        if hashlib.sha256(user.encode('utf-8')).hexdigest() != row['user_sha256'] or row['system_sha256'] != R._sha(R.J2_SYS):
            raise SystemExit(f'REFUSED: Stage A\' J2 input {arm} does not match its ledger hash')
        out.append(dict(input_id=f'J2_in{i}', source_arm=arm, user=user, user_sha256=row['user_sha256']))
    return out


def plan():
    return [(m, inp['input_id'], rep) for m in MODELS for inp in inputs() for rep in range(1, REPS + 1)]


class ProbeBudget(R.Budget):
    def reached(self):
        for name, used in (('tokens', self.tokens), ('yuan', self.yuan)):
            if used >= self.caps[name]:
                return f'{name} cap reached: {used} >= {self.caps[name]}'
        return None


def call_one(transport, ledger, budget, model, inp, rep):
    """One probe call with the write-ahead ledger. Returns (record, failure or None)."""
    system, user, max_tokens = R.J2_SYS, inp['user'], MAX_TOKENS[model]
    rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), condition='probe', rep=rep, arm=model, node='J2', backend=model,
               input_id=inp['input_id'], max_tokens=max_tokens, system_sha256=R._sha(system), user_sha256=R._sha(user),
               chars_in=len(system) + len(user), injected=False)
    budget.preflight(model, system, user, max_tokens)
    url, body = transport.describe(model, system, user, max_tokens)
    ledger.write({**rec, 'phase': 'sent', 'url': url, 'request_body': body})
    try:
        res = transport.call(model, system, user, max_tokens)
    except Exception as exc:
        budget.book(model, 0, 0)
        detail = f'{type(exc).__name__}: {exc}'[:300]
        error_body = getattr(exc, 'read', lambda: b'')()
        ledger.write({**rec, 'phase': 'done', 'url': url, 'request_body': body, 'raw_response': None, 'text': '',
                      'stop': 'transport_error', 'error': detail,
                      'error_body': error_body.decode('utf-8', 'replace')[:2000] if error_body else None})
        return None, f'transport error: {detail}'
    cost = budget.book(model, res['in'], res['out'])
    fault, _ = R.guard('J2', res)
    reported = str(res.get('response_model') or '')
    if not fault and reported and R.MODEL_FAMILY[model] not in reported.lower():
        fault = f'provider reports model {reported!r}'
    ledger.write({**rec, 'phase': 'done', 'url': url, 'request_body': body, 'raw_response': res.get('raw_response'),
                  'response_model': res.get('response_model'), 'usage_raw': res.get('usage_raw'), 'text': res.get('text', ''),
                  'stop': res.get('stop'), 'in': res['in'], 'out': res['out'], 'lat': res.get('lat'), 'yuan_accounting': cost,
                  'yuan_marginal': cost if model == 'ds' else 0.0, 'fault': fault})
    return dict(model=model, input_id=inp['input_id'], rep=rep, stop=res.get('stop'), fault=fault), fault


def run(transport, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    if R.read_ledger(ledger.path):
        raise SystemExit(f'REFUSED: {ledger.path} already has records; the probe scene is never rerun')
    budget = ProbeBudget(**CAPS)
    ins = {i['input_id']: i for i in inputs()}
    stopped_models, batch_stop, records = {}, None, []
    for model, input_id, rep in plan():
        if batch_stop:
            break
        if model in stopped_models:
            records.append(dict(model=model, input_id=input_id, rep=rep, skipped=f'model stopped: {stopped_models[model]}'))
            continue
        try:
            rec, failure = call_one(transport, ledger, budget, model, ins[input_id], rep)
        except R.Stop as stop:
            batch_stop = str(stop)
            break
        if failure:
            stopped_models[model] = failure
            records.append(dict(model=model, input_id=input_id, rep=rep, failure=failure))
        else:
            records.append(rec)
        reached = budget.reached()
        if reached:
            batch_stop = reached
    summary = dict(stopped_models=stopped_models, batch_stop=batch_stop, records=records,
                   used=dict(calls=budget.calls, tokens=budget.tokens, yuan_accounting=round(budget.yuan, 6),
                             yuan_marginal=round(budget.yuan_marginal, 6)), caps=CAPS, ledger_ok=R.ledger_integrity(ledger.path))
    (out_dir / 'RUN_SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), 'utf-8')
    return summary


def freeze_inputs():
    files = [Path(__file__).resolve(), HERE / 'J2_PROBE_DESIGN.md', SC_DIR / 'sc_e1_1_runner.py', SC_DIR / 'canary_A2/LEDGER.jsonl',
             Path(R.OLD.__file__).resolve(), Path(R.DS_TRANSPORT.__file__).resolve(), SC_DIR / 'detectors_v4.py', SC_DIR / 'sc_e1_scorer.py']
    return dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                inputs={i['input_id']: dict(source_arm=i['source_arm'], user_sha256=i['user_sha256']) for i in inputs()},
                j2_system_sha256=R._sha(R.J2_SYS), plan=[list(p) for p in plan()], caps=CAPS, max_tokens=MAX_TOKENS,
                models=dict(ds=R.DS_MODEL, glm=R.GLM_MODEL), endpoints=dict(ds=R.DS_BASE + '/chat/completions', glm=R.OLD.GLM_URL))


def check_real_gate(freeze_sha):
    if os.environ.get('J2_PROBE_GO') != '1':
        raise SystemExit('REFUSED: requires J2_PROBE_GO=1')
    p = HERE / 'FREEZE_J2_PROBE.json'
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != freeze_sha:
        raise SystemExit('REFUSED: --freeze does not match FREEZE_J2_PROBE.json')
    if json.loads(p.read_text('utf-8')) != json.loads(json.dumps(freeze_inputs())):
        raise SystemExit('REFUSED: frozen inputs changed since FREEZE_J2_PROBE.json was written')
    for key in (R.DS_KEY_ENV, 'STAGE_D_GLM_KEY'):
        if not os.environ.get(key, '').strip():
            raise SystemExit(f'REFUSED: {key} not set')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--freeze', default='')
    ap.add_argument('--write-freeze', action='store_true')
    a = ap.parse_args()
    if a.write_freeze:
        p = HERE / 'FREEZE_J2_PROBE.json'
        p.write_text(json.dumps(freeze_inputs(), ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_J2_PROBE sha256:', hashlib.sha256(p.read_bytes()).hexdigest())
        return
    check_real_gate(a.freeze)
    s = run(R.RealTransport())
    for r in s['records']:
        print(r)
    print('stopped_models:', s['stopped_models'], '| batch_stop:', s['batch_stop'], '| used:', s['used'], '| ledger_ok:', s['ledger_ok'])


if __name__ == '__main__':
    main()
