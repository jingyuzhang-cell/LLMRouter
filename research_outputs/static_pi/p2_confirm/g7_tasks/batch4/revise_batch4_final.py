#!/usr/bin/env python3
"""G7 batch-4 REVISION per operator adjudication (granularity only; v0.1 -> v1.0).
KM: dual-capacity splits (Ma/Xu each: total 900k + officer 300k + controller 600k),
    3x250k and 2x100k per-person splits, bans per-person (3 lifetime + 3 ten-year),
    6 per-person final-ban UNKNOWNs; 7-person/6-person groups KEPT as document groups
    (per operator item-4 instruction) with explicit per-person-amount semantics.
LY: per-person splits 3x1m + 2x500k on both stages.
MD: Lin-Yongfei dual-capacity split on both stages (D2 breakdown verified);
    Weng/Liu keep separate slots sharing the merged D2 span with mapping note.
Outputs: contracts/*_v1.0.json + FACT_SHEET_BATCH4_V1.md + SLOT_MAPPING_BATCH4.md."""
import hashlib, json, re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
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


def F(fid, subj, pred, val, kind, stage, allowed, ev, note=None, basis=None, meta=False):
    return dict(fid=fid, subj=subj, pred=pred, val=val, kind=kind, stage=stage,
                allowed=allowed, ev=ev, note=note, basis=basis, meta=meta)

