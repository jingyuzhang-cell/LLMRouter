#!/usr/bin/env python3
"""T1 development fork on SC-E1 checkpoint CP-S (operator GO 2026-11-06): 18 calls, one arm per invocation.

Arms run in the order A0, A3, A1, A2, three replicates each. Every request body is either a frozen rendered
file (A0 and A3 SINK, A1 and A2 J2) or built from the J2 output it follows with the frozen SINK template.
Caps: 18 calls / 200K tokens / ¥0.30 for T1 alone; per-arm call caps 3/3/6/6. No retry; write-ahead ledger.
The frozen V2 detectors provide the A2 feedback and the A3 deletions; nothing is hand-edited.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC_DIR = HERE.parent
sys.path[:0] = [str(SC_DIR), str(SC_DIR.parent)]
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_1_stage_a2 as A2M  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402
import detectors_v2 as D  # noqa: E402
import safety_metrics as SM  # noqa: E402

ARMS = ('A0', 'A3', 'A1', 'A2')
ARM_CALLS = {'A0': 3, 'A3': 3, 'A1': 6, 'A2': 6}
REPS = 3
CAPS = dict(calls=18, tokens=200_000, yuan=0.30)
OUT = HERE / 'run'
FLAGGED = ('F8', 'F9', 'F10', 'F11', 'F20')
RENDERED = {'A0_SINK': '46c9ceb7242c5dbabe5dea25b0f93f30d34b1aa721724e636c4447d0e5e81add',
            'A1_J2_blind': '203b074c7517519d82bf3d53313125efa370281c4b2a2bb326f8231e46c2d63f',
            'A2_J2_targeted': '902fad2074b25ad74a08097275c9e82c2871196bce2563108dd005af64df555e',
            'A3_SINK_bypass': 'd394b09bac22376b59090708df88a8e19d65edbbc28a8a5fb0997febc596d031'}
CP_S_J2_TEXT_SHA256 = None  # filled from the Stage A' ledger and checked against FREEZE_T1


class T1Budget(R.Budget):
    """The call cap is enforced before sending only, so the 18th planned call can still be scored; token and
    yuan caps stop the run as soon as they are reached."""

    def __init__(self, used, arm_cap):
        super().__init__(**CAPS)
        self.calls, self.tokens = used['calls'], used['tokens']
        self.yuan, self.yuan_marginal = used['yuan_accounting'], used['yuan_marginal']
        self.start_calls, self.arm_cap = self.calls, arm_cap

    def preflight(self, backend, system, user, max_tokens):
        if self.calls - self.start_calls + 1 > self.arm_cap:
            raise R.Stop(f'arm call cap {self.arm_cap} reached')
        super().preflight(backend, system, user, max_tokens)

    def reached(self):
        for name, used in (('tokens', self.tokens), ('yuan', self.yuan)):
            if used >= self.caps[name]:
                return f'{name} cap reached: {used} >= {self.caps[name]}'
        return None


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_inputs():
    """Checkpoint CP-S and every frozen request, each verified by hash before any call."""
    ct = SC.load_contract()
    SC.verify_pins()
    docs, slots_json = R.load_task(ct)
    slots = json.loads(slots_json)
    e = A2M.load_reused_e(SC_DIR / 'canary_A', docs)
    rows, _ = R.evidence_rows(e, SC.doc_index(ct))
    done = [r for r in R.read_ledger(SC_DIR / 'canary_A2/LEDGER.jsonl') if r['phase'] == 'done' and r['arm'] == 'Static']
    j1_row = next(r for r in done if r['node'] == 'J1')
    j2_row = next(r for r in done if r['node'] == 'J2')
    rendered = {k: (HERE / f'{k}.user.txt').read_text('utf-8') for k in RENDERED}
    bad = [k for k, v in rendered.items() if sha(v) != RENDERED[k]]
    if bad:
        raise SystemExit(f'REFUSED: rendered request changed: {bad}')
    if sha(rendered['A1_J2_blind']) != j2_row['user_sha256']:
        raise SystemExit('REFUSED: A1 request is not byte-identical to the Stage A\' Static J2 request')
    base_line = (HERE / 'base_total_line.txt').read_text('utf-8')

    def sink_user(j2_text):
        return f'核验结果：\n{j2_text}\n\n{R.evidence_block(rows)}\n\n{base_line}\n\n槽位：{slots_json}'
    if sink_user(j2_row['text']) != rendered['A0_SINK']:
        raise SystemExit('REFUSED: SINK template does not reproduce the rendered A0 request')
    return dict(ct=ct, slots=slots, rows=rows, e=e, j1=j1_row['text'], j2=j2_row['text'], rendered=rendered, sink_user=sink_user)


def used_so_far(ledger):
    used = dict(calls=0, tokens=0, yuan_accounting=0.0, yuan_marginal=0.0)
    for r in R.read_ledger(ledger):
        if r['phase'] != 'done':
            continue
        used['calls'] += 1
        used['tokens'] += (r.get('in') or 0) + (r.get('out') or 0)
        used['yuan_accounting'] += r.get('yuan_accounting') or 0.0
        used['yuan_marginal'] += r.get('yuan_marginal') or 0.0
    return used


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
    if json.loads(prev.read_text('utf-8'))['verdict'] != 'PASS':
        raise SystemExit(f'REFUSED: {ARMS[i - 1]} did not pass')


def replicate(arm, env, inp):
    """One replicate. Returns (sink parsed, new J2 parsed or None, sink request text)."""
    if arm == 'A0':
        user = inp['rendered']['A0_SINK']
        return env.call('SINK', 'ds', R.SINK_SYS, user).parsed, None, user
    if arm == 'A3':
        user = inp['rendered']['A3_SINK_bypass']
        return env.call('SINK', 'ds', R.SINK_SYS, user).parsed, None, user
    j2_user = inp['rendered']['A1_J2_blind' if arm == 'A1' else 'A2_J2_targeted']
    j2 = env.call('J2', 'ds', R.J2_SYS, j2_user)
    user = inp['sink_user'](j2.text)
    return env.call('SINK', 'ds', R.SINK_SYS, user).parsed, j2.parsed, user


def analyse(arm, sink, new_j2, inp):
    metrics = SC.score(sink, inp['ct'])
    st = {r['fact_id']: r['status'] for r in metrics['rows']}
    out = dict(metrics=metrics, safety=SM.metrics(metrics), R=sum(st[f] == 'TP' for f in FLAGGED),
               flagged_status={f: st[f] for f in FLAGGED})
    base = D.deterministic_total(OLD.extract_json(inp['e']['E_D2']))
    m3 = D.detect_m3(inp['slots'], sink, inp['rows'], base)
    out['m3_flags'] = {f: v['reason'] for f, v in m3.items() if v['state'] != 'CONSISTENT'}
    if new_j2 is not None:
        m1 = D.detect_m1(inp['slots'], new_j2, inp['rows'])
        out['j2_resuppressed'] = [f for f in FLAGGED if m1[f]['state'] == 'EXPLICIT_SUPPRESSION']
        out['j2_omitted'] = [f for f in FLAGGED if m1[f]['state'] == 'OMISSION']
        out['j2_status'] = {f: m1[f]['j2_status'] for f in FLAGGED}
    if arm == 'A3':
        groundable = {f['fact_id']: any(r['doc'] in f['allowed_citation_docs'] and SC.quote_grounds(f, r['quote']) for r in inp['rows'])
                      for f in inp['ct']['required_facts'] if f['fact_id'] in FLAGGED}
        out['deleted_entries'] = {f: dict(gold_groundable=groundable[f], terminal=st[f]) for f in FLAGGED}
        out['deletion_harm'] = dict(
            wrong_assertions_on_deleted=sum(st[f] in ('VALUE_WRONG', 'CONFLICT') for f in FLAGGED),
            deleted_label_was_correct=sum(not groundable[f] for f in FLAGGED))
    return out


def run_arm(arm, transport, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    inp = load_inputs()
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    budget = T1Budget(used_so_far(ledger.path), ARM_CALLS[arm])
    env = R.Env(transport, ledger, budget, 'normal', 0)
    env.arm = arm
    reps, stopped = [], None
    try:
        for rep in range(1, REPS + 1):
            env.rep = rep
            sink, new_j2, _ = replicate(arm, env, inp)
            try:
                res = analyse(arm, sink, new_j2, inp)
            except Exception as exc:
                raise R.Stop(f'{arm} r{rep}: scoring failed: {type(exc).__name__}: {exc}') from exc
            reps.append(dict(rep=rep, **res))
            if res['metrics']['asserted'] == 0:
                raise R.Stop(f'{arm} r{rep}: SINK returned no answers')
    except R.Stop as stop:
        stopped = str(stop)
    except Exception as exc:
        stopped = f'internal error: {type(exc).__name__}: {exc}'
    ledger_ok = R.ledger_integrity(ledger.path)
    verdict = 'PASS' if stopped is None and len(reps) == REPS and ledger_ok else 'FAIL'
    result = dict(arm=arm, verdict=verdict, stopped=stopped, ledger_ok=ledger_ok, replicates=reps,
                  arm_calls=budget.calls - budget.start_calls,
                  used_cumulative=dict(calls=budget.calls, tokens=budget.tokens, yuan_accounting=round(budget.yuan, 6),
                                       yuan_marginal=round(budget.yuan_marginal, 6)), caps=dict(CAPS, arm_calls=ARM_CALLS[arm]))
    (out_dir / f'ARM_{arm}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), 'utf-8')
    return result


def freeze_inputs():
    files = [Path(__file__).resolve(), HERE / 'render_fork_t1.py', HERE / 'base_total_line.txt', HERE / 'A2_addendum.txt',
             *(HERE / f'{k}.user.txt' for k in RENDERED), SC_DIR / 'sc_e1_1_runner.py', SC_DIR / 'sc_e1_scorer.py',
             SC_DIR / 'detectors_v2.py', SC_DIR / 'safety_metrics.py', SC_DIR / 'canary_A/LEDGER.jsonl', SC_DIR / 'canary_A2/LEDGER.jsonl',
             SC.CONTRACT_PATH, Path(OLD.__file__).resolve(), Path(R.DS_TRANSPORT.__file__).resolve(), HERE / 'FORK_T1_MATERIALS.md']
    return dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, rendered=RENDERED, caps=CAPS,
                arm_calls=ARM_CALLS, arm_order=list(ARMS), reps=REPS, flagged=list(FLAGGED), model=R.DS_MODEL,
                max_tokens=dict(J2=R.MAX_TOKENS['J2'], SINK=R.MAX_TOKENS['SINK']))


def check_real_gate(freeze_sha):
    if os.environ.get('SC_E1_1_T1_GO') != '1':
        raise SystemExit('REFUSED: requires SC_E1_1_T1_GO=1')
    path = HERE / 'FREEZE_T1.json'
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != freeze_sha:
        raise SystemExit('REFUSED: --freeze does not match FREEZE_T1.json')
    if json.loads(path.read_text('utf-8')) != json.loads(json.dumps(freeze_inputs())):
        raise SystemExit('REFUSED: frozen inputs changed since FREEZE_T1.json was written')
    if not os.environ.get(R.DS_KEY_ENV, '').strip():
        raise SystemExit(f'REFUSED: {R.DS_KEY_ENV} not set')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', choices=ARMS)
    ap.add_argument('--freeze', default='')
    ap.add_argument('--after', default='')
    ap.add_argument('--write-freeze', action='store_true')
    a = ap.parse_args()
    if a.write_freeze:
        p = HERE / 'FREEZE_T1.json'
        p.write_text(json.dumps(freeze_inputs(), ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_T1 sha256:', hashlib.sha256(p.read_bytes()).hexdigest())
        return
    if not a.arm:
        raise SystemExit('REFUSED: --arm is required')
    check_real_gate(a.freeze)
    check_order(a.arm, a.after, OUT)
    res = run_arm(a.arm, R.RealTransport())
    for r in res['replicates']:
        m = r['metrics']
        print(f"[{a.arm} r{r['rep']}] Q_all={m['Q_all']} R={r['R']} tp={m['tp']} asserted={m['asserted']} wrong={m['wrong']} "
              f"err={r['safety']['error_rate']} flagged={r['flagged_status']} resup={r.get('j2_resuppressed')}")
    print(f"verdict={res['verdict']} stopped={res['stopped']} arm_calls={res['arm_calls']} used={res['used_cumulative']}")
    print('ARM file sha256:', hashlib.sha256((OUT / f'ARM_{a.arm}.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
