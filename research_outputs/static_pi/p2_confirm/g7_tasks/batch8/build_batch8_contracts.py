#!/usr/bin/env python3
"""G7 批8 Gold 合同草案构建（v0.1，待操作员裁决）。
四任务：HS_300208 恒顺众昇（贾全臣死亡不追责明载+6人终局未列名+3禁入未载=9 UNKNOWN）；
JY_300117 嘉寓股份（未具名组→具名拆分+沈兰薇终局新增5万档+2禁入未载）；
JT2_300399 京天利（申辩成功：公司60→40/钱永耀30→20、60→40、合并90→60四处值变+决定书全角括号）；
WH_002194 武汉凡谷（汉字→阿拉伯数字纯格式差异+同号1号但鄂处罚字【】→[]前后缀括号双变）。
Outputs: contracts/*_v0.1.json + FACT_SHEET_BATCH8.md"""
import json, re, hashlib
from pathlib import Path
from collections import Counter
HERE = Path(__file__).parent

def strip_with_map(raw):
    out, idx = [], []
    for i, ch in enumerate(raw):
        if not ch.isspace(): out.append(ch); idx.append(i)
    return ''.join(out), idx

def strip_pageno(t):
    return re.sub(r'\n\s*\d+\s*(?=\n|$)', '', t)

docs_cache = {}
def load_doc(fname):
    if fname not in docs_cache:
        raw = strip_pageno((HERE / 'raw' / fname).read_text(errors='ignore'))
        st, idx = strip_with_map(raw)
        docs_cache[fname] = dict(raw=raw, stripped=st, idx=idx)
    return docs_cache[fname]

def span_of(doc, pattern):
    pat = re.sub(r'\s+', '', pattern)
    m = re.search(re.escape(pat), doc['stripped'])
    assert m, f'span not found: {pattern[:60]}'
    i, j = m.span()
    return dict(evidence_span=doc['stripped'][i:j],
                raw_evidence_span=doc['raw'][doc['idx'][i]:doc['idx'][j-1]+1])

def F(fid, subj, pred, val, kind, stage, allowed, ev, note=None, meta=False, cls=None, basis=None):
    d = dict(fact_id=fid, subject=subj, predicate=pred, value=val, value_kind=kind,
             fact_stage=stage, allowed_docs=allowed,
             stage_evidence=[dict(document_id=dd, **span_of(load_doc(files[dd]), pp)) for dd, pp in ev] if ev else [])
    if cls: d['fact_class'] = cls
    elif meta: d['fact_class'] = 'doc_metadata'
    elif val == 'UNKNOWN': d['fact_class'] = 'unknown_boundary'
    else: d['fact_class'] = 'stage_content'
    if note: d['note'] = note
    if basis: d['unknown_basis'] = basis
    return d

specs = []

