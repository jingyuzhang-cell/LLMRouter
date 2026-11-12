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

JIANGTE = dict(
    task='JT_002176', company='江西特种电机股份有限公司', code='002176',
    text_corrections={'D1': [('给子', '给予', 'PDF文本层伪影；2026-11-10页面渲染逐字核验原件印刷为"给予"')],
                      'D2': [('给子', '给予', '同上，D2第3页闵银章条目核验为"给予"')]},
    docs={'D1': 'raw/jiangte_D1_notice.txt', 'D2': 'raw/jiangte_D2_penalty.txt'},
    facts=[
      F('F1','江特电机','拟处罚款金额','六十万元','amount','拟',['D1'],[('D1',r'对江西特种电机股份有限公司责令改正，给予警告，并处以六十万元的罚款')],note='原文用汉字数字'),
      F('F2','朱军','拟处罚款金额','三十万元','amount','拟',['D1'],[('D1',r'对朱军、罗清华给予警告，并分别处以三十万元的罚款')],note='文本层误作给子，原件印刷给予（2026-11-10渲染核验）；规范化按原件，原始文本层保留'),
      F('F3','罗清华','拟处罚款金额','三十万元','amount','拟',['D1'],[('D1',r'对朱军、罗清华给予警告，并分别处以三十万元的罚款')],note='共用组跨度；规范化按原件给予'),
      F('F4','龙良萍','拟处罚款金额','二十万元','amount','拟',['D1'],[('D1',r'对龙良萍给予警告，并处以二十万元的罚款')]),
      F('F5','闵银章','拟处罚款金额','十万元','amount','拟',['D1'],[('D1',r'对闵银章给予警告，并处以十万元的罚款')]),
      F('F6','辛毅敏','拟处罚款金额','八万元','amount','拟',['D1'],[('D1',r'对辛毅敏、柳光明给予警告，并分别处以八万元的罚款')],note='共用组跨度'),
      F('F7','柳光明','拟处罚款金额','八万元','amount','拟',['D1'],[('D1',r'对辛毅敏、柳光明给予警告，并分别处以八万元的罚款')],note='共用组跨度'),
      F('F8','江西证监局','事先告知书文号','赣处罚字（2022）2号','docno','拟',['D1'],[('D1',r'赣处罚字（2022）2号')],meta=True,note='原文嵌套全角括号'),
      F('F9','江特电机','收到事先告知书日期','2022年9月14日','date','拟',['D1'],[('D1',r'2022年9月14日，公司收到')],meta=True),
      F('F10','江特电机','终局处罚款金额','60万元','amount','终',['D2'],[('D2',r'对江西特种电机股份有限公司责令改正，给予警告，并处以 60 万元的罚款')],note='原文阿拉伯数字（与D1汉字数字同值——书写格式阶段差异，不作值变化解读）'),
      F('F11','朱军','终局处罚款金额','30万元','amount','终',['D2'],[('D2',r'对朱军、罗清华给予警告，并分别处以 30 万元的罚款')],note='共用组跨度'),
      F('F12','罗清华','终局处罚款金额','30万元','amount','终',['D2'],[('D2',r'对朱军、罗清华给予警告，并分别处以 30 万元的罚款')],note='共用组跨度'),
      F('F13','龙良萍','终局处罚款金额','20万元','amount','终',['D2'],[('D2',r'对龙良萍给予警告，并处以 20 万元的罚款')]),
      F('F14','闵银章','终局处罚款金额','10万元','amount','终',['D2'],[('D2',r'对闵银章给予警告，并处以 10 万元的罚款')],note='文本层误作给子，原件印刷给予（2026-11-10渲染核验）'),
      F('F15','辛毅敏','终局处罚款金额','8万元','amount','终',['D2'],[('D2',r'对辛毅敏、柳光明给予警告，并分别处以 8 万元的罚款')],note='共用组跨度'),
      F('F16','柳光明','终局处罚款金额','8万元','amount','终',['D2'],[('D2',r'对辛毅敏、柳光明给予警告，并分别处以 8 万元的罚款')],note='共用组跨度'),
      F('F17','江西证监局','处罚决定书文号','【2022】4号','docno','终',['D2'],[('D2',r'【2022】4 号')],meta=True,note='原文全角方头括号'),
      F('F18','江特电机','收到处罚决定书日期','2022年10月13日','date','终',['D2'],[('D2',r'2022 年 10 月 13 日，公司收到')],meta=True),
      F('F19','江特电机','2018年年报虚增营业收入','67,403,160.76元','amount','中性',['D1','D2'],
        [('D1',r'虚增营业收入 67,403,160.76 元'),('D2',r'虚增营业收入 67,403,160.76')]),
    ])

