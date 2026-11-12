#!/usr/bin/env python3
"""G7 batch-2 Gold contract DRAFTS (v0.1, awaiting operator adjudication), zero model calls.
Same pipeline as adjudicated batch-1 v1.0: span-level annotation, fact_class taxonomy,
UNKNOWN bases, triple traceability (raw page text + raw span + normalized span)."""
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


SHUNTTIAN = dict(
    task='ST_600287', company='江苏舜天股份有限公司', code='600287',
    docs={'D1': '../batch1/raw/shuntian_D1_notice.txt', 'D2': '../batch1/raw/shuntian_D2_csrc.txt'},
    meta_facts={'F8', 'F9', 'F17', 'F18'},
    unknown_basis={'F16': '本任务输入的〔2024〕41号处罚决定书"我会决定"部分仅载罚款事项，未载明市场禁入措施（本文书范围内UNKNOWN，未载明≠未采取）。'
                          '审计备注：另有《市场禁入决定书》〔2024〕10号对高松采取3年证券市场禁入，但不属于本任务输入文书，不得作为作答依据'}, 
    facts=[
        ('F1', '江苏舜天', '拟处罚款金额', '1,000万元', 'amount', '拟', ['D1'],
         [('D1', r'对江苏舜天责令改正，给予警告，并处以 1,000 万元罚款')]),
        ('F2', '高松', '拟处罚款金额', '150万元', 'amount', '拟', ['D1'],
         [('D1', r'对高松给予警告，并处以 150 万元罚款')]),
        ('F3', '桂生春', '拟处罚款金额', '100万元', 'amount', '拟', ['D1'],
         [('D1', r'对桂生春给予警告，并处以 100 万元罚款')]),
        ('F4', '王重人', '拟处罚款金额', '60万元', 'amount', '拟', ['D1'],
         [('D1', r'对王重人、李焱、赵凡给予警告，并分别处以 60 万元罚款')]),
        ('F5', '李焱', '拟处罚款金额', '60万元', 'amount', '拟', ['D1'],
         [('D1', r'对王重人、李焱、赵凡给予警告，并分别处以 60 万元罚款')]),
        ('F6', '赵凡', '拟处罚款金额', '60万元', 'amount', '拟', ['D1'],
         [('D1', r'对王重人、李焱、赵凡给予警告，并分别处以 60 万元罚款')]),
        ('F7', '高松', '拟采取市场禁入措施', '3年证券市场禁入', 'ban', '拟', ['D1'],
         [('D1', r'对高松采取 3 年证券市场禁入措施')]),
        ('F8', '中国证监会', '事先告知书文号', '处罚字〔2023〕37号', 'docno', '拟', ['D1'],
         [('D1', r'处罚字〔2023〕37号')]),
        ('F9', '江苏舜天', '收到事先告知书日期', '2023年6月30日', 'date', '拟', ['D1'],
         [('D1', r'2023年6月30日，公司收到中国证券监督管理委员会出具的《行政处罚及市场禁入事先告知书》')]),
        ('F10', '江苏舜天', '终局处罚款金额', '1,000万元', 'amount', '终', ['D2'],
         [('D2', r'对江苏舜天股份有限公司责令改正,给予警告,并处以1,000万元罚款')]),
        ('F11', '高松', '终局处罚款金额', '150万元', 'amount', '终', ['D2'],
         [('D2', r'对高松给予警告,并处以150万元罚款')]),
        ('F12', '桂生春', '终局处罚款金额', '100万元', 'amount', '终', ['D2'],
         [('D2', r'对桂生春给予警告,并处以100万元罚款')]),
        ('F13', '王重人', '终局处罚款金额', '60万元', 'amount', '终', ['D2'],
         [('D2', r'对王重人、李焱、赵凡给予警告,并分别处以60万元罚款')]),
        ('F14', '李焱', '终局处罚款金额', '60万元', 'amount', '终', ['D2'],
         [('D2', r'对王重人、李焱、赵凡给予警告,并分别处以60万元罚款')]),
        ('F15', '赵凡', '终局处罚款金额', '60万元', 'amount', '终', ['D2'],
         [('D2', r'对王重人、李焱、赵凡给予警告,并分别处以60万元罚款')]),
        ('F16', '高松', '〔2024〕41号处罚决定书所载终局市场禁入措施', 'UNKNOWN', 'ban', '终', ['D2'], []),
        ('F17', '中国证监会', '处罚决定书文号', '〔2024〕41号', 'docno', '终', ['D2'],
         [('D2', r'〔2024〕41号')]),
        ('F18', '中国证监会', '处罚决定书作出日期', '2024年4月24日', 'date', '终', ['D2'],
         [('D2', r'2024年4月24日')]),
        ('F19', '江苏舜天', '2009-2021累计虚增营业收入', '10,333,448,392.98元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增营业收入10,333,448,392.98元'), ('D2', r'虚增营业收入10,333,448,392.98元')]),
        ('F20', '江苏舜天', '2009-2021累计虚增营业成本', '9,398,996,635.72元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增营业成本9,398,996,635.72元'), ('D2', r'虚增营业成本9,398,996,635.72元')]),
        ('F21', '江苏舜天', '2009-2021累计虚增利润总额', '934,451,757.26元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增利润总额934,451,757.26元'), ('D2', r'虚增利润总额934,451,757.26元')]),
        ('F22', '江苏舜天', '2009年年报虚增营业收入', '156,498,376.07元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'2009年年报虚增营业收入156,498,376.07元'), ('D2', r'2009年年报虚增营业收入156,498,376.07元')]),
    ])

