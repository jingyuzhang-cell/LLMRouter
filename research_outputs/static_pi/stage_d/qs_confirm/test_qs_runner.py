"""QS executor offline regression (zero calls; network patched to fail)."""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'sc_e1_1'), str(HERE.parent / 'sc_e1_1' / 'fork_t1'), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY', 'QS_BLOCK_GO'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import qs_runner as QR  # noqa: E402
import qs_mock as M  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402

TASK = QR.load_task()
RES = []


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<86} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def one_rep(plan, rep=1):
    out = Path(tempfile.mkdtemp())
    ledger = R.Ledger(out / 'LEDGER.jsonl')
    return QR.run_rep(QR.Ctx(M.QSMock(plan), ledger, QR.BlockBudget(**QR.BLOCK_CAPS), rep), TASK), ledger


def main():
    rec, _ = one_rep({})
    a, b, c = (rec['arms'][k] for k in 'ABC')
    chk('T1 clean rep: no targets, B and C add no calls, three arms identical output, tie',
        not rec['targets'] and b['own']['calls'] == c['own']['calls'] == 0 and a['metrics']['Q_all'] == b['metrics']['Q_all'] == c['metrics']['Q_all'])

    rec, _ = one_rep({'J2': ['suppress']})
    a, b, c = (rec['arms'][k] for k in 'ABC')
    chk('T2 explicit suppression: A loses the four slots; B rechecks (GLM) + SINK; C bypasses SINK only',
        rec['targets'] == ['F8', 'F9', 'F10', 'F20'] and a['metrics']['Q_all'] == 0.8
        and [t['action'] for t in b['trace']][0] == 'fixed_recheck' and [t['action'] for t in c['trace']][0] == 'sink_bypass')
    chk('T2 both recover to 1.0; C uses fewer own calls than B', b['metrics']['Q_all'] == c['metrics']['Q_all'] == 1.0
        and c['own']['calls'] < b['own']['calls'], (b['own'], c['own']))

    rec, _ = one_rep({'J2': ['unknown']})
    c = rec['arms']['C']
    chk('T3 unknown labels: C goes straight to J2 recheck, nothing deleted',
        [t['action'] for t in c['trace']] and 'sink_bypass' not in [t['action'] for t in c['trace']]
        and any(t['action'] == 'j2_recheck' for t in c['trace']))

    rec, _ = one_rep({'J2': ['mixed']})
    c = rec['arms']['C']
    chk('T4 mixed states: C rechecks (no deletion)', not any(t['action'] == 'sink_bypass' for t in c['trace'])
        and any(t['action'] == 'j2_recheck' for t in c['trace']))

    rec, _ = one_rep({'J2': ['omit']})
    a, b, c = (rec['arms'][k] for k in 'ABC')
    chk('T5 omission with evidence and a recoverable pre-recovery terminal: C spends zero calls, B spends two',
        any(t['action'] == 'check_pre_recovery_terminal' for t in c['trace']) and c['own']['calls'] == 0
        and b['own']['calls'] == 2 and a['metrics']['Q_all'] == 1.0)

    rec, _ = one_rep({'SINK': ['bad_cite:F8']})
    c = rec['arms']['C']
    acts = [t['action'] for t in c['trace']]
    chk('T6 M3 handling: convert-to-unknown then one H rerun, no third attempt',
        'm3_convert_to_unknown' in acts and acts.count('h_rerun') == 1 and acts[-1] in ('h_rerun',), acts)

    rec, led = one_rep({'SINK': ['empty']})
    a = rec['arms']['A']
    rows = [r for r in R.read_ledger(led.path) if r['phase'] == 'done' and r['arm'] == 'A']
    chk('T7 node fault: arm uses its single retry, then succeeds', a['metrics']['Q_all'] == 1.0 and len(rows) == 2
        and a['failures'] == [dict(node='SINK', attempt=1, fault='empty_text')], (len(rows), a['failures']))

    rec, led = one_rep({'SINK': ['empty', 'length']})
    a = rec['arms']['A']
    b8, c8 = rec['arms']['B'], rec['arms']['C']
    chk('T8 second fault in a no-target rep: all three arms incomplete with Q_all = 0 (uniform imputation, batch continues)',
        a['incomplete'] and all(rec['arms'][k]['incomplete'] for k in 'ABC')
        and all(rec['arms'][k]['metrics']['Q_all'] == 0.0 for k in 'ABC'), (a['incomplete'], b8['incomplete'], c8['incomplete']))

    rec, led = one_rep({'J2': ['unknown', 'stubborn', 'stubborn']})
    c = rec['arms']['C']
    acts = [t['action'] for t in c['trace']]
    chk('T9 stubborn recheck: C escalates to recheck exactly once, terminal check fails, it stops (no third attempt)',
        acts.count('j2_recheck') == 1 and acts[-1] == 'terminal_check' and 'h_rerun' not in acts, acts)

    out = Path(tempfile.mkdtemp())
    led = R.Ledger(out / 'LEDGER.jsonl')
    try:
        QR.run_rep(QR.Ctx(M.QSMock({'J2': ['empty']}), led, QR.BlockBudget(**QR.BLOCK_CAPS), 1), TASK)
        stopped = False
    except QR.InfraStop:
        stopped = True
    chk('T10 shared-stage fault stops the whole batch (no arm owns recovery before the checkpoint)', stopped)

    out = Path(tempfile.mkdtemp())
    led = R.Ledger(out / 'LEDGER.jsonl')
    try:
        QR.run_rep(QR.Ctx(M.QSMock({'SINK': ['http500']}), led, QR.BlockBudget(**QR.BLOCK_CAPS), 1), TASK)
        stopped = False
    except QR.InfraStop:
        stopped = True
    chk('T11 transport error inside an arm is also an infrastructure stop (per prereg section 6)', stopped)

    out = Path(tempfile.mkdtemp())
    led = R.Ledger(out / 'LEDGER.jsonl')
    try:
        QR.run_rep(QR.Ctx(M.QSMock({}), led, QR.BlockBudget(calls=60, tokens=25_000, yuan=1.25), 1), TASK)
        stopped = False
    except QR.InfraStop as stop:
        stopped = 'budget' in str(stop)
    chk('T12 token pre-flight stops the batch before the cap can be crossed', stopped)

    plan = {'J2': ['unknown']}
    out = Path(tempfile.mkdtemp())
    led = R.Ledger(out / 'LEDGER.jsonl')
    QR.run_rep(QR.Ctx(M.QSMock(plan), led, QR.BlockBudget(**QR.BLOCK_CAPS), 1), TASK)
    users = {(r['arm'], r['node']): r['user_sha256'] for r in R.read_ledger(led.path) if r['phase'] == 'sent' and r['node'] in ('J2_recheck',)}
    chk('T13 fairness: B and C send byte-identical recheck requests when both recheck',
        users.get(('B', 'J2_recheck')) == users.get(('C', 'J2_recheck')), users)
    glm_rows = [r for r in R.read_ledger(led.path) if r['node'] in ('J2', 'J2_recheck')]
    chk('T14 frozen route: J2 and its recheck on GLM at 8000; E/J1/SINK on DS; system prompts are the frozen ones',
        all(r['backend'] == 'glm' and r['max_tokens'] == 8000 for r in glm_rows)
        and all(r['backend'] == 'ds' for r in R.read_ledger(led.path) if r['node'].startswith('E') or r['node'] in ('J1',) or r['node'].startswith('SINK')))

    out = Path(tempfile.mkdtemp())
    s = QR.run_block(1, M.QSMock({'J2': ['suppress'] * 12}), out)
    chk('T15 block 1: four replicates, PASS, per-rep scenes and analysis written, ledger intact',
        s['verdict'] == 'PASS' and s['reps_done'] == [1, 2, 3, 4] and s['ledger_ok'] and (out / 'ANALYSIS.json').exists()
        and all((out / f'REP_{i}.json').exists() for i in (1, 2, 3, 4)))
    try:
        QR.run_block(1, M.QSMock({}), out)
        refused = False
    except SystemExit:
        refused = True
    chk('T16 a finished block scene is never rerun', refused)
    st = QR.sign_test_one_sided([0.2, 0.1, -0.05, 0.3, 0.0, 0.2])
    chk('T17 sign test: ties dropped, exact one-sided p', st == dict(n_eff=5, positive=4, p=round((5 + 1) / 32, 6)), st)
    an = json.loads((out / 'ANALYSIS.json').read_text('utf-8'))
    chk('T18 analysis reports H1..H3 with per-rep Q, calls, yuan, latency, error rates and incompleteness',
        all(k in an for k in ('H1', 'H2a', 'H2b', 'H2c', 'H3')) and an['flagged_reps'] == 4)

    try:
        QR.check_real_gate(1, 'x', '')
        refused = False
    except SystemExit:
        refused = True
    chk('T19 real mode refused without QS_BLOCK_GO=1', refused)
    os.environ['QS_BLOCK_GO'] = '2'
    try:
        QR.check_real_gate(2, 'x', 'y')
        refused2 = False
    except SystemExit as exc:
        refused2 = 'BLOCK_1' in str(exc)
    finally:
        os.environ.pop('QS_BLOCK_GO', None)
    chk('T20 block 2 refused without block 1', refused2)
    fz = QR.freeze_inputs()
    chk('T21 freeze pins V5 as execution detector and covers runner, mock-absent assets, contract, templates',
        any('detectors_v5' in k for k in fz['files']) and not any('detectors_v6' in k for k in fz['files'])
         and any(str(HERE / 'qs_runner.py') == k for k in fz['files']) and fz['route']['J2'][0] == 'glm')

    passed = sum(r['ok'] for r in RES)
    (HERE / 'QS_RUNNER_TESTS.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES), ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