JINLITAI = dict(
    task='JLT_300225', company='上海金力泰化工股份有限公司', code='300225',
    docs={'D1': 'raw/jinlitai_D1_notice.txt', 'D2': 'raw/jinlitai_D2_sina.txt'},
    facts=[
      F('F1','金力泰','拟处罚款金额','200万元','amount','拟',['D1'],[('D1',r'对金力泰给予警告，并处以200万元罚款')]),
      F('F2','罗甸','拟处罚款金额','100万元','amount','拟',['D1'],[('D1',r'对罗甸给予警告，并处以100万元罚款')]),
      F('F3','吴纯超','拟处罚款金额','80万元','amount','拟',['D1'],[('D1',r'对吴纯超给予警告，并处以80万元罚款')]),
      F('F4','隋静媛','拟处罚款金额','80万元','amount','拟',['D1'],[('D1',r'对隋静媛给予警告，并处以80万元罚款')]),
      F('F5','上海证监局','事先告知书文号','沪证监处罚字〔2025〕25号','docno','拟',['D1'],[('D1',r'沪证监处罚字〔2025〕25号')],meta=True),
      F('F6','金力泰','收到事先告知书日期','2025年9月15日','date','拟',['D1'],[('D1',r'2025年9月15日，公司收到')],meta=True),
      F('F7','金力泰','终局处罚款金额','200万元','amount','终',['D2'],[('D2',r'对金力泰给予警告，并处以200万元罚款')],note='与拟同值——纯同值陷阱'),
      F('F8','罗甸','终局处罚款金额','100万元','amount','终',['D2'],[('D2',r'对罗甸给予警告，并处以100万元罚款')]),
      F('F9','吴纯超','终局处罚款金额','80万元','amount','终',['D2'],[('D2',r'对吴纯超给予警告，并处以80万元罚款')]),
      F('F10','隋静媛','终局处罚款金额','80万元','amount','终',['D2'],[('D2',r'对隋静媛给予警告，并处以80万元罚款')]),
      F('F11','上海证监局','处罚决定书文号','沪〔2025〕23号','docno','终',['D2'],[('D2',r'沪〔2025〕23号')],meta=True),
      F('F12','金力泰','收到处罚决定书日期','2025年11月7日','date','终',['D2'],[('D2',r'2025年11月7日，公司收到')],meta=True),
      F('F13','金力泰','涉违规事项类型','未按期披露2024年年度报告','text','中性',['D1','D2'],
        [('D1',r'未在法定期限内披露2024年年度报告'),('D2',r'未在法定期限内披露2024年年度报告')]),
    ])

