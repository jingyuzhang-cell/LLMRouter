#!/usr/bin/env python3
"""G7 batch-4 Gold contract DRAFTS (Kangmei/Liyuan/Moda, v0.1 awaiting adjudication), zero model calls.
Same pipeline as adjudicated batch-1 v1.0: span-level annotation, fact_class taxonomy,
UNKNOWN bases, triple traceability (raw page text + raw span + normalized span)."""
import hashlib, json, re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent  # batch4/
strip_pageno = lambda s: re.sub(r'\n\s*\d{1,3}\s*\n', '\n', s)


def strip_with_map(raw):
    out, idx = [], []
    for i, ch in enumerate(raw):
        if not ch.isspace():
            out.append(ch)
            idx.append(i)
    return ''.join(out), idx


def span_of(doc, pattern):
    pat = re.sub(r'\s+', '', pattern)
    m = re.search(pat, doc['stripped'])
    assert m, f'span not found: {pattern[:60]}'
    i, j = m.span()
    return dict(evidence_span=doc['stripped'][i:j],
                raw_evidence_span=doc['raw'][doc['idx'][i]:doc['idx'][j - 1] + 1])



KANGMEI = dict(
    task='KM_600518', company='康美药业股份有限公司', code='600518',
    docs={'D1': 'raw/kangmei_D1_notice.txt', 'D2': '../batch1/raw/kangmei_D2_penalty.txt'},
    meta_facts={'F11','F12','F23','F24'},
    unknown_basis={'F21': 'D2"我会决定"部分仅载罚款事项，未载明市场禁入措施；未载明≠未采取（禁入另见单独市场禁入决定书，不属于本任务输入文书）',
                   'F22': 'D2"我会决定"部分仅载罚款事项，未载明市场禁入措施；未载明≠未采取（同上）'},
    facts=[
     ('F1','康美药业','拟处罚款金额','60万元','amount','拟',['D1'],[('D1', r'对康美药业股份有限公司责令改正，给予警告，并处以60万元的罚款')]),
     ('F2','马兴田','拟处罚款金额','90万元','amount','拟',['D1'],[('D1', r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
     ('F3','许冬瑾','拟处罚款金额','90万元','amount','拟',['D1'],[('D1', r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
     ('F4','邱锡伟','拟处罚款金额','30万元','amount','拟',['D1'],[('D1', r'对邱锡伟给予警告，并处以30万元的罚款')]),
     ('F5','庄义清、温少生、马焕洲（3人）','拟单人处罚款金额','25万元','amount','拟',['D1'],[('D1', r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')]),
     ('F6','马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄（7人）','拟单人处罚款金额','20万元','amount','拟',['D1'],[('D1', r'对马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄给予警告，并分别处以20万元的罚款')]),
     ('F7','张弘、郭崇慧、张平、李建华、韩中伟、王敏（6人）','拟单人处罚款金额','15万元','amount','拟',['D1'],[('D1', r'对张弘、郭崇慧、张平、李建华、韩中伟、王敏给予警告，并分别处以15万元的罚款')]),
     ('F8','唐煦、陈磊（2人）','拟单人处罚款金额','10万元','amount','拟',['D1'],[('D1', r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')]),
     ('F9','马兴田、许冬瑾、邱锡伟（3人）','拟采取市场禁入措施','终身证券市场禁入','ban','拟',['D1'],[('D1', r'对马兴田、许冬瑾、邱锡伟采取终身证券市场禁入措施')]),
     ('F10','庄义清、温少生、马焕洲（3人）','拟采取市场禁入措施','10年证券市场禁入','ban','拟',['D1'],[('D1', r'对庄义清、温少生、马焕洲采取10年证券市场禁入措施')]),
     ('F11','中国证监会','事先告知书文号','处罚字〔2019〕119号','docno','拟',['D1'],[('D1', r'处罚字〔2019〕119号')]),
     ('F12','康美药业','收到事先告知书日期','2019年8月16日','date','拟',['D1'],[('D1', r'2019年8月16日，公司及相关当事人收到证监会《行政处罚及市场禁入事先告知书》')]),
     ('F13','康美药业','终局处罚款金额','60万元','amount','终',['D2'],[('D2', r'对康美药业股份有限公司责令改正，给予警告，并处以60万元的罚款')]),
     ('F14','马兴田','终局处罚款金额','90万元','amount','终',['D2'],[('D2', r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
     ('F15','许冬瑾','终局处罚款金额','90万元','amount','终',['D2'],[('D2', r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
     ('F16','邱锡伟','终局处罚款金额','30万元','amount','终',['D2'],[('D2', r'对邱锡伟给予警告，并处以30万元的罚款')]),
     ('F17','庄义清、温少生、马焕洲（3人）','终局单人处罚款金额','25万元','amount','终',['D2'],[('D2', r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')]),
     ('F18','马汉耀等7人','终局单人处罚款金额','20万元','amount','终',['D2'],[('D2', r'对马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄给予警告，并分别处以20万元的罚款')]),
     ('F19','张弘等6人','终局单人处罚款金额','15万元','amount','终',['D2'],[('D2', r'对张弘、郭崇慧、张平、李建华、韩中伟、王敏给予警告，并分别处以15万元的罚款')]),
     ('F20','唐煦、陈磊（2人）','终局单人处罚款金额','10万元','amount','终',['D2'],[('D2', r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')]),
     ('F21','马兴田、许冬瑾、邱锡伟（3人）','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[]),
     ('F22','庄义清、温少生、马焕洲（3人）','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[]),
     ('F23','中国证监会','处罚决定书文号','[2020]24号','docno','终',['D2'],[('D2', r'\[2020\]24\s*号')]),
     ('F24','中国证监会','处罚决定书作出日期','2020年5月14日','date','终',['D2'],[('D2', r'2020年5月14日')]),
     ('F25','康美药业','2016年年报虚增营业收入','100.32亿元','amount','中性',['D1','D2'],[('D1', r'虚增营业收入100.32亿元'),('D2', r'虚增营业收入100.32亿元')]),
    ])

LIYUAN = dict(
    task='LY_688565', company='浙江海盐力源环保科技股份有限公司', code='688565',
    docs={'D1': 'raw/liyuan_D1_notice.txt', 'D2': '../batch2/raw/liyuan_D2_csrc.txt'},
    meta_facts={'F5','F6','F11','F12'},
    facts=[
     ('F1','力源科技','拟处罚款金额','300万元','amount','拟',['D1'],[('D1', r'责令改正，给予警告，并处以300万元罚款')]),
     ('F2','沈万中','拟处罚款金额','300万元','amount','拟',['D1'],[('D1', r'对沈万中给予警告，并处以300万元罚款')]),
     ('F3','裴志国、金史羿、沈学恩（3人）','拟单人处罚款金额','100万元','amount','拟',['D1'],[('D1', r'对裴志国、金史羿、沈学恩给予警告，并分别处以100万元罚款')]),
     ('F4','林虹辰、曹洋（2人）','拟单人处罚款金额','50万元','amount','拟',['D1'],[('D1', r'对林虹辰、曹洋给予警告，并分别处以50万元罚款')]),
     ('F5','浙江证监局','事先告知书文号','浙处罚字[2023]8号','docno','拟',['D1'],[('D1', r'浙处罚字\[2023\]8号')]),
     ('F6','力源科技','收到事先告知书日期','2023年6月9日','date','拟',['D1'],[('D1', r'2023年6月9日收到')]),
     ('F7','力源科技','终局处罚款金额','300万元','amount','终',['D2'],[('D2', r'责令改正，给予警告，并处以300万元罚款')]),
     ('F8','沈万中','终局处罚款金额','300万元','amount','终',['D2'],[('D2', r'对沈万中给予警告，并处以300万元罚款')]),
     ('F9','裴志国、金史羿、沈学恩（3人）','终局单人处罚款金额','100万元','amount','终',['D2'],[('D2', r'对裴志国、金史羿、沈学恩给予警告，并分别处以100万元罚款')]),
     ('F10','林虹辰、曹洋（2人）','终局单人处罚款金额','50万元','amount','终',['D2'],[('D2', r'对林虹辰、曹洋给予警告，并分别处以50万元罚款')]),
     ('F11','浙江证监局','处罚决定书文号','[2023]20号','docno','终',['D2'],[('D2', r'\[2023\]20号')]),
     ('F12','浙江证监局','处罚决定书作出日期','2023年6月20日','date','终',['D2'],[('D2', r'2023年6月20日')]),
     ('F13','力源科技','2021年年报虚增营业收入','103,838,981.52元','amount','中性',['D1','D2'],[('D1', r'虚增营业收入103,838,981.52元'),('D2', r'虚增营业收入103,838,981.52元')]),
     ('F14','力源科技','2021年年报虚增利润总额','27,072,877.87元','amount','中性',['D1','D2'],[('D1', r'虚增利润总额27,072,877.87元'),('D2', r'虚增利润总额27,072,877.87元')]),
    ])
MODA = dict(
    task='MD_002656', company='摩登大道时尚集团股份有限公司', code='002656',
    docs={'D1': 'raw/moda_D1_notice.txt', 'D2': 'raw/moda_D2_penalty.txt'},
    meta_facts={'F5','F6','F11','F12'},
    facts=[
     ('F1','摩登大道','拟处罚款金额','40万元','amount','拟',['D1'],[('D1', r'对摩登大道时尚集团股份有限公司给予警告，并处以40万元罚款')]),
     ('F2','林永飞','拟处罚款金额','60万元','amount','拟',['D1'],[('D1', r'对林永飞给予警告，并处以60万元罚款')]),
     ('F3','翁武强','拟处罚款金额','15万元','amount','拟',['D1'],[('D1', r'对翁武强给予警告，并处以15万元罚款')]),
     ('F4','刘文焱','拟处罚款金额','15万元','amount','拟',['D1'],[('D1', r'对刘文焱给予警告，并处以15万元罚款')]),
     ('F5','广东证监局','事先告知书文号','广东证监处罚字〔2021〕21号','docno','拟',['D1'],[('D1', r'广东证监处罚字〔2021〕21号')]),
     ('F6','摩登大道','收到事先告知书日期','2021年12月3日','date','拟',['D1'],[('D1', r'2021年12月3日')]),
     ('F7','摩登大道','终局处罚款金额','40万元','amount','终',['D2'],[('D2', r'对摩登大道时尚集团股份有限公司给予警告，并处以40万元罚款')]),
     ('F8','林永飞','终局处罚款金额','60万元','amount','终',['D2'],[('D2', r'对林永飞给予警告，并处以60万元罚款')]),
     ('F9','翁武强','终局处罚款金额','15万元','amount','终',['D2'],[('D2', r'对翁武强、刘文焱给予警告，并处以15万元罚款')]),
     ('F10','刘文焱','终局处罚款金额','15万元','amount','终',['D2'],[('D2', r'对翁武强、刘文焱给予警告，并处以15万元罚款')]),
     ('F11','广东证监局','处罚决定书文号','〔2022〕1号','docno','终',['D2'],[('D2', r'〔2022〕1号')]),
     ('F12','摩登大道','收到处罚决定书日期','2022年1月17日','date','终',['D2'],[('D2', r'2022年1月17日')]),
     ('F13','摩登大道','2018年度对外担保累计金额','21,928.50万元','amount','中性',['D1','D2'],[('D1', r'对外担保金额累计21,928.50万元'),('D2', r'对外担保金额累计21,928.50万元')]),
     ('F14','摩登大道','2019年度对外担保累计金额','31,928.50万元','amount','中性',['D1','D2'],[('D1', r'对外担保金额累计31,928.50万元'),('D2', r'对外担保金额累计31,928.50万元')]),
    ])

out_dir = HERE / 'contracts'; out_dir.mkdir(exist_ok=True)
sheet = ['# G7 批2 Gold 合同 v1.0（操作员裁决后定稿：0 DROP；舜天F16限定输入文书范围并附〔2024〕10号审计备注）', '',
         '管线与批1 v1.0 一致（跨度级标注/分类/UNKNOWN依据/三套可追溯）。', '']
totals = Counter()
for spec in (KANGMEI, LIYUAN, MODA):
    docs = {}
    for d, f in spec['docs'].items():
        t = strip_pageno((HERE / f).read_text(errors='ignore'))
        st, idx = strip_with_map(t)
        docs[d] = dict(raw=t, stripped=st, idx=idx)
    doc_sha = {d: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for d, f in spec['docs'].items()}
    META, UNK = spec.get('meta_facts', set()), spec.get('unknown_basis', {})
    facts = []
    sheet += [f"## {spec['task']} {spec['company']}（{spec['code']}）", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 | 证据跨度（截选） |',
              '|---|---|---|---|---|---|---|---|']
    for fid, subj, pred, val, kind, stage, allowed, ev in spec['facts']:
        entries = [dict(document_id=d, evidence_stage=stage, support_status='supports',
                        **span_of(docs[d], pat)) for d, pat in ev]
        fclass = ('doc_metadata' if fid in META else 'unknown_boundary' if val == 'UNKNOWN'
                  else 'stage_content' if stage != '中性' else 'background')
        facts.append(dict(fact_id=fid, subject=subj, predicate=pred, value=val, kind=kind,
                          critical=fclass == 'stage_content', fact_stage=stage, fact_class=fclass,
                          allowed_citation_docs=allowed, stage_evidence=entries,
                          unknown_basis=(UNK.get(fid, '终局未载明，不得倒推；不以未提及推定处罚不存在或拟罚已执行')
                                         if val == 'UNKNOWN' else None)))
        ev0 = entries[0] if entries else None
        show = ((ev0['evidence_span'][:24] + '…') if ev0 and len(ev0['evidence_span']) > 24
                else ev0['evidence_span'] if ev0 else '（未载明）')
        srclist = '+'.join(e['document_id'] for e in entries) if entries else '—'
        sheet.append(f"| {fid} | {subj} | {pred} | {val} | {stage} | {fclass} | {'/'.join(allowed)} | {show}({srclist}) |")
    cls = Counter(f['fact_class'] for f in facts)
    totals.update(cls)
    contract = dict(task=spec['task'], company=spec['company'], code=spec['code'],
                    schema='G7-V03-spanlevel-v0.1-draft',
                    source_pages={d: dict(pages={'1': docs[d]['raw']}, normalized=docs[d]['stripped'],
                                          raw_sha256=doc_sha[d], file=spec['docs'][d]) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['fact_stage'] == '拟' and f['fact_class'] != 'doc_metadata'),
                               n_d2_only=sum(1 for f in facts if f['fact_stage'] == '终' and f['fact_class'] != 'doc_metadata')))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v0.1.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}", '']
sheet += [f"**批2总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH2_V1.md').write_text('\n'.join(sheet) + '\n')
print('batch-4 drafts written:', sorted(p.name for p in out_dir.glob('*.json')))
print('批4分类总计:', dict(totals))
