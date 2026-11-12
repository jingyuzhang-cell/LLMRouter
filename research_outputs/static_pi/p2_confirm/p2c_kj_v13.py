#!/usr/bin/env python3
"""KJ_600806 v1.2 -> v1.3 per operator ruling (2026-11-08):
F20/F21 predicate -> 'D1拟采取市场禁入措施', evidence D1-only (g11 unchanged), dual_stage marks
D2 final UNKNOWN, entity_correspondence.market_bans marks final UNKNOWN; no scored-slot change (N=20)."""
import hashlib, json, os, stat, sys
from pathlib import Path
G = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
src, out = G / 'TASK_CONTRACT_KJ_600806_v1.2.json', G / 'TASK_CONTRACT_KJ_600806_v1.3.json'
if out.exists(): sys.exit('REFUSE: v1.3 exists')
c = json.loads(src.read_text()); old = json.loads(src.read_text())
assert len(c['required_facts']) == 21 and c['scoring']['primary'].startswith('Q_all = TP / N (N=20')
NOTE = 'D2（【2018】9号处罚决定书）未载禁入决定，终局UNKNOWN，不得表述为已确定的最终禁入措施'
for fid, dur in (('F20', '终身证券市场禁入'), ('F21', '5年证券市场禁入')):
    f = next(x for x in c['required_facts'] if x['fact_id'] == fid)
    f['predicate'] = 'D1拟采取市场禁入措施'
    f['dual_stage'] = dict(d1_proposed=dur, d2_final=f'UNKNOWN（{NOTE}）', change='final_unknown')
    f['derivation'] = dict(note=f'{NOTE}；本槽保留D1拟处罚事实，非对终局的确认', ruling='operator 2026-11-08')
    assert f['g11']['support_docs'] == ['D1']
c['entity_correspondence']['market_bans'] = dict(
    proposed=['王兴终身', '常宝强5年', '金晓峰5年'],
    final=f"UNKNOWN（{NOTE}）")
c['known_issues'].append(dict(issue='F20/F21为D1拟禁入，D2无禁入决定', handling='谓词标明"拟"，dual_stage与market_bans标注终局UNKNOWN；不新增计分槽（操作员裁决，含条件通过）'))
c['contract_version'] = 'v1.3'
c['revision'] = dict(supersedes='v1.2', supersedes_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                     date='2026-11-08', basis='operator ruling: KJ F20/F21 restricted to D1 proposed bans, final UNKNOWN',
                     facts_changed=dict(kind='predicate_semantics_only', scored_slots_unchanged=True, N=20))
for a, b in zip(old['required_facts'], c['required_facts']):
    for k in ('fact_id', 'value', 'value_kind', 'critical', 'status', 'subject', 'allowed_citation_docs', 'g11'):
        assert a.get(k) == b.get(k), (a['fact_id'], k)
out.write_text(json.dumps(c, ensure_ascii=False, indent=1) + '\n', 'utf-8'); os.chmod(out, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
sha = hashlib.sha256(out.read_bytes()).hexdigest()
with open('P2C_GOLD_REVISIONS.jsonl', 'a') as fh:
    fh.write(json.dumps(dict(date='2026-11-08', task='KJ_600806', from_version='v1.2', to_version='v1.3',
                             from_sha256=c['revision']['supersedes_sha256'], to_sha256=sha,
                             kind='predicate_semantics_only', facts_changed=False), ensure_ascii=False) + '\n')
print('KJ v1.3', sha)
