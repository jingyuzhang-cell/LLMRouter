#!/usr/bin/env python3
"""Recycle-upgrade CY/SL/ZQ (P2-PILOT adjudicated contracts) to G7 V03 span-level v0.1 drafts.
Zero model calls: stage/fact_class derived from allowed_citation_docs + predicate heuristics;
evidence spans taken from the contracts' own adjudicated source_evidence quotes and re-verified
as substrings of the stored document text. Fact sets are NOT re-authored."""
import json, re
from collections import Counter
from pathlib import Path

SRC = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
HERE = Path(__file__).parent
norm = lambda s: re.sub(r'\s+', '', s)
META_PAT = re.compile(r'文号|日期|收到|作出|公告编号')

def doc_text(sp, d):
    return '\n'.join(sp[d]['pages'][k]['text'] for k in sorted(sp[d]['pages']))

SPECS = [('CY', 'TASK_CONTRACT_CY_600525_v1.json'), ('SL', 'TASK_CONTRACT_SL_002766_v1.json'),
         ('ZQ', 'TASK_CONTRACT_ZQ_300526_v1.json')]
out = HERE / 'contracts'
sheet = ['# G7 批3（回收升级）Gold 合同草案核验单（v0.1，待操作员裁决）', '',
         '来源：P2-PILOT 已裁决合同（事实集与逐字quote均为当年人工裁决产物），本升级仅做阶段/分类标注与跨度复验，不重写事实。', '']
totals = Counter()
for code, fname in SPECS:
    c = json.loads((SRC / fname).read_text())
    code_num = re.search(r'(\d{6})', c['task_id']).group(1)
    task = f"{code}_{code_num}"
    company = c.get('company') or c['source_documents']['D1'].get('title', '').split('关于')[0]
    docs = {d: doc_text(c['source_pages'], d) for d in ('D1', 'D2')}
    stripped = {d: norm(t) for d, t in docs.items()}
    facts = []
    sheet += [f"## {task} {company}", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 | 证据跨度（截选） |',
              '|---|---|---|---|---|---|---|---|']
    for f in c['required_facts']:
        allowed = f.get('allowed_citation_docs') or []
        stage = '拟' if allowed == ['D1'] else '终' if allowed == ['D2'] else '中性'
        val = f.get('value')
        is_unk = 'UNKNOWN' in str(val)
        fclass = ('unknown_boundary' if is_unk else 'doc_metadata' if META_PAT.search(f['predicate'])
                  else 'stage_content' if stage != '中性' else 'background')
        entries = []
        for e in f.get('source_evidence') or []:
            q = e['quote']
            assert norm(q) in stripped[e['doc_id']], f"{task} {f['fact_id']} quote not in doc"
            entries.append(dict(document_id=e['doc_id'], evidence_span=norm(q), raw_evidence_span=q,
                                evidence_stage=stage, support_status='supports'))
        facts.append(dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                          value=val, kind=f.get('value_kind', 'text'),
                          critical=fclass == 'stage_content', fact_stage=stage, fact_class=fclass,
                          allowed_citation_docs=allowed, stage_evidence=entries,
                          unknown_basis=('终局未载明，不得倒推；不以未提及推定处罚不存在或拟罚已执行'
                                         if is_unk else None)))
        ev0 = entries[0] if entries else None
        show = ((ev0['evidence_span'][:22] + '…') if ev0 and len(ev0['evidence_span']) > 22
                else ev0['evidence_span'] if ev0 else '（无quote）')
        sheet.append(f"| {f['fact_id']} | {f['subject']} | {f['predicate']} | {str(val)[:18]} | {stage} | {fclass} | "
                     f"{'/'.join(allowed)} | {show}({'+'.join(e['document_id'] for e in entries) or '—'}) |")
    cls = Counter(x['fact_class'] for x in facts)
    totals.update(cls)
    contract = dict(task=task, company=company,
                    code=task.split('_')[-1], schema='G7-V03-spanlevel-v0.1-draft-recycled',
                    origin=f'P2-PILOT {fname}（操作员已裁决事实集，本版仅升级标注）',
                    source_pages={d: dict(pages={'1': docs[d]}, normalized=stripped[d],
                                          raw_sha256=c['source_pages'][d]['raw_sha256'],
                                          source_documents=c['source_documents'][d]) for d in ('D1', 'D2')},
                    required_facts=facts,
                    unknown_items_legacy=c.get('unknown_items'),
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for x in facts if x['fact_stage'] == '拟' and x['fact_class'] != 'doc_metadata'),
                               n_d2_only=sum(1 for x in facts if x['fact_stage'] == '终' and x['fact_class'] != 'doc_metadata')))
    (out / f'TASK_CONTRACT_{task}_v0.1.json').write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}", '']
sheet += [f"**批3回收总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH3.md').write_text('\n'.join(sheet) + '\n')
print('recycled drafts:', sorted(p.name for p in out.glob('*.json')))
print('批3分类:', dict(totals))
for code, fname in SPECS:
    c = json.loads((SRC / fname).read_text())
    print(code, 'unknown_items:', json.dumps(c.get('unknown_items'), ensure_ascii=False)[:150])
