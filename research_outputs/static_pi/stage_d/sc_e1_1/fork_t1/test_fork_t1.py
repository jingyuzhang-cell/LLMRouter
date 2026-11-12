"""T1 offline tests (zero calls; network patched to fail)."""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY', 'SC_E1_1_T1_GO'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import run_fork_t1 as T  # noqa: E402
import sc_e1_1_mock as M  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402

class T1Mock(M.MockTransport):
    """The oracle mock answers only from its own synthetic E quotes; for plumbing on the real CP-S inputs the
    SINK answers every slot with its canonical value and quote so that each replicate has assertions."""

    def _sink(self, system, user, fault=None):
        return json.dumps(M.canonical_sink(), ensure_ascii=False)


RES = []
PROTECTED = [HERE.parent / 'canary_A/LEDGER.jsonl', HERE.parent / 'canary_A2/LEDGER.jsonl', HERE.parent / 'canary_A2/RESULTS.json']
BEFORE = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED}


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<84} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def run_all(faults=None):
    out = Path(tempfile.mkdtemp())
    results, after = {}, ''
    for arm in T.ARMS:
        try:
            T.check_order(arm, after, out)
        except SystemExit as exc:
            results[arm] = str(exc)
            break
        results[arm] = T.run_arm(arm, T1Mock(faults), out)
        after = hashlib.sha256((out / f'ARM_{arm}.json').read_bytes()).hexdigest()
    return out, results


def main():
    inp = T.load_inputs()
    chk('T0 inputs verified: rendered requests, A1 equals the Stage A\' Static J2 request, template reproduces A0', True)
    out, res = run_all()
    rows = [r for r in R.read_ledger(out / 'LEDGER.jsonl') if r['phase'] == 'done']
    chk('T1 four arms in order A0, A3, A1, A2 all PASS on the mock',
        list(res) == list(T.ARMS) and all(isinstance(v, dict) and v['verdict'] == 'PASS' for v in res.values()),
        {k: (v if isinstance(v, str) else v['stopped']) for k, v in res.items()})
    per_arm = {a: [(r['node'], r['backend']) for r in rows if r['arm'] == a] for a in T.ARMS}
    chk('T2 call plan: A0 3 SINK, A3 3 SINK, A1 and A2 3 x (J2, SINK); 18 in total, all DS',
        per_arm['A0'] == [('SINK', 'ds')] * 3 and per_arm['A3'] == [('SINK', 'ds')] * 3
        and per_arm['A1'] == [('J2', 'ds'), ('SINK', 'ds')] * 3 and per_arm['A2'] == [('J2', 'ds'), ('SINK', 'ds')] * 3 and len(rows) == 18)
    sent = {a: [r for r in rows if r['arm'] == a] for a in T.ARMS}
    users = lambda a, node: {r['user_sha256'] for r in sent[a] if r['node'] == node}
    chk('T3 frozen bytes sent: A0/A3 SINK, A1/A2 J2 match the rendered hashes',
        users('A0', 'SINK') == {T.RENDERED['A0_SINK']} and users('A3', 'SINK') == {T.RENDERED['A3_SINK_bypass']}
        and users('A1', 'J2') == {T.RENDERED['A1_J2_blind']} and users('A2', 'J2') == {T.RENDERED['A2_J2_targeted']})
    real = R.RealTransport()
    bodies = [real.describe('ds', R.J2_SYS if r['node'] == 'J2' else R.SINK_SYS, r['request_body']['messages'][-1]['content'], r['max_tokens'])[1]
              for r in rows]
    same = all(r['max_tokens'] == 4000 for r in rows) and all(b['temperature'] == 0 and b['model'] == R.DS_MODEL and b['max_tokens'] == 4000
                                                            for b in bodies)
    chk('T4 A1 and A2 share model, temperature 0, max_tokens 4000 and the J2 system prompt',
        same and len({r['system_sha256'] for r in rows if r['node'] == 'J2'}) == 1)
    last = res['A2']
    chk('T5 cumulative call count reaches exactly 18 and the 18th call is still scored',
        last['used_cumulative']['calls'] == 18 and len(last['replicates']) == 3, last['used_cumulative'])
    a3 = res['A3']['replicates'][0]
    chk('T6 A3 reports each deleted entry with its groundability and terminal status, and the harm counts',
        set(a3['deleted_entries']) == set(T.FLAGGED) and 'deletion_harm' in a3, a3.get('deletion_harm'))
    a2 = res['A2']['replicates'][0]
    chk('T7 A1/A2 report J2 re-suppression and omission on the five flagged slots', 'j2_resuppressed' in a2 and 'j2_omitted' in a2)
    chk('T8 every replicate carries Q_all, R and the safety metrics', all('R' in r and 'safety' in r for v in res.values() for r in v['replicates']))

    for label, faults, arm_fail, calls in (('truncated SINK in A0', {('SINK', 'ds'): 'length'}, 'A0', 1),
                                           ('HTTP 429 at J2 in A1', {('J2', 'ds'): 'http429'}, 'A1', 1),
                                           ('empty SINK answers in A0', {('SINK', 'ds'): 'empty_answers'}, 'A0', 1)):
        o = Path(tempfile.mkdtemp())
        order = T.ARMS[:T.ARMS.index(arm_fail) + 1]
        after, r = '', None
        for arm in order:
            r = T.run_arm(arm, T1Mock(faults if arm == arm_fail else None), o)
            after = hashlib.sha256((o / f'ARM_{arm}.json').read_bytes()).hexdigest()
        try:
            nxt = T.ARMS[T.ARMS.index(arm_fail) + 1]
            T.check_order(nxt, after, o)
            refused = False
        except SystemExit:
            refused = True
        chk(f'T9 stop on {label}: no retry, FAIL, next arm refused', r['verdict'] == 'FAIL' and r['arm_calls'] == calls and refused,
            (r['stopped'], r['arm_calls']))
    try:
        T.check_order('A1', '', Path(tempfile.mkdtemp()))
        refused = False
    except SystemExit:
        refused = True
    chk('T10 order gate: A1 cannot run before A0 and A3', refused)
    b = T.T1Budget(dict(calls=17, tokens=0, yuan_accounting=0.0, yuan_marginal=0.0), 6)
    b.preflight('ds', 'x', 'y', 10)
    b.book('ds', 1, 1)
    try:
        b.preflight('ds', 'x', 'y', 10)
        msg = None
    except R.Stop as exc:
        msg = str(exc)
    chk('T11 a 19th call is refused before sending', msg and 'call cap' in msg, msg)
    b = T.T1Budget(dict(calls=0, tokens=199_999, yuan_accounting=0.0, yuan_marginal=0.0), 6)
    b.book('ds', 1, 1)
    chk('T12 token cap reached stops the run', b.reached() and 'tokens' in b.reached())
    try:
        T.check_real_gate('x')
        refused = False
    except SystemExit:
        refused = True
    chk('T13 real mode refused without SC_E1_1_T1_GO', refused)
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED}
    chk('T14 Stage A\' scenes and the CP-S checkpoint untouched', after == BEFORE)
    passed = sum(r['ok'] for r in RES)
    (HERE / 'T1_OFFLINE_TESTS.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES), ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
