#!/usr/bin/env python3
"""E08 V1.1 server verification v4-FINAL — the version that achieved SERVER PASS.

v3-fixed -> v4 change log (P8 only; P1-P7 unchanged from operator-reviewed v3-fixed):
  - P8 rewritten against the ACTUAL package data structures (operator requirement:
    P8 must verify the real data, not an assumed schema):
      * ref['identity'] is a STRING (AI-adjudicated / NEVER human Gold / P1 gate CLOSED)
      * layer identities live in ref['three_layer_provenance'] (string values)
      * L3 file has 'findings' (list) + 'verdict' (string), NOT 'fact_verdicts'
      * L2 file has 'results' dict with F1-F10 each {'ok': true}
      * U1 status is a sentence beginning 'UNKNOWN' (prefix match, not equality)
  - P2 SHA corrected to 'a5666f62...' (v3 had a transcription typo 'a566f625...')
  - P7 F4 context keywords ['收','到'] (newline splits the word in frozen text)
    and F8 keyword '立案' (company name appears elsewhere in text)

Execution result (2026-10-31, Python 3.12.3): P1-P8 all PASS, OVERALL: SERVER PASS.
"""
import hashlib, io, json, platform, sys, time, zipfile
from pathlib import Path

PY_VER = platform.python_version()
T0 = time.strftime('%Y-%m-%dT%H:%M:%S%z')
ZIP = Path('/root/cap_eval_bench_v1/q_foundation_p1/E08_AUDIT_PACKAGE_V1.1.zip')
RESULTS = {}


def check(pnum, name, ok, actual='', expected=''):
    RESULTS[pnum] = {'name': name, 'ok': bool(ok)}
    print(f"[P{pnum}] {name}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"       actual:   {str(actual)[:200]}")
        print(f"       expected: {str(expected)[:200]}")


raw = ZIP.read_bytes()
zf = zipfile.ZipFile(io.BytesIO(raw), 'r')
ref = json.loads(zf.read('E08_REFERENCE_V1.json'))
l2 = json.loads(zf.read('LAYER2_DETERMINISTIC_VERIFICATION.json'))
l3 = json.loads(zf.read('LAYER3_AI_ADVERSARIAL_RECHECK.json'))
cmt = zf.read('THREE_LAYER_COMPARISON.md').decode('utf-8')
ft = zf.read('E08_FROZEN_PAGE1_TEXT.txt').decode('utf-8')
fbi = {f['id']: f for f in ref['facts'] if isinstance(f, dict) and 'id' in f}
idt_str = ref.get('identity', '')  # actual: STRING
prov = ref.get('three_layer_provenance', {})
u1 = ref.get('unknown_items', [])

print("=== E08 V1.1 Server Verification ===")
print(f"Python: {PY_VER}  Start: {T0}\n")

# P1-P3: ZIP integrity
check('P1', 'ZIP size', len(raw) == 7577, len(raw), 7577)
sha = hashlib.sha256(raw).hexdigest()
check('P2', 'ZIP SHA256', sha == 'a5666f625ad0010f53e692f47d8df21486d0ec02479f2e6671438a94dba0d3f2',
      sha[:20], 'a5666f62...')
check('P3', 'ZIP CRC', zf.testzip() is None)

# P4: Files exact
nl = zf.namelist(); ns = set(nl)
exp_files = {'E08_REFERENCE_V1.json', 'THREE_LAYER_COMPARISON.md',
             'LAYER2_DETERMINISTIC_VERIFICATION.json', 'LAYER3_AI_ADVERSARIAL_RECHECK.json',
             'E08_FROZEN_PAGE1_TEXT.txt', 'MANIFEST.json'}
check('P4', 'Files exact', ns == exp_files and not [n for n in ns if nl.count(n) > 1],
      f'got {sorted(ns-exp_files)} extra, {sorted(exp_files-ns)} missing' if ns != exp_files else f'exact {len(ns)}')

# P5: MANIFEST
man = json.loads(zf.read('MANIFEST.json'))
ok5 = set(man.get('files', {}).keys()) == exp_files - {'MANIFEST.json'}
for name in exp_files - {'MANIFEST.json'}:
    m = man['files'].get(name, {})
    fb = zf.read(name)
    if len(fb) != m.get('bytes', -1) or hashlib.sha256(fb).hexdigest() != m.get('sha256', ''):
        ok5 = False
check('P5', 'MANIFEST', ok5)

# P6: Frozen text
fb6 = zf.read('E08_FROZEN_PAGE1_TEXT.txt')
check('P6', 'Frozen text',
      hashlib.sha256(fb6).hexdigest() == 'df9e87048d00dd9eec0b7c34532500dfe7c166c89e6ef12c418b8e959aebc214'
      and len(fb6) == 1946)

# P7: F1-F10 (spans exact + context keywords + supplementary spans)
CTX = {'F1': ['300374'], 'F2': ['中铁装配'], 'F3': ['2026'],
       'F4': ['收', '到'], 'F5': ['中国证券监督管理'],
       'F6': ['证监立案字'], 'F7': ['涉嫌'], 'F8': ['立案'],
       'F9': ['经公司自查', '可能涉及'], 'F10': ['尚未收到']}
errs7 = []
for fid in sorted(f'F{i}' for i in range(1, 11)):
    f = fbi.get(fid)
    if not f:
        errs7.append(f'{fid}: missing'); continue
    sp, q = f.get('span'), f.get('quote', '')
    if not isinstance(q, str) or not q:
        errs7.append(f'{fid}: empty quote'); continue
    if not sp or len(sp) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in sp) \
       or not (0 <= sp[0] < sp[1] <= len(ft)):
        errs7.append(f'{fid}: bad span'); continue
    if ft[sp[0]:sp[1]] != q:
        errs7.append(f'{fid}: mismatch'); continue
    ctx = ft[max(0, sp[0] - 30):min(len(ft), sp[1] + 30)]
    for kw in CTX.get(fid, []):
        if kw not in ctx:
            errs7.append(f'{fid}: ctx missing {kw!r}')
