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

# 拟阶段补充事实（操作员批3裁决：选项二；四规则——优先罚款金额/拟终独立计分/逐人依据"分别"/保留UNKNOWN）
def _swm(raw):
    out, idx = [], []
    for i, ch in enumerate(raw):
        if not ch.isspace():
            out.append(ch); idx.append(i)
    return ''.join(out), idx

ADDITIONS = {
 'CY': [
  ('F24','长园集团','拟处罚款金额','50','amount','拟',[('D1', r'对长园集团给予警告,并处以50万元的罚款')]),
  ('F25','尹智勇','拟处罚款金额','30','amount','拟',[('D1', r'对尹智勇给予警告,并处以30万元罚款')]),
  ('F26','史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华（6人）','拟单人行政处罚罚款金额','20','amount','拟',[('D1', r'对史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华给予警告,并分别处以20万元罚款')]),
  ('F27','徐成斌','拟处罚款金额','10','amount','拟',[('D1', r'对徐成斌给予警告,并处以10万元罚款')]),
  ('F28','隋淑静、姚太平、贺勇（3人）','拟单人行政处罚罚款金额','3','amount','拟',[('D1', r'对隋淑静、姚太平、贺勇给予警告，并分别处以3万元罚款')]),
  ('F29','尹智勇','拟采取市场禁入措施','10年','ban','拟',[('D1', r'对尹智勇采取10年证券市场禁入措施')]),
  ('F30','史忻、刘瑞（2人）','拟单人市场禁入年限','5年','ban','拟',[('D1', r'对史忻、刘瑞分别采取5年证券市场禁入措施')]),
 ],
 'SL': [
  ('F24','深圳市索菱实业股份有限公司','拟处罚款金额','60','amount','拟',[('D1', r'责令索菱股份改正,给予警告,并处以60万元的罚款')]),
  ('F25','肖行亦','拟处罚款金额','90','amount','拟',[('D1', r'对肖行亦给予警告,并处以90万元的罚款')]),
  ('F26','叶玉娟、钟贵荣、王大威（3人）','拟单人行政处罚罚款金额','30','amount','拟',[('D1', r'对叶玉娟、钟贵荣、王大威给予警告，并分别处以30万元的罚款')]),
  ('F27','郭小宝','拟单人行政处罚罚款金额','20','amount','拟',[('D1', r'对郭小宝、黄子龙、童方义给予警告，并分别处以20万元的罚款')]),
  ('F31','黄子龙','拟单人行政处罚罚款金额','20','amount','拟',[('D1', r'对郭小宝、黄子龙、童方义给予警告，并分别处以20万元的罚款')]),
  ('F32','童方义','拟单人行政处罚罚款金额','20','amount','拟',[('D1', r'对郭小宝、黄子龙、童方义给予警告，并分别处以20万元的罚款')]),
  ('F28','吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎（6人）','拟单人行政处罚罚款金额','15','amount','拟',[('D1', r'对吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎给予警告，并分别处以15万元的罚款')]),
  ('F29','邓先海、蔡春喜、谌勇超（3人）','拟单人行政处罚罚款金额','8','amount','拟',[('D1', r'对邓先海、蔡春喜、谌勇超给予警告,并分别处以8万元的罚款')]),
  ('F30','肖行亦','拟采取市场禁入措施','终身','ban','拟',[('D1', r'对肖行亦采取终身市场禁入措施')]),
 ],
 'ZQ': [
  ('F24','中潜股份有限公司','拟处罚款金额','350','amount','拟',[('D1', r'对中潜股份责令改正，给予警告,并处以350万元罚款')]),
  ('F25','张顺、仰智慧（2人）','拟单人行政处罚罚款金额','200','amount','拟',[('D1', r'对张顺、仰智慧给予警告，并分别处以200万元罚款')]),
  ('F26','郭建兵、明小燕（2人）','拟单人行政处罚罚款金额','150','amount','拟',[('D1', r'对郭建兵、明小燕给予警告，并分别处以150万元罚款')]),
  ('F27','卓泽鹏','拟单人行政处罚罚款金额','70','amount','拟',[('D1', r'对卓泽鹏、张继红给予警告，并分别处以70万元罚款')]),
  ('F31','张继红','拟单人行政处罚罚款金额','70','amount','拟',[('D1', r'对卓泽鹏、张继红给予警告，并分别处以70万元罚款')]),
  ('F32','卓泽鹏','终局处罚款金额','UNKNOWN','amount','终',[]),
  ('F28','徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧（7人）','拟单人行政处罚罚款金额','50','amount','拟',[('D1', r'对徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以50万元罚款')]),
 ],
}

