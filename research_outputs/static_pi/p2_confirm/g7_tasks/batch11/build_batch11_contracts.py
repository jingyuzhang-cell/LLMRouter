#!/usr/bin/env python3
"""G7 批11 Gold 合同草案构建（v0.1，待操作员裁决）。
三任务：BQL_600074 保千里（汉字→阿拉伯+予以/给予警告+依据/根据三重格式变体）；
LT_600695 绿庭投资（全同值汉字+D2明文'维持事先告知的处罚'+编号一、→（1））；
AZ_002667 鞍重股份（编号1.→一、+'责任人员/责任人'措辞+告知书文号仅D2载明）。"""
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

def F(fid, subj, pred, val, kind, stage, allowed, ev, note=None, meta=False, cls=None, basis=None, alloc=None):
    d = dict(fact_id=fid, subject=subj, predicate=pred, value=val, value_kind=kind,
             fact_stage=stage, allowed_docs=allowed,
             stage_evidence=[dict(document_id=dd, **span_of(load_doc(files[dd]), pp)) for dd, pp in ev] if ev else [])
    if cls: d['fact_class'] = cls
    elif meta: d['fact_class'] = 'doc_metadata'
    elif val == 'UNKNOWN': d['fact_class'] = 'unknown_boundary'
    else: d['fact_class'] = 'stage_content'
    if note: d['note'] = note
    if basis: d['unknown_basis'] = basis
    if alloc: d['allocation'] = alloc
    return d

specs = []

# ============ BQL_600074 保千里：三重格式变体 ============
files = dict(D1='bql_D1_notice.txt', D2='bql_D2_penalty.txt')
specs.append(dict(
    task='BQL_600074', company='江苏保千里视像科技集团股份有限公司', code='600074',
    facts=[
      F('F1','庄敏','拟处罚款金额（214条违法项）','六十万元','amount','拟',['D1'],[('D1','对庄敏责令改正，予以警告，并处以六十万元的罚款')],note='D1用“予以警告”+汉字金额'),
      F('F2','陈海昌、庄明、蒋俊杰（3人）','拟单人处罚款金额（214条违法项）','十五万元','amount','拟',['D1'],[('D1','对陈海昌、庄明、蒋俊杰责令改正，给予警告，并分别处以十五万元的罚款')],note='共用组跨度；该组D1用“给予警告”'),
      F('F3','保千里','拟处罚款金额（193条违法项）','四十万元','amount','拟',['D1'],[('D1','对保千里责令改正，给予警告，并处以四十万元罚款')]),
      F('F4','童爱平、王务云（2人）','拟单人处罚款金额','二十万元','amount','拟',['D1'],[('D1','对童爱平、王务云给予警告，并分别处以二十万元罚款')],note='共用组跨度'),
      F('F5','林硕奇、王培琴、茅建华、费滨海、沙智慧（5人）','拟单人处罚款金额','十万元','amount','拟',['D1'],[('D1','对林硕奇、王培琴、茅建华、费滨海、沙智慧给予警告，并分别处以十万元罚款')],note='共用组跨度；组槽计为1个群组事实'),
      F('F6','中国证监会','事先告知书文号','处罚字【2017】87号','docno','拟',['D1'],[('D1','处罚字【2017】87号')],meta=True,note='全角括号【】'),
      F('F7','保千里','收到事先告知书日期','2017年7月11日','date','拟',['D1'],[('D1','2017年7月11日，公司及控股股东')],meta=True),
      F('F8','庄敏','终局处罚款金额（214条违法项）','60万元','amount','终',['D2'],[('D2','对庄敏责令改正，给予警告，并处以60万元罚款')],note='同值；D2“给予警告”+阿拉伯数字——予以→给予+汉字→数字双格式差异不作值变化解读'),
      F('F9','陈海昌、庄明、蒋俊杰（3人）','终局单人处罚款金额（214条违法项）','15万元','amount','终',['D2'],[('D2','对陈海昌、庄明、蒋俊杰责令改正，给予警告，并分别处以15万元罚款')],note='共用组跨度；同值'),
      F('F10','保千里','终局处罚款金额（193条违法项）','40万元','amount','终',['D2'],[('D2','对保千里责令改正，给予警告，并处以40万元罚款')],note='同值；D1“依据”→D2“根据”法条引导词差异'),
      F('F11','童爱平、王务云（2人）','终局单人处罚款金额','20万元','amount','终',['D2'],[('D2','对童爱平、王务云给予警告，并分别处以20万元罚款')],note='共用组跨度；同值'),
      F('F12','林硕奇等5人','终局处罚组构成（各10万元组）','10万元/组','amount','终',['D2'],[('D2','对林硕奇、王培琴、茅建华、费滨海、沙智慧给予警告，并分别处以10万元罚款')],note='组构成与拟一致；组槽计为1个群组事实'),
      F('F13','中国证监会','处罚决定书文号','【2017】78号','docno','终',['D2'],[('D2','《行政处罚决定书》（编号：【2017】78号）')],meta=True,note='全角括号'),
      F('F14','保千里','收到处罚决定书日期','2017年8月11日','date','终',['D2'],[('D2','2017年8月11日，公司及控股股东')],meta=True),
    ],
    docs=files))