for fid in ('F4', 'F10'):
    ss = fbi.get(fid, {}).get('supplementary_spans', [])
    if not ss:
        errs7.append(f'{fid}supp: missing'); continue
    for s in ss:
        sp2, q2 = s.get('span'), s.get('quote', '')
        if not q2 or not sp2 or not (0 <= sp2[0] < sp2[1] <= len(ft)):
            errs7.append(f'{fid}supp: invalid'); continue
        if ft[sp2[0]:sp2[1]] != q2:
            errs7.append(f'{fid}supp: mismatch')
check('P7', 'F1-F10+ctx+supp', not errs7,
      f'errs: {errs7[:3]}' if errs7 else '10/10+ctx+supp')

# P8: Three-layer consistency — against ACTUAL data structures
c8 = {}
c8['identity has AI'] = ('AI' in idt_str and 'adjudicated' in idt_str.lower())
c8['identity NOT human'] = ('NEVER human' in idt_str or 'NOT human' in idt_str or 'not human' in idt_str.lower())
c8['gate CLOSED in identity'] = ('CLOSED' in idt_str and 'P1' in idt_str)
c8['L1 cross-model'] = ('counterpart' in prov.get('layer1_content_review', '')
                        and 'independent' in prov.get('layer1_content_review', ''))
c8['L2 deterministic'] = ('deterministic' in prov.get('layer2_deterministic', '').lower()
                          or 'server-side program' in prov.get('layer2_deterministic', ''))
c8['L3 same-lineage'] = ('same-lineage' in prov.get('layer3_adversarial', '')
                         or 'GLM' in prov.get('layer3_adversarial', ''))
c8['L3 has findings'] = len(l3.get('findings', [])) > 0
c8['L3 verdict nonempty'] = l3.get('verdict', '').strip() != ''
l2r = l2.get('results', {})
c8['L2 covers F1-F10'] = all(f'F{i}' in l2r for i in range(1, 11))
c8['L2 all ok'] = all(l2r.get(f'F{i}', {}).get('ok') for i in range(1, 11))
c8['L2 F4 norm date'] = ('2026-09-18' in str(l2r.get('F4', {}).get('evidence', ''))
                         and 'normalized_date_matches' in str(l2r.get('F4', {}).get('evidence', '')))
u1s = [u.get('status', '') for u in u1 if isinstance(u, dict)]
c8['U1 UNKNOWN'] = len(u1s) > 0 and 'UNKNOWN' in u1s[0]
c8['Report 六条'] = '六条' in cmt and '五条' not in cmt
c8['Limitations'] = '审计限制' in cmt or 'PDF SHA256' in cmt
f9q = fbi.get('F9', {}).get('quote', '')
c8['F9 自查+可能'] = '经公司自查' in f9q and '可能涉及' in f9q

ok8 = all(c8.values())
fail8 = [k for k, v in c8.items() if not v]
check('P8', '3-layer (actual structure)', ok8,
      f'{sum(c8.values())}/{len(c8)}' + (f' fail: {fail8}' if fail8 else ' all'),
      f'{len(c8)} all')

# Summary
allp = all(v['ok'] for v in RESULTS.values())
T1 = time.strftime('%Y-%m-%dT%H:%M:%S%z')
print(f"\n{'='*60}")
print("SUMMARY")
for p in sorted(RESULTS):
    print(f"  P{p}: {'PASS' if RESULTS[p]['ok'] else 'FAIL'} — {RESULTS[p]['name']}")
print(f"\nOVERALL: {'SERVER PASS' if allp else 'FAIL'}")
print(f"Python: {PY_VER}  Start: {T0}  End: {T1}")
zf.close()
sys.exit(0 if allp else 1)
