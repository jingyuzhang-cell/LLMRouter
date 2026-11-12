#!/usr/bin/env python3
"""Qianshan contract v1 from the reviewed DRAFT (operator review 2026-11-06). The DRAFT is read, never written.

Changes from the DRAFT: F18 states its required titles explicitly and records 法定代表人 as a separate
legal identity that is neither required nor wrong; status, approval record and scoring text updated.
No Gold value changes.
"""
import copy
import hashlib
import json
from pathlib import Path

PKG = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/QS_300216')
DRAFT = PKG / 'TASK_CONTRACT_QS_v1_DRAFT.json'
DRAFT_SHA256 = '02e1a35f6b01b944e4ea34f41efaeae9e4e93687d48a1d81b2a15d023baa3240'
V1 = PKG / 'TASK_CONTRACT_QS_v1.json'


def build():
    raw = DRAFT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DRAFT_SHA256, 'draft changed'
    draft = json.loads(raw)
    ct = copy.deepcopy(draft)
    f18 = next(f for f in ct['required_facts'] if f['fact_id'] == 'F18')
    f18['grounding'].update(required_titles=['董事长', '总经理'], additional_identity='法定代表人',
                            rule_note='TP needs both required titles; 法定代表人 may be added and is not an error; '
                                      '法定代表人 alone, or one required title alone, does not complete the slot')
    for f in ct['required_facts']:
        f['status'] = 'GOLD_APPROVED'
    ct.update(contract_version='v1', status='GOLD_APPROVED',
              approval=dict(date='2026-11-06', by='operator', result='conditional pass; condition (F18 wording) applied in v1',
                            accepted=['20 slots and document whitelists', 'scorer additions: unit conversion with Decimal and '
                                      'round-half-up to the gold precision; affirmative 是否 slots; the two penalty-line wordings',
                                      'SINK deterministic derived-value line computed from real extraction output'],
                            draft=dict(path=str(DRAFT), sha256=DRAFT_SHA256)))
    ct['positioning'] = ('独立确认任务（操作员 2026-11-06 选定）。Gold 由规则从原文构建，操作员审阅有条件通过（F18 口径已按审阅意见写入 v1）。'
                         '确认实验预注册与授权之前不得调用任何模型。')
    ct['scoring']['amount_rule'] = ('same unit: exact Decimal equality; other unit of the same dimension: convert with Decimal; '
                                    'a finer unit is rounded half-up to the gold precision (91,662,331.39元 -> 9166.23万元); '
                                    '9166.2万元 is wrong')
    ct['scoring']['title_rule'] = 'F18: required titles 董事长 and 总经理; 法定代表人 is recorded separately and never required'
    return ct


def main():
    payload = json.dumps(build(), ensure_ascii=False, indent=1) + '\n'
    if V1.exists() and V1.read_text('utf-8') != payload:
        raise SystemExit(f'REFUSED: {V1} exists with different content; versions are never overwritten')
    V1.write_text(payload, 'utf-8')
    print('v1 sha256:', hashlib.sha256(V1.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