# ============ LT_600695 绿庭投资：明文维持+编号变体 ============
files = dict(D1='lt_D1_notice.txt', D2='lt_D2_penalty.txt')
specs.append(dict(
    task='LT_600695', company='上海绿庭投资控股集团股份有限公司', code='600695',
    facts=[
      F('F1','绿庭投资','拟处罚款金额','三十万元','amount','拟',['D1'],[('D1','对绿庭投资给予警告，并处以三十万元的罚款')],note='D1汉字金额；条目用“一、”编号'),
      F('F2','俞乃奋','拟处罚款金额','三万元','amount','拟',['D1'],[('D1','对俞乃奋给予警告，并处以三万元的罚款')]),
      F('F3','李冬青','拟处罚款金额','三万元','amount','拟',['D1'],[('D1','对李冬青给予警告，并处以三万元的罚款')]),
      F('F4','上海证监局','事先告知书文号','处罚字【2019】3号','docno','拟',['D1'],[('D1','处罚字【2019】3号')],meta=True),
      F('F5','绿庭投资','收到事先告知书日期','2019年8月14日','date','拟',['D1'],[('D1','2019年8月14日公司及原董事长')],meta=True),
      F('F6','绿庭投资','终局处罚款金额','三十万元','amount','终',['D2'],[('D2','（1）对绿庭投资给予警告，并处以三十万元的罚款')],note='D2明文“决定维持事先告知的处罚”+（1）编号+汉字金额（两文书格式一致）'),
      F('F7','俞乃奋','终局处罚款金额','三万元','amount','终',['D2'],[('D2','对俞乃奋给予警告，并处以三万元的罚款')],note='同值'),
      F('F8','李冬青','终局处罚款金额','三万元','amount','终',['D2'],[('D2','对李冬青给予警告，并处以三万元的罚款')],note='同值'),
      F('F9','绿庭投资','收到处罚决定书日期','2019年9月16日','date','终',['D2'],[('D2','2019年9月16日，本公司及原董事长')],meta=True,note='D2公告未载决定书文号（无终侧文号槽）'),
    ],
    docs=files))

