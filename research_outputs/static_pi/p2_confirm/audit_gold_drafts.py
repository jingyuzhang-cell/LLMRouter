#!/usr/bin/env python3
"""Zero-call post-build audit for P2-C Gold DRAFT contracts.

For each contract: (1) every doc in allowed_citation_docs without an attached quote must contain
the value (number/date) or the predicate anchor (text); (2) no value/d2_final may over-claim absence
("未处罚/未采取/已撤销"); (3) UNKNOWN slots carry no value and are excluded from critical and N.
Usage: audit_gold_drafts.py NAME [NAME ...]
"""
import json, re, sys, unicodedata
from pathlib import Path

GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
def n(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
OVER = re.compile(r'"(value|d2_final)": "[^"]*(未处罚|未采取|已撤销|整组撤销)')

ok = True
for nm in sys.argv[1:]:
    c = json.loads((GOLD / f'TASK_CONTRACT_{nm}_v1_DRAFT.json').read_text('utf-8'))
    txt = {k: n(v['pages']['1']['text']) for k, v in c['source_pages'].items()}
    issues = []
    unk = {f['fact_id'] for f in c['required_facts'] if f['status'] == 'GOLD_DRAFT_UNKNOWN'}
    for f in c['required_facts']:
        if f['fact_id'] in unk:
            if f['value'] is not None: issues.append(f'{f["fact_id"]} UNKNOWN has value')
            continue
        have = {e['doc_id'] for e in f['source_evidence']}
        for d in set(f['allowed_citation_docs']) - have:
            v, k = f['value'], f['value_kind']
            if k == 'number':
                x = v.lstrip('约'); probe = [f'{x}万', f'{float(x):,.2f}'.rstrip('0').rstrip('.')]
            elif k == 'date':
                p = v.split('-'); probe = [f'{p[0]}年{int(p[1])}月' + (f'{int(p[2])}日' if len(p) > 2 else '')]
            else:
                probe = [n(f['grounding'].get('predicate_anchor') or '')]
            if not any(q and q in txt[d] for q in probe):
                issues.append(f'{f["fact_id"]} value not found in uncited {d}: {v}')
    s = json.dumps(c, ensure_ascii=False)
    if OVER.search(s): issues.append('absence over-claim present')
    if unk & set(c['critical_fact_ids']): issues.append('UNKNOWN in critical list')
    m = re.search(r'N=(\d+)', c['scoring']['primary'])
    if int(m.group(1)) != len(c['required_facts']) - len(unk): issues.append('declared N mismatch')
    ok &= not issues
    print(f'{nm:11} {"OK" if not issues else issues}')
sys.exit(0 if ok else 1)
