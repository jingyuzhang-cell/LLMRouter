#!/usr/bin/env python3
"""P2-C batch 3 Gold contract builder: *ST三维 / 金刚玻璃 / *ST佳电 / 文化长城 / ST汇洲.

Same schema / verbatim self-check as batch 2. Semantics per operator batch-2 ruling:
  - party absent from D2  -> "D2未再载明对应处罚" (not "撤销", never 0)
  - D2 silent on market ban -> final ban UNKNOWN (not "未采取")
  - no explicit receipt date -> UNKNOWN or an explicitly-named disclosure-date slot
  - D1 wording that does not fix a per-person amount -> UNKNOWN, never back-filled from D2
"""
import hashlib, json, re, sys, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
NOT_RESTATED = 'D2未再载明对应处罚（D2全文未出现且未作说明；不认定为法律意义上的撤销，终罚不计为0）'
BAN_UNKNOWN = 'D2为《行政处罚决定书》公告，未载市场禁入决定；池内无单独市场禁入决定书，终局是否采取无法由D1/D2确认'

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))


class Task:
    def __init__(self, d1f, d2f):
        self.d1f, self.d2f = d1f, d2f
        self.D = {'D1': (RAW / d1f).read_text('utf-8'), 'D2': (RAW / d2f).read_text('utf-8')}
        self.N = {k: norm(v) for k, v in self.D.items()}
        self.M = {k: json.loads((RAW / f.replace('.txt', '.meta.json')).read_text())
                  for k, f in (('D1', d1f), ('D2', d2f))}
        self.F, self.unknown = [], []

    def ev(self, doc, quote):
        if norm(quote) not in self.N[doc]:
            raise ValueError(f'NOT VERBATIM in {doc} ({self.d1f if doc=="D1" else self.d2f}): {quote[:70]}')
        return [dict(doc_id=doc, page=1, quote=quote, pdf_sha256=self.M[doc]['sha256'])]

    def add(self, fid, subj, pred, val, kind, crit, docs, rule, sa, pa, quotes, unit=None, **kw):
        f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
                 critical=crit, evidence_required=True, value_kind=kind, subject=subj, predicate=pred,
                 value=val, allowed_citation_docs=docs, source_evidence=quotes,
                 grounding=dict(rule=rule, subject_anchor=sa, predicate_anchor=pa))
        if unit: f['unit'] = unit
        for k in ('derivation', 'dual_stage'):
            if k in kw: f[k] = kw[k]
        self.F.append(f)

    def add_unknown(self, fid, subj, pred, kind, docs, rule, quotes, reason):
        self.add(fid, subj, pred, None, kind, False, docs, rule, None, None, quotes)
        self.F[-1]['status'] = 'GOLD_DRAFT_UNKNOWN'
        self.unknown.append(dict(fact_id=fid, reason=reason))

    def write(self, name, task_id, positioning, question, cutoff, d1_title, d2_title,
              corr, known_issues, totals_check):
        n_scored = sum(1 for f in self.F if f['status'] != 'GOLD_DRAFT_UNKNOWN')
        c = dict(
            task_id=task_id, contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
            positioning=positioning, question=question, cutoff=cutoff,
            source_documents={k: dict(title=t, url=self.M[k]['url'], retrieved_at=self.M[k]['retrieved_at'],
                                      pdf_sha256=self.M[k]['sha256'])
                              for k, t in (('D1', d1_title), ('D2', d2_title))},
            source_pages={k: dict(raw_sha256=self.M[k]['sha256'],
                                  pages={'1': dict(text=self.D[k], page_sha256=hashlib.sha256(self.D[k].encode()).hexdigest())})
                          for k in ('D1', 'D2')},
            required_facts=self.F,
            critical_fact_ids=[f['fact_id'] for f in self.F if f.get('critical') and f['status'] != 'GOLD_DRAFT_UNKNOWN'],
            unknown_items=self.unknown,
            entity_correspondence=corr,
            scoring=dict(primary=f'Q_all = TP / N (N={n_scored}' + (', excluding UNKNOWN)' if self.unknown else ')'),
                         safety='error_rate (None when nothing asserted)',
                         auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
            provenance=dict(nature='两份公告 PDF', model_calls=0, independence='DAG-line independent'),
            known_issues=known_issues,
        )
        out = OUT / f'TASK_CONTRACT_{name}_v1_DRAFT.json'
        out.write_text(json.dumps(c, ensure_ascii=False, indent=1) + '\n', 'utf-8')
        bad = [(f['fact_id'], e['doc_id']) for f in self.F for e in f['source_evidence']
               if norm(e['quote']) not in self.N[e['doc_id']]]
        print(f'{name}: slots={len(self.F)} critical={len(c["critical_fact_ids"])} unknown={len(self.unknown)} '
              f'N={n_scored} verbatim={"OK" if not bad else bad} totals={"OK" if totals_check else "MISMATCH"} '
              f'sha256={hashlib.sha256(out.read_bytes()).hexdigest()}')
        return not bad and totals_check


results = []

# =====================================================================================
# 1. *ST三维 000755 — 2018-04-19立案(晋证调查字2018002) 晋证监处罚字〔2018〕02号 → 〔2018〕03号
# =====================================================================================
t = Task('000755_notice_1527264000000.pdf.txt', '000755_decision_1529683200000.pdf.txt')
G10 = '高志武、刘永安、阎保安、李红星、田建文、王勤旺、王国胜、张建平、王永义、梁国胜'
G12a = '王彩俊、张建华、李存慧、秦联晋、霍斌、王巧萍、王永翔、李杰伟、'
G12b = '张洪波、王新芳、乔志勇、牛武钢给予警告，并分别处以 3 万元罚款'
t.add('F1', '山西三维集团股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '山西三维', '罚款',
      t.ev('D2', '一、对山西三维责令改正，给予警告，并处以 60 万元罚款') + t.ev('D1', '一、对山西三维责令改正，给予警告，并处以 60 万元罚款'),
      unit='万元', dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '王玉柱、杨志贵、祁百发、田旭东、牛俊江', '单人行政处罚罚款金额', '10', 'number', True, ['D1', 'D2'], 'amount', '王玉柱', '罚款',
      t.ev('D2', '二、对王玉柱、杨志贵、祁百发、田旭东、牛俊江给予警告，并分别处以 10 万元罚款'), unit='万元')
t.add('F3', '梁小元', '行政处罚罚款金额', '8', 'number', False, ['D1', 'D2'], 'amount', '梁小元', '罚款',
      t.ev('D2', '三、对梁小元给予警告，并处以 8 万元罚款'), unit='万元')
t.add('F4', '高志武等10人', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '高志武', '罚款',
      t.ev('D2', f'四、对{G10}给予警告，并分别处以 5 万元罚款'), unit='万元',
      derivation=dict(note='D1该项人名"张建平"被PDF页码"2"截断（归一化为"张建2平"），gold人名=张建平'))
t.add('F5', '王彩俊等12人', '单人行政处罚罚款金额', '3', 'number', False, ['D1', 'D2'], 'amount', '王彩俊', '罚款',
      t.ev('D1', f'五、对{G12a}{G12b}'), unit='万元',
      derivation=dict(note='D2该项在"李杰伟、"与"张洪波"之间插入PDF页码"2"；D1文本完整'))
t.add('F6', '全部当事人', '罚款合计', '204', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对山西三维责令改正，给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+10×5+8+5×10+3×12=204万', parties=29))
t.add('F7', '全部当事人', '拟处罚罚款合计', '204', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、对山西三维责令改正，给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+10×5+8+5×10+3×12=204万（与D2逐项一致）', parties=29))
t.add('F8', '全部处罚事项', 'D1拟罚→D2终罚阶段变化', '无变化（5项罚款、29主体逐项一致）', 'text', True, ['D1', 'D2'], 'text', None, '阶段变化',
      t.ev('D1', '二、对王玉柱、杨志贵、祁百发、田旭东、牛俊江给予警告，并分别处以10 万元罚款') +
      t.ev('D2', '二、对王玉柱、杨志贵、祁百发、田旭东、牛俊江给予警告，并分别处以 10万元罚款'),
      dual_stage=dict(d1_proposed='204万/29主体', d2_final='204万/29主体', change='none'))
t.add('F9', '山西三维', '违法行为定性', '定期报告中披露的环境保护相关内容与多次受到环保行政处罚及排污超标的事实不符', 'text', True, ['D1', 'D2'], 'text', '山西三维', '环境保护',
      t.ev('D1', '中披露的环境保护相关内容，与其多次受到环保部门行政处罚的事实不符'))
t.add('F10', '山西三维（2014-2017年环保行政处罚）', '环保罚款金额合计', '285.8448', 'number', True, ['D1', 'D2'], 'amount', '洪洞县环境保护局', '罚款金额',
      t.ev('D1', '山西三维陆续收到洪洞县环境保护局出具的七份《行政处罚决定书》，责令其改正环境污染行为，涉及罚款金额共计 2,858,448.00 元') +
      t.ev('D2', '涉及罚款金额共计 2,858,448.00 元'), unit='万元',
      derivation=dict(original_yuan='2,858,448.00', standard_wan='285.8448', note='七份环保处罚决定书'))
t.add('F11', '山西三维', '调查通知书收到日期', '2018-04-19', 'date', True, ['D1', 'D2'], 'date', '山西三维', '调查',
      t.ev('D2', '2018 年 4 月 19 日，山西三维集团股份有限公司') + t.ev('D1', '2018 年 4 月 19 日，山西三维集团股份有限公司'))
t.add('F12', '山西三维', '事先告知书收到日期', '2018-05-25', 'date', True, ['D1', 'D2'], 'date', '山西三维', '告知书',
      t.ev('D1', '公司于 2018 年 5 月 25 日收到中国证券监督管理委员会山西监管局《行政处罚事先告知书》') +
      t.ev('D2', '2018 年 5 月 25 日，公司收到中国证券监督管理委员会山西监管局《行政处罚事先告知书》'))
t.add('F13', '山西三维', '行政处罚决定书收到日期', '2018-06-22', 'date', True, ['D2'], 'date', '山西三维', '决定书',
      t.ev('D2', '2018 年 6 月 22 日，公司收到中国证券监督管理委员会山西监管局《行政处罚决定书》'))
t.add('F14', '行政处罚决定书', '文号', '〔2018〕03号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《行政处罚决定书》（﹝2018﹞03 号）'),
      derivation=dict(note='原文括号为﹝﹞（U+FE5D/FE5E），NFKC归一为〔〕'))
results.append(t.write(
    'SW_000755', 'P2_SW_000755_PENALTY',
    'P2-C 确认实验任务。零变化型：29主体204万D1=D2；违法性质为环保处罚信息不实披露（非财务造假），附两处"页码插入人名"陷阱（D1"张建/2/平"、D2"李杰伟、/2/张洪波"）。',
    '山西三维信息披露违法案：终罚各主体金额？合计？拟罚合计？D1到D2有何变化？违法行为定性？2014-2017年环保罚款合计？调查通知书、告知书、决定书收到日期？决定书文号？',
    '2018-06-22',
    '关于收到《行政处罚事先告知书》的公告（2018-05-25收到，晋证监处罚字〔2018〕02号）',
    '关于收到中国证监会行政处罚决定书的公告（2018-06-22收到，〔2018〕03号）',
    dict(final_lines_D2=[['山西三维', 60], ['王玉柱等5人', 10], ['梁小元', 8], ['高志武等10人', 5], ['王彩俊等12人', 3]],
         proposed_lines_D1='与final_lines_D2完全一致', final_total_wan=204, proposed_total_wan=204, changes='无',
         market_bans=dict(proposed=[], final=[]),
         aliases=[dict(canonical='山西三维集团股份有限公司', variants=['山西三维', '公司'], where='both docs')]),
    [dict(issue='D1第四项人名"张建平"被页码"2"截断，归一化文本含伪名"张建2平"', handling='gold人名=张建平；引文取D2干净文本'),
     dict(issue='D2第五项"李杰伟、"与"张洪波"间插入页码"2"', handling='引文取D1干净文本'),
     dict(issue='本案无市场禁入', handling='不设禁入槽')],
    60 + 50 + 8 + 50 + 36 == 204))

# =====================================================================================
# 2. 金刚玻璃 300093 — 2019-01-24立案(粤证调查通字190031) 〔2020〕9号告知 → 〔2020〕3号处罚+〔2020〕1号禁入
# =====================================================================================
t = Task('300093_notice_1584979200000.pdf.txt', '300093_decision_1587312000000.pdf.txt')
G14 = '罗伟广、苏佩玉、范波、罗嘉贤、杨时青、蔡祥、卢侠巍、陈小卫、郑鸿生、张坚华、安吉申、何清、肖华、林顺福'
G6 = '林伟锋、支毅、庄毓新、梁艳媚、肖蔚红、陈伟英'
t.add('F1', '广东金刚玻璃科技股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '金刚玻璃', '罚款',
      t.ev('D2', '一、对广东金刚玻璃科技股份有限公司责令改正，给予警告，并处以 60 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '庄大建', '行政处罚罚款金额', '30', 'number', True, ['D1', 'D2'], 'amount', '庄大建', '罚款',
      t.ev('D2', '二、对庄大建给予警告，并处以 30 万元罚款'), unit='万元')
t.add('F3', '林仰先', '行政处罚罚款金额', '20', 'number', True, ['D1', 'D2'], 'amount', '林仰先', '罚款',
      t.ev('D2', '三、对林仰先给予警告，并处以 20 万元罚款'), unit='万元')
t.add('F4', '林文卿、林臻', '单人行政处罚罚款金额', '10', 'number', True, ['D2'], 'amount', '林文卿', '罚款',
      t.ev('D2', '四、对林文卿、林臻给予警告，并分别处以 10 万元罚款'), unit='万元',
      derivation=dict(note='仅D2写"分别"，可确定每人10万；D1无"分别"，D1每人拟罚不可确定（见F9/F10）'))
t.add('F5', '罗伟广等14人', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '罗伟广', '罚款',
      t.ev('D2', f'五、对{G14}给予警告，并分别处以 5 万元罚款'), unit='万元')
t.add('F6', '林伟锋等6人', '单人行政处罚罚款金额', '3', 'number', False, ['D1', 'D2'], 'amount', '林伟锋', '罚款',
      t.ev('D2', f'六、对{G6}给予警告，并分别处以 3 万元罚款'), unit='万元')
t.add('F7', '全部当事人', '罚款合计', '218', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对广东金刚玻璃科技股份有限公司责令改正，给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+30+20+10×2+5×14+3×6=218万', parties=25))
t.add('F8', '林文卿、林臻', 'D1拟罚条款表述', 'D1原文为"对林文卿、林臻给予警告，并处以10万元罚款"（无"分别"），D2改为"并分别处以10万元罚款"', 'text', True, ['D1', 'D2'], 'text', '林文卿', '罚款',
      t.ev('D1', '四、对林文卿、林臻给予警告，并处以 10 万元罚款') + t.ev('D2', '四、对林文卿、林臻给予警告，并分别处以 10 万元罚款'),
      derivation=dict(scope='断言两文书措辞差异；不断言D1拟罚为每人10万或合计10万',
                      forbidden=['以D2"分别"倒推D1每人拟罚10万', '断言D1拟罚合计为218万']))
t.add_unknown('F9', '林文卿、林臻', '单人拟处罚罚款金额', 'number', ['D1'], 'amount',
              t.ev('D1', '四、对林文卿、林臻给予警告，并处以 10 万元罚款'),
              'D1对两人仅写"并处以10万元罚款"而无"分别"，每人拟罚（10万或合计10万）不可唯一确定；不得由D2倒推（冻结标准，同皇台先例）')
t.add_unknown('F10', '全部当事人', '拟处罚罚款合计', 'number', ['D1'], 'penalty_line_sum',
              t.ev('D1', '一、对广东金刚玻璃科技股份有限公司责令改正，给予警告，并处以 60 万元罚款'),
              '依赖F9；若按"分别"为218万、按合计为208万，D1本身不能区分')
t.add('F11', '庄大建', '市场禁入措施', '10年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '庄大建', '禁入',
      t.ev('D2', '一、对庄大建采取 10 年证券市场禁入措施') + t.ev('D1', '对庄大建采取 10 年证券市场禁入措施'),
      dual_stage=dict(d1_proposed='10年', d2_final='10年', change='unchanged'))
t.add('F12', '林仰先', '市场禁入措施', '5年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '林仰先', '禁入',
      t.ev('D2', '二、对林仰先采取 5 年证券市场禁入措施') + t.ev('D1', '林仰先采取 5 年证券市场禁入措施'),
      dual_stage=dict(d1_proposed='5年', d2_final='5年', change='unchanged'))
t.add('F13', '金刚玻璃《2015年年度报告》', '虚增营业收入', '5458.76', 'number', True, ['D2'], 'amount', '金刚玻璃', '营业收入',
      t.ev('D2', '《2015 年年度报告》虚增营业收入 5,458.76 万元，虚增利息收入 919.54 万元，虚增利润 6,205.34 万元，占当期披露利润总额的 1,072.90%'),
      unit='万元', derivation=dict(note='同句：虚增利息收入919.54万元、虚增利润6,205.34万元、占1,072.90%'))
t.add('F14', '金刚玻璃', '违法行为定性', '2015年至2017年虚增营业收入、利息收入及营业利润，相关定期报告存在虚假记载', 'text', True, ['D2'], 'text', '金刚玻璃', '虚增',
      t.ev('D2', '金刚玻璃在 2015 年至 2017 年期间虚增营业收入、利息收入及营业利'))
t.add('F15', '金刚玻璃', '调查通知书收到日期', '2019-01-24', 'date', True, ['D1', 'D2'], 'date', '金刚玻璃', '调查',
      t.ev('D2', '于 2019 年 1 月 24 日收到中国证券监督管理委员会'))
t.add('F16', '金刚玻璃', '事先告知书收到日期', '2020-03-23', 'date', True, ['D1', 'D2'], 'date', '金刚玻璃', '告知书',
      t.ev('D2', '2020 年 3 月 23 日，公司收到中国证监会广东监管局下发的《中国证券监督管理委员会广东监管局行政处罚及市场禁入事先告知书》〔2020〕9 号'))
t.add('F17', '金刚玻璃', '行政处罚决定书收到日期', '2020-04-17', 'date', True, ['D2'], 'date', '金刚玻璃', '决定书',
      t.ev('D2', '2020 年 4 月 17 日，公司收到中国证监会广东监管局下发的《中国证券监督管理委员会广东监管局行政处罚决定书》（〔2020〕3 号）'))
t.add('F18', '市场禁入决定书', '文号', '〔2020〕1号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《中国证券监督管理委员会广东监管局市场禁入决定书》（〔2020〕1 号）'))
results.append(t.write(
    'JG_300093', 'P2_JG_300093_PENALTY',
    'P2-C 确认实验任务。25主体、金额无实质变化；关键难点为文书间措辞不一致：D1对林文卿、林臻缺"分别"致每人拟罚不可确定，D2补"分别"——考察不以终局倒推拟罚。',
    '金刚玻璃信息披露违法案：终罚各主体金额？合计？D1对林文卿、林臻的拟罚条款如何表述，能否确定每人拟罚？拟罚合计？庄大建、林仰先市场禁入？2015年年报虚增营业收入？违法行为定性？调查、告知书、决定书日期？禁入决定书文号？',
    '2020-04-17',
    '关于收到中国证监会广东监管局《行政处罚及市场禁入事先告知书》的公告（2020-03-23收到，〔2020〕9号）',
    '关于收到《行政处罚决定书》及《市场禁入决定书》的公告（2020-04-17收到，〔2020〕3号/〔2020〕1号）',
    dict(final_lines_D2=[['金刚玻璃', 60], ['庄大建', 30], ['林仰先', 20], ['林文卿、林臻', 10], ['罗伟广等14人', 5], ['林伟锋等6人', 3]],
         proposed_lines_D1=[['金刚玻璃', 60], ['庄大建', 30], ['林仰先', 20], ['林文卿、林臻', '"处以10万元"（无"分别"，每人不可确定）'],
                            ['罗伟广等14人', 5], ['林伟锋等6人', 3]],
         final_total_wan=218, proposed_total_wan='UNKNOWN',
         changes='金额无可证实的变化；林文卿/林臻条款措辞D1→D2由"处以"变为"分别处以"',
         market_bans=dict(ten_year=['庄大建'], five_year=['林仰先'], proposed_identical=True),
         aliases=[dict(canonical='广东金刚玻璃科技股份有限公司', variants=['金刚玻璃', '公司'], where='both docs')]),
    [dict(issue='D1第四项对两人缺"分别"', handling='F9/F10 UNKNOWN，不由D2倒推；F8记录措辞差异'),
     dict(issue='扫描表"218万"系按"分别"推定的D1值', handling='D1拟罚合计以UNKNOWN为准')],
    60 + 30 + 20 + 20 + 70 + 18 == 218))

# =====================================================================================
# 3. *ST佳电 000922 — 2017-04-06立案(调查通字171039) 处罚字[2017]94号 → [2017]97号
# =====================================================================================
t = Task('000922_notice_1506441600000.pdf.txt', '000922_decision_1512748800000.pdf.txt')
t.add('F1', '哈尔滨电气集团佳木斯电机股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '佳电股份', '罚款',
      t.ev('D2', '1、对佳电股份责令改正，给予警告，并处以 60 万元的罚款') + t.ev('D1', '一、对佳电股份责令改正，给予警告，并处以 60 万元罚款'),
      unit='万元', dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '赵明', '行政处罚罚款金额', '30', 'number', True, ['D1', 'D2'], 'amount', '赵明', '罚款',
      t.ev('D2', '2、对赵明给予警告，并处以 30 万元的罚款'), unit='万元')
t.add('F3', '梁喜华', '行政处罚罚款金额', '20', 'number', True, ['D1', 'D2'], 'amount', '梁喜华', '罚款',
      t.ev('D2', '3、对梁喜华给予警告，并处以 20 万元的罚款'), unit='万元')
t.add('F4', '张英健、杜文朋', '单人行政处罚罚款金额', '10', 'number', False, ['D1', 'D2'], 'amount', '张英健', '罚款',
      t.ev('D2', '4、对张英健、杜文朋给予警告，并分别处以 10 万元的罚款'), unit='万元')
t.add('F5', '张志祥、陈光浩、王红霞', '单人行政处罚罚款金额', '8', 'number', False, ['D1', 'D2'], 'amount', '张志祥', '罚款',
      t.ev('D2', '5、对张志祥、陈光浩、王红霞给予警告，并分别处以 8 万元的罚款'), unit='万元')
t.add('F6', '孙传尧、贾绍华、胡凤滨、郭寅', '单人行政处罚罚款金额', '7', 'number', False, ['D1', 'D2'], 'amount', '孙传尧', '罚款',
      t.ev('D2', '6、对孙传尧、贾绍华、胡凤滨、郭寅给予警告，并分别处以 7 万元的罚款'), unit='万元')
t.add('F7', '要志成等6人', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '要志成', '罚款',
      t.ev('D2', '7、对要志成、王小明、刘洪文、崔剑、王晓文、张军给予警告，并分别处以 5 万元的罚款'), unit='万元')
t.add('F8', '李国强等5人', '单人行政处罚罚款金额', '3', 'number', False, ['D1', 'D2'], 'amount', '李国强', '罚款',
      t.ev('D2', '8、对李国强、高全宏、张胜根、常忠、闫红给予警告，并分别处以 3 万元的罚款'), unit='万元')
t.add('F9', '全部当事人', '罚款合计', '227', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '1、对佳电股份责令改正，给予警告，并处以 60 万元的罚款'), unit='万元',
      derivation=dict(rule='60+30+20+10×2+8×3+7×4+5×6+3×5=227万', parties=23))
t.add('F10', '全部当事人', '拟处罚罚款合计', '227', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、对佳电股份责令改正，给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='同D2逐项一致', parties=23))
t.add('F11', '赵明', '拟市场禁入措施', '5年证券市场禁入', 'text', True, ['D1'], 'text', '赵明', '禁入',
      t.ev('D1', '一、对赵明采取 5 年证券市场禁入措施'))
t.add('F12', '梁喜华', '拟市场禁入措施', '3年证券市场禁入', 'text', True, ['D1'], 'text', '梁喜华', '禁入',
      t.ev('D1', '二、对梁喜华采取 3 年证券市场禁入措施'))
t.add_unknown('F13', '赵明、梁喜华', '市场禁入措施终局结果', 'text', ['D2'], 'text',
              t.ev('D2', '8、对李国强、高全宏、张胜根、常忠、闫红给予警告，并分别处以 3 万元的罚款'), BAN_UNKNOWN)
t.add('F14', '佳电股份', '2013年度调增利润总额', '15843.73', 'number', True, ['D1', 'D2'], 'amount', '佳电股份', '利润总额',
      t.ev('D1', '调增2013 年度利润总额 158,437,287.54 元') + t.ev('D2', '调增2013年度利润总额158,437,287.54元'), unit='万元',
      derivation=dict(original_yuan='158,437,287.54', standard_wan='15843.73', note='同句另载调增2014年度39,942,583.68元、调减2015年度198,379,871.22元'))
t.add('F15', '佳电股份', '违法行为定性', '为完成业绩承诺进行财务调整，所披露信息存在虚假记载', 'text', True, ['D1', 'D2'], 'text', '佳电股份', '虚假记载',
      t.ev('D1', '为保证业绩承诺的完成，佳电股份董事长兼总经理赵明决定从财务处理上做一些调整安排'))
t.add('F16', '佳电股份', '调查通知书收到日期', '2017-04-06', 'date', True, ['D2'], 'date', '佳电股份', '调查',
      t.ev('D2', '2017 年 4 月 6 日，哈尔滨电气集团佳木斯电机股份有限公司'))
t.add('F17', '佳电股份', '事先告知书收到日期', '2017-09-25', 'date', True, ['D1', 'D2'], 'date', '佳电股份', '告知书',
      t.ev('D2', '2017 年 9 月 25 日，公司及相关当事人收到证监会下发的《行政处罚及市场禁入事先告知书》（处罚字[2017]94 号）') +
      t.ev('D1', '2017 年 9 月 25 日，公司收到证监会下发的《行政处罚及市场禁入事先告知'))
t.add('F18', '佳电股份', '行政处罚决定书收到日期', '2017-12-08', 'date', True, ['D2'], 'date', '佳电股份', '决定书',
      t.ev('D2', '2017 年 12 月 8 日，公司及相关当事人收到证监会下发的《行政处罚决定书》（[2017]97 号）'))
results.append(t.write(
    'JD_000922', 'P2_JD_000922_PENALTY',
    'P2-C 确认实验任务。23主体、8个金额档、D1=D2金额零变化；2人拟禁入但D2处罚决定书未载禁入（终局UNKNOWN）。',
    '佳电股份信息披露违法案：终罚各主体金额？合计？拟罚合计？赵明、梁喜华拟市场禁入及终局？2013年度调增利润总额？违法行为定性？调查、告知书、决定书日期？',
    '2017-12-08',
    '关于收到中国证监会《行政处罚及市场禁入事先告知书》的公告（2017-09-25收到，处罚字[2017]94号）',
    '关于公司及相关当事人收到中国证监会《行政处罚决定书》的公告（2017-12-08收到，[2017]97号）',
    dict(final_lines_D2=[['佳电股份', 60], ['赵明', 30], ['梁喜华', 20], ['张英健、杜文朋', 10], ['张志祥等3人', 8],
                         ['孙传尧等4人', 7], ['要志成等6人', 5], ['李国强等5人', 3]],
         proposed_lines_D1='与final_lines_D2完全一致', final_total_wan=227, proposed_total_wan=227,
         changes='罚款零变化；禁入终局UNKNOWN',
         market_bans=dict(proposed=['赵明5年', '梁喜华3年'], final='UNKNOWN'),
         aliases=[dict(canonical='哈尔滨电气集团佳木斯电机股份有限公司', variants=['佳电股份', '公司'], where='both docs')]),
    [dict(issue='D2未载禁入，池内无单独禁入决定书', handling='F13终局UNKNOWN，不推断未采取'),
     dict(issue='D1项次用"一、"，D2用"1、"', handling='不影响事实')],
    60 + 30 + 20 + 20 + 24 + 28 + 30 + 15 == 227))

# =====================================================================================
# 4. 文化长城 300089 — 2019-11-04立案(粤证调查通字190221) 广东证监处罚字(2021)7号 → 【2021】12号+禁入【2021】1号
# =====================================================================================
t = Task('300089_notice_1625500800000.pdf.txt', '300089_decision_1630592121000.pdf.txt')
t.add('F1', '广东文化长城集团股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '文化长城', '罚款',
      t.ev('D2', '一对广东文化长城集团股份有限公司给予警告，并处以 60 万元罚款') + t.ev('D1', '一、对文化长城给予警告，并处以 60 万元罚款'),
      unit='万元', dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '蔡廷祥', '行政处罚罚款金额', '90', 'number', True, ['D1', 'D2'], 'amount', '蔡廷祥', '罚款',
      t.ev('D2', '二对蔡廷祥给予警告，并处以 90 万元罚款，其中对其作为直接负责的主管人员处以 30 万元罚款，对其作为实际控制人处以 60 万元罚款'),
      unit='万元', derivation=dict(note='构成：直接负责的主管人员30万+实际控制人60万'))
t.add('F3', '许高镭', '行政处罚罚款金额', '25', 'number', True, ['D1', 'D2'], 'amount', '许高镭', '罚款',
      t.ev('D2', '三、对许高镭给予警告，并处以 25 万元罚款'), unit='万元')
t.add('F4', '任锋、蔡雪凯', '单人行政处罚罚款金额', '20', 'number', False, ['D1', 'D2'], 'amount', '任锋', '罚款',
      t.ev('D2', '四、对任锋、蔡雪凯给予警告，并分别处以 20 万元罚款'), unit='万元')
t.add('F5', '吴淡珠、罗晨鹏', '单人行政处罚罚款金额', '10', 'number', False, ['D1', 'D2'], 'amount', '吴淡珠', '罚款',
      t.ev('D2', '五、对吴淡珠、罗晨鹏给予警告，并分别处以 10 万元罚款'), unit='万元')
t.add('F6', '谢建歆、金永丽、陈伟雄、谢洁', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '谢建歆', '罚款',
      t.ev('D2', '六、对谢建歆、金永丽、陈伟雄、谢洁给予警告，并分别处以 5 万元罚款'), unit='万元')
t.add('F7', '高洪星', '行政处罚罚款金额', '3', 'number', False, ['D1', 'D2'], 'amount', '高洪星', '罚款',
      t.ev('D2', '七、对高洪星给予警告，并处以 3 万元罚款'), unit='万元')
t.add('F8', '全部当事人', '罚款合计', '258', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一对广东文化长城集团股份有限公司给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+90+25+20×2+10×2+5×4+3=258万', parties=12))
t.add('F9', '全部当事人', '拟处罚罚款合计', '258', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、对文化长城给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='同D2逐项一致', parties=12))
t.add('F10', '全部处罚事项', 'D1拟罚→D2终罚阶段变化', '无变化（7项罚款、12主体、2项市场禁入逐项一致）', 'text', True, ['D1', 'D2'], 'text', None, '阶段变化',
      t.ev('D1', '七、对高洪星给予警告，并处以 3 万元罚款') + t.ev('D2', '七、对高洪星给予警告，并处以 3 万元罚款'),
      dual_stage=dict(d1_proposed='258万+2项禁入', d2_final='258万+2项禁入', change='none'))
t.add('F11', '蔡廷祥', '市场禁入措施', '10年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '蔡廷祥', '禁入',
      t.ev('D2', '一、对蔡廷祥采取 10 年证券市场禁入措施') + t.ev('D1', '一、对蔡廷祥采取 10 年证券市场禁入措施'))
t.add('F12', '许高镭', '市场禁入措施', '5年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '许高镭', '禁入',
      t.ev('D2', '二、对许高镭采取 5 年证券市场禁入措施') + t.ev('D1', '二、对许高镭采取 5 年证券市场禁入措施'))
t.add('F13', '文化长城《2018年年度报告》', '虚增营业收入', '约6467', 'number', True, ['D2'], 'amount', '文化长城', '营业收入',
      t.ev('D2', '导致 2018 年度报告虚增营业收入约 6,467万元，虚增营业利润的约 5,939 万元，占文化长城当期披露利润总额 24.49%'),
      unit='万元', derivation=dict(note='原文为约数"约6,467万元"，保留"约"；同句虚增营业利润约5,939万元、占24.49%'))
t.add('F14', '文化长城', '违法行为定性（之一）', '2018年年度报告虚增营业收入及利润，存在虚假记载', 'text', True, ['D2'], 'text', '文化长城', '虚假记载',
      t.ev('D2', '文化长城 2018 年年度报告虚增营业收入及利润，存在虚假记载'))
t.add('F15', '文化长城', '调查通知书收到日期', '2019-11-04', 'date', True, ['D1', 'D2'], 'date', '文化长城', '调查',
      t.ev('D2', '于 2019 年 11 月 4 日收到中国证券监督管理委员会《调查通知书》（粤证调查通字 190221 号）') +
      t.ev('D1', '于 2019 年 11 月 4 日收到中国证券监督管理委员会《调查通知书》（粤证调查通字 190221 号）'))
t.add('F16', '文化长城', '事先告知书收到日期', '2021-07-04', 'date', True, ['D1', 'D2'], 'date', '文化长城', '告知书',
      t.ev('D1', '公司于 2021 年 7 月 4 日收到中国证监会广东监管局对原董监高及公司出具的《行政处罚及市场禁入事先告知书》（广东证监处罚字(2021)7 号）'))
t.add('F17', '文化长城', '行政处罚决定书收到日期', '2021-09-02', 'date', True, ['D2'], 'date', '文化长城', '决定书',
      t.ev('D2', '公司于 2021年 9 月 2 日收到中国证监会广东监管局对原董监高及公司出具的《行政处罚决定书》'))
t.add('F18', '行政处罚决定书', '文号', '【2021】12号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《行政处罚决定书》【2021】12 号具体内容如下'))
results.append(t.write(
    'WC_300089', 'P2_WC_300089_PENALTY',
    'P2-C 确认实验任务。零变化型：12主体258万+2项禁入D1=D2；实控人双重身份罚款构成；D2项次标号缺"、"、禁入文号写作"【2021】年1号"等排版不规范。',
    '文化长城信息披露违法案：终罚各主体金额？合计？拟罚合计？D1到D2有何变化？蔡廷祥、许高镭市场禁入？2018年年报虚增营业收入？违法行为定性？调查、告知书、决定书日期？决定书文号？',
    '2021-09-02',
    '关于收到《行政处罚及市场禁入事先告知书》的公告（2021-07-04收到，广东证监处罚字(2021)7号）',
    '关于收到《行政处罚决定书》及《市场禁入决定书》的公告（2021-09-02收到，【2021】12号/【2021】1号）',
    dict(final_lines_D2=[['文化长城', 60], ['蔡廷祥', 90], ['许高镭', 25], ['任锋、蔡雪凯', 20], ['吴淡珠、罗晨鹏', 10],
                         ['谢建歆等4人', 5], ['高洪星', 3]],
         proposed_lines_D1='与final_lines_D2完全一致', final_total_wan=258, proposed_total_wan=258, changes='无',
         market_bans=dict(ten_year=['蔡廷祥'], five_year=['许高镭'], proposed_identical=True),
         aliases=[dict(canonical='广东文化长城集团股份有限公司', variants=['文化长城', '公司'], where='both docs')]),
    [dict(issue='扫描表"14主体/348万"与逐条核实12主体/258万不符', handling='以逐条核实为准'),
     dict(issue='D2第一、二项写作"一对""二对"（缺"、"）；禁入文号D2一处写"【2021】年1号"', handling='照录原文'),
     dict(issue='F13原文为约数', handling='gold值保留"约"字，按原文精度判分')],
    60 + 90 + 25 + 40 + 20 + 20 + 3 == 258))

