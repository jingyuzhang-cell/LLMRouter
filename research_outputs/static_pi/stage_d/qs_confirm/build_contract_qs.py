#!/usr/bin/env python3
"""Build the Qianshan (300216) Gold contract DRAFT from the two source documents (zero model calls).

Every value is read from the documents by a fixed rule and every evidence quote is located verbatim
(whitespace-insensitive, PDF page markers removed) in its source text, with its raw character offset.
The contract is a DRAFT until the operator has reviewed it; its sha256 is pinned only after approval.
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/QS_300216')
CONTRACT = OUT / 'TASK_CONTRACT_QS_v1_DRAFT.json'
DOCS = {'D1': ('300216_notice_1575290526000.pdf', '事先告知书公告（2019-12-02，公告编号2019-129）'),
        'D2': ('300216_decision_1596729600000.pdf', '行政处罚决定书及市场禁入决定书公告（2020-08-07，公告编号2020-079）')}
PAGE_MARK = re.compile(r'\s*\d{1,3}\s*\x0c')
# Applied to NFKC-normalized text, where full-width punctuation has become ASCII.
PENALTY_LINE = re.compile(r'[一二三四五六七八九十]、对([^。;]{1,200}?)(?:责令改正,)?给予警告,并(?:分别)?处以(\d+)万元的罚款')
PROPOSED_LINE = re.compile(r'\([一二三四五六七八九十]\)对([^。;]{1,300}?)(?:责令改正,)?给予警告,并(?:分别)?处以(\d+)万元罚款')

# fact_id, subject, predicate, unit, value_kind, value, critical, allowed docs, rule, subject anchor, predicate anchor, evidence quote(s)
SLOTS = [
    ('F1', '湖南千山制药机械股份有限公司', '行政处罚罚款金额', '万元', 'number', '60', True, ['D2'], 'amount', '千山', '罚款',
     [('D2', '一、对湖南千山制药机械股份有限公司责令改正，给予警告，并处以60万元的罚款')]),
    ('F2', '刘祥华', '行政处罚罚款金额', '万元', 'number', '30', True, ['D2'], 'amount', '刘祥华', '罚款',
     [('D2', '二、对刘祥华、刘华山给予警告，并分别处以30万元的罚款')]),
    ('F3', '刘华山', '行政处罚罚款金额', '万元', 'number', '30', True, ['D2'], 'amount', '刘华山', '罚款',
     [('D2', '二、对刘祥华、刘华山给予警告，并分别处以30万元的罚款')]),
    ('F4', '周大连', '行政处罚罚款金额', '万元', 'number', '15', True, ['D2'], 'amount', '周大连', '罚款',
     [('D2', '三、对周大连给予警告，并处以15万元的罚款')]),
    ('F5', '姜纯', '行政处罚罚款金额', '万元', 'number', '10', True, ['D2'], 'amount', '姜纯', '罚款',
     [('D2', '四、对姜纯给予警告，并处以10万元的罚款')]),
    ('F6', '钟波等7人', '单人行政处罚罚款金额', '万元', 'number', '4', False, ['D2'], 'amount', '钟波', '罚款',
     [('D2', '五、对钟波、刘燕、邓铁山、王国华、郑国胜、彭勋德、黄盛秋给予警告，并分别处以4万元的罚款')]),
    ('F7', '付慧龙等2人', '单人行政处罚罚款金额', '万元', 'number', '3', False, ['D2'], 'amount', '付慧龙', '罚款',
     [('D2', '六、对付慧龙、金杰给予警告，并分别处以3万元的罚款')]),
    ('F8', '千山药机2016年度', '虚增在建工程', '万元', 'number', '9166.23', True, ['D2'], 'amount', None, '在建工程',
     [('D2', '千山药机2016年年度报告以上述方式虚增在建工程9,166.23万元')]),
    ('F9', '千山药机2016年度（太平洋证券保理业务）', '虚减应收账款', '万元', 'number', '11656.10', True, ['D2'], 'amount', None, '应收账款',
     [('D2', '导致2016年度虚减应收账款11656.10万元')]),
    ('F10', '千山药机2016年度（华冠花炮烟花生产线）', '虚增收入', '万元', 'number', '22435.90', True, ['D2'], 'amount', None, '虚增收入',
     [('D2', '上述行为导致公司2016年虚增收入22,435.90万元')]),
    ('F11', '刘祥华', '持股比例', '%', 'number', '14.83', False, ['D1', 'D2'], 'amount', '刘祥华', '持股比例',
     [('D2', '刘祥华担任千山药机董事长、法定代表人、总经理，是公司的实际控制人之一，截至2017年12月30日，持有公司股票5,358.35万股，持股比例达14.83%')]),
    ('F12', '千山药机', '调查通知书收到日期', None, 'date', '2018-01-16', True, ['D1'], 'date', None, '调查通知书',
     [('D1', '湖南千山制药机械股份有限公司（以下简称“公司”、“千山药机”）于2018年1月16日收到中国证券监督管理委员会下发的《调查通知书》（编号：湘稽调查字0528号）')]),
    ('F13', '千山药机', '事先告知书收到日期', None, 'date', '2019-11-29', True, ['D1'], 'date', None, '告知书',
     [('D1', '2019年11月29日，湖南千山制药机械股份有限公司收到中国证监会下发的（处罚字[2019]149号）《中国证券监督管理委员会行政处罚及市场禁入事先告知书》')]),
    ('F14', '千山药机及相关当事人', '行政处罚决定书收到日期', None, 'date', '2020-08-06', True, ['D2'], 'date', None, '决定书',
     [('D2', '及相关当事人于2020年8月6日收到中国证券监督管理委员会（以下简称“中国证监会”）对公司及相关当事人的《行政处罚决定书》（[2020]32号）')]),
    ('F15', '行政处罚决定书', '文号', None, 'text', '[2020]32号', False, ['D2'], 'doc_number', None, '行政处罚决定书',
     [('D2', '对公司及相关当事人的《行政处罚决定书》（[2020]32号）及《市场禁入决定书》([2020]10号)')]),
    ('F16', '市场禁入决定书', '文号', None, 'text', '[2020]10号', False, ['D2'], 'doc_number', None, '市场禁入决定书',
     [('D2', '对公司及相关当事人的《行政处罚决定书》（[2020]32号）及《市场禁入决定书》([2020]10号)')]),
    ('F17', '事先告知书', '文号', None, 'text', '处罚字[2019]149号', False, ['D1'], 'doc_number', None, '告知书',
     [('D1', '近日，公司及相关当事人收到中国证券监督管理委员会下发的《行政处罚及市场禁入事先告知书》（编号：处罚字[2019]149号）')]),
    ('F18', '刘祥华', '职务', None, 'text', '董事长、总经理', True, ['D1', 'D2'], 'title_set', '刘祥华', None,
     [('D2', '刘祥华担任千山药机董事长、法定代表人、总经理，是公司的实际控制人之一')]),
    ('F19', '全部当事人', '罚款合计', '万元', 'number', '179', False, ['D2'], 'penalty_line_sum', None, '罚款',
     [('D2', '一、对湖南千山制药机械股份有限公司责令改正，给予警告，并处以60万元的罚款'),
      ('D2', '二、对刘祥华、刘华山给予警告，并分别处以30万元的罚款'),
      ('D2', '三、对周大连给予警告，并处以15万元的罚款'),
      ('D2', '四、对姜纯给予警告，并处以10万元的罚款'),
      ('D2', '五、对钟波、刘燕、邓铁山、王国华、郑国胜、彭勋德、黄盛秋给予警告，并分别处以4万元的罚款'),
      ('D2', '六、对付慧龙、金杰给予警告，并分别处以3万元的罚款')]),
    ('F20', '千山药机（依据《事先告知书》认定的事实）', '是否触及重大违法强制退市情形', None, 'text', '是', False, ['D1'], 'affirmation',
     None, '强制退市',
     [('D1', '根据《事先告知书》认定的事实，公司2015-2018年连续四年净利润实际为负，触及《深圳证券交易所上市公司重大违法强制退市实施办法》第四条第（三）项规定的重大违法强制退市情形')]),
]

QUESTION = ('千山药机（300216）信息披露违法违规案：证监会最终对公司及各责任人员分别处以多少罚款？全部当事人罚款合计多少？'
            '2016年度虚增在建工程、虚减应收账款（太平洋证券保理业务）、虚增收入（华冠花炮烟花生产线）各是多少？'
            '刘祥华的持股比例与职务？调查通知书、事先告知书、行政处罚决定书各于何日收到？三份文书的文号？'
            '依据《事先告知书》认定的事实，是否触及重大违法强制退市情形？')


def norm(x):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))


def locate(text, quote):
    """Raw (start, end) of the unique whitespace-insensitive occurrence closest to the document start."""
    clean = PAGE_MARK.sub(lambda m: ' ' * len(m.group(0)), text)
    keep = [i for i, ch in enumerate(clean) if not ch.isspace()]
    flat = ''.join(clean[i] for i in keep)
    nf = unicodedata.normalize('NFKC', flat)
    if len(nf) != len(flat):
        raise ValueError('NFKC changed length; offsets would drift')
    q = norm(quote)
    pos = nf.find(q)
    if pos < 0:
        raise ValueError(f'not verbatim: {quote}')
    return keep[pos], keep[pos + len(q) - 1] + 1, nf.count(q)


def penalty_lines(flat, pattern):
    rows = []
    for names, amount in pattern.findall(flat):
        parties = [p for p in names.split('、') if p]
        rows.append(dict(parties=parties, amount_wan=int(amount)))
    return rows


def build():
    texts, sources = {}, {}
    for d, (pdf, title) in DOCS.items():
        pdf_path, txt_path = RAW / pdf, RAW / (pdf + '.txt')
        meta = json.loads((RAW / (pdf + '.meta.json')).read_text('utf-8'))
        assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == meta['sha256']
        texts[d] = txt_path.read_text('utf-8')
        sources[d] = dict(title=title, url=meta['url'], retrieved_at=meta['retrieved_at'], pdf_sha256=meta['sha256'],
                          text_sha256=hashlib.sha256(texts[d].encode()).hexdigest(), text_tool='pdftotext 22.02.0 -layout')
    flat = {d: norm(PAGE_MARK.sub('', t)) for d, t in texts.items()}

    final = penalty_lines(flat['D2'], PENALTY_LINE)
    proposed = penalty_lines(flat['D1'], PROPOSED_LINE)
    total = sum(len(r['parties']) * r['amount_wan'] for r in final)
    proposed_total = sum(len(r['parties']) * r['amount_wan'] for r in proposed)
    assert total == 179 and proposed_total == 320, (total, proposed_total)

    facts = []
    for fid, subj, pred, unit, kind, value, crit, allowed, rule, s_anchor, p_anchor, quotes in SLOTS:
        ev = []
        for d, q in quotes:
            start, end, count = locate(texts[d], q)
            ev.append(dict(doc_id=d, page=1, quote=q, char_start=start, char_end=end, occurrences=count,
                           pdf_sha256=sources[d]['pdf_sha256']))
        f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text', critical=crit,
                 evidence_required=True, value_kind=kind, subject=subj, predicate=pred, value=value,
                 allowed_citation_docs=allowed, grounding=dict(rule=rule, subject_anchor=s_anchor, predicate_anchor=p_anchor),
                 source_evidence=ev)
        if unit:
            f['unit'] = unit
        if fid == 'F19':
            f['derivation'] = dict(rule='sum over the D2 penalty lines of (number of parties x amount per party)',
                                   lines=[[('、'.join(r['parties'])), r['amount_wan']] for r in final],
                                   computation='60 + 30×2 + 15 + 10 + 4×7 + 3×2 = 179', parties=sum(len(r['parties']) for r in final))
        facts.append(f)

    final_amount = {p: r['amount_wan'] for r in final for p in r['parties']}
    final_amount['千山药机'] = final_amount.pop('湖南千山制药机械股份有限公司')
    correspondence = []
    for r in proposed:
        for p in r['parties']:
            fin = final_amount.get(p)
            correspondence.append(dict(party=p, proposed_wan=r['amount_wan'], final_wan=fin,
                                       change='unchanged' if fin == r['amount_wan'] else ('not penalized in D2' if fin is None else 'adjusted')))
    assert len(correspondence) == 25 and sum(c['final_wan'] is not None for c in correspondence) == 14

    contract = dict(
        task_id='QS_300216_PENALTY_CONFIRM', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
        positioning='独立确认任务（操作员 2026-11-06 选定）。Gold 由规则从原文构建，未经操作员审阅确认前不得调用任何模型。',
        question=QUESTION, cutoff='2020-08-07', source_documents=sources,
        source_pages={d: dict(raw_sha256=sources[d]['pdf_sha256'], pages={'1': dict(text=texts[d], page_sha256=sources[d]['text_sha256'])})
                      for d in texts},
        required_facts=facts, critical_fact_ids=[f['fact_id'] for f in facts if f['critical']], unknown_items=[],
        entity_correspondence=dict(
            proposed_lines_D1=[['、'.join(r['parties']), r['amount_wan']] for r in proposed],
            final_lines_D2=[['、'.join(r['parties']), r['amount_wan']] for r in final],
            parties=correspondence, proposed_total_wan=proposed_total, final_total_wan=total,
            aliases=[dict(canonical='湖南千山制药机械股份有限公司', variants=['千山药机', '公司'], where='D1 uses 千山药机 in the penalty line; D2 uses the full name'),
                     dict(canonical='刘祥华', variants=['刘样华'], where='D2 typo, 3 occurrences; never in a penalty line')],
            adjustment_reasons=[dict(party='刘祥华', proposed='90万元（直接负责的主管人员30万 + 实际控制人60万）', final='30万元',
                                     source='D2: 采纳其申辩意见不再适用《证券法》第一百九十三条第三款')]),
        known_source_issues=[
            dict(issue='D2 states 2015年虚增收入8,914.36万元 once, but 8,974.36万元 in the same section and in the market-ban decision; D1 gives 89,743,589.76元', handling='not a scored slot'),
            dict(issue='D1 states amounts in 元, D2 in 万元 (same quantities, D2 rounded to 2 decimals)', handling='scorer converts units; claims finer than the gold unit are compared at the gold precision'),
            dict(issue='D2 omits D1 overall profit totals and percentages (2015: 79,505,270.96元, 95.76%; 2016: 357,331,482.4元, 160.05%)', handling='not scored'),
            dict(issue='D2 text-layer typos: 刘样华, 于山药机, 上诲中成, 租货, 天字, 合同全额, 行致处罚', handling='recorded; none sits in a Gold evidence quote'),
        ],
        scoring=dict(primary='Q_all = TP / N (N = 20)', safety='error_rate (None when nothing asserted), error_burden, coverage, abstention_rate, silent_omission_rate; gate error_rate <= baseline + 5pp, UNDEFINED never passes',
                     auxiliary=['Q_terminal (P2 formula)', 'E_literal'], scorer='qs_scorer.py (contract-driven; arm-blind)'),
        provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext 文本层；Gold 值与证据跨度由本脚本按规则从原文读取',
                        model_calls=0, independence='working tree, git HEAD and full git history: zero hits on code, names, all 25 parties, case numbers and event entities (INDEPENDENT_CASE_REPORT.md, QS audit)'),
    )
    return contract


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build(), ensure_ascii=False, indent=1) + '\n'
    CONTRACT.write_text(payload, 'utf-8')
    print('draft contract sha256:', hashlib.sha256(CONTRACT.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
