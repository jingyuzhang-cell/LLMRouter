"""Stage A' offline tests (zero calls: urlopen is patched to fail on any network attempt)."""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY', 'SC_E1_1_CANARY_GO', 'SC_E1_1_A2_GO'):
    os.environ.pop(key, None)


def _no_network(*a, **k):
    raise AssertionError('network attempted during offline test')


urllib.request.urlopen = _no_network

import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_mock as M  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_1_stage_a2 as A2  # noqa: E402

CT = SC.load_contract()
DOCS, _ = R.load_task(CT)
RES = []


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<74} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def make_prior():
    """A canary_A look-alike: two paid E calls and one truncated GLM J1, written by the real Env."""
    prior = Path(tempfile.mkdtemp())
    t = M.MockTransport({('J1', 'glm'): 'length'})
    env = R.Env(t, R.Ledger(prior / 'LEDGER.jsonl'), R.Budget(13, 230_000, 0.30), 'normal', 1)
    texts = {'E_D1': env.call('E_D1', 'ds', R.E_SYS, R.e_user(DOCS['D1'])).text,
             'E_D2': env.call('E_D2', 'ds', R.E_SYS, R.e_user(DOCS['D2'])).text}
    saved = R.J1_DEFAULT_BACKEND
    R.J1_DEFAULT_BACKEND = 'glm'
    try:
        env.call('J1', 'glm', R.J1_SYS, R.j1_user(texts))
    except R.Stop:
        pass
    finally:
        R.J1_DEFAULT_BACKEND = saved
    return prior, {k: R._sha(v) for k, v in texts.items()}


def arm_sha(out, arm):
    return hashlib.sha256((Path(out) / f'ARM_{arm}.json').read_bytes()).hexdigest()


def run_in_order(out, prior, expected, faults=None):
    results = {}
    after = ''
    for arm in A2.ARMS:
        try:
            A2.check_order(arm, after, out)
        except SystemExit as exc:
            results[arm] = str(exc)
            break
        results[arm] = A2.run_arm(arm, M.MockTransport(faults), out, prior, expected)
        after = arm_sha(out, arm)
    return results


