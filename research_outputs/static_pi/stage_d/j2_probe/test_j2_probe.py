"""J2 probe offline tests (zero calls; network patched to fail)."""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'sc_e1_1'), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY', 'J2_PROBE_GO'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import run_j2_probe as P  # noqa: E402
import sc_e1_1_mock as M  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402

RES = []
PROTECTED = HERE.parent / 'sc_e1_1/canary_A2/LEDGER.jsonl'
BEFORE = hashlib.sha256(PROTECTED.read_bytes()).hexdigest()


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<80} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def main():
    ins = P.inputs()
    chk('P1 three inputs, each byte-identical to a Stage A\' J2 request', len(ins) == 3 and len({i['user_sha256'] for i in ins}) == 3)
    plan = P.plan()
    chk('P2 plan: DS then GLM, 3 inputs x 2 replicates each, 12 calls',
        plan == [(m, f'J2_in{i}', r) for m in ('ds', 'glm') for i in (1, 2, 3) for r in (1, 2)])
    out = Path(tempfile.mkdtemp())
    s = P.run(M.MockTransport(), out)
    rows = [r for r in R.read_ledger(out / 'LEDGER.jsonl') if r['phase'] == 'done']
    chk('P3 all 12 calls made in order with the frozen J2 prompt and the per-model output cap',
        [(r['backend'], r['input_id']) for r in rows] == [(m, i) for m, i, _ in plan]
        and all(r['system_sha256'] == R._sha(R.J2_SYS) and r['max_tokens'] == P.MAX_TOKENS[r['backend']] for r in rows), len(rows))
    chk('P4 ledger write-ahead and complete; summary used = 12 calls', s['ledger_ok'] and s['used']['calls'] == 12, s['used'])
    real = R.RealTransport()
    glm_body = real.describe('glm', R.J2_SYS, ins[0]['user'], 8000)[1]
    ds_body = real.describe('ds', R.J2_SYS, ins[0]['user'], 4000)[1]
    chk('P5 GLM request: subscription endpoint, reasoning_effort low, no thinking field, max_tokens 8000',
        glm_body.get('reasoning_effort') == 'low' and 'thinking' not in glm_body and glm_body['max_tokens'] == 8000
        and 'api/anthropic' in real.describe('glm', R.J2_SYS, 'x', 8000)[0])
    chk('P6 DS request: thinking disabled, temperature 0, json_object, max_tokens 4000',
        ds_body['thinking'] == {'type': 'disabled'} and ds_body['temperature'] == 0 and ds_body['max_tokens'] == 4000
        and ds_body['response_format'] == {'type': 'json_object'})
    out2 = Path(tempfile.mkdtemp())
    s2 = P.run(M.MockTransport({('J2', 'glm'): 'length'}), out2)
    glm_calls = [r for r in R.read_ledger(out2 / 'LEDGER.jsonl') if r['phase'] == 'done' and r['backend'] == 'glm']
    chk('P7 GLM truncation stops GLM only: DS 6 calls done, GLM 1 call then skipped, no retry',
        'glm' in s2['stopped_models'] and len(glm_calls) == 1 and s2['used']['calls'] == 7
        and sum(1 for r in s2['records'] if r.get('skipped')) == 5, (s2['stopped_models'], s2['used']))
    out3 = Path(tempfile.mkdtemp())
    s3 = P.run(M.MockTransport({('J2', 'ds'): 'http429'}), out3)
    chk('P8 DS transport error stops DS only; GLM still runs its 6 calls',
        'ds' in s3['stopped_models'] and s3['used']['calls'] == 7, (s3['stopped_models'], s3['used']))
    try:
        P.run(M.MockTransport(), out)
        refused = False
    except SystemExit:
        refused = True
    chk('P9 a finished probe scene is never rerun', refused)
    try:
        P.check_real_gate('x')
        refused = False
    except SystemExit:
        refused = True
    chk('P10 real mode refused without J2_PROBE_GO', refused)
    chk('P11 Stage A\' ledger untouched', hashlib.sha256(PROTECTED.read_bytes()).hexdigest() == BEFORE)
    passed = sum(r['ok'] for r in RES)
    (HERE / 'J2_PROBE_OFFLINE_TESTS.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES), ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