KANGMEI = dict(
    task='KM_600518', company='康美药业股份有限公司', code='600518',
    docs={'D1': 'raw/kangmei_D1_notice.txt', 'D2': '../batch1/raw/kangmei_D2_penalty.txt'},
    map_old_new={'F1': 'F1', 'F2': 'F2,F3,F4', 'F3': 'F5,F6,F7', 'F4': 'F8', 'F5': 'F9,F10,F11',
                 'F6': 'F12(组槽保留,明确每人各20万)', 'F7': 'F13(组槽保留,明确每人各15万)',
                 'F8': 'F14,F15', 'F9': 'F16,F17,F18', 'F10': 'F19,F20,F21',
                 'F13': 'F24', 'F14': 'F25,F26,F27', 'F15': 'F28,F29,F30', 'F16': 'F31',
                 'F17': 'F32,F33,F34', 'F18': 'F35(组槽)', 'F19': 'F36(组槽)', 'F20': 'F37,F38',
                 'F21': 'F39,F40,F41', 'F22': 'F42,F43,F44', 'F25': 'F47'},
    facts=[
      # —— 拟阶段 ——
      F('F1','康美药业','拟处罚款金额','60万元','amount','拟',['D1'],[('D1',r'对康美药业股份有限公司责令改正，给予警告，并处以60万元的罚款')]),
      F('F2','马兴田','拟处罚款合计金额','90万元','amount','拟',['D1'],[('D1',r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
      F('F3','马兴田','拟处罚款金额（直接负责的主管人员）','30万元','amount','拟',['D1'],[('D1',r'作为直接负责的主管人员罚款30万元')],note='双身份拆槽，与合计槽F2同源'),
      F('F4','马兴田','拟处罚款金额（实际控制人）','60万元','amount','拟',['D1'],[('D1',r'作为实际控制人罚款60万元')],note='双身份拆槽'),
      F('F5','许冬瑾','拟处罚款合计金额','90万元','amount','拟',['D1'],[('D1',r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
      F('F6','许冬瑾','拟处罚款金额（直接负责的主管人员）','30万元','amount','拟',['D1'],[('D1',r'作为直接负责的主管人员罚款30万元')],note='双身份拆槽，与合计槽F5同源'),
      F('F7','许冬瑾','拟处罚款金额（实际控制人）','60万元','amount','拟',['D1'],[('D1',r'作为实际控制人罚款60万元')],note='双身份拆槽'),
      F('F8','邱锡伟','拟处罚款金额','30万元','amount','拟',['D1'],[('D1',r'对邱锡伟给予警告，并处以30万元的罚款')]),
      F('F9','庄义清','拟处罚款金额','25万元','amount','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度（原文"分别"）'),
      F('F10','温少生','拟处罚款金额','25万元','amount','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度'),
      F('F11','马焕洲','拟处罚款金额','25万元','amount','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度'),
      F('F12','马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄（7人）','拟单人处罚款金额（每人各20万元）','20万元','amount','拟',['D1'],[('D1',r'对马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄给予警告，并分别处以20万元的罚款')],note='组槽保留（裁决第4条）；值为单人金额，非群体合计'),
      F('F13','张弘、郭崇慧、张平、李建华、韩中伟、王敏（6人）','拟单人处罚款金额（每人各15万元）','15万元','amount','拟',['D1'],[('D1',r'对张弘、郭崇慧、张平、李建华、韩中伟、王敏给予警告，并分别处以15万元的罚款')],note='组槽保留；值为单人金额'),
      F('F14','唐煦','拟处罚款金额','10万元','amount','拟',['D1'],[('D1',r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')],note='共用组跨度'),
      F('F15','陈磊','拟处罚款金额','10万元','amount','拟',['D1'],[('D1',r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')],note='共用组跨度'),
      F('F16','马兴田','拟采取市场禁入措施','终身证券市场禁入','ban','拟',['D1'],[('D1',r'对马兴田、许冬瑾、邱锡伟采取终身证券市场禁入措施')],note='共用组跨度'),
      F('F17','许冬瑾','拟采取市场禁入措施','终身证券市场禁入','ban','拟',['D1'],[('D1',r'对马兴田、许冬瑾、邱锡伟采取终身证券市场禁入措施')],note='共用组跨度'),
      F('F18','邱锡伟','拟采取市场禁入措施','终身证券市场禁入','ban','拟',['D1'],[('D1',r'对马兴田、许冬瑾、邱锡伟采取终身证券市场禁入措施')],note='共用组跨度'),
      F('F19','庄义清','拟采取市场禁入措施','10年证券市场禁入','ban','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲采取10年证券市场禁入措施')],note='共用组跨度'),
      F('F20','温少生','拟采取市场禁入措施','10年证券市场禁入','ban','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲采取10年证券市场禁入措施')],note='共用组跨度'),
      F('F21','马焕洲','拟采取市场禁入措施','10年证券市场禁入','ban','拟',['D1'],[('D1',r'对庄义清、温少生、马焕洲采取10年证券市场禁入措施')],note='共用组跨度'),
      F('F22','中国证监会','事先告知书文号','处罚字〔2019〕119号','docno','拟',['D1'],[('D1',r'处罚字〔2019〕119号')],meta=True),
      F('F23','康美药业','收到事先告知书日期','2019年8月16日','date','拟',['D1'],[('D1',r'2019年8月16日，公司及相关当事人收到证监会')],meta=True),
      # —— 终阶段 ——
      F('F24','康美药业','终局处罚款金额','60万元','amount','终',['D2'],[('D2',r'对康美药业股份有限公司责令改正，给予警告，并处以60万元的罚款')]),
      F('F25','马兴田','终局处罚款合计金额','90万元','amount','终',['D2'],[('D2',r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
      F('F26','马兴田','终局处罚款金额（直接负责的主管人员）','30万元','amount','终',['D2'],[('D2',r'作为直接负责的主管人员罚款30万元')]),
      F('F27','马兴田','终局处罚款金额（实际控制人）','60万元','amount','终',['D2'],[('D2',r'作为实际控制人罚款60万元')]),
      F('F28','许冬瑾','终局处罚款合计金额','90万元','amount','终',['D2'],[('D2',r'对马兴田、许冬瑾给予警告，并分别处以90万元的罚款')]),
      F('F29','许冬瑾','终局处罚款金额（直接负责的主管人员）','30万元','amount','终',['D2'],[('D2',r'作为直接负责的主管人员罚款30万元')]),
      F('F30','许冬瑾','终局处罚款金额（实际控制人）','60万元','amount','终',['D2'],[('D2',r'作为实际控制人罚款60万元')]),
      F('F31','邱锡伟','终局处罚款金额','30万元','amount','终',['D2'],[('D2',r'对邱锡伟给予警告，并处以30万元的罚款')]),
      F('F32','庄义清','终局处罚款金额','25万元','amount','终',['D2'],[('D2',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度'),
      F('F33','温少生','终局处罚款金额','25万元','amount','终',['D2'],[('D2',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度'),
      F('F34','马焕洲','终局处罚款金额','25万元','amount','终',['D2'],[('D2',r'对庄义清、温少生、马焕洲给予警告，并分别处以25万元的罚款')],note='共用组跨度'),
      F('F35','马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄（7人）','终局单人处罚款金额（每人各20万元）','20万元','amount','终',['D2'],[('D2',r'对马汉耀、林大浩、李石、江镇平、李定安、罗家谦、林国雄给予警告，并分别处以20万元的罚款')],note='组槽保留；值为单人金额'),
      F('F36','张弘、郭崇慧、张平、李建华、韩中伟、王敏（6人）','终局单人处罚款金额（每人各15万元）','15万元','amount','终',['D2'],[('D2',r'对张弘、郭崇慧、张平、李建华、韩中伟、王敏给予警告，并分别处以15万元的罚款')],note='组槽保留；值为单人金额'),
      F('F37','唐煦','终局处罚款金额','10万元','amount','终',['D2'],[('D2',r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')],note='共用组跨度'),
      F('F38','陈磊','终局处罚款金额','10万元','amount','终',['D2'],[('D2',r'对唐煦、陈磊给予警告，并分别处以10万元的罚款')],note='共用组跨度'),
      # —— UNKNOWN（逐人） ——
      *[F(f'F{39+i}', n, '终局市场禁入措施', 'UNKNOWN', 'ban', '终', ['D2'], [],
          basis='D2"我会决定"部分仅载罚款事项，未载明该人员市场禁入；未载明≠未采取（禁入另有单独决定书，不属于本任务输入文书，不得作为作答依据）')
        for i, n in enumerate(['马兴田', '许冬瑾', '邱锡伟', '庄义清', '温少生', '马焕洲'])],
      F('F45','中国证监会','处罚决定书文号','[2020]24号','docno','终',['D2'],[('D2',r'\[2020\]24\s*号')],meta=True),
      F('F46','中国证监会','处罚决定书作出日期','2020年5月14日','date','终',['D2'],[('D2',r'2020年5月14日')],meta=True),
      F('F47','康美药业','2016年年报虚增营业收入','100.32亿元','amount','中性',['D1','D2'],
        [('D1',r'虚增营业收入100.32亿元'),('D2',r'虚增营业收入100.32亿元')]),
    ])

LIYUAN = dict(
    task='LY_688565', company='浙江海盐力源环保科技股份有限公司', code='688565',
    docs={'D1': 'raw/liyuan_D1_notice.txt', 'D2': '../batch2/raw/liyuan_D2_csrc.txt'},
    map_old_new={'F1':'F1','F2':'F2','F3':'F3,F4,F5','F4':'F6,F7','F5':'F8','F6':'F9',
                 'F7':'F10','F8':'F11','F9':'F12,F13,F14','F10':'F15,F16','F11':'F17','F12':'F18',
                 'F13':'F19','F14':'F20'},
    facts=[
      F('F1','力源科技','拟处罚款金额','300万元','amount','拟',['D1'],[('D1',r'责令改正，给予警告，并处以300万元罚款')]),
      F('F2','沈万中','拟处罚款金额','300万元','amount','拟',['D1'],[('D1',r'对沈万中给予警告，并处以300万元罚款')]),
      *[F(f'F{3+i}', n, '拟处罚款金额','100万元','amount','拟',['D1'],
          [('D1',r'对裴志国、金史羿、沈学恩给予警告，并分别处以100万元罚款')],note='共用组跨度（原文"分别"）')
        for i, n in enumerate(['裴志国','金史羿','沈学恩'])],
      *[F(f'F{6+i}', n, '拟处罚款金额','50万元','amount','拟',['D1'],
          [('D1',r'对林虹辰、曹洋给予警告，并分别处以50万元罚款')],note='共用组跨度')
        for i, n in enumerate(['林虹辰','曹洋'])],
      F('F8','浙江证监局','事先告知书文号','浙处罚字[2023]8号','docno','拟',['D1'],[('D1',r'浙处罚字\[2023\]8号')],meta=True),
      F('F9','力源科技','收到事先告知书日期','2023年6月9日','date','拟',['D1'],[('D1',r'2023年6月9日收到')],meta=True),
      F('F10','力源科技','终局处罚款金额','300万元','amount','终',['D2'],[('D2',r'责令改正，给予警告，并处以300万元罚款')]),
      F('F11','沈万中','终局处罚款金额','300万元','amount','终',['D2'],[('D2',r'对沈万中给予警告，并处以300万元罚款')]),
      *[F(f'F{12+i}', n, '终局处罚款金额','100万元','amount','终',['D2'],
          [('D2',r'对裴志国、金史羿、沈学恩给予警告，并分别处以100万元罚款')],note='共用组跨度')
        for i, n in enumerate(['裴志国','金史羿','沈学恩'])],
      *[F(f'F{15+i}', n, '终局处罚款金额','50万元','amount','终',['D2'],
          [('D2',r'对林虹辰、曹洋给予警告，并分别处以50万元罚款')],note='共用组跨度')
        for i, n in enumerate(['林虹辰','曹洋'])],
      F('F17','浙江证监局','处罚决定书文号','[2023]20号','docno','终',['D2'],[('D2',r'\[2023\]20号')],meta=True),
      F('F18','浙江证监局','处罚决定书作出日期','2023年6月20日','date','终',['D2'],[('D2',r'2023年6月20日')],meta=True),
      F('F19','力源科技','2021年年报虚增营业收入','103,838,981.52元','amount','中性',['D1','D2'],
        [('D1',r'虚增营业收入103,838,981.52元'),('D2',r'虚增营业收入103,838,981.52元')]),
      F('F20','力源科技','2021年年报虚增利润总额','27,072,877.87元','amount','中性',['D1','D2'],
        [('D1',r'虚增利润总额27,072,877.87元'),('D2',r'虚增利润总额27,072,877.87元')]),
    ])

MODA = dict(
    task='MD_002656', company='摩登大道时尚集团股份有限公司', code='002656',
    docs={'D1': 'raw/moda_D1_notice.txt', 'D2': 'raw/moda_D2_penalty.txt'},
    map_old_new={'F1':'F1','F2':'F2,F3,F4','F3':'F5','F4':'F6','F5':'F7','F6':'F8',
                 'F7':'F9','F8':'F10,F11,F12','F9':'F13','F10':'F14','F11':'F15','F12':'F16',
                 'F13':'F17','F14':'F18'},
    facts=[
      F('F1','摩登大道','拟处罚款金额','40万元','amount','拟',['D1'],[('D1',r'对摩登大道时尚集团股份有限公司给予警告，并处以40万元罚款')]),
      F('F2','林永飞','拟处罚款合计金额','60万元','amount','拟',['D1'],[('D1',r'对林永飞给予警告，并处以60万元罚款')]),
      F('F3','林永飞','拟处罚款金额（直接负责的主管人员）','20万元','amount','拟',['D1'],[('D1',r'作为直接负责的主管人员处以20万元罚款')],note='双身份拆槽'),
      F('F4','林永飞','拟处罚款金额（实际控制人）','40万元','amount','拟',['D1'],[('D1',r'作为实际控制人处以40万元罚款')],note='双身份拆槽'),
      F('F5','翁武强','拟处罚款金额','15万元','amount','拟',['D1'],[('D1',r'对翁武强给予警告，并处以15万元罚款')]),
      F('F6','刘文焱','拟处罚款金额','15万元','amount','拟',['D1'],[('D1',r'对刘文焱给予警告，并处以15万元罚款')]),
      F('F7','广东证监局','事先告知书文号','广东证监处罚字〔2021〕21号','docno','拟',['D1'],[('D1',r'广东证监处罚字〔2021〕21号')],meta=True),
      F('F8','摩登大道','收到事先告知书日期','2021年12月3日','date','拟',['D1'],[('D1',r'2021年12月3日')],meta=True),
      F('F9','摩登大道','终局处罚款金额','40万元','amount','终',['D2'],[('D2',r'对摩登大道时尚集团股份有限公司给予警告，并处以40万元罚款')]),
      F('F10','林永飞','终局处罚款合计金额','60万元','amount','终',['D2'],[('D2',r'对林永飞给予警告，并处以60万元罚款')]),
      F('F11','林永飞','终局处罚款金额（直接负责的主管人员）','20万元','amount','终',['D2'],[('D2',r'作为直接负责的主管人员处以20万元罚款')],note='D2明确分身份记载，拆槽'),
      F('F12','林永飞','终局处罚款金额（实际控制人）','40万元','amount','终',['D2'],[('D2',r'作为实际控制人处以40万元罚款')],note='D2明确分身份记载，拆槽'),
      F('F13','翁武强','终局处罚款金额','15万元','amount','终',['D2'],[('D2',r'对翁武强、刘文焱给予警告，并处以15万元罚款')],note='映射说明：D1单独条目、D2合并"分别"条目，共用D2跨度（分组变化型）'),
      F('F14','刘文焱','终局处罚款金额','15万元','amount','终',['D2'],[('D2',r'对翁武强、刘文焱给予警告，并处以15万元罚款')],note='同F13，共用D2合并条目跨度'),
      F('F15','广东证监局','处罚决定书文号','〔2022〕1号','docno','终',['D2'],[('D2',r'〔2022〕1号')],meta=True),
      F('F16','摩登大道','收到处罚决定书日期','2022年1月17日','date','终',['D2'],[('D2',r'2022年1月17日')],meta=True),
      F('F17','摩登大道','2018年度对外担保累计金额','21,928.50万元','amount','中性',['D1','D2'],
        [('D1',r'对外担保金额累计21,928.50万元'),('D2',r'对外担保金额累计21,928.50万元')]),
      F('F18','摩登大道','2019年度对外担保累计金额','31,928.50万元','amount','中性',['D1','D2'],
        [('D1',r'对外担保金额累计31,928.50万元'),('D2',r'对外担保金额累计31,928.50万元')]),
    ])

out_dir = HERE / 'contracts'
sheet = ['# G7 批4 Gold 合同 v1.0（粒度修订后定稿：双身份拆槽/多人拆槽/组槽保留/禁入与UNKNOWN逐人）', '']
mapping_md = ['# 批4 新旧事实槽映射（v0.1 -> v1.0）', '']
totals = Counter()
for spec in (KANGMEI, LIYUAN, MODA):
    docs = {}
    for d, f in spec['docs'].items():
        t = strip_pageno((HERE / f).read_text(errors='ignore'))
        st, idx = strip_with_map(t)
        docs[d] = dict(raw=t, stripped=st, idx=idx)
    doc_sha = {d: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for d, f in spec['docs'].items()}
    facts, n_span_ok = [], 0
    sheet += [f"## {spec['task']} {spec['company']}（{spec['code']}）", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 |', '|---|---|---|---|---|---|---|']
    for r in spec['facts']:
        entries = []
        for d, pat in r['ev']:
            sp = span_of(docs[d], pat)
            n_span_ok += 1
            entries.append(dict(document_id=d, evidence_stage=r['stage'], support_status='supports', **sp))
        val = r['val']
        fclass = ('doc_metadata' if r['meta'] else 'unknown_boundary' if val == 'UNKNOWN'
                  else 'stage_content' if r['stage'] != '中性' else 'background')
        facts.append(dict(fact_id=r['fid'], subject=r['subj'], predicate=r['pred'], value=val,
                          kind=r['kind'], critical=fclass == 'stage_content', fact_stage=r['stage'],
                          fact_class=fclass, allowed_citation_docs=r['allowed'],
                          stage_evidence=entries, note=r['note'],
                          unknown_basis=(r['basis'] if val == 'UNKNOWN' else None)))
        sheet.append(f"| {r['fid']} | {r['subj']} | {r['pred']} | {val} | {r['stage']} | {fclass} | {'/'.join(r['allowed'])} |")
    cls = Counter(f['fact_class'] for f in facts)
    totals.update(cls)
    contract = dict(task=spec['task'], company=spec['company'], code=spec['code'],
                    schema='G7-V03-spanlevel-v1.0',
                    adjudicated='2026-11-10 操作员批4粒度裁决（双身份/多人拆槽，组槽保留，UNKNOWN逐人）',
                    slot_mapping_v01_to_v10=spec['map_old_new'],
                    source_pages={d: dict(pages={'1': docs[d]['raw']}, normalized=docs[d]['stripped'],
                                          raw_sha256=doc_sha[d], file=spec['docs'][d]) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['fact_stage'] == '拟' and f['fact_class'] == 'stage_content'),
                               n_d2_only=sum(1 for f in facts if f['fact_stage'] == '终' and f['fact_class'] != 'doc_metadata'),
                               spans_verified=n_span_ok))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v1.0.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}｜跨度校验 {n_span_ok} 条全部通过", '']
    mapping_md += [f"## {spec['task']}", '']
    for old, new in spec['map_old_new'].items():
        mapping_md.append(f"- {old} -> {new}")
    mapping_md.append('')
sheet += [f"**批4修订后总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH4_V1.md').write_text('\n'.join(sheet) + '\n')
(HERE / 'SLOT_MAPPING_BATCH4.md').write_text('\n'.join(mapping_md) + '\n')
print('v1.0 written:', sorted(p.name for p in out_dir.glob('*_v1.0.json')))
print('批4修订后分类:', dict(totals))
