"""Build TASK_CONTRACT_SC_E1_v1_1.json from v1 (zero calls). v1 is read, never written.

Gold values are copied unchanged. Changes: four non-verbatim evidence quotes replaced by source
spans, source_evidence stored as a JSON list (v1 stored a Python repr string), per-slot citation
whitelist and grounding rule frozen in the contract, positioning and independence corrected,
P2-draft-to-contract slot mapping recorded.
"""
import ast
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import sc_e1_scorer as SC  # noqa: E402

PKG = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/SC_E1_ZHANGZIDAO')
V1 = PKG / 'TASK_CONTRACT_SC_E1_v1.json'
V1_1 = PKG / 'TASK_CONTRACT_SC_E1_v1_1.json'
V1_SHA256 = 'dcbcd22143772c22'

# (doc, start text, end text): the replacement span runs from start through end in the source.
SPANS = {
    'F12': ('D1', '2018 年 2 月 9 日，獐子岛集团股份有限公司（以下简称“公司”）', '连调查字[2018]001 号）'),
    'F13': ('D1', '2019 年 7 月 9 日，公司及相关人员收到中国证监会下发的', '（处罚字【2019】95 号）'),
    'F14': ('D2', '2020 年 6 月 23 日，獐子岛集团股份有限公司（以下简称“公司”）', '决定书》【2020】29 号'),
}
PENALTY_LINE_STARTS = ['对獐子岛集团股份有限公司给予警告', '对吴厚刚、梁峻给予警告', '对孙福君、勾荣给予警告',
                       '对邹建、王涛、罗伟新', '对于成家、赵颖、石敬江给予警告']

GROUNDING = {
    'F1': ('amount', '獐子岛', '罚款', ['D2']),
    'F2': ('amount', '吴厚刚', '罚款', ['D2']),
    'F3': ('amount', '梁峻', '罚款', ['D2']),
    'F4': ('amount', '孙福君', '罚款', ['D2']),
    'F5': ('amount', '勾荣', '罚款', ['D2']),
    'F6': ('amount', '邹建', '罚款', ['D2']),
    'F7': ('amount', '于成家', '罚款', ['D2']),
    'F8': ('amount', None, '营业成本', ['D2']),
    'F9': ('amount', None, '营业外支出', ['D2']),
    'F10': ('amount', None, '虚增利润', ['D2']),
    'F11': ('amount', None, '利润总额', ['D2']),
    'F12': ('date', None, '调查通知书', ['D1', 'D2']),
    'F13': ('date', None, '告知书', ['D1', 'D2']),
    'F14': ('date', None, '决定书', ['D2']),
    'F15': ('doc_number', None, '行政处罚决定书', ['D2']),
    'F16': ('doc_number', None, '市场禁入决定书', ['D2']),
    'F17': ('doc_number', None, '告知书', ['D1', 'D2']),
    'F18': ('title_set', '吴厚刚', None, ['D2']),
    'F19': ('penalty_line_sum', None, '万元罚款', ['D2']),
    'F20': ('negation', None, '强制退市', ['D1', 'D2']),
}

P2_DRAFT = [
    ('F1', '獐子岛集团 罚款金额 60万元', 'F1', 'same'),
    ('F2', '吴厚刚 罚款金额 30万元', 'F2', 'same'),
    ('F3', '梁峻 罚款金额 30万元', 'F3', 'same'),
    ('F4', '孙福君 罚款金额 20万元', 'F4', 'same'),
    ('F5', '勾荣 罚款金额 20万元', 'F5', 'same'),
    ('F6', '邹建等8人 单人罚款金额 4万元', 'F6', 'same'),
    ('F7', '于成家等3人 单人罚款金额 3万元', 'F7', 'same'),
    ('F8', '獐子岛集团 立案调查日期 2018-02-09', 'F12', 'renumbered; predicate now 立案调查通知收到日期'),
    ('F9', '獐子岛集团 告知书收到日期 2019-07-09', 'F13', 'renumbered'),
    ('F10', '獐子岛集团 处罚决定书收到日期 2020-06-23', 'F14', 'renumbered'),
    ('F11', '处罚决定书 文号 【2020】29号', 'F15', 'renumbered'),
    ('F12', '市场禁入决定书 文号 【2020】9号', 'F16', 'renumbered'),
    ('F13', '獐子岛集团 违法行为类型 信息披露违法违规', None, 'dropped'),
    ('F14', '獐子岛集团 涉及业务 底播虾夷扇贝', None, 'dropped'),
    ('F15', '告知书 文号 处罚字【2019】95号', 'F17', 'renumbered'),
    ('F16', '吴厚刚 职务 董事长、总裁', 'F18', 'renumbered'),
    ('F17', '调查通知书 文号 连调查字【2018】001号', None, 'dropped'),
    ('F18', '獐子岛集团 是否触及重大违法强制退市 否', 'F20', 'renumbered'),
    ('F19', '全部当事人 罚款合计 246万元', 'F19', 'value corrected 246 -> 201 (see F19 verification)'),
    ('F20', '告知书→决定书 罚款金额是否调整 是（部分人员调整）', None, 'dropped'),
]
ADDED_IN_V1 = ['F8', 'F9', 'F10', 'F11']

