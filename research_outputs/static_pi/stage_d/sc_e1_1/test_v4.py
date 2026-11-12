"""Offline regression for detectors V4 (zero calls; network patched to fail). Replays every real J2 output."""
import ast
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
for key in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
    os.environ.pop(key, None)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network attempted'))

import detectors_v2 as V2  # noqa: E402
import detectors_v3 as V3  # noqa: E402
import detectors_v4 as V4  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_1_stage_a2 as A2  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402

RES = []
FLAGGED = ('F8', 'F9', 'F10', 'F11', 'F20')


def chk(name, cond, detail=''):
    RES.append(dict(name=name, ok=bool(cond), detail=str(detail)[:300]))
    print(f'  {name:<84} {"PASS" if cond else "FAIL"} {"" if cond else detail}')


def main():
    V4.verify_pins()
    chk('L1 V2 and V3 files are the frozen ones', True)
    cls = {s: V4.classify(s) for s in ('已核验', 'Verified', 'correct', 'supported', 'computed', 'unverifiable', '无法核验', 'not_found',
                                       'partially_verified', '部分核验', None)}
    chk('L2 classifier: seen affirmatives, V2 suppressions plus not_found, anything else unknown, missing None',
        cls == {'已核验': 'affirmed', 'Verified': 'affirmed', 'correct': 'affirmed', 'supported': 'affirmed', 'computed': 'affirmed',
                'unverifiable': 'suppressed', '无法核验': 'suppressed', 'not_found': 'suppressed', 'partially_verified': 'unknown',
                '部分核验': 'unknown', None: None}, cls)

    ct = SC.load_contract()
    docs, slots_json = R.load_task(ct)
    slots = json.loads(slots_json)
    e = A2.load_reused_e(HERE / 'canary_A', docs)
    rows, _ = R.evidence_rows(e, SC.doc_index(ct))
    j2_rows = [r for p in (HERE / 'canary_A2/LEDGER.jsonl', HERE / 'fork_t1/run/LEDGER.jsonl') for r in R.read_ledger(p)
               if r['phase'] == 'done' and r['node'] == 'J2']
    chk('L3 replay covers every real J2 output (3 Stage A\' + 6 T1)', len(j2_rows) == 9, len(j2_rows))
    diffs, t1 = [], {}
    for r in j2_rows:
        j2 = OLD.extract_json(r['text'])
        a, b = V3.detect_m1(slots, j2, rows), V4.detect_m1(slots, j2, rows)
        key = f"{'T1' if 'fork' in str(r.get('arm', '')) or r['arm'] in ('A1', 'A2') else 'A2prime'}:{r['arm']}:r{r['rep']}"
        for fid in a:
            if a[fid]['state'] != b[fid]['state']:
                diffs.append((key, fid, a[fid]['state'], b[fid]['state'], b[fid]['j2_status']))
        if r['arm'] in ('A1', 'A2'):
            t1[key] = {f: b[f]['state'] for f in FLAGGED}
    chk('L4 T1 A1 r3 (status not_found): V4 flags all five slots as explicit suppression where V3 reported NONE',
        t1.get('T1:A1:r3') == {f: 'EXPLICIT_SUPPRESSION' for f in FLAGGED}, t1.get('T1:A1:r3'))
    chk('L5 T1 A1 r1, r2 (unverifiable): explicit suppression, as in V2/V3',
        t1.get('T1:A1:r1') == t1.get('T1:A1:r2') == {f: 'EXPLICIT_SUPPRESSION' for f in FLAGGED})
    chk('L6 T1 A2 replicates (已核验): NONE on all five', all(t1.get(f'T1:A2:r{i}') == {f: 'NONE' for f in FLAGGED} for i in (1, 2, 3)))
    expected = {('T1:A1:r3', f) for f in FLAGGED}
    chk('L7 the only differences from V3 across all nine real J2 outputs are the five not_found slots',
        {(d[0], d[1]) for d in diffs} == expected and all(d[2] == 'NONE' and d[3] == 'EXPLICIT_SUPPRESSION' for d in diffs), diffs)
    unk = V4.detect_m1(slots[:9], dict(verified=[dict(fact_id=s['fact_id'], status='部分核验') for s in slots[:9]]), rows)
    chk('L8 an unseen label with candidate evidence is UNKNOWN_LABEL, never silently NONE',
        {v['state'] for f, v in unk.items() if v['candidates']} == {'UNKNOWN_LABEL'}, unk)
    polar = dict(fact_id='P', subject='甲公司', predicate='是否触及重大违法强制退市情形')
    prow = [dict(row='R1', doc='D1', label='x', quote='根据《事先告知书》认定的事实，公司触及《上市公司重大违法强制退市实施办法》第四条规定的重大违法强制退市情形')]
    chk('L9 polar slots keep V3 candidates: not_found on an affirmative row is explicit suppression',
        V4.detect_m1([polar], dict(verified=[dict(fact_id='P', status='not_found')]), prow)['P']['state'] == 'EXPLICIT_SUPPRESSION')
    tree = ast.parse((HERE / 'detectors_v4.py').read_text('utf-8'))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    chk('L10 V4 reads no Gold or contract', not names & {'required_facts', 'source_evidence', 'allowed_citation_docs', 'contract', 'SC'})
    passed = sum(r['ok'] for r in RES)
    files = {p: hashlib.sha256((HERE / p).read_bytes()).hexdigest() for p in ('detectors_v4.py', 'detectors_v3.py', 'detectors_v2.py')}
    (HERE / 'V4_REGRESSION.json').write_text(json.dumps(dict(passed=passed, total=len(RES), results=RES, files=files,
                                                             v3_v4_differences=diffs), ensure_ascii=False, indent=1), 'utf-8')
    print(f'\n{passed}/{len(RES)} passed')
    sys.exit(0 if passed == len(RES) else 1)


if __name__ == '__main__':
    main()