# ============ AZ_002667 鞍重股份：编号+措辞+文号证据分离 ============
files = dict(D1='az_D1_notice.txt', D2='az_D2_penalty.txt')
AZ13D1 = '对其他直接责任人员温萍、高永春、梁晓东、黄涛、白璐、戴国富、程国彬、王君、韩秀冰、蒋辉、冯微微、杨永伟、封海霞给予警告，并分别处以3万元罚款'
AZ13D2 = '对其他直接责任人温萍、高永春、梁晓东、黄涛、白璐、戴国富、程国彬、王君、韩秀冰、蒋辉、冯微微、杨永伟、封海霞给予警告，并分别处以3万元罚款'
specs.append(dict(
    task='AZ_002667', company='鞍山重型矿山机器股份有限公司', code='002667',
    facts=[
      F('F1','鞍重股份','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','对鞍重股份给予警告，并处以60万元罚款')],note='D1条目用“1.”编号'),
      F('F2','杨永柱','拟处罚款金额（直接负责的主管人员）','30万元','amount','拟',['D1'],[('D1','对直接负责的主管人员杨永柱给予警告，并处以30万元罚款')]),
      F('F3','张宝田','拟处罚款金额（直接负责的主管人员）','20万元','amount','拟',['D1'],[('D1','对直接负责的主管人员张宝田给予警告，并处以20万元罚款')]),
      F('F4','温萍等13人','拟单人处罚款金额（其他直接责任人员）','3万元','amount','拟',['D1'],[('D1',AZ13D1)],note='共用组跨度；组槽计为1个群组事实'),
      F('F5','鞍重股份','收到事先告知书日期','2017年3月10日','date','拟',['D1'],[('D1','2017年3月10日，公司及杨永柱')],meta=True),
      F('F6','鞍重股份','终局处罚款金额','60万元','amount','终',['D2'],[('D2','对鞍重股份给予警告，并处以60万元罚款')],note='同值；D2条目用“一、”编号——编号格式阶段差异'),
      F('F7','杨永柱','终局处罚款金额（直接负责的主管人员）','30万元','amount','终',['D2'],[('D2','对直接负责的主管人员杨永柱给予警告，并处以30万元罚款')],note='同值'),
      F('F8','张宝田','终局处罚款金额（直接负责的主管人员）','20万元','amount','终',['D2'],[('D2','对直接负责的主管人员张宝田给予警告，并处以20万元罚款')],note='同值'),
      F('F9','温萍等13人','终局处罚组构成（各3万元组）','3万元/组','amount','终',['D2'],[('D2',AZ13D2)],note='组构成与拟一致；D1“其他直接责任人员”→D2“其他直接责任人”——措辞差异（人员→人）；组槽计为1个群组事实'),
      F('F10','中国证监会','事先告知书文号','处罚字【2017】31号','docno','拟',['D2'],[('D2','处罚字【2017】31号')],meta=True,note='事件阶段=拟；证据来源=D2（D1未载文号）——事件阶段与证据来源分离（宜华F34模式）'),
      F('F11','鞍重股份','收到处罚决定书日期','2017年4月27日','date','终',['D2'],[('D2','2017年4月27日，公司及杨永柱')],meta=True,note='D2公告未载决定书文号（无终侧文号槽）'),
    ],
    docs=files))

# ============ 构建 ============
out_dir = HERE / 'contracts'; out_dir.mkdir(exist_ok=True)
sheet = ['# G7 批11 Gold 合同草案核验单（v0.1，待操作员裁决：保千里/绿庭投资/鞍重股份）', '',
         '来源：cninfo 官方公告 PDF；逐事实逐字证据跨度已程序化校验。UNKNOWN=终局未载明（不倒推）。', '']
cls_tot, grand = {}, 0
for spec in specs:
    files = spec['docs']
    facts = spec['facts']
    ids = [f['fact_id'] for f in facts]
    assert len(ids) == len(set(ids)), f"{spec['task']} fact_id 重复"
    cls = Counter(f['fact_class'] for f in facts)
    doc_sha = {d: hashlib.sha256((HERE / 'raw' / f).read_bytes()).hexdigest()[:16] for d, f in spec['docs'].items()}
    contract = dict(task=spec['task'], company=spec['company'], code=spec['code'],
                    schema='G7-V03-spanlevel-v0.1-draft',
                    source_pages={d: dict(file=spec['docs'][d], sha256_16=doc_sha[d],
                        chars=len(load_doc(spec['docs'][d])['stripped'])) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['allowed_docs'] == ['D1']),
                               n_d2_only=sum(1 for f in facts if f['allowed_docs'] == ['D2']),
                               spans_verified=sum(len(f['stage_evidence']) for f in facts)))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v0.1.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += [f"## {spec['task']} {spec['company']}（{spec['code']}）", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 | 备注 |', '|---|---|---|---|---|---|---|---|']
    for f in facts:
        basis = f"；basis：{f['unknown_basis']}" if 'unknown_basis' in f else ''
        sheet.append(f"| {f['fact_id']} | {f['subject'][:26]} | {f['predicate']} | {f['value']} | {f['fact_stage']} | {f['fact_class']} | {'/'.join(f['allowed_docs'])} | {f.get('note','')}{basis} |")
    sheet += ['', f"事实合计 {len(facts)}：阶段内容 {cls.get('stage_content',0)}｜元数据 {cls.get('doc_metadata',0)}；阶段敏感拟 {contract['stats']['n_d1_only']} / 终 {contract['stats']['n_d2_only']}；跨度校验 {contract['stats']['spans_verified']} 处全部通过。", '']
    cls_tot.update({k: cls_tot.get(k, 0) + v for k, v in cls.items()}); grand += len(facts)
sheet += [f'**批11草案总计 {grand}**']
(HERE / 'FACT_SHEET_BATCH11.md').write_text('\n'.join(sheet) + '\n')
print('v0.1 written:', sorted(p.name for p in out_dir.glob('*_v0.1.json')))
print('批11总计', grand)