DROP_FIDS = {'CY': ['F20'], 'SL': ['F19', 'F20', 'F21', 'F22'], 'ZQ': ['F22', 'F23']}  # 操作员批3终裁：与新增成对槽重复

out = HERE / 'contracts'
sheet = ['# G7 批3 Gold 合同 v1.0（操作员终裁后定稿：删重复7条、逐人拆分、卓泽鹏终局UNKNOWN）', '',
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
    docs_idx = {d: _swm(docs[d]) for d in ('D1', 'D2')}
    new_rows = []
    for fid, subj, pred, val, kind, stage, ev in ADDITIONS.get(code, []):
        entries = []
        for d, pat in ev:
            m = re.search(re.sub(r'\s+', '', pat), docs_idx[d][0])
            assert m, f'{task} 新增{fid} span未找到'
            i, j = m.span()
            entries.append(dict(document_id=d, evidence_span=docs_idx[d][0][i:j],
                                raw_evidence_span=docs[d][docs_idx[d][1][i]:docs_idx[d][1][j-1]+1],
                                evidence_stage=stage, support_status='supports'))
        new_rows.append(dict(fact_id=fid, subject=subj, predicate=pred, value=val, kind=kind,
                             critical=True, fact_stage=stage, fact_class='stage_content',
                             allowed_citation_docs=[d for d, _ in ev], stage_evidence=entries,
                             unknown_basis=None, origin='批3拟阶段补充（操作员选项二裁决）'))
    dropped = DROP_FIDS.get(code, [])
    kept_old = [f for f in c['required_facts'] if f['fact_id'] not in dropped]
    if dropped:
        print(f'{task} DROP(重复): {dropped}')
    for f in kept_old + new_rows:
        if f.get('origin'):
            allowed = f['allowed_citation_docs']
        else:
            allowed = f.get('allowed_citation_docs') or []
        if f.get('origin') and f['value'] == 'UNKNOWN':
            f['fact_class'] = 'unknown_boundary'; f['critical'] = False
            f['unknown_basis'] = 'D2当事人名单及处罚决定均未载明卓泽鹏；未载明≠确认未处罚，不得倒推拟罚已执行或撤销'
            facts.append(f)
            sheet.append(f"| {f['fact_id']} | {f['subject']} | {f['predicate']} | UNKNOWN | {f['fact_stage']} | {f['fact_class']} | D2 | （未载明）(—) |")
            continue
        if f.get('origin'):
            if f['subject'] == '黄子龙':
                f['note'] = "终局文书作'黃子龙'（异体字，同一人）"
            facts.append(f)
            ev0 = f['stage_evidence'][0]
            show = (ev0['evidence_span'][:22] + '…') if len(ev0['evidence_span']) > 22 else ev0['evidence_span']
            sheet.append(f"| {f['fact_id']} | {f['subject']} | {f['predicate']} | {f['value']} | {f['fact_stage']} | {f['fact_class']} | "
                         f"{'/'.join(f['allowed_citation_docs'])} | {show}({'+'.join(e['document_id'] for e in f['stage_evidence'])}) |")
            continue
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
                    code=task.split('_')[-1], schema='G7-V03-spanlevel-v1.0', adjudicated='2026-11-10 操作员批3终裁（选项二+重复项删除+逐人拆分+卓泽鹏终局UNKNOWN）',
                    origin=f'P2-PILOT {fname}（操作员已裁决事实集，本版仅升级标注）',
                    source_pages={d: dict(pages={'1': docs[d]}, normalized=stripped[d],
                                          raw_sha256=c['source_pages'][d]['raw_sha256'],
                                          source_documents=c['source_documents'][d]) for d in ('D1', 'D2')},
                    required_facts=facts,
                    unknown_items_legacy=c.get('unknown_items'),
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for x in facts if x['fact_stage'] == '拟' and x['fact_class'] != 'doc_metadata'),
                               n_d2_only=sum(1 for x in facts if x['fact_stage'] == '终' and x['fact_class'] != 'doc_metadata')))
    (out / f'TASK_CONTRACT_{task}_v1.0.json').write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}", '']
sheet += [f"**批3回收总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH3_V1.md').write_text('\n'.join(sheet) + '\n')
print('recycled drafts:', sorted(p.name for p in out.glob('*.json')))
print('批3分类:', dict(totals))
for code, fname in SPECS:
    c = json.loads((SRC / fname).read_text())
    print(code, 'unknown_items:', json.dumps(c.get('unknown_items'), ensure_ascii=False)[:150])