PENALTY_LINE_RE = re.compile(r'[一二三四五六七八]、对([^;。]*?)给予警告,?并(?:分别)?处以(\d+)万元罚款')


def display(raw):
    """Source span -> quote: drop PDF page-number markers and every whitespace run that contains a
    line break (PDF line wraps split words); keep in-line spaces as the source prints them."""
    t = re.sub(r'\s*\d{1,3}\s*\x0c', '', raw)
    t = re.sub(r'[ \t]*[\r\n][\s]*', '', t)
    return t.strip()


def find_span(text, start, end):
    norm = lambda s: re.sub(r'\s+', '', s)
    ns, ne = norm(start), norm(end)
    starts = [i for i in range(len(text)) if not text[i].isspace() and norm(text[i:i + 3 * len(start)]).startswith(ns)]
    if len(starts) != 1:
        raise ValueError(f'start anchor matched {len(starts)} times: {start}')
    i = starts[0]
    j = i
    while not norm(text[i:j]).endswith(ne):
        j += 1
        if j > len(text):
            raise ValueError(f'end anchor not found: {end}')
    return i, display(text[i:j])


def penalty_table(norm_doc):
    return [(names.split('、'), int(amount)) for names, amount in PENALTY_LINE_RE.findall(norm_doc)]


def build():
    raw_bytes = V1.read_bytes()
    assert hashlib.sha256(raw_bytes).hexdigest().startswith(V1_SHA256), 'v1 contract changed'
    v1 = json.loads(raw_bytes)
    ct = copy.deepcopy(v1)
    pages = {d: v['pages']['1']['text'] for d, v in v1['source_pages'].items()}
    idx = {d: SC.norm_doc(t) for d, t in pages.items()}
    raw_sha = {d: v['raw_sha256'] for d, v in v1['source_pages'].items()}

    log = []
    for f in ct['required_facts']:
        fid = f['fact_id']
        ev = f['source_evidence']
        ev = ast.literal_eval(ev) if isinstance(ev, str) else ev
        f['source_evidence'] = ev
        if fid in SPANS:
            doc, start, end = SPANS[fid]
            off, quote = find_span(pages[doc], start, end)
            old = ev[0]['quote']
            ev[0] = dict(doc_id=doc, page=1, quote=quote, char_offset=off, raw_sha256=raw_sha[doc])
            log.append(dict(fact_id=fid, change='evidence quote replaced by verbatim source span',
                            old_quote=old, new_quote=quote, char_offset=off))
        if fid == 'F19':
            old = ev[0]['quote']
            lines = []
            for head in PENALTY_LINE_STARTS:
                off, quote = find_span(pages['D2'], head, '万元罚款')
                lines.append(dict(doc_id='D2', page=1, quote=quote, char_offset=off, raw_sha256=raw_sha['D2']))
            f['source_evidence'] = lines
            final, proposed = penalty_table(idx['D2']), penalty_table(idx['D1'])
            f['verification'] = dict(
                final_lines_D2=[['、'.join(n), a] for n, a in final],
                parties_final_D2=sum(len(n) for n, _ in final),
                sum_final_D2=sum(len(n) * a for n, a in final),
                proposed_lines_D1=[['、'.join(n), a] for n, a in proposed],
                parties_proposed_D1=sum(len(n) for n, _ in proposed),
                sum_proposed_D1=sum(len(n) * a for n, a in proposed),
                p2_draft_value=246,
                note='246 is derivable from neither document; 201 is the D2 final total, 344 the D1 proposed total.')
            log.append(dict(fact_id='F19', change="evidence '一至五项处罚决定' does not occur in D2; replaced by the "
                                                  'five D2 penalty lines the derivation sums', old_quote=old))
        rule, subject, predicate, docs = GROUNDING[fid]
        f['allowed_citation_docs'] = docs
        f['grounding'] = dict(rule=rule, subject_anchor=subject, predicate_anchor=predicate)
        for e in f['source_evidence']:
            e['verbatim'] = SC.norm_text(e['quote']) in idx[e['doc_id']]

    ct['contract_version'] = 'v1.1'
    ct['supersedes'] = dict(path=str(V1), sha256=hashlib.sha256(raw_bytes).hexdigest(),
                            note='v1 is kept unchanged; scoring code refuses v1.')
    ct['positioning'] = ('开发污染任务上的机制验证与管线验证，不属于独立确认性实验。'
                         '文书与开发任务 ZHANGZIDAO 相同；P2 写入前台账已有 94 次相关调用。')
    ct['provenance'] = dict(v1['provenance'],
                            independence='NOT INDEPENDENT. Same documents as development task ZHANGZIDAO '
                                         '(sentence-level identity 84/84 D1, 290/290 D2); >=110 ledger calls on '
                                         'this event, 94 before the P2 pre-registration. v1 claim withdrawn.',
                            gold_status='MVR_v1.1: values unchanged from v1; every evidence quote verified as a '
                                        'whitespace-normalized substring of its source document.')
    ct['scoring'] = dict(
        primary='Q_all = TP / N, N = number of required_facts (20)',
        auxiliary=['Q_terminal = 0.5*F + 0.3*E + 0.2*C (P2 section 4; F and E over asserted slots)',
                   'E_literal = asserted slots with a correct value and a verbatim quote in a contract document '
                   '/ asserted slots (P2 literal evidence caliber)'],
        tp='value correct (rule below) AND cited doc in allowed_citation_docs AND quote verbatim in that doc '
           '(>= 6 chars) AND quote grounds the slot (subject_anchor, predicate_anchor and rule-specific value '
           'evidence all present)',
        verbatim='NFKC, all whitespace removed, PDF page-number/form-feed markers removed, then substring test',
        rules=dict(amount='number and unit equal (scorer_qp1_v2 caliber); the quote contains the gold number+unit',
                   date='calendar date equal; the quote contains it as Y年M月D日',
                   doc_number='(year, number) tuple equal; the quote contains the tuple',
                   title_set='every gold title present (a 副-prefixed title does not count); the quote too',
                   negation='the value denies; the quote contains a denial phrase',
                   penalty_line_sum='number and unit equal; the quote is a penalty line (digits followed by 万元罚款)'),
        frozen_before_calls=True, arm_blind=True)
    ct['p2_draft_mapping'] = dict(
        rows=[dict(p2_slot=p, p2_definition=d, v1_1_slot=v, change=c) for p, d, v, c in P2_DRAFT],
        added_in_contract=ADDED_IN_V1,
        timing='P2 draft table written 2026-11-05 12:41; contract v1 written 2026-11-05 14:12.')
    ct['revision_log'] = [
        dict(version='v1.1', date='2026-11-06', basis='operator decision 2026-11-06 (SC-E1.1 Stage A GO, conditional)',
             changes=log + [
                 dict(change='source_evidence converted from a Python repr string to a JSON list (all 20 slots); '
                             'content unchanged except the rows above'),
                 dict(change='allowed_citation_docs and grounding added to every slot (frozen before any call)'),
                 dict(change='positioning, independence and gold_status corrected; scoring and P2 mapping recorded'),
                 dict(change='no Gold value changed', checked=True)])]
    return v1, ct


def main():
    v1, ct = build()
    assert [f['value'] for f in ct['required_facts']] == [f['value'] for f in v1['required_facts']]
    assert all(e['verbatim'] for f in ct['required_facts'] for e in f['source_evidence'])
    payload = json.dumps(ct, ensure_ascii=False, indent=1) + '\n'
    if V1_1.exists() and V1_1.read_text('utf-8') != payload:
        raise SystemExit(f'REFUSED: {V1_1} exists with different content; versions are never overwritten')
    V1_1.write_text(payload, 'utf-8')
    print('v1.1 sha256:', hashlib.sha256(V1_1.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