JINGLAN = dict(
    task='JL_000711', company='京蓝科技股份有限公司', code='000711',
    docs={'D1': '../batch1/raw/probe_jinglan_notice.txt', 'D2': '../batch1/raw/jinglan_D2_penalty.txt'},
    meta_facts={'F6', 'F7', 'F13', 'F14'},
    facts=[
        ('F1', '京蓝科技', '拟处罚款金额', '400万元', 'amount', '拟', ['D1'],
         [('D1', r'责令京蓝科技股份有限公司改正，给予警告，并处以 400 万元罚款')]),
        ('F2', '杨仁贵', '拟处罚款金额', '200万元', 'amount', '拟', ['D1'],
         [('D1', r'对杨仁贵给予警告，并处以 200 万元罚款')]),
        ('F3', '殷晓东', '拟处罚款金额', '200万元', 'amount', '拟', ['D1'],
         [('D1', r'对殷晓东给予警告，并处以 200 万元罚款')]),
        ('F4', '郝鑫', '拟处罚款金额', '150万元', 'amount', '拟', ['D1'],
         [('D1', r'对郝鑫给予警告，并处以 150 万元罚款')]),
        ('F5', '梁晋', '拟处罚款金额', '100万元', 'amount', '拟', ['D1'],
         [('D1', r'对梁晋给予警告，并处以 100 万元罚款')]),
        ('F6', '中国证监会', '事先告知书文号', '处罚字〔2025〕3号', 'docno', '拟', ['D1'],
         [('D1', r'处罚字〔2025〕3号')]),
        ('F7', '京蓝科技', '收到事先告知书日期', '2025年7月8日', 'date', '拟', ['D1'],
         [('D1', r'2025年7月8日，公司收到中国证监会下发的《行政处罚事先告知书》')]),
        ('F8', '京蓝科技', '终局处罚款金额', '400万元', 'amount', '终', ['D2'],
         [('D2', r'责令京蓝科技股份有限公司改正，给予警告，并处以 400 万元罚款')]),
        ('F9', '杨仁贵', '终局处罚款金额', '200万元', 'amount', '终', ['D2'],
         [('D2', r'对杨仁贵给予警告，并处以 200 万元罚款')]),
        ('F10', '殷晓东', '终局处罚款金额', '200万元', 'amount', '终', ['D2'],
         [('D2', r'对殷晓东给予警告，并处以 200 万元罚款')]),
        ('F11', '郝鑫', '终局处罚款金额', '150万元', 'amount', '终', ['D2'],
         [('D2', r'对郝鑫给予警告，并处以 150 万元罚款')]),
        ('F12', '梁晋', '终局处罚款金额', '100万元', 'amount', '终', ['D2'],
         [('D2', r'对梁晋给予警告，并处以 100 万元罚款')]),
        ('F13', '黑龙江证监局', '行政处罚决定书文号', '〔2025〕2号', 'docno', '终', ['D2'],
         [('D2', r'〔2025〕2号')]),
        ('F14', '京蓝科技', '收到处罚决定书日期', '2025年8月15日', 'date', '终', ['D2'],
         [('D2', r'2025年8月15日，公司收到中国证券监督管理委员会黑龙江监管局下发的《行政处罚决定书》')]),
        ('F15', '京蓝科技', '2020年年报虚增营业收入', '16291.03万元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增营业收入16291.03万元'), ('D2', r'虚增营业收入16291.03万元')]),
        ('F16', '京蓝科技', '2020年年报虚增营业成本', '9654.67万元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增营业成本9654.67万元'), ('D2', r'虚增营业成本9654.67万元')]),
        ('F17', '京蓝科技', '2020年年报虚增利润总额', '6636.37万元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增利润总额6636.37万元'), ('D2', r'虚增利润总额6636.37万元')]),
        ('F18', '京蓝科技', '2020年年报虚增净利润', '5770.75万元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增净利润5770.75万元'), ('D2', r'虚增净利润5770.75万元')]),
    ])