# ============ HS_300208 恒顺众昇：当事人死亡明载+6人未列名+3禁入未载 ============
files = dict(D1='hs_D1_notice.txt', D2='hs_D2_penalty.txt')
HS8D1 = '对王天文、陈旭光、叶迎春、严冬梅、徐茂顺、强力、肖红英、应明、曲少波、张培荣、付思奇、袁瑞峰、付大志、张振波给予警告，并分别处以3万元罚款'
HS8D2 = '对王天文、陈旭光、叶迎春、应明、曲少波、张培荣、付大志、张振波给予警告，并分别处以3万元罚款'
specs.append(dict(
    task='HS_300208', company='青岛市恒顺众昇集团股份有限公司', code='300208',
    facts=[
      F('F1','恒顺众昇','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','对恒顺众昇责令改正，给予警告，并处以60万元罚款')]),
      F('F2','贾全臣','拟处罚款金额（信息披露责任人员）','30万元','amount','拟',['D1'],[('D1','对贾全臣作为恒顺众昇信息披露违法行为的责任人员给予警告，并处以30万元罚款')],note='双身份之一'),
      F('F3','贾全臣','拟处罚款金额（实际控制人指使）','30万元','amount','拟',['D1'],[('D1','对其作为实际控制人指使上市公司从事信息披露违法行为，给予警告，并处以30万元罚款')],note='双身份拆槽'),
      F('F4','陈肖强、刘涛（2人）','拟单人处罚款金额','20万元','amount','拟',['D1'],[('D1','对陈肖强、刘涛给予警告，并分别处以20万元罚款')],note='共用组跨度'),
      F('F5','姚刚、莫柏欣（2人）','拟单人处罚款金额','15万元','amount','拟',['D1'],[('D1','对姚刚、莫柏欣给予警告，并分别处以15万元罚款')],note='共用组跨度'),
      F('F6','贾晓钰','拟处罚款金额','10万元','amount','拟',['D1'],[('D1','对贾晓钰作为恒顺众昇信息披露违法行为的责任人员给予警告，并处以10万元罚款')]),
      F('F7','贾玉兰','拟处罚款金额','5万元','amount','拟',['D1'],[('D1','对贾玉兰给予警告，并处以5万元罚款')]),
      F('F8','王天文等14人','拟单人处罚款金额','3万元','amount','拟',['D1'],[('D1',HS8D1)],note='共用组跨度；终局缩编为8人'),
      F('F9','中国证监会','事先告知书文号','处罚字[2017]101号','docno','拟',['D1'],[('D1','处罚字[2017]101号')],meta=True),
      F('F10','恒顺众昇','收到事先告知书日期','2017年10月13日','date','拟',['D1'],[('D1','2017年10月13日，公司收到')],meta=True),
      F('F11','贾全臣','拟采取市场禁入措施','10年证券市场禁入','ban','拟',['D1'],[('D1','对贾全臣采取10年证券市场禁入措施')]),
      F('F12','陈肖强','拟采取市场禁入措施','5年证券市场禁入','ban','拟',['D1'],[('D1','对陈肖强、刘涛采取5年证券市场禁入措施')],note='与刘涛共用跨度'),
      F('F13','刘涛','拟采取市场禁入措施','5年证券市场禁入','ban','拟',['D1'],[('D1','对陈肖强、刘涛采取5年证券市场禁入措施')],note='与陈肖强共用跨度'),
      F('F14','恒顺众昇','终局处罚款金额','60万元','amount','终',['D2'],[('D2','对恒顺众昇责令改正，给予警告，并处以60万元罚款')],note='同值'),
      F('F15','陈肖强、刘涛（2人）','终局单人处罚款金额','20万元','amount','终',['D2'],[('D2','对陈肖强、刘涛给予警告，并分别处以20万元罚款')],note='同值'),
      F('F16','姚刚、莫柏欣（2人）','终局单人处罚款金额','15万元','amount','终',['D2'],[('D2','对姚刚、莫柏欣给予警告，并分别处以15万元罚款')],note='同值'),
      F('F17','贾晓钰','终局处罚款金额','10万元','amount','终',['D2'],[('D2','对贾晓钰给予警告，并处以10万元罚款')],note='同值；D1另载其股东警告（无金额）终局仅载罚款'),
      F('F18','贾玉兰','终局处罚款金额','5万元','amount','终',['D2'],[('D2','对贾玉兰给予警告，并处以5万元罚款')],note='同值'),
      F('F19','王天文、陈旭光、叶迎春、应明、曲少波、张培荣、付大志、张振波（8人）','终局处罚组构成（各3万元组）','3万元/组','amount','终',['D2'],[('D2',HS8D2)],note='已知组构成变化（原14人组缩编为8人）；评分重点=成员构成；组槽计为1个群组事实。三情形区分（裁决）：移出原处罚组=已知组构成变化（本槽）；终局处罚结果未载明=UNKNOWN（F24-F29）；明文不予追责=已知终局结果（F22）——不混用'),
      F('F20','中国证监会','处罚决定书文号','[2018]31号','docno','终',['D2'],[('D2','《行政处罚决定书》([2018]31号)')],meta=True),
      F('F21','恒顺众昇','收到处罚决定书日期','2018年4月26日','date','终',['D2'],[('D2','2018年4月26日，公司收到')],meta=True),
      F('F22','贾全臣','终局处罚结果','不再追究（当事人死亡）','outcome','终',['D2'],[('D2','贾全臣（2017年11月死亡，不再追究其行政责')],note='D2申辩听证段明文：贾全臣（2017年11月死亡，不再追究其行政责任）——已知终局处理结果，非UNKNOWN，亦非组构成变化'),
      F('F23','戴一鸣','终局处罚结果','UNKNOWN','outcome','终',['D2'],[],basis='已全文核实：D2（含申辩听证段）0次出现（D1拟对其仅股东警告无金额）；终局处理结果未载明——未载明≠未处罚，不倒推'),
      *[F(f'F{23+i}', n, '终局处罚款金额', 'UNKNOWN', 'amount', '终', ['D2'], [],
          basis='已全文核实：D2（含陈述申辩段、听证段）0次出现该当事人（D1拟列于14人组各3万）；退出原处罚组不自动等于UNKNOWN，但其终局处理结果确未载明——未载明≠未处罚，不倒推')
        for i, n in enumerate(['严冬梅','徐茂顺','强力','肖红英','付思奇','袁瑞峰'], start=1)],
      F('F30','贾全臣','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='D2仅处罚决定书（未含市场禁入决定书内容）；禁入终局未载明≠未采取，不倒推'),
      F('F31','陈肖强','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='同F30；另有单独市场禁入决定书不属于本任务输入文书'),
      F('F32','刘涛','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='同F30'),
    ],
    docs=files))

# ============ JY_300117 嘉寓股份：未具名组→具名拆分+沈兰薇新增 ============
files = dict(D1='jy_D1_notice.txt', D2='jy_D2_penalty.txt')
JY23 = '给予陈其泽、田新甲、张初虎、许小林、屈瀑、白艳红、陈业进、李莉萍、姜仁、刘龙华、尹秀超、谭红旭、徐曙光、王金秀、薛莹、张国峰、牟世凤、朱廷财、周建勇、喻久旺、朱小虎、王浩、苏文军、吴海英警告'
specs.append(dict(
    task='JY_300117', company='北京嘉寓门窗幕墙股份有限公司', code='300117',
    facts=[
      F('F1','嘉寓股份','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','给予嘉寓股份警告，并处以60万元罚款')],note='D1用"给予…警告"语序（无"对"字）'),
      F('F2','田家玉','拟处罚款金额','30万元','amount','拟',['D1'],[('D1','给予嘉寓股份时任董事长田家玉警告，并处以30万元罚款')],note='D1带职务前缀'),
      F('F3','胡满姣','拟处罚款金额','15万元','amount','拟',['D1'],[('D1','给予嘉寓股份时任财务总监胡满姣警告，并处以15万元罚款')],note='D1带职务前缀'),
      F('F4','时任董事、监事、高级管理人员、会计机构负责人（未具名组）','拟单人处罚款金额','3万元','amount','拟',['D1'],[('D1','给予嘉寓股份时任董事、监事、高级管理人员、会计机构负责人警告，并分别处以3万元罚款')],note='条件PASS（裁决）：群组按原文唯一界定=「时任董监高及会计机构负责人中被处以3万元者」（角色+金额），金额3万原文明确；不虚构人员姓名；终局具名化见F13（23人组），沈兰薇5万（F12）不在本组（拟文书未出现）——拟组与终局具名组人员对应关系文书未载明，不得推断'),
      F('F5','田家玉','拟采取市场禁入措施','8年证券市场禁入','ban','拟',['D1'],[('D1','对时任董事长田家玉采取8年证券市场禁入措施')]),
      F('F6','胡满姣','拟采取市场禁入措施','5年证券市场禁入','ban','拟',['D1'],[('D1','对时任财务总监胡满姣采取5年证券市场禁入措施')]),
      F('F7','中国证监会','事先告知书文号','处罚字[2016]115号','docno','拟',['D1'],[('D1','处罚字[2016]115号')],meta=True),
      F('F8','嘉寓股份','收到事先告知书日期','2016年12月30日','date','拟',['D1'],[('D1','2016年12月30日公司在发布')],meta=True),
      F('F9','嘉寓股份','终局处罚款金额','60万元','amount','终',['D2'],[('D2','给予嘉寓股份警告，并处以60万元罚款')],note='同值'),
      F('F10','田家玉','终局处罚款金额','30万元','amount','终',['D2'],[('D2','给予田家玉警告，并处以30万元罚款')],note='同值；D2去职务前缀'),
      F('F11','胡满姣','终局处罚款金额','15万元','amount','终',['D2'],[('D2','给予胡满姣警告，并处以15万元罚款')],note='同值；D2去职务前缀'),
      F('F12','沈兰薇','终局处罚款金额','5万元','amount','终',['D2'],[('D2','给予沈兰薇警告，并处以5万元罚款')],note='拟阶段文书0次出现（终局新增当事人+新增5万档位）；涉D1对其金额按证据不足处理'),
      F('F13','陈其泽等23人（终局具名组）','终局处罚组构成（各3万元组）','3万元/组','amount','终',['D2'],[('D2',JY23)],note='评分重点=成员构成（拟阶段未具名组的具名化）；组槽计为1个群组事实'),
      F('F14','中国证监会','处罚决定书文号','[2017]38号','docno','终',['D2'],[('D2','《行政处罚决定书》（编号：[2017]38号）')],meta=True),
      F('F15','田家玉','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='D2仅处罚决定书（公告未载市场禁入决定书内容）；终局未载明≠未采取，不倒推'),
      F('F16','胡满姣','终局市场禁入措施','UNKNOWN','ban','终',['D2'],[],basis='同F15'),
    ],
    docs=files))

