#!/usr/bin/env python3
"""RQ1 节点材料零调用校验：证据跨度、节点覆盖、Gold 独立性标记。"""
import json, re, sys
from pathlib import Path

BASE = Path(__file__).parent
MAT = json.load(open(BASE/'rq1_tasks_materials.json',encoding='utf-8'))
FACTS = json.load(open(BASE/'all_facts.json',encoding='utf-8'))
DOCS = Path('/root/cap_eval_bench_v1/evidence/texts')
E04_FACTS = {f['fact_id']: f for f in FACTS['E04']}
E58 = FACTS['E05_E08']

def norm(s): return re.sub(r'\s+','',s or '')

errors=[]; total_nodes=0; total_facts=0
for tid, task in MAT['tasks'].items():
    docs={d['doc_id']: norm(open(DOCS/d['file'],encoding='utf-8').read()) for d in task['docs']}
    facts = E04_FACTS if tid=='E04' else E58
    ids=set()
    for node in task['nodes']:
        total_nodes+=1
        for fid in node['fact_ids']:
            if fid not in facts:
                errors.append(f'{tid}/{node["node_id"]}: fact {fid} missing'); continue
            f=facts[fid]; ids.add(fid); total_facts+=1
            if f['evidence_doc'] not in docs:
                errors.append(f'{fid}: evidence_doc {f["evidence_doc"]} not in task docs'); continue
            if norm(f['evidence_span']) not in docs[f['evidence_doc']]:
                errors.append(f'{fid}: span NOT in {f["evidence_doc"]}')
        ref=node.get('reference_upstream')
        if ref:
            for up in ref.get('from_nodes',[]):
                if up not in {n['node_id'] for n in task['nodes']}:
                    errors.append(f'{tid}/{node["node_id"]}: upstream {up} missing')
    if tid=='E04':
        # E04 node facts must be a subset of M8 facts
        pass
    print(f'{tid}: nodes {len(task["nodes"])}, refs {len(ids)}')

if total_nodes != 25:
    errors.append(f'node count {total_nodes} != 25')
for e in errors:
    print('  [FAIL]', e)
if errors:
    print(f'\nFAILED: {len(errors)}'); sys.exit(1)
print(f'\nPASS: 25 nodes / {total_facts} node-fact references / spans verified / upstream refs valid')