ZHUOJIN = dict(
    task='ZJ_688701', company='浙江卓锦环保科技股份有限公司', code='688701',
    docs={'D1': 'raw/zhuojin_D1_notice.txt', 'D2': 'raw/zhuojin_D2_csrc.txt'},
    meta_facts={'F6', 'F7', 'F13', 'F14'},
    facts=[
        ('F1', '卓锦股份', '拟处罚款金额', '300万元', 'amount', '拟', ['D1'],
         [('D1', r'对浙江卓锦环保科技股份有限公司责令改正，给予警告，并处以300万元罚款')]),
        ('F2', '卓未龙', '拟处罚款金额', '300万元', 'amount', '拟', ['D1'],
         [('D1', r'对卓未龙给予警告，并处以300万元罚款')]),
        ('F3', '姚群英', '拟处罚款金额', '100万元', 'amount', '拟', ['D1'],
         [('D1', r'对姚群英给予警告，并处以100万元罚款')]),
        ('F4', '胡愚', '拟处罚款金额', '50万元', 'amount', '拟', ['D1'],
         [('D1', r'对胡愚、王志宏给予警告，并分别处以50万元罚款')]),
        ('F5', '王志宏', '拟处罚款金额', '50万元', 'amount', '拟', ['D1'],
         [('D1', r'对胡愚、王志宏给予警告，并分别处以50万元罚款')]),
        ('F6', '浙江证监局', '事先告知书文号', '浙处罚字[2023]6号', 'docno', '拟', ['D1'],
         [('D1', r'浙处罚字\[2023\]6号')]),
        ('F7', '卓锦股份', '收到事先告知书日期', '2023年4月28日', 'date', '拟', ['D1'],
         [('D1', r'2023年4月28日收到中国证券监督管理委员会浙江监管局下发的《行政处罚事先告知书》')]),
        ('F8', '卓锦股份', '终局处罚款金额', '300万元', 'amount', '终', ['D2'],
         [('D2', r'对浙江卓锦环保科技股份有限公司责令改正，给予警告，并处以300万元罚款')]),
        ('F9', '卓未龙', '终局处罚款金额', '300万元', 'amount', '终', ['D2'],
         [('D2', r'对卓未龙给予警告，并处以300万元罚款')]),
        ('F10', '姚群英', '终局处罚款金额', '100万元', 'amount', '终', ['D2'],
         [('D2', r'对姚群英给予警告，并处以100万元罚款')]),
        ('F11', '胡愚', '终局处罚款金额', '50万元', 'amount', '终', ['D2'],
         [('D2', r'对胡愚、王志宏给予警告，并分别处以50万元罚款')]),
        ('F12', '王志宏', '终局处罚款金额', '50万元', 'amount', '终', ['D2'],
         [('D2', r'对胡愚、王志宏给予警告，并分别处以50万元罚款')]),
        ('F13', '浙江证监局', '处罚决定书文号', '[2023]16号', 'docno', '终', ['D2'],
         [('D2', r'\[2023\]16号')]),
        ('F14', '浙江证监局', '处罚决定书作出日期', '2023年5月19日', 'date', '终', ['D2'],
         [('D2', r'2023年5月19日')]),
        ('F15', '卓锦股份', '2021年虚减营业成本金额', '27,965,247.68元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚减营业成本27,965,247.68元'), ('D2', r'虚减营业成本27,965,247.68元')]),
        ('F16', '卓锦股份', '2021年虚增利润总额金额', '27,056,697.68元', 'amount', '中性', ['D1', 'D2'],
         [('D1', r'虚增利润总额27,056,697.68元'), ('D2', r'虚增利润总额27,056,697.68元')]),
        ('F17', '胡愚', '文书所载时任职务', '董事会秘书、副总经理', 'text', '中性', ['D1', 'D2'],
         [('D1', r'时任董事会秘书、副总经理胡愚'), ('D2', r'时任董事会秘书、副总经理胡愚')]),
    ])

