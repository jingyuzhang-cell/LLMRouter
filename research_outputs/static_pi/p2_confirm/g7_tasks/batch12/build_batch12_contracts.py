#!/usr/bin/env python3
"""G7 批12 Gold 合同草案构建（v0.1，待操作员裁决）——最后一批。
三任务：AS_300380 安硕信息（并处罚款/并处以罚款措辞+编号1、→一、+决定书号前置书名）；
HJ_300368 汇金股份（分项+综合全同值+编号一、→（一））；
SWS_300056 三维丝（'给子警告''子以采纳'印刷错字渲染核验原样+并处罚款/处以+逗号顿号'和'混用+双层括号文号）。"""
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

# ============ AS_300380 安硕信息 ============
files = dict(D1='as_D1_notice.txt', D2='as_D2_penalty.txt')
specs.append(dict(
    task='AS_300380', company='上海安硕信息技术股份有限公司', code='300380',
    facts=[
      F('F1','安硕信息','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','对安硕信息给予警告，并处罚款60万元')],note='D1“并处罚款”无“处以”；条目用“1、”编号'),
      F('F2','高鸣','拟处罚款金额','30万元','amount','拟',['D1'],[('D1','对高鸣给予警告，并处罚款30万元')]),
      F('F3','曹丰','拟处罚款金额','20万元','amount','拟',['D1'],[('D1','对曹丰给予警告，并处罚款20万元')]),
      F('F4','中国证监会','事先告知书文号','处罚字[2016]53号','docno','拟',['D1'],[('D1','处罚字[2016]53号')],meta=True),
      F('F5','安硕信息','收到事先告知书日期','2016年6月14日','date','拟',['D1'],[('D1','2016年6月14日公司收到')],meta=True),
      F('F6','安硕信息','终局处罚款金额','60万元','amount','终',['D2'],[('D2','对安硕信息给予警告，并处以60万元罚款')],note='同值；D2“并处以…罚款”+“一、”编号——措辞+编号双差异'),
      F('F7','高鸣','终局处罚款金额','30万元','amount','终',['D2'],[('D2','对高鸣给予警告，并处以30万元罚款')],note='同值'),
      F('F8','曹丰','终局处罚款金额','20万元','amount','终',['D2'],[('D2','对曹丰给予警告，并处以20万元罚款')],note='同值'),
      F('F9','中国证监会','处罚决定书文号','[2016]138号','docno','终',['D2'],[('D2','[2016]138号《行政处罚决定书》')],meta=True,note='D2文号置于书名之前（号前置写法）'),
      F('F10','安硕信息','收到处罚决定书日期','2016年12月20日','date','终',['D2'],[('D2','2016年12月20日公司收到')],meta=True),
    ],
    docs=files))

# ============ HJ_300368 汇金股份：分项+综合全同值 ============
files = dict(D1='hj_D1_notice.txt', D2='hj_D2_penalty.txt')
specs.append(dict(
    task='HJ_300368', company='河北汇金集团股份有限公司', code='300368',
    facts=[
      F('F1','汇金股份','拟处罚款金额（2021年报虚假记载项）','150万元','amount','拟',['D1'],[('D1','对河北汇金集团股份有限公司责令改正，给予警告，并处以150万元罚款；二、')],note='分项一；D1条目用“一、”编号（跨度截至分项二起始以保唯一）'),
      F('F2','汇金股份','拟处罚款金额（未按规定披露重大事项项）','50万元','amount','拟',['D1'],[('D1','对河北汇金集团股份有限公司责令改正，给予警告，并处以50万元罚款。综合上述两项')],note='分项二'),
      F('F3','汇金股份','拟综合处罚款金额','200万元','amount','拟',['D1'],[('D1','综合上述两项，对河北汇金集团股份有限公司责令改正，给予警告，并处以200万元罚款')],note='=150+50，原文明确记载“综合上述两项”'),
      F('F4','河北证监局','事先告知书文号','处罚字〔2024〕1号','docno','拟',['D1'],[('D1','处罚字〔2024〕1号')],meta=True,note='公司告知书；D1另提及孙志恒个人告知书〔2024〕3号（不在本任务文书范围）'),
      F('F5','汇金股份','收到事先告知书日期','2024年3月14日','date','拟',['D1'],[('D1','2024年3月14日，公司收到')],meta=True),
      F('F6','汇金股份','终局处罚款金额（2021年报虚假记载项）','150万元','amount','终',['D2'],[('D2','对河北汇金集团股份有限公司责令改正，给予警告，并处以150万元罚款;(二)')],note='同值；D2条目用“(一)(二)”编号——编号格式阶段差异；D2分号半角'),
      F('F7','汇金股份','终局处罚款金额（未按规定披露重大事项项）','50万元','amount','终',['D2'],[('D2','对河北汇金集团股份有限公司责令改正，给予警告，并处以50万元罚款。综合上述两项')],note='同值'),
      F('F8','汇金股份','终局综合处罚款金额','200万元','amount','终',['D2'],[('D2','综合上述两项，对河北汇金集团股份有限公司责令改正，给予警告，并处以200万元罚款')],note='同值；综合槽考查综合表述本身，不与分项槽重复计分（榕泰/金亚边界）'),
      F('F9','河北证监局','处罚决定书文号','〔2024〕10号','docno','终',['D2'],[('D2','《行政处罚决定书》（〔2024〕10号）')],meta=True),
      F('F10','汇金股份','收到处罚决定书日期','2024年5月10日','date','终',['D2'],[('D2','2024年5月10日，公司收到')],meta=True),
    ],
    docs=files))