# ============ JT2_300399 京天利：申辩成功四处值变 ============
files = dict(D1='jt_D1_notice.txt', D2='jt_D2_penalty.txt')
specs.append(dict(
    task='JT2_300399', company='北京无线天利移动信息技术股份有限公司', code='300399',
    facts=[
      F('F1','京天利','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','对京天利给予警告，责令改正，并处以60万元的罚款')]),
      F('F2','钱永耀','拟处罚款金额（第一项）','30万元','amount','拟',['D1'],[('D1','对钱永耀处以30万元的罚款')],note='D1对钱永耀无"给予警告"措辞'),
      F('F3','钱永耀','拟处罚款金额（第二项）','60万元','amount','拟',['D1'],[('D1','对钱永耀处以60万元的罚款')],note='D1对钱永耀无"给予警告"措辞'),
      F('F4','钱永耀','拟合并处罚款金额','90万元','amount','拟',['D1'],[('D1','两项合并，对钱永耀处以罚款90万元')],note='=30+60，原文明确记载"两项合并"'),
      F('F5','中国证监会','事先告知书文号','处罚字[2016]8号','docno','拟',['D1'],[('D1','处罚字[2016]8号')],meta=True),
      F('F6','京天利','收到事先告知书日期','2016年1月19日','date','拟',['D1'],[('D1','2016年1月19日公司收到')],meta=True),
      F('F7','京天利','终局处罚款金额','40万元','amount','终',['D2'],[('D2','对京天利给予警告，责令改正，并处以40万元的罚款')],note='值变60→40（D1公告载公司拟申辩）'),
      F('F8','钱永耀','终局处罚款金额（第一项）','20万元','amount','终',['D2'],[('D2','对钱永耀给予警告，并处以20万元的罚款')],note='值变30→20；D2增加"给予警告"措辞'),
      F('F9','钱永耀','终局处罚款金额（第二项）','40万元','amount','终',['D2'],[('D2','对钱永耀给予警告，并处以40万元的罚款')],note='值变60→40；D2增加"给予警告"措辞'),
      F('F10','钱永耀','终局合并处罚款金额','60万元','amount','终',['D2'],[('D2','两项合并，对钱永耀给予警告，并处以罚款60万元')],note='值变90→60；=20+40，原文明确记载'),
      F('F11','中国证监会','处罚决定书文号','【2016】81号','docno','终',['D2'],[('D2','行政处罚决定书（【2016】81号')],meta=True,note='全角括号【】'),
      F('F12','京天利','收到处罚决定书日期','2016年6月28日','date','终',['D2'],[('D2','2016年6月28日，公司收到')],meta=True),
    ],
    docs=files))