def main():
    prior, expected = make_prior()
    used0 = A2.usage_from_ledgers([prior / 'LEDGER.jsonl'])
    chk('T1 prior usage is read from the ledger: 3 calls including the truncated J1', used0['calls'] == 3, used0)
    chk('T1 J1 now routes to DS; J2/SINK unchanged; prompts byte-identical to the frozen runner',
        [R.frozen_request('normal', n)[0] for n in ('J1', 'J2', 'SINK')] == ['ds', 'ds', 'ds']
        and (R.J1_SYS, R.J2_SYS, R.SINK_SYS) == (OLD.J1_SYS, OLD.J2_SYS, OLD.SINK_SYS))

    out = Path(tempfile.mkdtemp())
    res = run_in_order(out, prior, expected)
    rows = [r for r in R.read_ledger(out / 'LEDGER.jsonl') if r['phase'] == 'done']
    chk('T2 three arms run in order, each PASS', all(isinstance(res[a], dict) and res[a]['acceptance']['verdict'] == 'PASS'
                                                     for a in A2.ARMS), {a: (r if isinstance(r, str) else r['stopped']) for a, r in res.items()})
    chk('T2 each arm spends exactly 3 calls; cumulative ends at 12 of 13',
        [res[a]['used_arm_calls'] for a in A2.ARMS] == [3, 3, 3] and res['Joint-Dynamic']['used_cumulative']['calls'] == 12)
    chk('T2 no E call is made; every new call is J1/J2/SINK on DS',
        [(r['node'], r['backend']) for r in rows] == [('J1', 'ds'), ('J2', 'ds'), ('SINK', 'ds')] * 3)
    j1 = rows[0]
    chk('T2 the reused E outputs reach J1 byte for byte',
        j1['request_body']['messages'][-1]['content'] == R.j1_user({k: next(
            r['text'] for r in R.read_ledger(prior / 'LEDGER.jsonl') if r['phase'] == 'done' and r['node'] == k) for k in ('E_D1', 'E_D2')}))
    chk('T2 J1 system prompt sent is the frozen J1_SYS', j1['system_sha256'] == R._sha(OLD.J1_SYS))
    agg = json.loads((out / 'RESULTS.json').read_text('utf-8'))
    chk('T2 aggregate and ledger-only rescore agree', R.rescore(out) == {f"normal|1|{r['arm']}": r['metrics'] for r in agg['records']}
        and agg['acceptance']['verdict'] == 'PASS')
    chk('T2 no recovery action in any arm', all(res[a]['record']['trace'][0]['action'] == R.NONE for a in A2.ARMS))

    for arm, after, label in (('Fixed-Recovery', '', 'second arm without the first'),
                              ('Static', '', 'rerun of a finished arm')):
        fresh = Path(tempfile.mkdtemp()) if label.startswith('second') else out
        try:
            A2.check_order(arm, after, fresh)
            msg = None
        except SystemExit as exc:
            msg = str(exc)
        chk(f'T3 order gate refuses {label}', msg and 'REFUSED' in msg, msg)
    out2 = Path(tempfile.mkdtemp())
    A2.run_arm('Static', M.MockTransport(), out2, prior, expected)
    try:
        A2.check_order('Fixed-Recovery', 'not-the-sha', out2)
        msg = None
    except SystemExit as exc:
        msg = str(exc)
    chk('T3 order gate refuses a wrong --after sha', msg and '--after' in msg, msg)
    A2.check_order('Fixed-Recovery', arm_sha(out2, 'Static'), out2)
    chk('T3 order gate accepts the right --after sha', True)

    bad = dict(expected, E_D2='0' * 64)
    try:
        A2.run_arm('Static', M.MockTransport(), Path(tempfile.mkdtemp()), prior, bad)
        msg = None
    except SystemExit as exc:
        msg = str(exc)
    chk('T4 a reused E output whose text hash differs is refused before any call', msg and 'text sha256' in msg, msg)
    tampered = Path(tempfile.mkdtemp())
    lines = (prior / 'LEDGER.jsonl').read_text('utf-8').splitlines()
    edited = []
    for line in lines:
        r = json.loads(line)
        if r['node'] == 'E_D1':
            r['system_sha256'] = R._sha('另一个提示词')
        edited.append(json.dumps(r, ensure_ascii=False))
    (tampered / 'LEDGER.jsonl').write_text('\n'.join(edited) + '\n', 'utf-8')
    try:
        A2.run_arm('Static', M.MockTransport(), Path(tempfile.mkdtemp()), tampered, expected)
        msg = None
    except SystemExit as exc:
        msg = str(exc)
    chk('T4 a reused E output from a different prompt is refused', msg and 'system prompt' in msg, msg)

    b = A2.ArmBudget(dict(calls=3, tokens=0, yuan_accounting=0.0, yuan_marginal=0.0))
    for _ in range(3):
        b.preflight('ds', 'x', 'y', 10)
        b.book('ds', 1, 1)
    try:
        b.preflight('ds', 'x', 'y', 10)
        msg = None
    except R.Stop as exc:
        msg = str(exc)
    chk('T5 a 4th call in one arm is stopped before sending', msg and 'arm call cap' in msg, msg)
    b = A2.ArmBudget(dict(calls=3, tokens=229_000, yuan_accounting=0.0, yuan_marginal=0.0))
    try:
        b.preflight('ds', R.J1_SYS, 'x' * 9000, 8000)
        msg = None
    except R.Stop as exc:
        msg = str(exc)
    chk('T5 cumulative token cap counts canary_A usage', msg and 'token' in msg, msg)
    b = A2.ArmBudget(dict(calls=3, tokens=0, yuan_accounting=0.29, yuan_marginal=0.0))
    try:
        b.preflight('ds', R.J1_SYS, 'x' * 9000, 8000)
        msg = None
    except R.Stop as exc:
        msg = str(exc)
    chk('T5 cumulative yuan cap counts canary_A usage', msg and 'yuan' in msg, msg)

    out3 = Path(tempfile.mkdtemp())
    res = run_in_order(out3, prior, expected, {('J1', 'ds'): 'length'})
    chk('T6 truncation at DS J1: arm stops after 1 call, FAIL, next arm refused',
        res['Static']['stopped'] and 'truncated' in res['Static']['stopped'] and res['Static']['used_arm_calls'] == 1
        and res['Static']['acceptance']['verdict'] == 'FAIL' and 'did not pass' in res['Fixed-Recovery'], res)
    for label, faults, want in (('SINK empty answers', {('SINK', 'ds'): 'empty_answers'}, 'no answers'),
                                ('HTTP 429 at J2', {('J2', 'ds'): 'http429'}, 'transport error'),
                                ('J2 parse failure', {('J2', 'ds'): 'bad_json'}, 'json_invalid')):
        r = A2.run_arm('Static', M.MockTransport(faults), Path(tempfile.mkdtemp()), prior, expected)
        chk(f'T6 {label}: stop, FAIL, scene kept', r['stopped'] and want in r['stopped'] and r['acceptance']['verdict'] == 'FAIL', r['stopped'])
    r = A2.run_arm('Fixed-Recovery', M.MockTransport({('J1', 'ds'): 'no_final'}), Path(tempfile.mkdtemp()), prior, expected)
    chk('T6 a recovery wanted in the normal condition stops before any recovery call',
        'recovery action' in (r['stopped'] or '') and r['used_arm_calls'] == 1, r['stopped'])
    real_score = SC.score
    try:
        SC.score = lambda *a: (_ for _ in ()).throw(ValueError('scorer broke'))
        r = A2.run_arm('Static', M.MockTransport(), Path(tempfile.mkdtemp()), prior, expected)
    finally:
        SC.score = real_score
    chk('T6 scoring exception stops the arm and fails it', 'scoring failed' in (r['stopped'] or '') and r['acceptance']['verdict'] == 'FAIL', r['stopped'])

    def refused(go, sha):
        if go:
            os.environ['SC_E1_1_A2_GO'] = '1'
        try:
            A2.check_real_gate(sha)
            return None
        except SystemExit as exc:
            return str(exc)
        finally:
            os.environ.pop('SC_E1_1_A2_GO', None)
    chk('T7 real mode refused without SC_E1_1_A2_GO', 'SC_E1_1_A2_GO' in (refused(False, 'x') or ''))
    chk('T7 real mode refused with a wrong freeze sha', 'FREEZE_A2' in (refused(True, 'x') or ''))

    old_freeze = json.loads((HERE / 'FREEZE.json').read_text('utf-8'))
    unchanged = {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() == v for p, v in old_freeze['files'].items()}
    chk('T8 runner, scorer, contract, prompts source and scoring dependencies are unchanged since the Stage A freeze',
        all(unchanged.values()), unchanged)
    canary = HERE / 'canary_A'
    def read_only(path):
        return (os.stat(path).st_mode & 0o222) == 0  # root bypasses permission bits, so check the mode itself
    chk('T8 canary_A ledger and results carry no write bits and the ledger hash is pinned in the A2 freeze',
        read_only(canary / 'LEDGER.jsonl') and read_only(canary / 'RESULTS.json')
        and str(canary / 'LEDGER.jsonl') in json.loads(json.dumps(A2.freeze_inputs()))['files'])
    real_e = A2.load_reused_e(canary, DOCS)
    chk('T8 the real canary_A E outputs pass the reuse checks', set(real_e) == {'E_D1', 'E_D2'})

    passed = sum(r['ok'] for r in RES)
    (HERE / 'REGRESSION_A2_RESULTS.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES),
                                                                ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