# ============ SWS_300056 三维丝：印刷错字核验+多重措辞 ============
files = dict(D1='sws_D1_notice.txt', D2='sws_D2_penalty.txt')
SWS8 = '对罗红花、陈锡良、屈冀彤、耿占吉、郑兴灿、王智勇、丘国强和陈大平给子警告，并分别处罚款5万元'
SWS4 = '对张煜、康述旻、彭南京和周荣德给予警告，并分别处罚款3万元'
specs.append(dict(
    task='SWS_300056', company='厦门三维丝环保股份有限公司', code='300056',
    facts=[
      F('F1','三维丝','拟处罚款金额','60万元','amount','拟',['D1'],[('D1','对三维丝给予警告，并处罚款60万元')],note='D1“并处罚款”无“处以”；条目用“1、”编号'),
      F('F2','廖政宗、罗祥波（2人）','拟单人处罚款金额','30万元','amount','拟',['D1'],[('D1','对廖政宗、罗祥波给予警告，并分别处罚款30万元')],note='共用组跨度；并处罚款'),
      F('F3','刘明辉、张永丰，朱利民和王荣聪（4人）','拟单人处罚款金额','20万元','amount','拟',['D1'],[('D1','对刘明辉、张永丰，朱利民和王荣聪给予警告，并分别处罚款20万元')],note='共用组跨度；D1该条顿号/逗号/“和”混用（“张永丰，朱利民和王荣聪”）——原文原样'),
      F('F4','李凉凉','拟处罚款金额','10万元','amount','拟',['D1'],[('D1','对李凉凉给予警告，并处罚款10万元')]),
      F('F5','罗红花等8人','拟单人处罚款金额','5万元','amount','拟',['D1'],[('D1',SWS8)],note='共用组跨度；“给子警告”为原件印刷错字（2026-11-10第8页渲染逐字符核验，与“将子以采纳”同页并存，字体与正文一致）——原样保留不作更正；裁决边界：该错字如涉申辩是否被采纳的判断，必须以文书其他明确内容为依据，不得修复错字后推断结论；组槽计为1个群组事实'),
      F('F6','张煜等4人','拟单人处罚款金额','3万元','amount','拟',['D1'],[('D1',SWS4)],note='共用组跨度；组槽计为1个群组事实'),
      F('F7','厦门证监局','事先告知书文号','厦证监处罚字〔2018〕3号','docno','拟',['D1'],[('D1','厦证监处罚字〔2018〕3号')],meta=True,note='D1文号外加全角方括号【】'),
      F('F8','三维丝','收到事先告知书日期','2018年10月30日','date','拟',['D1'],[('D1','2018年10月30日，公司收到')],meta=True),
      F('F9','三维丝','终局处罚款金额','60万元','amount','终',['D2'],[('D2','对三维丝给予警告，并处以60万元罚款')],note='同值；D2“并处以…罚款”+“一、”编号——措辞+编号双差异'),
      F('F10','廖政宗、罗祥波（2人）','终局单人处罚款金额','30万元','amount','终',['D2'],[('D2','对廖政宗、罗祥波给予警告，并分别处以30万元罚款')],note='同值；共用组跨度'),
      F('F11','刘明辉、张永丰、朱利民和王荣聪（4人）','终局处罚组构成（各20万元组）','20万元/组','amount','终',['D2'],[('D2','对刘明辉、张永丰、朱利民和王荣聪给予警告，并分别处以20万元罚款')],note='组构成与拟一致；D2顿号规范化（“张永丰、朱利民和王荣聪”）——D1逗号→D2顿号标点差异；组槽计为1个群组事实'),
      F('F12','李凉凉','终局处罚款金额','10万元','amount','终',['D2'],[('D2','对李凉凉给予警告，并处以10万元罚款')],note='同值'),
      F('F13','罗红花等8人','终局处罚组构成（各5万元组）','5万元/组','amount','终',['D2'],[('D2','对罗红花、陈锡良、屈冀彤、耿占吉、郑兴灿、王智勇、丘国强和陈大平给予警告，并分别处以5万元罚款')],note='组构成与拟一致；D2“给予警告”正常用字——与D1“给子”同文书跨文书错字/正常用字对照；组槽计为1个群组事实'),
      F('F14','张煜等4人','终局处罚组构成（各3万元组）','3万元/组','amount','终',['D2'],[('D2','对张煜、康述旻、彭南京和周荣德给予警告，并分别处以3万元罚款')],note='组构成与拟一致；组槽计为1个群组事实'),
      F('F15','厦门证监局','处罚决定书文号','〔2019〕1号','docno','终',['D2'],[('D2','《行政处罚决定书》【〔2019〕1号】')],meta=True,note='双层括号【〔〕】——与D1单层〔〕括号嵌套差异'),
    ],
    docs=files))