# ============ WH_002194 武汉凡谷：汉字→数字+同号异写 ============
files = dict(D1='wh_D1_notice.txt', D2='wh_D2_penalty.txt')
specs.append(dict(
    task='WH_002194', company='武汉凡谷电子技术股份有限公司', code='002194',
    facts=[
      F('F1','武汉凡谷','拟处罚款金额','三十万元','amount','拟',['D1'],[('D1','对武汉凡谷给予警告，并处以三十万元的罚款')],note='D1汉字数字'),
      F('F2','孟凡博、王志松（2人）','拟单人处罚款金额（直接负责的主管人员）','五万元','amount','拟',['D1'],[('D1','对直接负责的主管人员孟凡博、王志松给予警告，并分别处以五万元的罚款')],note='共用组跨度；D1汉字'),
      F('F3','范志辉','拟处罚款金额','三万元','amount','拟',['D1'],[('D1','对其他直接责任人员范志辉给予警告，并处以三万元的罚款')],note='D1汉字'),
      F('F4','湖北证监局','事先告知书文号','鄂处罚字【2018】1号','docno','拟',['D1'],[('D1','鄂处罚字【2018】1号')],meta=True,note='带鄂前缀+全角括号'),
      F('F5','武汉凡谷','收到事先告知书日期','2018年2月6日','date','拟',['D1'],[('D1','2018年2月6日，公司及相关当事人收到')],meta=True),
      F('F6','武汉凡谷','终局处罚款金额','30万元','amount','终',['D2'],[('D2','对武汉凡谷给予警告，并处以30万元的罚款')],note='D2阿拉伯数字——书写格式阶段差异，不作值变化解读'),
      F('F7','孟凡博、王志松（2人）','终局单人处罚款金额（直接负责的主管人员）','5万元','amount','终',['D2'],[('D2','对直接负责的主管人员孟凡博、王志松给予警告，并分别处以5万元的')],note='共用组跨度；D2阿拉伯数字；原文该条被翻页页眉打断（“…5万元的〔页眉〕罚款”），跨度止于断点前'),
      F('F8','范志辉','终局处罚款金额','3万元','amount','终',['D2'],[('D2','对其他直接责任人员范志辉给予警告，并处以3万元的罚款')],note='D2阿拉伯数字'),
      F('F9','湖北证监局','处罚决定书文号','[2018]1号','docno','终',['D2'],[('D2','《行政处罚决定书》（[2018]1号')],meta=True,note='同号1但去鄂前缀+半角括号——与D1文号写法双差异'),
      F('F10','武汉凡谷','收到处罚决定书日期','2018年3月2日','date','终',['D2'],[('D2','2018年3月2日，公司及相关当事人收到')],meta=True),
      F('F11','武汉凡谷2016年半年度报告','虚增营业利润','15,595,879.52元','amount','中性',['D1','D2'],[('D1','虚增营业利润15,595,879.52元'),('D2','虚增营业利润15,595,879.52元')],cls='background'),
      F('F12','武汉凡谷2016年第三季度报告','虚增营业利润','38,106,460.58元','amount','中性',['D1','D2'],[('D1','虚增营业利润38,106,460.58元'),('D2','虚增营业利润38,106,460.58元')],cls='background'),
      F('F13','武汉凡谷2016年半年度报告','虚增营业利润占当期披露营业利润比例','51.17%','ratio','中性',['D1','D2'],[('D1','占当期披露营业利润的51.17%'),('D2','占当期披露营业利润的51.17%')],cls='background'),
    ],
    docs=files))

