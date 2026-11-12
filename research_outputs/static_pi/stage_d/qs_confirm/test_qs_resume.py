"""Offline tests for the minimal block-2 resumption amendment (zero calls; network patched to fail)."""
import hashlib
import json
import os
import shutil
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
    print(f'  {name:<88} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def seed_scene(dst):
    """A run directory in the post-stop state: reps 1-5 done, rep 6 registered, block-2 stop record present."""
    src = HERE / 'run'
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3, 4, 5, 6):
        shutil.copy(src / f'REP_{i}.json', dst / f'REP_{i}.json')
    shutil.copy(src / 'LEDGER.jsonl', dst / 'LEDGER.jsonl')
    shutil.copy(src / 'BLOCK_1.json', dst / 'BLOCK_1.json')
    shutil.copy(src / 'BLOCK_2.json', dst / 'BLOCK_2.json')
    return dst


def main():
    rep6 = json.loads((HERE / 'run/REP_6.json').read_text('utf-8'))
    chk('A1 rep 6 registered: three incomplete arms, Q_all 0, safety UNDEFINED, cause recorded, no rerun of its call',
        all(rep6['arms'][k]['incomplete'] and rep6['arms'][k]['metrics']['Q_all'] == 0.0 for k in 'ABC')
        and all(rep6['arms'][k]['safety']['error_rate'] is None for k in 'ABC')
        and rep6['registration']['kind'] == 'INCOMPLETE_REPLICATE')
    an = QR.analyse(HERE / 'run')
    chk('A2 analysis over six reps: rep 6 counts as ties in both C-A and C-B', an['reps'] == 6
        and an['per_rep'][5]['q'] == dict(A=0.0, B=0.0, C=0.0) and an['H1']['test']['n_eff'] == 4, an['per_rep'][5])

    tmp = seed_scene(tempfile.mkdtemp())
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp.glob('*')}
    s = QR.run_block(2, M.QSMock({'J2': ['suppress'] * 12}), tmp, resume=True)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp.glob('*')}
    chk('B1 resume runs only reps 7 and 8; scenes of reps 1-6 and both block records are byte-untouched',
        s['reps_done'] == [7, 8] and all(before[k] == after[k] for k in before if k.startswith('REP_') or k.startswith('BLOCK_'))
        and (tmp / 'BLOCK_2_RESUME.json').exists(), s['reps_done'])
    chk('B2 resumed summary is PASS with resume flag, and the analysis now covers eight reps',
        s['verdict'] == 'PASS' and s['resumed'] is True and json.loads((tmp / 'BLOCK_2_RESUME.json').read_text('utf-8'))['analysis']['reps'] == 8)
    prior2 = QR.used_from_ledger(HERE / 'run/LEDGER.jsonl', 2)
    used = json.loads((tmp / 'BLOCK_2_RESUME.json').read_text('utf-8'))['used']
    chk('B3 the resumed budget continues from this block\'s earlier spend only (block-2 prior = 10 calls / 124,056 tok / ¥0.2187)',
        prior2['calls'] == 10 and prior2['tokens'] == 124056 and abs(prior2['yuan_accounting'] - 0.218665) < 1e-6
        and used['calls'] > prior2['calls'] and used['tokens'] > prior2['tokens'], prior2)

    tmp2 = seed_scene(tempfile.mkdtemp())
    try:
        QR.run_block(2, M.QSMock({}), tmp2)
        refused = False
    except SystemExit:
        refused = True
    chk('B4 without --resume the runner still refuses when a replicate scene exists', refused)

    tmp3 = seed_scene(tempfile.mkdtemp())
    s5 = QR.run_block(2, M.QSMock({'E': ['length']}), tmp3, resume=True)
    chk('B5 the shared-stage stop rule is unchanged in resume mode (E_D1 truncation stops the batch again)',
        s5['verdict'] == 'FAIL' and s5['reps_done'] == [] and 'shared-stage node fault at E_D1' in (s5['stopped'] or ''), s5['stopped'])

    os.environ['QS_BLOCK_GO'] = '2'
    blk2 = hashlib.sha256((HERE / 'run/BLOCK_2.json').read_bytes()).hexdigest()
    try:
        QR.check_real_gate(2, 'x', 'y', resume=True)
        r1 = None
    except SystemExit as exc:
        r1 = str(exc)
    chk('B6 resume gate: wrong --after against the stop record is refused', 'BLOCK_2' in (r1 or ''), r1)
    try:
        QR.check_real_gate(2, 'x', blk2, resume=False)
        r2 = None
    except SystemExit as exc:
        r2 = str(exc)
    chk('B7 the non-resume block-2 gate still chains to BLOCK_1, not the stop record', 'BLOCK_1' in (r2 or ''), r2)
    fz = QR.freeze_inputs()
    chk('B8 the freeze pins the amended runner and the rep-6 registration', any(p.endswith('qs_runner.py') for p in fz['files'])
        and any(p.endswith('REP_6.json') for p in fz['files']) and any(p.endswith('RESUME_AMENDMENT.md') for p in fz['files']))
    st6 = QR.sign_test_one_sided([0.25, 0.35, 0.30, 0.20, 0.0, 0.0, 0.25, 0.25])
    chk('B9 statistics path: 6 positive of 6 valid pairs gives p=0.015625 (matches the operator arithmetic)',
        st6 == dict(n_eff=6, positive=6, p=0.015625), st6)

    passed = sum(r['ok'] for r in RES)
    (HERE / 'RESUME_TESTS.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES), ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