# =====================================================================================
# 5. ST汇洲(天马股份) 002122 — 2018-04-27立案(浙证调查字2018118) 处罚字[2019]83号 → [2019]120号
#    (池内2025年决定书 立案字01120250011 为另案，排除)
# =====================================================================================
t = Task('002122_notice_1562601600000.pdf.txt', '002122_decision_1572969600000.pdf.txt')
t.add('F1', '天马轴承集团股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '天马股份', '罚款',
      t.ev('D2', '一、对天马轴承集团股份有限公司责令改正、给予警告，并处以 60 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '徐茂栋', '行政处罚罚款金额', '90', 'number', True, ['D1', 'D2'], 'amount', '徐茂栋', '罚款',
      t.ev('D2', '二、对徐茂栋给予警告，并处以 90 万元罚款，其中作为直接负责的主管人员罚款 30 万元，作为实际控制人罚款 60 万元'),
      unit='万元', derivation=dict(note='构成：直接负责的主管人员30万+实际控制人60万'))
t.add('F3', '傅淼、陶振武', '单人行政处罚罚款金额', '30', 'number', True, ['D1', 'D2'], 'amount', '傅淼', '罚款',
      t.ev('D2', '三、对傅森、陶振武给予警告，并分别处以 30 万元罚款') + t.ev('D1', '三、对傅淼、陶振武给予警告，并分别处以 30 万元罚款'),
      unit='万元', derivation=dict(note='D2决定条款写"傅森"，D2当事人列表与申辩段均写"傅淼"，D1亦为"傅淼"；规范名=傅淼，"傅森"为D2条款内异写'))
t.add('F4', '韦京汉、杨利军、张志成', '单人行政处罚罚款金额', '20', 'number', False, ['D1', 'D2'], 'amount', '韦京汉', '罚款',
      t.ev('D2', '四、对韦京汉、杨利军、张志成给予警告，并分别处以 20 万元罚款'), unit='万元')
t.add('F5', '马兴法、刘艳秋', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '马兴法', '罚款',
      t.ev('D2', '五、对马兴法、刘艳秋给予警告，并分别处以 5 万元罚款'), unit='万元')
t.add('F6', '丁海胜、赵华、胡亮、岳基伟、郭松波', '单人行政处罚罚款金额', '3', 'number', True, ['D2'], 'amount', '丁海胜', '罚款',
      t.ev('D2', '六、对丁海胜、赵华、胡亮、岳基伟、郭松波给予警告，并分别处以 3 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='9人各3万', d2_final='5人各3万', change='members_not_restated_in_D2'))
t.add('F7', '全部当事人', '罚款合计', '295', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对天马轴承集团股份有限公司责令改正、给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+90+30×2+20×3+5×2+3×5=295万', parties=14))
t.add('F8', '全部当事人', '拟处罚罚款合计', '317', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '我会拟决定：一、对天马轴承集团股份有限公同责令改正、给予警告，并处以 60 万元罚款'), unit='万元',
      derivation=dict(rule='60+90+30×2+20×3+10+5×2+3×9=317万', parties=19,
                      note='差22万=王薇(10)+周方强、张云龙、陈丹红、王义艳(各3)D2未再载明；为文书记载差，不代表五人终罚为0'))
t.add('F9', '王薇', '拟处罚记录与D2载明情况', 'D1拟10万元；D2未再载明对应处罚', 'text', True, ['D1', 'D2'], 'text', '王薇', '罚款',
      t.ev('D1', '五、对王薇给予警告，并处以 10 万元罚款') + t.ev('D2', '五、对马兴法、刘艳秋给予警告，并分别处以 5 万元罚款'),
      dual_stage=dict(d1_proposed='10万元', d2_final=NOT_RESTATED, change='not_restated_in_D2'))
t.add('F10', '周方强、张云龙、陈丹红、王义艳', '拟处罚记录与D2载明情况', 'D1拟各3万元；D2未再载明对应处罚', 'text', True, ['D1', 'D2'], 'text', '周方强', '罚款',
      t.ev('D1', '七、对周方强、张云龙、隊丹红、丁海胜、赵华、胡亮、岳基伟，王义艳、郭松波给予警告，并分别处以 3 万元罚款') +
      t.ev('D2', '六、对丁海胜、赵华、胡亮、岳基伟、郭松波给予警告，并分别处以 3 万元罚款'),
      derivation=dict(note='D1处罚条款写"隊丹红"，D1当事人列表写"陈丹红"；规范名=陈丹红'),
      dual_stage=dict(d1_proposed='各3万元', d2_final=NOT_RESTATED, change='not_restated_in_D2'))
t.add('F11', '徐茂栋', '拟市场禁入措施', '终身市场禁入', 'text', True, ['D1'], 'text', '徐茂栋', '禁入',
      t.ev('D1', '我会拟决定对徐茂栋采取终身市场禁入措施'))
t.add('F12', '傅淼、陶振武', '拟市场禁入措施', '3年市场禁入', 'text', True, ['D1'], 'text', '傅淼', '禁入',
      t.ev('D1', '我会拟决定对傅淼、陶振武采取 3 年市场禁入措施'))
t.add_unknown('F13', '徐茂栋、傅淼、陶振武', '市场禁入措施终局结果', 'text', ['D2'], 'text',
              t.ev('D2', '六、对丁海胜、赵华、胡亮、岳基伟、郭松波给予警告，并分别处以 3 万元罚款'), BAN_UNKNOWN)
t.add('F14', '天马股份', '违法行为定性（之一）', '徐茂栋及其控制的企业与天马股份存在关联关系（未按规定披露）', 'text', True, ['D1', 'D2'], 'text', '徐茂栋', '关联关系',
      t.ev('D2', '一、徐茂栋及其控制的企业与天马股份存在关联关系'))
t.add('F15', '天马股份', '调查通知书收到日期', '2018-04-27', 'date', True, ['D1', 'D2'], 'date', '天马股份', '调查',
      t.ev('D2', '2018 年 4 月 27 日，公司收到中国证券监督管理委员会') + t.ev('D1', '公司于 2018 年 4 月 27 日收到中国证券监督管理委员会'))
t.add('F16', '天马股份', '事先告知书公告披露日期', '2019-07-10', 'date', True, ['D2'], 'date', '天马股份', '告知书',
      t.ev('D2', '公司于 2019 年 7 月 10 日披露了中国证监会下发的处罚字[2019]83 号'),
      derivation=dict(note='D1仅称"近日"收到；本槽为披露日，不作为收到日'))
t.add('F17', '中国证监会', '行政处罚决定书落款日期', '2019-10-31', 'date', True, ['D2'], 'date', '中国证券监督管理委员会', '落款',
      t.ev('D2', '中国证券监督管理委员会 2019 年 10 月 31 日'),
      derivation=dict(note='决定书正文落款日（作出日），非公司收到日'))
t.add_unknown('F18', '天马股份', '行政处罚决定书收到日期', 'date', ['D2'], 'date',
              t.ev('D2', '于今日收到中国证券监督管理委员会下发的[2019]120 号《行政处罚决定书》'),
              'D2仅称"于今日收到"，未载具体日期；公告落款二〇一九年十一月五日为公告日，按规则不以公告日替代收到日')
t.add('F19', '行政处罚决定书', '文号', '[2019]120号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '[2019]120 号《行政处罚决定书》'))
results.append(t.write(
    'HZ_002122', 'P2_HZ_002122_PENALTY',
    'P2-C 确认实验任务。19→14主体：5人D1拟罚、D2未再载明（王薇10万+4人各3万）；跨文书人名异写（傅淼/傅森、陈丹红/隊丹红）；3人拟禁入终局UNKNOWN。',
    '天马股份信息披露违法案：终罚各主体金额？合计？拟罚合计？王薇及周方强等4人D1拟罚与D2载明情况？徐茂栋、傅淼、陶振武拟市场禁入及终局？违法行为定性？调查日期、告知书披露日、决定书落款日与收到日？决定书文号？',
    '2019-11-05',
    '关于收到中国证监会《行政处罚及市场禁入事先告知书》的公告（2019-07，处罚字[2019]83号）',
    '关于收到中国证监会《行政处罚决定书》的公告（2019-11-05公告，[2019]120号）',
    dict(final_lines_D2=[['天马股份', 60], ['徐茂栋', 90], ['傅淼、陶振武', 30], ['韦京汉等3人', 20], ['马兴法、刘艳秋', 5], ['丁海胜等5人', 3]],
         proposed_lines_D1=[['天马股份', 60], ['徐茂栋', 90], ['傅淼、陶振武', 30], ['韦京汉等3人', 20], ['王薇', 10],
                            ['马兴法、刘艳秋', 5], ['周方强等9人', 3]],
         final_total_wan=295, proposed_total_wan=317,
         changes=[dict(party='王薇', d1=10, d2=None, note='D2未再载明对应处罚')] +
                 [dict(party=p, d1=3, d2=None, note='D2未再载明对应处罚') for p in ('周方强', '张云龙', '陈丹红', '王义艳')],
         market_bans=dict(proposed=['徐茂栋终身', '傅淼3年', '陶振武3年'], final='UNKNOWN'),
         aliases=[dict(canonical='天马轴承集团股份有限公司', variants=['天马股份', '公司', '天马轴承集团股份有限公同（D1错字）'], where='both docs'),
                  dict(canonical='傅淼', variants=['傅森（D2决定条款）'], where='D2'),
                  dict(canonical='陈丹红', variants=['隊丹红（D1处罚条款）'], where='D1')]),
    [dict(issue='池内decision_1763481600000（2025，立案字01120250011）为另案', handling='不纳入'),
     dict(issue='D1多处错字（"公同""给子警告""隊丹红""之目起""市场进入事先告知书"）', handling='引文照录原文；人名按别名表规范化'),
     dict(issue='D2决定条款"傅森"与同文其余处"傅淼"不一致', handling='规范名傅淼，答"傅森"按别名接受'),
     dict(issue='5人D1拟罚、D2全文未出现且未作说明', handling='F9/F10表述为"D2未再载明对应处罚"，不认定撤销、不计0'),
     dict(issue='D2收到日仅"于今日"', handling='F18 UNKNOWN；另设F17决定书落款日（文书明载）')],
    60 + 90 + 60 + 60 + 10 + 15 == 295 and 60 + 90 + 60 + 60 + 10 + 10 + 27 == 317))

print('ALL OK' if all(results) else 'FAILURES PRESENT')
sys.exit(0 if all(results) else 1)
