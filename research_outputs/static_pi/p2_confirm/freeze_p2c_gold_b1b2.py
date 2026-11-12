#!/usr/bin/env python3
"""Freeze P2-C Gold batch 1+2 (10 contracts) into read-only v1 files + hash baseline.

Convention mirrors P2-B pilot freeze: contract_version 'v1', status 'GOLD_APPROVED', approval block,
file mode 0444. Refuses to overwrite an existing v1 (revisions must go to v1.1+, never in place).
"""
import hashlib, json, os, stat, sys
from pathlib import Path

GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT = Path('/root/research_outputs/static_pi/p2_confirm/P2C_GOLD_BASELINE_B1B2.json')
DATE = '2026-11-08'

ACCEPT = {
    'FG_600399': (1, 'ACCEPTED', '批1；同等标准（逐字引文/合计复算）已完成，按操作员裁决直接纳入冻结'),
    'KJ_600806': (1, 'ACCEPTED_WITH_RULING_REVISION', '批1；冻结前按批2裁决口径修订：6人由"剔除/未处罚"改为"D2未再载明对应处罚"，不认定撤销、不计0'),
    'GD_839680': (1, 'ACCEPTED', '批1；同等标准已完成，直接纳入冻结'),
    'KR_002072': (1, 'ACCEPTED_WITH_RULING_REVISION', '批1；冻结前按批2裁决口径修订：15人组改为"D2未再载明对应处罚"；吴联模禁入终局由"未采取"改为UNKNOWN(F21)'),
    'DY_002086': (1, 'ACCEPTED', '批1；零变化型，直接纳入冻结'),
    'BQ_600074': (2, 'APPROVED', '批2裁决：通过；保留金额下调及处罚项次变化'),
    'DG_002715': (2, 'APPROVED', '批2裁决：通过；禁入终局UNKNOWN，不推断未采取'),
    'HX_300427': (2, 'CONDITIONALLY_APPROVED', '批2裁决：有条件通过；接受D1转述摘要，须如实说明来源性质，拟罚合计UNKNOWN不计0、不倒推'),
    'YS_300376': (2, 'APPROVED_AFTER_REVISION', '批2裁决：修订后通过；关易波、林丹丹表述为"D2未再载明对应处罚"，不认定撤销、不计0'),
    'TX_000070': (2, 'APPROVED', '批2裁决：通过；零变化保留，决定书收到日UNKNOWN'),
}

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
    name='P2-C Gold baseline (batch 1 + batch 2)', date=DATE, n_tasks=len(entries),
    rules=['冻结后不修改Gold；事实错误走正式版本修订(v1.1+)，不覆盖v1',
           'D2未记载≠终罚为零；D2未出现某人≠法律意义上的撤销',
           '文书未明确收到日期，不以公告日期替代（UNKNOWN）',
           '摘要未披露金额，不得由终罚倒推拟罚',
           'UNKNOWN槽不计入N、不计入critical、不得计为0',
           '扫描表数值仅用于初筛，不作Gold依据'],
    builders=dict(
        batch1=[f'/root/research_outputs/static_pi/p2_confirm/build_contract_{x}.py'
                for x in ('fg600399', 'kj600806', 'gd839680', 'kr002072', 'dy002086')],
        batch2=['/root/research_outputs/static_pi/p2_confirm/build_contracts_batch2.py']),
    contracts=entries,
    not_in_scope=dict(p2b_pilot=['ZQ_300526', 'CY_600525', 'SL_002766'],
                      note='P2-B试点冻结件，不属P2-C正式池，未改动'),
)
OUT.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + '\n', 'utf-8')
os.chmod(OUT, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
print('baseline sha256:', sha(OUT))
for k, v in entries.items():
    print(f"{k}  b{v['batch']}  {v['acceptance']:30} slots={v['slots']:2} crit={v['critical']:2} N={v['scored_N']:2} unk={v['unknown']}  {v['sha256'][:16]}")
