#!/usr/bin/env python3
"""Freeze one P2-C Gold batch into read-only v1 files + hash baseline.

Convention mirrors P2-B pilot freeze: contract_version 'v1', status 'GOLD_APPROVED', approval block,
file mode 0444. Refuses to overwrite an existing v1 (revisions must go to v1.1+, never in place).
"""
import hashlib, json, os, stat, sys
from pathlib import Path

GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT = Path(sys.argv[2])
DATE = '2026-11-08'

ACCEPT = json.loads(Path(sys.argv[1]).read_text('utf-8'))
ACCEPT = {k: tuple(v) for k, v in ACCEPT.items()}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

if OUT.exists():
    sys.exit(f'REFUSE: baseline already exists: {OUT}')
for name in ACCEPT:
    if (GOLD / f'TASK_CONTRACT_{name}_v1.json').exists():
        sys.exit(f'REFUSE: frozen v1 already exists for {name}')

entries = {}
for name, (batch, status, note) in ACCEPT.items():
    draft = GOLD / f'TASK_CONTRACT_{name}_v1_DRAFT.json'
    c = json.loads(draft.read_text('utf-8'))
    assert c['status'] == 'DRAFT_PENDING_OPERATOR_REVIEW', (name, c['status'])
    c['contract_version'] = 'v1'
    c['status'] = 'GOLD_APPROVED'
    c['approval'] = dict(date=DATE, by='operator', batch=batch, acceptance=status, result=note,
                         draft_sha256=sha(draft))
    out = GOLD / f'TASK_CONTRACT_{name}_v1.json'
    out.write_text(json.dumps(c, ensure_ascii=False, indent=1) + '\n', 'utf-8')
    os.chmod(out, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    facts = c['required_facts']
    entries[name] = dict(
        file=str(out), sha256=sha(out), version='v1', batch=batch, acceptance=status, note=note,
        draft_sha256=sha(draft), task_id=c['task_id'],
        slots=len(facts), critical=len(c['critical_fact_ids']),
        unknown=[u['fact_id'] for u in c['unknown_items']],
        scored_N=sum(1 for f in facts if f['status'] != 'GOLD_DRAFT_UNKNOWN'))

baseline = dict(
    name=f'P2-C Gold baseline ({OUT.stem})', date=DATE, n_tasks=len(entries),
    rules=['冻结后不修改Gold；事实错误走正式版本修订(v1.1+)，不覆盖v1',
           'D2未记载≠终罚为零；D2未出现某人≠法律意义上的撤销',
           '文书未明确收到日期，不以公告日期替代（UNKNOWN）',
           '摘要未披露金额，不得由终罚倒推拟罚',
           'UNKNOWN槽不计入N、不计入critical、不得计为0',
           '扫描表数值仅用于初筛，不作Gold依据'],
    builders=sys.argv[3:],
    contracts=entries,
    prior_baselines=['/root/research_outputs/static_pi/p2_confirm/P2C_GOLD_BASELINE_B1B2.json'],
)
OUT.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + '\n', 'utf-8')
os.chmod(OUT, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
print('baseline sha256:', sha(OUT))
for k, v in entries.items():
    print(f"{k}  b{v['batch']}  {v['acceptance']:30} slots={v['slots']:2} crit={v['critical']:2} N={v['scored_N']:2} unk={v['unknown']}  {v['sha256'][:16]}")