# ============ 构建 ============
out_dir = HERE / 'contracts'; out_dir.mkdir(exist_ok=True)
sheet = ['# G7 批8 Gold 合同 v1.0（裁决后定稿：四案签收；恒顺三情形区分+嘉寓F4条件保留）',
         '', '来源：cninfo 官方公告 PDF（静态页直取）；逐事实逐字证据跨度已程序化校验为文书原文子串。',
         '阶段敏感 = 允许文书单份（拟→D1、终→D2）。UNKNOWN = 终局文书未载明（不倒推）。', '']
cls_tot, grand = {}, 0
for spec in specs:
    files = spec['docs']
    facts = spec['facts']
    ids = [f['fact_id'] for f in facts]
    assert len(ids) == len(set(ids)), f"{spec['task']} fact_id 重复"
    cls = Counter(f['fact_class'] for f in facts)
    doc_sha = {d: hashlib.sha256((HERE / 'raw' / f).read_bytes()).hexdigest()[:16] for d, f in spec['docs'].items()}
    contract = dict(task=spec['task'], company=spec['company'], code=spec['code'],
                    schema='G7-V03-spanlevel-v1.0', adjudicated='2026-11-10 操作员批8裁决（恒顺三情形区分+6人UNKNOWN经全文核实；嘉寓F4条件PASS按角色+金额唯一界定不虚构姓名）',
                    source_pages={d: dict(file=spec['docs'][d], sha256_16=doc_sha[d],
                        chars=len(load_doc(spec['docs'][d])['stripped'])) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['allowed_docs'] == ['D1']),
                               n_d2_only=sum(1 for f in facts if f['allowed_docs'] == ['D2']),
                               spans_verified=sum(len(f['stage_evidence']) for f in facts)))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v1.0.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    d1o = contract['stats']['n_d1_only']; d2o = contract['stats']['n_d2_only']
    sheet += [f"## {spec['task']} {spec['company']}（{spec['code']}）", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 | 备注 |', '|---|---|---|---|---|---|---|---|']
    for f in facts:
        ev = '＋'.join(f"{e['document_id']}[{e['evidence_span'][:20]}…]" for e in f['stage_evidence']) or '—（UNKNOWN）'
        basis = f"；basis：{f['unknown_basis']}" if 'unknown_basis' in f else ''
        sheet.append(f"| {f['fact_id']} | {f['subject'][:26]} | {f['predicate']} | {f['value']} | {f['fact_stage']} | {f['fact_class']} | {'/'.join(f['allowed_docs'])} | {f.get('note','')}{basis} |")
    sheet += ['', f"事实合计 {len(facts)}：阶段内容 {cls.get('stage_content',0)}｜UNKNOWN {cls.get('unknown_boundary',0)}｜元数据 {cls.get('doc_metadata',0)}｜背景 {cls.get('background',0)}；阶段敏感（单文书）拟 {d1o} / 终 {d2o}；跨度校验 {contract['stats']['spans_verified']} 处全部通过。", '']
    cls_tot.update({k: cls_tot.get(k, 0) + v for k, v in cls.items()}); grand += len(facts)
sheet += [f'**批8草案总计 {grand}：阶段内容 {cls_tot.get("stage_content",0)}｜UNKNOWN {cls_tot.get("unknown_boundary",0)}｜元数据 {cls_tot.get("doc_metadata",0)}｜背景 {cls_tot.get("background",0)}**']
(HERE / 'FACT_SHEET_BATCH8.md').write_text('\n'.join(sheet) + '\n')
print('v0.1 written:', sorted(p.name for p in out_dir.glob('*_v0.1.json')))
print('批8分类:', dict(cls_tot), '总计', grand)
