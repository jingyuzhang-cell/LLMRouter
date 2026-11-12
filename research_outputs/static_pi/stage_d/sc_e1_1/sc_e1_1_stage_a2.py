#!/usr/bin/env python3
"""SC-E1.1 Stage A': Stage A rerun with J1 temporarily on DeepSeek, one arm per invocation.

Operator decision 2026-11-06 (P2_AMENDMENT_SC_E1_1_A2.md). The two E outputs paid for in canary_A
are reused byte for byte, never re-extracted. Each arm may spend at most 3 calls and runs only after
the previous arm passed; the previous arm's result file sha256 must be passed back with --after, so
every step forward follows an inspection. Caps are cumulative with canary_A and read from the
ledgers: 13 calls / 230K tokens / ¥0.30.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402

# Temporary route for this infrastructure validation only (amendment section 1); not a pool decision.
R.J1_DEFAULT_BACKEND, R.J1_ALT_BACKEND = 'ds', 'glm'

ARMS = R.ARMS
ARM_CALL_CAP = 3
CAPS = dict(calls=13, tokens=230_000, yuan=0.30)
PRIOR_DIR = HERE / 'canary_A'
OUT_DIR = HERE / 'canary_A2'
E_TEXT_SHA256 = {'E_D1': '36da710ed635acf69d35a560af62b5ae9d062bab97c43a17879807084155b283',
                 'E_D2': 'cd8062d51124876db92604b05495eb769104e34225614babc9346b345785ae2b'}
E_DOC = {'E_D1': 'D1', 'E_D2': 'D2'}


class ArmBudget(R.Budget):
    def __init__(self, prior, arm_cap=ARM_CALL_CAP):
        super().__init__(**CAPS)
        self.calls, self.tokens = prior['calls'], prior['tokens']
        self.yuan, self.yuan_marginal = prior['yuan_accounting'], prior['yuan_marginal']
        self.start_calls, self.arm_cap = self.calls, arm_cap

    def preflight(self, backend, system, user, max_tokens):
        if self.calls - self.start_calls + 1 > self.arm_cap:
            raise R.Stop(f'arm call cap {self.arm_cap} reached')
        super().preflight(backend, system, user, max_tokens)


def usage_from_ledgers(paths):
    used = dict(calls=0, tokens=0, yuan_accounting=0.0, yuan_marginal=0.0)
    for path in paths:
        for r in R.read_ledger(path):
            if r['phase'] != 'done' or r['injected']:
                continue
            used['calls'] += 1
            used['tokens'] += (r.get('in') or 0) + (r.get('out') or 0)
            used['yuan_accounting'] += r.get('yuan_accounting') or 0.0
            used['yuan_marginal'] += r.get('yuan_marginal') or 0.0
    return used


def load_reused_e(prior_dir, docs, expected=E_TEXT_SHA256):
    ledger = Path(prior_dir) / 'LEDGER.jsonl'
    if not R.ledger_integrity(ledger):
        raise SystemExit(f'REFUSED: {ledger} fails integrity')
    done = [r for r in R.read_ledger(ledger) if r['phase'] == 'done']
    texts = {}
    for node, doc in E_DOC.items():
        rows = [r for r in done if r['node'] == node]
        if len(rows) != 1:
            raise SystemExit(f'REFUSED: {len(rows)} {node} rows in {ledger}')
        r = rows[0]
        problems = [name for name, ok in (
            ('text sha256', R._sha(r['text']) == expected[node]),
            ('system prompt', r['system_sha256'] == R._sha(R.E_SYS)),
            ('user prompt', r['user_sha256'] == R._sha(R.e_user(docs[doc]))),
            ('payload', r['request_body']['messages'][-1]['content'] == R.e_user(docs[doc])),
            ('backend', r['backend'] == 'ds' and 'deepseek' in str(r.get('response_model')).lower()),
            ('clean stop', r['stop'] == 'stop' and not r.get('fault'))) if not ok]
        if problems:
            raise SystemExit(f'REFUSED: reused {node} fails {problems}')
        texts[node] = r['text']
    return texts


def check_order(arm, after_sha, out_dir):
    out_dir = Path(out_dir)
    if (out_dir / f'ARM_{arm}.json').exists():
        raise SystemExit(f'REFUSED: arm {arm} already ran; its scene is never rerun')
    ledger = out_dir / 'LEDGER.jsonl'
    if ledger.exists() and not R.ledger_integrity(ledger):
        raise SystemExit(f'REFUSED: {ledger} fails integrity')
    i = ARMS.index(arm)
    if i == 0:
        return
    prev = out_dir / f'ARM_{ARMS[i - 1]}.json'
    if not prev.exists():
        raise SystemExit(f'REFUSED: {ARMS[i - 1]} has not run')
    if hashlib.sha256(prev.read_bytes()).hexdigest() != after_sha:
        raise SystemExit(f'REFUSED: --after does not match {prev.name}')
    if json.loads(prev.read_text('utf-8'))['acceptance']['verdict'] != 'PASS':
        raise SystemExit(f'REFUSED: {ARMS[i - 1]} did not pass')


def run_arm(arm, transport, out_dir=OUT_DIR, prior_dir=PRIOR_DIR, expected_e=E_TEXT_SHA256):
    out_dir, prior_dir = Path(out_dir), Path(prior_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = SC.load_contract()
    SC.verify_pins()
    docs, slots_json = R.load_task(contract)
    e_texts = load_reused_e(prior_dir, docs, expected_e)
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    budget = ArmBudget(usage_from_ledgers([prior_dir / 'LEDGER.jsonl', ledger.path]))
    env = R.Env(transport, ledger, budget, 'normal', 1)

    record, stopped = None, None
    try:
        out = R.run_execution(arm, env, (docs, SC.doc_index(contract), slots_json), e_texts, allow_recovery=False)
        try:
            metrics = SC.score(out['sink'], contract)
        except Exception as exc:
            raise R.Stop(f'{arm}: scoring failed: {type(exc).__name__}: {exc}') from exc
        record = dict(arm=arm, condition='normal', rep=1, **out, metrics=metrics)
        if metrics['Q_all'] is None:
            stopped = f'{arm}: Q_all is NULL for a complete execution'
        elif metrics['asserted'] == 0:
            stopped = f'{arm}: SINK returned no answers'
    except R.Stop as stop:
        stopped = str(stop)
    except Exception as exc:
        stopped = f'internal error: {type(exc).__name__}: {exc}'

    acceptance = R.canary_acceptance([record] if record else [], stopped, R.ledger_integrity(ledger.path))
    result = dict(arm=arm, stopped=stopped, used_arm_calls=budget.calls - budget.start_calls,
                  used_cumulative=dict(calls=budget.calls, tokens=budget.tokens, yuan_accounting=round(budget.yuan, 6),
                                       yuan_marginal=round(budget.yuan_marginal, 6)),
                  caps=dict(CAPS, arm_calls=ARM_CALL_CAP),
                  route={n: R.frozen_request('normal', n)[0] for n in ('J1', 'J2', 'SINK')},
                  acceptance=acceptance, record=record)
    (out_dir / f'ARM_{arm}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), 'utf-8')
    write_aggregate(out_dir, result)
    return result


def write_aggregate(out_dir, last):
    """RESULTS.json in the shape the Stage A tools read (runner --rescore, analyze_stage_a.py)."""
    arms = [json.loads((out_dir / f'ARM_{a}.json').read_text('utf-8')) for a in ARMS if (out_dir / f'ARM_{a}.json').exists()]
    records = [a['record'] for a in arms if a['record']]
    done = [r for r in R.read_ledger(out_dir / 'LEDGER.jsonl') if r['phase'] == 'done' and not r['injected']]
    stopped = next((a['stopped'] for a in arms if a['stopped']), None)
    summary = dict(stage='A2', contract_sha256=SC.CONTRACT_SHA256, stopped=stopped, used=last['used_cumulative'],
                   caps=last['caps'], arms_run=[a['arm'] for a in arms],
                   models_reported=sorted({f"{r['backend']}:{r.get('response_model')}" for r in done}),
                   acceptance=R.canary_acceptance(records, stopped, R.ledger_integrity(out_dir / 'LEDGER.jsonl')),
                   records=records)
    (out_dir / 'RESULTS.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), 'utf-8')


def freeze_inputs():
    files = [Path(__file__).resolve(), Path(R.__file__).resolve(), HERE / 'sc_e1_scorer.py', Path(OLD.__file__).resolve(),
             SC.CONTRACT_PATH, Path(R.DS_TRANSPORT.__file__).resolve(), HERE / 'P2_AMENDMENT_SC_E1_1_A2.md',
             PRIOR_DIR / 'LEDGER.jsonl', *(Path(p) for p in SC.PINNED_SHA256)]
    return dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                contract_sha256=SC.CONTRACT_SHA256, reused_e_text_sha256=E_TEXT_SHA256,
                prompts={n: R._sha(v) for n, v in (('J1_SYS', R.J1_SYS), ('J2_SYS', R.J2_SYS), ('SINK_SYS', R.SINK_SYS))},
                route={n: R.frozen_request('normal', n)[0] for n in ('J1', 'J2', 'SINK')},
                max_tokens=R.MAX_TOKENS, caps=CAPS, arm_call_cap=ARM_CALL_CAP, arm_order=list(ARMS),
                models=dict(ds=R.DS_MODEL), endpoint=R.DS_BASE + '/chat/completions')


def check_real_gate(freeze_sha):
    if os.environ.get('SC_E1_1_A2_GO') != '1':
        raise SystemExit('REFUSED: requires SC_E1_1_A2_GO=1')
    path = HERE / 'FREEZE_A2.json'
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != freeze_sha:
        raise SystemExit('REFUSED: --freeze does not match FREEZE_A2.json')
    SC.verify_pins()
    SC.load_contract()
    if json.loads(path.read_text('utf-8')) != json.loads(json.dumps(freeze_inputs())):
        raise SystemExit('REFUSED: frozen inputs changed since FREEZE_A2.json was written')
    if not os.environ.get(R.DS_KEY_ENV, '').strip():
        raise SystemExit(f'REFUSED: {R.DS_KEY_ENV} not set')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', choices=ARMS)
    ap.add_argument('--freeze', default='')
    ap.add_argument('--after', default='')
    ap.add_argument('--write-freeze', action='store_true')
    args = ap.parse_args()
    if args.write_freeze:
        path = HERE / 'FREEZE_A2.json'
        path.write_text(json.dumps(freeze_inputs(), ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_A2 sha256:', hashlib.sha256(path.read_bytes()).hexdigest())
        return
    if not args.arm:
        raise SystemExit('REFUSED: --arm is required')
    check_real_gate(args.freeze)
    check_order(args.arm, args.after, OUT_DIR)
    result = run_arm(args.arm, R.RealTransport())
    m = (result['record'] or {}).get('metrics') or {}
    print(f"[{args.arm}] stopped={result['stopped']} verdict={result['acceptance']['verdict']} "
          f"Q_all={m.get('Q_all')} Q_terminal={m.get('Q_terminal')} E_literal={m.get('E_literal')} "
          f"asserted={m.get('asserted')} tp={m.get('tp')} wrong={m.get('wrong')} "
          f"arm_calls={result['used_arm_calls']} cumulative={result['used_cumulative']}")
    print('ARM file sha256:', hashlib.sha256((OUT_DIR / f'ARM_{args.arm}.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