ZANGGE = dict(
    task='ZG_000408', company='藏格控股股份有限公司', code='000408',
    docs={'D1': 'raw/zangge_D1_notice.txt', 'D2': 'raw/zangge_D2_csrc.txt'},
    facts=[
      F('F1','藏格控股','拟处罚款金额','60万元','amount','拟',['D1'],[('D1',r'对藏格控股责令改正，给予警告，并处以60万元的罚款')]),
      F('F2','肖永明','拟处罚款合计金额','90万元','amount','拟',['D1'],[('D1',r'对肖永明给予警告，并处以90万元的罚款')],note='D1/D2原文均明确记载90万元合计（非推导值），按裁决保留'),
      F('F3','肖永明','拟处罚款金额（直接负责的主管人员）','30万元','amount','拟',['D1'],[('D1',r'其中作为直接负责的主管人员罚款30万元')],note='双身份拆槽'),
      F('F4','肖永明','拟处罚款金额（实际控制人）','60万元','amount','拟',['D1'],[('D1',r'作为实际控制人罚款60万元')],note='双身份拆槽'),
      F('F5','吴卫东','拟处罚款金额','20万元','amount','拟',['D1'],[('D1',r'对吴卫东、刘威给予警告，并分别处以20万元的罚款')],note='共用组跨度'),
      F('F6','刘威','拟处罚款金额','20万元','amount','拟',['D1'],[('D1',r'对吴卫东、刘威给予警告，并分别处以20万元的罚款')],note='共用组跨度'),
      *[F(f'F{7+i}' if i == 0 else f'F{24+i}', n, '拟处罚款金额', '3万元', 'amount', '拟', ['D1'],
          [('D1', r'对曹邦俊、肖瑶、王聚宝、郑钜夫、王卫国、姚焕然、亓昭英、邵静、侯选明、李光俊、蒋秀恒、方丽、张生顺给予警告，并分别处以3万元的罚款')],
          note='逐人拆槽（裁决），共用13人组跨度（原文"分别"）')
        for i, n in enumerate(['曹邦俊','肖瑶','王聚宝','郑钜夫','王卫国','姚焕然','亓昭英','邵静','侯选明','李光俊','蒋秀恒','方丽','张生顺'])],
      F('F8','肖永明','拟采取市场禁入措施','5年市场禁入','ban','拟',['D1'],[('D1',r'对肖永明采取5年市场禁入措施')]),
      F('F9','吴卫东','拟采取市场禁入措施','3年市场禁入','ban','拟',['D1'],[('D1',r'对吴卫东釆取3年市场禁入措施')],note='镜像文本作釆取；任务输入文书原样保留，未经原件PDF视觉核验'),
      F('F10','青海证监局','事先告知书文号','青证监处罚字[2019]1号','docno','拟',['D1'],[('D1',r'青证监处罚字\[2019\]1号')],meta=True),
      F('F11','藏格控股','收到事先告知书日期','2019年11月25日','date','拟',['D1'],[('D1',r'2019年11月25日，公司收到')],meta=True),
      F('F12','藏格控股','终局处罚款金额','60万元','amount','终',['D2'],[('D2',r'对藏格控股责令改正，给予警告，并处以60万元的罚款')]),
      F('F13','肖永明','终局处罚款合计金额','90万元','amount','终',['D2'],[('D2',r'对肖永明给予警告，并处以90万元的罚款')]),
      F('F14','肖永明','终局处罚款金额（直接负责的主管人员）','30万元','amount','终',['D2'],[('D2',r'其中作为直接负责的主管人员罚款30万元')]),
      F('F15','肖永明','终局处罚款金额（实际控制人）','60万元','amount','终',['D2'],[('D2',r'作为实际控制人罚款60万元')]),
      F('F16','吴卫东','终局处罚款金额','20万元','amount','终',['D2'],[('D2',r'对吴卫东、刘威给予警告，并分别处以20万元的罚款')],note='共用组跨度'),
      F('F17','刘威','终局处罚款金额','20万元','amount','终',['D2'],[('D2',r'对吴卫东、刘威给予警告，并分别处以20万元的罚款')],note='共用组跨度'),
      *[F(f'F{18+i}' if i == 0 else f'F{36+i}', n, '终局处罚款金额', '3万元', 'amount', '终', ['D2'],
          [('D2', r'对曹邦俊、肖瑶、王聚宝、郑钜夫、王卫国、姚焕然、亓昭英、邵静、侯选明、李光俊、蒋秀恒、方丽、张生顺给予警告，并分别处以3万元的罚款')],
          note='逐人拆槽（裁决），共用13人组跨度')
        for i, n in enumerate(['曹邦俊','肖瑶','王聚宝','郑钜夫','王卫国','姚焕然','亓昭英','邵静','侯选明','李光俊','蒋秀恒','方丽','张生顺'])],
      F('F19','青海证监局','处罚决定书文号','行政处罚决定书（2019）2号','docno','终',['D2'],[('D2',r'行政处罚决定书（2019）2号')],meta=True),
      F('F20','青海证监局','处罚决定书作出日期','2019年11月28日','date','终',['D2'],[('D2',r'2019年11月28日')],meta=True),
      F('F21','肖永明','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='D2全文零处出现禁入，处罚决定部分仅载罚款；未载明≠未采取（另有市场禁入决定书，不属于本任务输入文书，不得作为作答依据）'),
      F('F22','吴卫东','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='同F21，D2未载明'),
      F('F23','藏格控股','2017年年报虚增利润总额','477,383,385.51元','amount','中性',['D1','D2'],
        [('D1',r'虚增利润总额477,383,385.51元（含相关的其他收益）'),('D2',r'虚增利润总额477,383,385.51元\(含相关的其他收益\)')],note='两文书括号全角/半角书写差异，原样各自保留'),
      F('F24','藏格控股','2018年年报虚增利润总额','128,325,919.05元','amount','中性',['D1','D2'],
        [('D1',r'虚增利润总额128,325,919.05元'),('D2',r'虚增利润总额128,325,919.05元')]),
    ])
out_dir = HERE / 'contracts'
sheet = ['# G7 批5 Gold 合同 v1.0（裁决后定稿：金力泰PASS；江特OCR视觉核验更正；藏格13人逐人拆槽）', '']
mapping_md = ['# 批4 新旧事实槽映射（v0.1 -> v1.0）', '']
totals = Counter()
for spec in (JIANGTE, JINLITAI, ZANGGE):
    docs = {}
    corrections = []
    for d, f in spec['docs'].items():
        t = strip_pageno((HERE / f).read_text(errors='ignore'))
        st, idx = strip_with_map(t)
        for wrong, right, why in spec.get('text_corrections', {}).get(d, []):
            pos = st.find(wrong)
            assert pos >= 0, f'{spec["task"]} correction target missing: {wrong}'
            st = st[:pos] + right + st[pos + len(wrong):]  # 等长替换，idx保持对齐
            corrections.append(dict(doc=d, text_layer=wrong, printed=right, reason=why,
                                    context=st[max(0, pos - 10):pos + len(wrong) + 10]))
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
                    text_corrections=corrections,
                    schema='G7-V03-spanlevel-v1.0', adjudicated='2026-11-10 操作员批5裁决（江特OCR核验更正/藏格13人拆槽/F2保留）',
                    
                    
                    source_pages={d: dict(pages={'1': docs[d]['raw']}, normalized=docs[d]['stripped'],
                                          raw_sha256=doc_sha[d], file=spec['docs'][d]) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['fact_stage'] == '拟' and f['fact_class'] == 'stage_content'),
                               n_d2_only=sum(1 for f in facts if f['fact_stage'] == '终' and f['fact_class'] != 'doc_metadata'),
                               spans_verified=n_span_ok))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v1.0.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}｜跨度校验 {n_span_ok} 条全部通过", '']
    mapping_md += [f"## {spec['task']}", '(批5为初稿，无映射)', '']
sheet += [f"**批4修订后总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH5.md').write_text('\n'.join(sheet) + '\n')
(HERE / '_unused.md').write_text('\n'.join(mapping_md) + '\n')
print('v1.0 written:', sorted(p.name for p in out_dir.glob('*_v1.0.json')))
print('批4修订后分类:', dict(totals))
