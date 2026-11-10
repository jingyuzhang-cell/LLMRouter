#!/usr/bin/env python3
"""Zero-call tests of p2c_runner.py option-C paths (fake transport; no network).
T1 J2R truncation -> RECOVERY_FAILED_TRUNCATED, arm terminal == G2 terminal (fallback), cost booked, 52 blocks run.
T2 shared J2 truncation -> G2-G6 EXECUTION_FAILED Q=0, G1 executed, next block continues.
T3 transport error -> whole batch halts at the first call.
T4 budget call cap -> whole batch halts (infrastructure).
T1 uses a controlled stub of M1/M3/evidence (monkey-patched in this test only, runner untouched) so every slot
is an S2 target and the recovery arms take the J2R path."""
import json, sys, tempfile
sys.path[:0] = ['/root/research_outputs/static_pi/p2_confirm', '/root/research_outputs/static_pi/stage_d/qs_confirm',
                '/root/research_outputs/static_pi/stage_d/sc_e1_1', '/root/research_outputs/static_pi/stage_d']
import p2c_runner as P
R = P.R


class Fake:
    def __init__(self, mode=None):
        self.mode, self.n = mode, 0

    def describe(self, *a):
        return 'fake://', {}

    def call(self, backend, system, user, mt):
        self.n += 1
        if self.mode == 'transport':
            raise ConnectionError('connection reset by peer (simulated)')
        if (self.mode == 'J2R' and backend == 'glm' and mt == 12000) or (self.mode == 'J2' and backend == 'glm' and mt == 8000):
            return {'text': '{"verified": [', 'stop': 'max_tokens', 'in': 900, 'out': mt, 'raw_response': None, 'response_model': 'fake'}
        if system in (R.SINK_SYS, P.G1_SYS):
            body = {'answers': [{'fact_id': 'F1', 'value': 'x', 'quote': 'y', 'doc': 'D2'}], 'unknown_slots': []}
        elif system == R.J1_SYS:
            body = {'party_matrix': []}
        elif system == R.J2_SYS:
            body = {'verified': []}
        else:
            body = {'parties': []}
        return {'text': json.dumps(body), 'stop': 'stop', 'in': 900, 'out': 300, 'raw_response': None, 'response_model': 'fake'}


def run(mode, caps=None, stub_targets=False):
    real_rand, real_caps = P.RANDOMIZATION, dict(P.CAPS)
    seen, keep = [], {}
    orig = P.TaskScorer.score
    P.TaskScorer.score = lambda self, sink: (seen.append(json.dumps(sink, sort_keys=True)), orig(self, sink))[1]
    if stub_targets:
        keep = dict(m1=P.D5.detect_m1, m3=P.D5.detect_m3, er=R.evidence_rows)
        P.D5.detect_m1 = lambda slots, j2, rows: {f['fact_id']: dict(state='UNKNOWN_LABEL', j2_status='待核',
                                                                     label_class='unknown', candidates=1, candidate_rows=['R1']) for f in slots}
        P.D5.detect_m3 = lambda slots, sink, rows, base: {}
        R.evidence_rows = lambda et, dn: ([dict(row='R1', doc='D2', label='测试', quote='测试引文')], None)
    if caps:
        P.CAPS.update(caps)
    out = tempfile.mkdtemp()
    fk = Fake(mode)
    try:
        rec = P.run_pilot(fk, out_dir=out)
    finally:
        P.RANDOMIZATION, P.TaskScorer.score = real_rand, orig
        if stub_targets:
            P.D5.detect_m1, P.D5.detect_m3, R.evidence_rows = keep['m1'], keep['m3'], keep['er']
        P.CAPS.clear(); P.CAPS.update(real_caps)
    led = [json.loads(l) for l in open(f'{out}/LEDGER.jsonl')]
    return rec, led, seen, fk.n


ok = {}
rec, led, seen, n = run('J2R', stub_targets=True)
fails = [(k, a, v['arms'][a]['status']) for k, v in rec.items() for a in P.ARMS
         if v['arms'][a]['status'].startswith('RECOVERY_FAILED_TRUNCATED')]
fb = all(seen[i * 6 + P.ARMS.index(a)] == seen[i * 6 + P.ARMS.index('G2')]
         for i, v in enumerate(rec.values()) for a in P.ARMS if v['arms'][a]['status'].startswith('RECOVERY_FAILED'))
j2r = [r for r in led if r['phase'] == 'done' and r['node'] == 'J2R']
ok['T1'] = bool(fails) and fb and len(rec) == 52 and all(r['fault'] == 'truncated' and r['out'] == 12000 and r['yuan_accounting'] > 0 for r in j2r) \
           and all('stopped' not in v for v in rec.values())
print('T1 J2R truncation:', 'PASS' if ok['T1'] else 'FAIL', '| blocks done', len(rec),
      '| recovery-failed sample', fails[:2], '| fallback terminal == G2 terminal:', fb, '| J2R rows booked:', len(j2r))

rec, led, seen, n = run('J2')
g1 = [r for r in led if r['phase'] == 'done' and r['node'] == 'G1']
c2 = all(v['shared_fault'] == 'J2 fault: truncated' and v['arms']['G1']['status'] == 'OK' and not v['arms']['G1']['execution_failed']
         and all(v['arms'][a]['execution_failed'] and v['arms'][a]['Q'] == 0.0 for a in ('G2', 'G3', 'G4', 'G5', 'G6')) for v in rec.values())
ok['T2'] = c2 and len(rec) == 52 and len(g1) == 52
print('T2 shared J2 truncation:', 'PASS' if ok['T2'] else 'FAIL', '| blocks recorded', len(rec), '| G1 executed', len(g1),
      '| G2-G6 Q=0 & EXECUTION_FAILED:', c2, '| calls/block', n / 52)

rec, led, seen, n = run('transport')
v = list(rec.values())
ok['T3'] = len(rec) == 1 and 'transport' in v[0].get('stopped', '') and n == 1 and any(r.get('stop') == 'transport_error' for r in led)
print('T3 transport error:', 'PASS' if ok['T3'] else 'FAIL', '| stopped:', v[0].get('stopped'), '| calls', n)

rec, led, seen, n = run(None, caps=dict(calls=3))
v = list(rec.values())
ok['T4'] = len(rec) == 1 and 'cap reached' in v[0].get('stopped', '') and n == 3
print('T4 budget call cap:', 'PASS' if ok['T4'] else 'FAIL', '| stopped:', v[0].get('stopped'), '| calls', n, '| rec', list(rec))

print('ALL', 'PASS' if all(ok.values()) else 'FAIL')
sys.exit(0 if all(ok.values()) else 1)