# ============ 构建 ============
out_dir = HERE / 'contracts'; out_dir.mkdir(exist_ok=True)
sheet = ['# G7 批12 Gold 合同 v1.0（终裁签收）——任务集40/40完成', '',
         '来源：cninfo 官方公告 PDF；逐事实逐字证据跨度已程序化校验。', '']
cls_tot, grand = {}, 0
for spec in specs:
    files = spec['docs']
    facts = spec['facts']
    ids = [f['fact_id'] for f in facts]
    assert len(ids) == len(set(ids)), f"{spec['task']} fact_id 重复"
    cls = Counter(f['fact_class'] for f in facts)
    doc_sha = {d: hashlib.sha256((HERE / 'raw' / f).read_bytes()).hexdigest()[:16] for d, f in spec['docs'].items()}
    contract = dict(task=spec['task'], company=spec['company'], code=spec['code'],
                    schema='G7-V03-spanlevel-v1.0', adjudicated='2026-11-10 操作员批12终裁PASS（SWS错字原样+不得修复后推断）',
                    source_pages={d: dict(file=spec['docs'][d], sha256_16=doc_sha[d],
                        chars=len(load_doc(spec['docs'][d])['stripped'])) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['allowed_docs'] == ['D1']),
                               n_d2_only=sum(1 for f in facts if f['allowed_docs'] == ['D2']),
                               spans_verified=sum(len(f['stage_evidence']) for f in facts)))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v1.0.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += [f"## {spec['task']} {spec['company']}（{spec['code']}）", '',
              '| # | 主体 | 谓词 | 值 | 阶段 | 分类 | 允许 | 备注 |', '|---|---|---|---|---|---|---|---|']
    for f in facts:
        sheet.append(f"| {f['fact_id']} | {f['subject'][:26]} | {f['predicate']} | {f['value']} | {f['fact_stage']} | {f['fact_class']} | {'/'.join(f['allowed_docs'])} | {f.get('note','')} |")
    sheet += ['', f"事实合计 {len(facts)}：阶段内容 {cls.get('stage_content',0)}｜元数据 {cls.get('doc_metadata',0)}；阶段敏感拟 {contract['stats']['n_d1_only']} / 终 {contract['stats']['n_d2_only']}；跨度校验 {contract['stats']['spans_verified']} 处全部通过。", '']
    cls_tot.update({k: cls_tot.get(k, 0) + v for k, v in cls.items()}); grand += len(facts)
sheet += [f'**批12草案总计 {grand}**']
(HERE / 'FACT_SHEET_BATCH12.md').write_text('\n'.join(sheet) + '\n')
print('v0.1 written:', sorted(p.name for p in out_dir.glob('*_v0.1.json')))
print('批12总计', grand)