out_dir = HERE / 'contracts'; out_dir.mkdir(exist_ok=True)
sheet = ['# G7 批2 Gold 合同 v1.0（操作员裁决后定稿：0 DROP；舜天F16限定输入文书范围并附〔2024〕10号审计备注）', '',
         '管线与批1 v1.0 一致（跨度级标注/分类/UNKNOWN依据/三套可追溯）。', '']
totals = Counter()
for spec in (SHUNTTIAN, JINGLAN, ZHUOJIN):
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
                    schema='G7-V03-spanlevel-v1.0', adjudicated='2026-11-10 操作员批2裁决（0 DROP; 舜天F16限定文书范围+审计备注）',
                    source_pages={d: dict(pages={'1': docs[d]['raw']}, normalized=docs[d]['stripped'],
                                          raw_sha256=doc_sha[d], file=spec['docs'][d]) for d in spec['docs']},
                    required_facts=facts,
                    stats=dict(n_facts=len(facts), **{f'n_{k}': v for k, v in cls.items()},
                               n_d1_only=sum(1 for f in facts if f['fact_stage'] == '拟' and f['fact_class'] != 'doc_metadata'),
                               n_d2_only=sum(1 for f in facts if f['fact_stage'] == '终' and f['fact_class'] != 'doc_metadata')))
    (out_dir / f"TASK_CONTRACT_{spec['task']}_v1.0.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1))
    sheet += ['', f"合计 {len(facts)}：阶段内容 {cls['stage_content']}｜UNKNOWN {cls['unknown_boundary']}｜元数据 {cls['doc_metadata']}｜背景 {cls['background']}", '']
sheet += [f"**批2总计 {sum(totals.values())}：阶段内容 {totals['stage_content']}｜UNKNOWN {totals['unknown_boundary']}｜元数据 {totals['doc_metadata']}｜背景 {totals['background']}**"]
(HERE / 'FACT_SHEET_BATCH2_V1.md').write_text('\n'.join(sheet) + '\n')
print('batch-2 drafts written:', sorted(p.name for p in out_dir.glob('*.json')))
print('批2分类总计:', dict(totals))
