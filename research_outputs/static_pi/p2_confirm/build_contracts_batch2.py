#!/usr/bin/env python3
"""P2-C batch 2 Gold contract builder: *ST保千 / 登云股份 / *ST红相 / ST易事特 / ST特信.

Same slot schema and verbatim self-check as the batch-1 per-task builders.
Pairing verified 2026-11-08 by doc-number + investigation-number chain (see BATCH2 review doc).
"""
import hashlib, json, re, sys, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')

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
        crit = len(c['critical_fact_ids'])
        print(f'{name}: slots={len(self.F)} critical={crit} unknown={len(self.unknown)} '
              f'verbatim={"OK" if not bad else bad} totals={"OK" if totals_check else "MISMATCH"} '
              f'sha256={hashlib.sha256(out.read_bytes()).hexdigest()}')
        return not bad and totals_check


results = []

# =====================================================================================
# 1. *ST保千 600074 — B案: 2017-12-11立案(苏证调查字2017090) 处罚字[2019]68号 → [2019]141号+禁入[2019]23号
#    (池内A案 处罚字【2017】87号→【2017】78号 为另案，12主体零变化，不用)
# =====================================================================================
t = Task('600074_notice_1556294400000.pdf.txt', '600074_decision_1584633600000.pdf.txt')
G19 = '陈杨辉、丁立红、张乾峰、黄焱、周少强、曹亦为、周含军、蒋建平、陈献文、陈德银、龙刚、林宋伟、李小虎、李翊、童爱平、王务云、梁国华、颜佳德、林新阳'
t.add('F1', '江苏保千里视像科技集团股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '保千里', '罚款',
      t.ev('D2', '一、对保千里责令改正，给予警告，并处以60万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '庄敏', '行政处罚罚款金额', '90', 'number', True, ['D1', 'D2'], 'amount', '庄敏', '罚款',
      t.ev('D2', '二、对庄敏给予警告，并处以90万元罚款。其中作为直接负责的主管人员罚款30万元，作为指使从事违法行为的实际控制人罚款60万元'),
      unit='万元', derivation=dict(note='构成：直接负责的主管人员30万+指使从事违法行为的实际控制人60万'),
      dual_stage=dict(d1_proposed='90万元(30+60)', d2_final='90万元(30+60)', change='unchanged'))
t.add('F3', '鹿鹏、何年丰', '单人行政处罚罚款金额', '30', 'number', True, ['D1', 'D2'], 'amount', '鹿鹏', '罚款',
      t.ev('D2', '三、对鹿鹏、何年丰给予警告，并分别处以30万元罚款'), unit='万元')
t.add('F4', '周皓琳', '行政处罚罚款金额', '15', 'number', True, ['D2'], 'amount', '周皓琳', '罚款',
      t.ev('D2', '四、对周皓琳给予警告，并处以15万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='20万元', d2_final='15万元', change='reduced'))
t.add('F5', '陈杨辉等19人', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '陈杨辉', '罚款',
      t.ev('D2', f'对{G19}给予警告，并分别处以5万元罚款'), unit='万元')
t.add('F6', '全部当事人', '罚款合计', '320', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对保千里责令改正，给予警告，并处以60万元罚款'), unit='万元',
      derivation=dict(rule='60+90+30×2+15+5×19=320万', parties=24))
t.add('F7', '全部当事人', '拟处罚罚款合计', '325', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、对保千里责令改正，给予警告，并处以60万元罚款'), unit='万元',
      derivation=dict(rule='60+90+30×2+20+5×19=325万', parties=24, note='差5万=周皓琳20→15'))
t.add('F8', '周皓琳', '拟处罚罚款金额（终罚：15万元）', '20', 'number', True, ['D1', 'D2'], 'amount', '周皓琳', '罚款',
      t.ev('D1', '对直接负责的主管人员周皓琳给予警告，并处以20万元罚款') + t.ev('D2', '四、对周皓琳给予警告，并处以15万元罚款'),
      unit='万元', derivation=dict(note='D1列于"直接负责的主管人员"项（第三项），D2改列第四项与其他责任人员同项'),
      dual_stage=dict(d1_proposed='20万元（主管人员档）', d2_final='15万元（第四项）', change='reduced'))
t.add('F9', '庄敏', '市场禁入措施', '终身证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '庄敏', '禁入',
      t.ev('D2', '对庄敏采取终身证券市场禁入措施') + t.ev('D1', '对庄敏采取终身证券市场禁入措施'))
t.add('F10', '鹿鹏、何年丰', '市场禁入措施', '5年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '鹿鹏', '禁入',
      t.ev('D2', '对鹿鹏、何年丰分别采取 5 年证券市场禁') + t.ev('D1', '对鹿鹏、何年丰采取5年证券市场禁入措施'))
t.add('F11', '保千里', '违法行为定性', '未按规定披露关联方及关联交易', 'text', True, ['D1', 'D2'], 'text', '保千里', '关联交易',
      t.ev('D2', '一、未按规定披露关联方及关联交易') + t.ev('D1', '一、未披露关联方及关联交易'),
      derivation=dict(note='D1表述"未披露关联方及关联交易"，D2改为"未按规定披露关联方及关联交易"；二者均判为正确'))
t.add('F12', '保千里对关联小微企业销售（2016年度）', '销售收入', '16.16', 'number', True, ['D1', 'D2'], 'amount', '保千里', '销售收入',
      t.ev('D2', '2016 年度销售收入 16.16 亿元，相应利润 7.10 亿元，占当年净利润比重 88.79%') +
      t.ev('D1', '2016 年度销售收入 16.16 亿元，相应利润 7.10 亿'), unit='亿元',
      derivation=dict(note='同句：相应利润7.10亿元，占当年净利润比重88.79%'))
t.add('F13', '保千里', '调查通知书收到日期', '2017-12-11', 'date', True, ['D1', 'D2'], 'date', '保千里', '调查',
      t.ev('D2', '年 12 月 11 日收到中国证券监督管理委员会'),
      derivation=dict(note='年份"2017"见同句前文，调查通知书编号苏证调查字2017090号'))
t.add('F14', '保千里', '事先告知书收到日期', '2019-04-26', 'date', True, ['D1', 'D2'], 'date', '保千里', '告知书',
      t.ev('D2', '2019 年 4 月 26 日，公司收到中国证监会《行政处罚及市场禁入事先告知书》（处罚字[2019]68 号）'))
t.add('F15', '保千里', '行政处罚决定书收到日期', '2020-03-19', 'date', True, ['D2'], 'date', '保千里', '决定书',
      t.ev('D2', '2020 年 3 月 19 日，公司收到中国证监会《行政处罚决定书》（[2019]141 号）'))
t.add('F16', '行政处罚决定书', '文号', '[2019]141号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《行政处罚决定书》（[2019]141 号）'))
t.add('F17', '市场禁入决定书', '文号', '[2019]23号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《市场禁入决定书》（[2019]23 号）'))
results.append(t.write(
    'BQ_600074', 'P2_BQ_600074_PENALTY',
    'P2-C 确认实验任务。24主体（含19人同额组）、实控人双重身份罚款构成、3人禁入；唯一阶段变化为周皓琳20→15万且换档。池内另有2016立案A案，已排除。',
    '保千里信息披露违法案（2017立案）：终罚各主体金额？合计？拟罚合计？周皓琳拟罚与终罚？庄敏、鹿鹏、何年丰市场禁入？违法行为定性？2016年度关联销售收入？调查通知书、告知书、决定书收到日期？处罚与禁入决定书文号？',
    '2020-03-19',
    '关于收到中国证监会《行政处罚及市场禁入事先告知书》的公告（2019-04，处罚字[2019]68号）',
    '关于收到中国证监会《行政处罚决定书》及《市场禁入决定书》的公告（2020-03-19，[2019]141号/[2019]23号）',
    dict(final_lines_D2=[['保千里', 60], ['庄敏', 90], ['鹿鹏、何年丰', 30], ['周皓琳', 15], ['陈杨辉等19人', 5]],
         proposed_lines_D1=[['保千里', 60], ['庄敏', 90], ['鹿鹏、何年丰', 30], ['周皓琳', 20], ['陈杨辉等19人', 5]],
         final_total_wan=320, proposed_total_wan=325,
         changes=[dict(party='周皓琳', d1=20, d2=15, note='同时由主管人员项改列第四项')],
         market_bans=dict(lifetime=['庄敏'], five_year=['鹿鹏', '何年丰'], proposed_identical=True),
         aliases=[dict(canonical='江苏保千里视像科技集团股份有限公司', variants=['保千里', '公司'], where='both docs')]),
    [dict(issue='raw池含两案：A案（调查字2016902，处罚字【2017】87号→【2017】78号，12主体，金额零变化）与B案（本合同）', handling='选B案：结构更丰富且有阶段变化'),
     dict(issue='扫描表"32主体/440万"与逐条核实24主体/320万（终）/325万（拟）不符', handling='以逐条核实为准；扫描正则过计'),
     dict(issue='D2中"一、未按规定披露关联方及关联交易"后紧随PDF页码"8"', handling='引文截止于页码前')],
    60 + 90 + 60 + 15 + 95 == 320 and 60 + 90 + 60 + 20 + 95 == 325))

# =====================================================================================
# 2. 登云股份 002715 — 2015-10-20立案(调查通字152810) 处罚字[2017]42号 → [2017]60号
# =====================================================================================
t = Task('002715_notice_1493395200000.pdf.txt', '002715_decision_1496678400000.pdf.txt')
t.add('F1', '怀集登云汽配股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '登云股份', '罚款',
      t.ev('D2', '一、责令登云股份改正，给予警告，并处以 60 万元的罚款') + t.ev('D1', '一、责令登云股份改正，给予警告，并处以 60 万元的罚款'),
      unit='万元', dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
t.add('F2', '欧洪先、潘炜', '单人行政处罚罚款金额', '30', 'number', True, ['D1', 'D2'], 'amount', '欧洪先', '罚款',
      t.ev('D2', '二、对欧洪先、潘炜给予警告，并分别处以 30 万元的罚款'), unit='万元')
t.add('F3', '张弢', '行政处罚罚款金额', '20', 'number', True, ['D1', 'D2'], 'amount', '张弢', '罚款',
      t.ev('D2', '三、对张弢给予警告，并处以 20 万元罚款') + t.ev('D1', '对张弢、邓剑雄给予警告，并处以张弢 20 万元、邓剑雄 15 万元的罚款'),
      unit='万元')
t.add('F4', '邓剑雄', '行政处罚罚款金额', '15', 'number', True, ['D1', 'D2'], 'amount', '邓剑雄', '罚款',
      t.ev('D2', '四、对邓剑雄给予警告，并处以 15 万元罚款'), unit='万元')
t.add('F5', '罗天友等5人', '单人行政处罚罚款金额', '10', 'number', False, ['D1', 'D2'], 'amount', '罗天友', '罚款',
      t.ev('D2', '五、对罗天友、符麟军、杨华健、周立成、李区给予警告，并分别处以 10 万元罚款'), unit='万元')
t.add('F6', '刘永朱等4人', '单人行政处罚罚款金额', '9', 'number', False, ['D1', 'D2'], 'amount', '刘永朱', '罚款',
      t.ev('D2', '六、对刘永朱、李萍、魏晓源、奚志伟给予警告，并分别处以 9 万元罚款'), unit='万元')
t.add('F7', '钱艺等3人', '单人行政处罚罚款金额', '8', 'number', False, ['D1', 'D2'], 'amount', '钱艺', '罚款',
      t.ev('D2', '七、对钱艺、莫剑少、李煜叶给予警告，并分别处以 8 万元罚款'), unit='万元')
t.add('F8', '李盘生', '行政处罚罚款金额', '7', 'number', False, ['D1', 'D2'], 'amount', '李盘生', '罚款',
      t.ev('D2', '八、对李盘生给予警告，并处以 7 万元罚款'), unit='万元')
t.add('F9', '邓晶、董川、谢少华、罗华欢', '单人行政处罚罚款金额', '6', 'number', False, ['D1', 'D2'], 'amount', '邓晶', '罚款',
      t.ev('D2', '九、对邓晶、董川、谢少华、罗华欢给予警告，并分别处以 6 万元的罚款'), unit='万元',
      derivation=dict(note='D1分列第八、九两项（邓晶、董川 / 谢少华、罗华欢），D2合并为一项，金额不变'))
t.add('F10', '苏武俊、张江洋、许建生、叶景年', '单人行政处罚罚款金额', '5', 'number', False, ['D1', 'D2'], 'amount', '苏武俊', '罚款',
      t.ev('D2', '十、对苏武俊、张江洋、许建生、叶景年给予警告，并分别处以 5 万元的罚款'), unit='万元',
      derivation=dict(note='D1分列第十、十一两项，D2合并，金额不变'))
t.add('F11', '全部当事人', '罚款合计', '316', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、责令登云股份改正，给予警告，并处以 60 万元的罚款'), unit='万元',
      derivation=dict(rule='60+30×2+20+15+10×5+9×4+8×3+7+6×4+5×4=316万', parties=26))
t.add('F12', '全部当事人', '拟处罚罚款合计', '316', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、责令登云股份改正，给予警告，并处以 60 万元的罚款'), unit='万元',
      derivation=dict(rule='60+30×2+(20+15)+10×5+9×4+8×3+7+6×2+6×2+5×3+5=316万', parties=26,
                      note='罚款金额与主体D1→D2零变化；仅项次合并/拆分（11项→10项）'))
t.add('F13', '王玉枢', '处理结果', '已逝世，不再追究相关责任', 'text', True, ['D1'], 'text', '王玉枢', '追究',
      t.ev('D1', '十二、王玉枢已逝世，不再追究相关责任'))
t.add('F14', '欧洪先、潘炜', '拟市场禁入措施', '5年证券市场禁入', 'text', True, ['D1'], 'text', '欧洪先', '禁入',
      t.ev('D1', '我会拟对欧洪先、潘炜分别采取 5 年证券市场禁入措施'))
t.add_unknown('F15', '欧洪先、潘炜', '市场禁入措施终局结果', 'text', ['D2'], 'text',
              t.ev('D2', '十、对苏武俊、张江洋、许建生、叶景年给予警告，并分别处以 5 万元的罚款。上述当事人应自收到本处罚决定书之日起 15 日内'),
              'D2为《行政处罚决定书》公告，未载市场禁入决定；池内无单独市场禁入决定书，终局是否采取无法由D1/D2确认')
t.add('F16', '登云股份', '违法行为定性', 'IPO申请文件存在虚假记载、重大遗漏', 'text', True, ['D1', 'D2'], 'text', '登云股份', '虚假记载',
      t.ev('D1', '登云股份首次公开发行股票并在中小板上市（以下简称 IPO）申请文件存在虚假记载、重大遗漏'))
t.add('F17', '登云股份', '立案调查收到日期', '2015-10-20', 'date', True, ['D1', 'D2'], 'date', '登云股份', '立案',
      t.ev('D2', '于 2015 年 10 月 20 日收') + t.ev('D1', '于 2015 年 10 月 20 日收'))
t.add('F18', '登云股份', '事先告知书收到日期', '2017-04-28', 'date', True, ['D1'], 'date', '登云股份', '告知书',
      t.ev('D1', '2017 年 4 月 28 日，公司及张弢、欧洪先、罗天友、李区、符麟军、杨华健'))
t.add('F19', '登云股份', '行政处罚决定书收到日期', '2017-06-05', 'date', True, ['D2'], 'date', '登云股份', '决定书',
      t.ev('D2', '2017 年 6 月 5 日，公司及张弢、欧洪先、罗天友、李区、符麟军、杨华健'))
t.add('F20', '行政处罚及市场禁入事先告知书', '文号', '处罚字[2017]42号', 'text', False, ['D1'], 'doc_number', None, '文号',
      t.ev('D1', '处罚字[2017]42 号'))
results.append(t.write(
    'DG_002715', 'P2_DG_002715_PENALTY',
    'P2-C 确认实验任务。26主体、10个金额档的密集分档结构；金额零变化但项次重组（拆分/合并），并含"逝世不追究"条款与终局未知的禁入——考察对结构重排的鲁棒性。',
    '登云股份IPO信息披露违法案：终罚各主体金额？合计？拟罚合计？D1到D2有何变化？王玉枢如何处理？欧洪先、潘炜拟市场禁入措施？违法行为定性？立案、告知书、决定书日期？告知书文号？',
    '2017-06-05',
    '关于收到中国证券监督管理委员会《行政处罚及市场禁入事先告知书》的公告（2017-04-28收到，处罚字[2017]42号）',
    '关于收到中国证券监督管理委员会《行政处罚决定书》的公告（2017-06-05收到，[2017]60号）',
    dict(final_lines_D2=[['登云股份', 60], ['欧洪先、潘炜', 30], ['张弢', 20], ['邓剑雄', 15], ['罗天友等5人', 10],
                         ['刘永朱等4人', 9], ['钱艺等3人', 8], ['李盘生', 7], ['邓晶等4人', 6], ['苏武俊等4人', 5]],
         proposed_lines_D1='金额与主体同final_lines_D2；项次为11项（张弢/邓剑雄同项，6万档与5万档各分两项）+第十二项王玉枢逝世不追究',
         final_total_wan=316, proposed_total_wan=316,
         changes='金额零变化；项次重组；禁入终局UNKNOWN',
         market_bans=dict(proposed=['欧洪先5年', '潘炜5年'], final='UNKNOWN'),
         aliases=[dict(canonical='怀集登云汽配股份有限公司', variants=['登云股份', '公司'], where='both docs')]),
    [dict(issue='扫描表"25主体/9档/256万"与逐条核实26主体/10档/316万不符', handling='以逐条核实为准'),
     dict(issue='D1第七项"对李盘生……并分别处以7万元"对单人用"分别"', handling='照录原文，不影响金额'),
     dict(issue='D2未载禁入决定，池内无单独禁入决定书', handling='F15终局标UNKNOWN，不推断"未采取"')],
    60 + 60 + 20 + 15 + 50 + 36 + 24 + 7 + 24 + 20 == 316 and 60 + 60 + 35 + 50 + 36 + 24 + 7 + 12 + 12 + 15 + 5 == 316))

# =====================================================================================
# 3. *ST红相 300427 — 2023-05-11立案 厦证监处罚字[2024]1号 → [2024]1号处罚+[2024]1号禁入
#    D1 为2024-03-01公告中转述的告知书摘要（个人拟罚金额未披露）
# =====================================================================================
t = Task('300427_notice_1709295394000.pdf.txt', '300427_decision_1712157889000.pdf.txt')
t.add('F1', '红相股份有限公司', '行政处罚罚款金额（四项合并）', '2513', 'number', True, ['D1', 'D2'], 'amount', '红相股份', '罚款',
      t.ev('D2', '1.对红相股份责令改正，给予警告，并处以 2,513 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='2513万元', d2_final='2513万元', change='unchanged'))
t.add('F2', '杨成', '行政处罚罚款金额（四项合并）', '2288', 'number', True, ['D2'], 'amount', '杨成', '罚款',
      t.ev('D2', '2.对杨成给予警告，并处以 2,288 万元罚款'), unit='万元')
t.add('F3', '何东武', '行政处罚罚款金额（四项合并）', '365', 'number', True, ['D2'], 'amount', '何东武', '罚款',
      t.ev('D2', '3.对何东武给予警告，并处以 365 万元罚款'), unit='万元')
t.add('F4', '吴章坤', '行政处罚罚款金额（四项合并）', '330', 'number', True, ['D2'], 'amount', '吴章坤', '罚款',
      t.ev('D2', '4.对吴章坤给予警告，并处以 330 万元罚款'), unit='万元')
t.add('F5', '廖雪林、马露萍', '单人行政处罚罚款金额（四项合并）', '305', 'number', False, ['D2'], 'amount', '廖雪林', '罚款',
      t.ev('D2', '5.对廖雪林、马露萍给予警告，并分别处以 305 万元罚款'), unit='万元')
t.add('F6', '李喜娇', '行政处罚罚款金额（四项合并）', '250', 'number', False, ['D2'], 'amount', '李喜娇', '罚款',
      t.ev('D2', '6.对李喜娇给予警告，并处以 250 万元罚款'), unit='万元')
t.add('F7', '张青、陈水明', '单人行政处罚罚款金额（四项合并）', '75', 'number', False, ['D2'], 'amount', '张青', '罚款',
      t.ev('D2', '6.对李喜娇给予警告，并处以 250 万元罚款；7.对张青、陈水明给予警告，并分别处以 75 万元罚款'), unit='万元')
t.add('F8', '吕坚', '行政处罚罚款金额（四项合并）', '50', 'number', False, ['D2'], 'amount', '吕坚', '罚款',
      t.ev('D2', '7.对张青、陈水明给予警告，并分别处以 75 万元罚款；8.对吕坚给予警告，并处以 50 万元罚款。上述当事人应自收到本处罚决定书之日起'),
      unit='万元')
t.add('F9', '全部当事人', '罚款合计（四项合并）', '6556', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '综合上述四项：'), unit='万元',
      derivation=dict(rule='2513+2288+365+330+305×2+250+75×2+50=6556万', parties=10,
                      note='以"综合上述四项"合并段为终罚；四项分项罚款段不得重复加总'))
t.add_unknown('F10', '全部当事人', '拟处罚罚款合计', 'number', ['D1'], 'penalty_line_sum',
              t.ev('D1', '给予警告，并分别处以不同金额的罚款'),
              '当前D1为2024-03-01公告对告知书的转述摘要（非告知书原文），仅载公司拟罚2513万，九名个人仅称"分别处以不同金额的罚款"；拟罚合计不可得。不得计为0，不得由终罚金额倒推')
t.add('F11', '个人当事人（杨成等9人）', '当前D1（告知书转述摘要）对个人拟罚金额的披露情况', '当前D1未披露具体数字（仅称"分别处以不同金额的罚款"）', 'text', True, ['D1'], 'text', '杨成', '罚款',
      t.ev('D1', '给予警告，并分别处以不同金额的罚款'),
      derivation=dict(scope='仅断言当前D1摘要未披露；不断言告知书原文未载明，也不断言拟罚金额不存在',
                      forbidden=['将个人拟罚计为0', '由终罚金额倒推拟罚金额', '将D1摘要表述为告知书原文']))
t.add('F12', '杨成', '市场禁入措施', '终身市场禁入', 'text', True, ['D1', 'D2'], 'text', '杨成', '禁入',
      t.ev('D2', '对杨成采取终身市场禁入措施') + t.ev('D1', '拟对杨成采取终身市场禁入措施'),
      dual_stage=dict(d1_proposed='终身', d2_final='终身', change='unchanged'))
t.add('F13', '何东武', '市场禁入措施', '5年市场禁入', 'text', True, ['D1', 'D2'], 'text', '何东武', '禁入',
      t.ev('D2', '我局决定：对何东武采取 5 年市场禁入措施') + t.ev('D1', '拟对何东武采取 5 年市场禁入措施'),
      dual_stage=dict(d1_proposed='5年', d2_final='5年', change='unchanged'))
t.add('F14', '红相股份', '违法行为定性（信息披露）', '2017年-2022年年度报告存在虚假记载', 'text', True, ['D2'], 'text', '红相股份', '虚假记载',
      t.ev('D2', '红相股份 2017 年-2022 年年度报告存在虚假记载'))
t.add('F15', '红相股份', '违法行为定性（发行）', '2020年申请发行股份及支付现金购买资产并募集配套资金涉嫌欺诈发行', 'text', False, ['D1', 'D2'], 'text', '红相股份', '欺诈发行',
      t.ev('D1', '2020 年申请发行股份及支付现金购买资产并募集配套资金涉嫌欺诈发行'))
t.add('F16', '红相股份', '2017年虚增营业收入', '10489.44', 'number', True, ['D2'], 'amount', '红相股份', '营业收入',
      t.ev('D2', '2017 年虚增营业收入 10,489.44 万元，虚增利润总额 5,972.44 万元'), unit='万元')
t.add('F17', '红相股份', '立案告知书收到日期', '2023-05-11', 'date', True, ['D1', 'D2'], 'date', '红相股份', '立案',
      t.ev('D2', '于 2023 年 5 月 11 日收到中国证券') + t.ev('D1', '公司于 2023 年 5 月 11 日收到中国证券监督管理委员会'))
t.add('F18', '红相股份', '事先告知书收到日期', '2024-02-27', 'date', True, ['D1', 'D2'], 'date', '红相股份', '告知书',
      t.ev('D2', '2024 年 2 月 27 日，公司及相关当事人收到中国证券监督管理委员会厦门监管局下发的《行政处罚及市场禁入事先告知书》（厦证监处罚字[2024]1 号）') +
      t.ev('D1', '2024 年 2 月 27 日，公司及杨成先生等人收到中国证券监督管理委员'))
t.add('F19', '红相股份', '行政处罚决定书收到日期', '2024-04-03', 'date', True, ['D2'], 'date', '红相股份', '决定书',
      t.ev('D2', '2024 年 4 月 3 日，公司及相关当事人收到中国证券监督管理委员会厦门监'))
t.add('F20', '行政处罚决定书', '文号', '[2024]1号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '（[2024]1 号）及《市场禁入决定书》'))
results.append(t.write(
    'HX_300427', 'P2_HX_300427_PENALTY',
    'P2-C 确认实验任务。D2含四项违法分项罚款段+"综合上述四项"合并段（终罚须取合并段，防重复加总）；D1为另一公告对告知书的转述摘要（非告知书原文），个人拟罚金额在该摘要中未披露——考察多段汇总与证据边界识别（不得倒推、不得计0）。',
    '红相股份违法案：合并后终罚各主体金额？合计？拟罚合计能否确定？个人拟罚金额D1是否披露？杨成、何东武市场禁入？违法行为定性？2017年虚增营业收入？立案、告知书、决定书日期？决定书文号？',
    '2024-04-03',
    '红相股份2024-03-01公告（非告知书原公告；其中转述厦证监处罚字[2024]1号告知书主要内容）',
    '关于收到《行政处罚决定书》及《市场禁入决定书》的公告（2024-04-03收到，[2024]1号）',
    dict(final_lines_D2=[['红相股份', 2513], ['杨成', 2288], ['何东武', 365], ['吴章坤', 330], ['廖雪林、马露萍', 305],
                         ['李喜娇', 250], ['张青、陈水明', 75], ['吕坚', 50]],
         proposed_lines_D1=[['红相股份', 2513], ['杨成等9人', '当前D1未披露具体数字']],
         final_total_wan=6556, proposed_total_wan='UNKNOWN',
         changes='公司与禁入不变；个人金额D1未披露，阶段变化不可判定',
         market_bans=dict(lifetime=['杨成'], five_year=['何东武'], proposed_identical=True),
         aliases=[dict(canonical='红相股份有限公司', variants=['红相股份', '公司'], where='both docs')]),
    [dict(issue='D1非告知书原公告（2024-018未入池），而是2024-03-01公告对告知书的转述摘要', handling='仅对D1明载的事实设槽；拟罚合计设UNKNOWN；论文须如实说明D1来源性质（操作员批2裁决：有条件通过）'),
     dict(issue='三个概念须区分：当前D1摘要未披露 / 告知书原文未披露 / 拟罚金额不存在', handling='证据只支持第一项；F10 UNKNOWN不计0，F11仅断言第一项'),
     dict(issue='扫描表"13主体/22档/12124万"系四项分项段与合并段全部加总的过计', handling='终罚以"综合上述四项"合并段6556万为准'),
     dict(issue='池内decision_1712923461000（2024-04-12，〔2024〕5号等）为另一文书', handling='不纳入本合同')],
    2513 + 2288 + 365 + 330 + 610 + 250 + 150 + 50 == 6556))

# =====================================================================================
# 4. ST易事特 300376 — 2023立案 处罚字[2024]88号 → [2024]147号  (2018年[2018]36号为另案)
# =====================================================================================
t = Task('300376_notice_1720169107000.pdf.txt', '300376_decision_1735660800000.pdf.txt')
t.add('F1', '易事特集团股份有限公司', '行政处罚罚款金额', '800', 'number', True, ['D1', 'D2'], 'amount', '易事特', '罚款',
      t.ev('D2', '一、对易事特集团股份有限公司责令改正，给予警告，并处以 800 万元罚款') +
      t.ev('D1', '对易事特集团股份有限公司责令改正，给予警告，并处以 800 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='800万元', d2_final='800万元', change='unchanged'))
t.add('F2', '何思模', '行政处罚罚款金额', '1000', 'number', True, ['D1', 'D2'], 'amount', '何思模', '罚款',
      t.ev('D2', '二、对原实际控制人何思模处以 1000 万元罚款') + t.ev('D1', '对原实际控制人何思模处以 1000 万罚款'), unit='万元',
      derivation=dict(note='何思模未被"给予警告"，仅罚款；D1写"1000万罚款"缺"元"字'))
t.add('F3', '何佳', '行政处罚罚款金额', '400', 'number', True, ['D1', 'D2'], 'amount', '何佳', '罚款',
      t.ev('D2', '三、对何佳给予警告，并处以 400 万元罚款'), unit='万元')
t.add('F4', '张顺江', '行政处罚罚款金额', '300', 'number', False, ['D1', 'D2'], 'amount', '张顺江', '罚款',
      t.ev('D2', '四、对张顺江给予警告，并处以 300 万元罚款'), unit='万元')
t.add('F5', '陈硕等5人', '单人行政处罚罚款金额', '80', 'number', False, ['D1', 'D2'], 'amount', '陈硕', '罚款',
      t.ev('D2', '五、对陈硕、胡志强、鄢银科、赵久红、时小莉给予警告，并分别处以 80 万元罚款'), unit='万元')
t.add('F6', '肖大志、牛鸿、于玮、万祖岩、王进军', '单人行政处罚罚款金额', '50', 'number', True, ['D2'], 'amount', '肖大志', '罚款',
      t.ev('D2', '六、对肖大志、牛鸿、于玮、万祖岩、王进军给予警告，并分别处以 50 万元罚款'), unit='万元',
      dual_stage=dict(d1_proposed='7人各50万（含关易波、林丹丹）', d2_final='5人各50万', change='members_not_restated_in_D2'))
t.add('F7', '全部当事人', '罚款合计', '3150', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对易事特集团股份有限公司责令改正，给予警告，并处以 800 万元罚款'), unit='万元',
      derivation=dict(rule='800+1000+400+300+80×5+50×5=3150万', parties=14))
t.add('F8', '全部当事人', '拟处罚罚款合计', '3250', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '对易事特集团股份有限公司责令改正，给予警告，并处以 800 万元罚款'), unit='万元',
      derivation=dict(rule='800+1000+400+300+80×5+50×7=3250万', parties=16, note='差100万=关易波、林丹丹（各拟50万）D2未再载明；该差额是文书记载差，不代表二人终罚为0'))
t.add('F9', '关易波', '拟处罚记录与D2载明情况', 'D1拟50万元；D2未再载明对应处罚', 'text', True, ['D1', 'D2'], 'text', '关易波', '罚款',
      t.ev('D1', '对肖大志、牛鸿、关易波、林丹丹、于玮、万祖岩、王进军给予警告，并分别处以 50 万元罚款') +
      t.ev('D2', '六、对肖大志、牛鸿、于玮、万祖岩、王进军给予警告，并分别处以 50 万元罚款'),
      dual_stage=dict(d1_proposed='50万元', d2_final='D2未再载明对应处罚（D2全文未出现且未作说明；不认定为法律意义上的撤销，终罚不计为0）', change='not_restated_in_D2'))
t.add('F10', '林丹丹', '拟处罚记录与D2载明情况', 'D1拟50万元；D2未再载明对应处罚', 'text', True, ['D1', 'D2'], 'text', '林丹丹', '罚款',
      t.ev('D1', '对肖大志、牛鸿、关易波、林丹丹、于玮、万祖岩、王进军给予警告，并分别处以 50 万元罚款') +
      t.ev('D2', '六、对肖大志、牛鸿、于玮、万祖岩、王进军给予警告，并分别处以 50 万元罚款'),
      dual_stage=dict(d1_proposed='50万元', d2_final='D2未再载明对应处罚（D2全文未出现且未作说明；不认定为法律意义上的撤销，终罚不计为0）', change='not_restated_in_D2'))
t.add('F11', '何思模', '市场禁入措施', '10年市场禁入', 'text', True, ['D1', 'D2'], 'text', '何思模', '禁入',
      t.ev('D2', '我会决定：对何思模采取 10 年市场禁入措施') + t.ev('D1', '我会拟决定，对何思模采取 10 年市场禁入措施'),
      dual_stage=dict(d1_proposed='10年', d2_final='10年', change='unchanged'))
t.add('F12', '易事特', '违法行为定性', '通过开展虚假贸易业务虚增营业收入、营业成本、利润总额', 'text', True, ['D1', 'D2'], 'text', '易事特', '虚增',
      t.ev('D1', '易事特涉嫌通过开展虚假贸易业务虚增营业收入、营业成本、利润总'))
t.add('F13', '易事特', '2019年虚增营业收入', '32924.09', 'number', True, ['D1', 'D2'], 'amount', '易事特', '营业收入',
      t.ev('D2', '营业收入 329,240,857.67 元，占当年披露营业收入的 9.84%') +
      t.ev('D1', '易事特涉嫌虚增营业收入 329,240,857.67 元，占当年披露营业收入的 9.84%'), unit='万元',
      derivation=dict(original_yuan='329,240,857.67', standard_wan='32924.09', note='占当年披露营业收入9.84%'))
t.add('F14', '易事特', '立案告知书公告披露日期', '2023-05-11', 'date', True, ['D1', 'D2'], 'date', '易事特', '立案',
      t.ev('D2', '于 2023 年 5 月 11 日披露《关于公司及第一大股东之控制人收到中国证券监督管理委员会立案告知书的公告》'),
      derivation=dict(note='两文书均以披露日表述（公告2023-034），未载收到日'))
t.add('F15', '易事特', '事先告知书公告披露日期', '2024-07-05', 'date', True, ['D2'], 'date', '易事特', '告知书',
      t.ev('D2', '公司于 2024 年 7 月 5 日披露《关于收到中国证券监督管理委员会<行政处罚及市场禁入事先告知书>的公告》'),
      derivation=dict(note='D1仅称"近日"收到；D2给出告知书公告披露日（公告2024-037）'))
t.add('F16', '易事特', '行政处罚决定书收到日期', '2024-12-31', 'date', True, ['D2'], 'date', '易事特', '决定书',
      t.ev('D2', '2024 年 12 月 31 日，公司及相关当事人收到中国证监会下发的《行政处罚决定书》（[2024]147 号）'))
t.add('F17', '行政处罚决定书', '文号', '[2024]147号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《行政处罚决定书》（[2024]147 号）'))
t.add('F18', '行政处罚及市场禁入事先告知书', '文号', '处罚字[2024]88号', 'text', False, ['D1', 'D2'], 'doc_number', None, '文号',
      t.ev('D1', '（处罚字[2024]88 号）'))
results.append(t.write(
    'YS_300376', 'P2_YS_300376_PENALTY',
    'P2-C 确认实验任务。大额（实控人1000万、公司800万）、14主体；阶段变化=同档组内2人（关易波、林丹丹）D1拟罚、D2未再载明且无说明——须比对名单才能发现，且不得升级为"已撤销"的法律结论。',
    '易事特信息披露违法案（2023立案）：终罚各主体金额？合计？拟罚合计？关易波、林丹丹拟罚与终局？何思模市场禁入？违法行为定性？2019年虚增营业收入？立案、告知书公告日与决定书收到日？两文书文号？',
    '2024-12-31',
    '关于收到中国证券监督管理委员会《行政处罚及市场禁入事先告知书》的公告（2024-07-05，处罚字[2024]88号）',
    '关于收到中国证券监督管理委员会《行政处罚决定书》的公告（2024-12-31收到，[2024]147号）',
    dict(final_lines_D2=[['易事特', 800], ['何思模', 1000], ['何佳', 400], ['张顺江', 300], ['陈硕等5人', 80], ['肖大志等5人', 50]],
         proposed_lines_D1=[['易事特', 800], ['何思模', 1000], ['何佳', 400], ['张顺江', 300], ['陈硕等5人', 80], ['肖大志等7人（含关易波、林丹丹）', 50]],
         final_total_wan=3150, proposed_total_wan=3250,
         changes=[dict(party='关易波', d1=50, d2=None, note='D2未再载明对应处罚'), dict(party='林丹丹', d1=50, d2=None, note='D2未再载明对应处罚')],
         market_bans=dict(ten_year=['何思模'], proposed_identical=True),
         aliases=[dict(canonical='易事特集团股份有限公司', variants=['易事特', '公司'], where='both docs'),
                  dict(canonical='何思模', variants=['原实际控制人', '第一大股东之控制人'], where='both docs')]),
    [dict(issue='池内decision_1527242428000（2018，[2018]36号，调查通字171986）为另案', handling='不纳入'),
     dict(issue='关易波、林丹丹D1列入拟处罚，D2全文不出现、未作说明', handling='F9/F10表述为"D2未再载明对应处罚"，不认定为撤销，终罚不计为0（操作员批2裁决：修订后通过）'),
     dict(issue='D1"何思模处以1000万罚款"缺"元"字', handling='照录原文')],
    800 + 1000 + 400 + 300 + 400 + 250 == 3150 and 800 + 1000 + 400 + 300 + 400 + 350 == 3250))

# =====================================================================================
# 5. ST特信 000070 — 2023-05-07立案 〔2024〕9号告知书 → 〔2024〕9号决定书（深圳局）
# =====================================================================================
t = Task('000070_notice_1715529600000.pdf.txt', '000070_decision_1720195200000.pdf.txt')
t.add('F1', '深圳市特发信息股份有限公司', '行政处罚罚款金额', '800', 'number', True, ['D1', 'D2'], 'amount', '特发信息', '罚款',
      t.ev('D2', '一、对深圳市特发信息股份有限公司给予警告，并处以 800 万元罚款') +
      t.ev('D1', '一、对深圳市特发信息股份有限公司给予警告，并处以 800 万元的罚款'), unit='万元',
      dual_stage=dict(d1_proposed='800万元', d2_final='800万元', change='unchanged'))
t.add('F2', '蒋勤俭', '行政处罚罚款金额', '400', 'number', True, ['D1', 'D2'], 'amount', '蒋勤俭', '罚款',
      t.ev('D2', '二、对蒋勤俭给予警告，并处以 400 万元罚款'), unit='万元')
t.add('F3', '陈传荣', '行政处罚罚款金额', '350', 'number', True, ['D1', 'D2'], 'amount', '陈传荣', '罚款',
      t.ev('D2', '三、对陈传荣给予警告，并处以 350 万元罚款'), unit='万元')
t.add('F4', '易宗湘', '行政处罚罚款金额', '200', 'number', True, ['D1', 'D2'], 'amount', '易宗湘', '罚款',
      t.ev('D2', '四、对易宗湘给予警告，并处以 200 万元罚款'), unit='万元')
t.add('F5', '杨洪宇、李增民', '单人行政处罚罚款金额', '150', 'number', False, ['D1', 'D2'], 'amount', '杨洪宇', '罚款',
      t.ev('D2', '五、对杨洪宇、李增民给予警告，并分别处以 150 万元罚款'), unit='万元')
t.add('F6', '张大军、王凌、刘颖', '单人行政处罚罚款金额', '100', 'number', False, ['D1', 'D2'], 'amount', '张大军', '罚款',
      t.ev('D2', '六、对张大军、王凌、刘颖给予警告，并分别处以 100 万元罚款'), unit='万元')
t.add('F7', '全部当事人', '罚款合计', '2350', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
      t.ev('D2', '一、对深圳市特发信息股份有限公司给予警告，并处以 800 万元罚款'), unit='万元',
      derivation=dict(rule='800+400+350+200+150×2+100×3=2350万', parties=9))
t.add('F8', '全部当事人', '拟处罚罚款合计', '2350', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
      t.ev('D1', '一、对深圳市特发信息股份有限公司给予警告，并处以 800 万元的罚款'), unit='万元',
      derivation=dict(rule='800+400+350+200+150×2+100×3=2350万（与D2逐项一致）', parties=9))
t.add('F9', '全部处罚事项', 'D1拟罚→D2终罚阶段变化', '无变化（6项罚款、9主体、3项市场禁入均逐项一致）', 'text', True, ['D1', 'D2'], 'text', None, '阶段变化',
      t.ev('D1', '六、对张大军、王凌、刘颖给予警告，并分别处以 100 万元罚款') +
      t.ev('D2', '六、对张大军、王凌、刘颖给予警告，并分别处以 100 万元罚款'),
      dual_stage=dict(d1_proposed='2350万+3项禁入', d2_final='2350万+3项禁入', change='none'))
BANS_D2 = '对蒋勤俭采取 10 年证券市场禁入措施，对陈传荣采取 8 年证券市场禁入措施，对易宗湘采取 6 年证券市场禁入措施'
t.add('F10', '蒋勤俭', '市场禁入措施', '10年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '蒋勤俭', '禁入',
      t.ev('D2', BANS_D2) + t.ev('D1', '勤俭采取 10 年证券市场禁入措施'))
t.add('F11', '陈传荣', '市场禁入措施', '8年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '陈传荣', '禁入',
      t.ev('D2', BANS_D2) + t.ev('D1', '对陈传荣采取 8 年证券市场禁入'))
t.add('F12', '易宗湘', '市场禁入措施', '6年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '易宗湘', '禁入',
      t.ev('D2', BANS_D2) + t.ev('D1', '对易宗湘采取 6 年证券市场禁入措施'))
t.add('F13', '特发东智（子公司）', '2019年虚构销售业务虚增营业收入', '32755.30', 'number', True, ['D1', 'D2'], 'amount', '特发东智', '营业收入',
      t.ev('D2', '虚增营业收入 32,755.30 万元、营业成本 28,368.59 万元，虚增利润总额 4,386.71 万元'), unit='万元',
      derivation=dict(note='同句：虚增营业成本28,368.59万元、虚增利润总额4,386.71万元'))
t.add('F14', '特发信息', '立案告知书收到日期', '2023-05-07', 'date', True, ['D1', 'D2'], 'date', '特发信息', '立案',
      t.ev('D2', '于 2023 年 5 月 7 日收到中国证券监督管理委员会'))
t.add('F15', '特发信息', '事先告知书收到日期', '2024-05-10', 'date', True, ['D1', 'D2'], 'date', '特发信息', '告知书',
      t.ev('D1', '2024 年 5 月 10 日，深圳市特发信息股份有限公司') + t.ev('D2', '2024 年 5 月 10 日，公司及相关人员收到中国证监会深圳监管局'))
t.add_unknown('F16', '特发信息', '行政处罚决定书收到日期', 'date', ['D2'], 'date',
              t.ev('D2', '近日，公司及当事人收到中国证监会深圳监管局出具的《行政处罚决定书》（〔2024〕9 号）'),
              'D2仅载"近日"收到；公告落款二〇二四年七月八日为披露日，不作为收到日（与*ST昆机F17同一处理）')
t.add('F17', '行政处罚决定书', '文号', '〔2024〕9号', 'text', False, ['D2'], 'doc_number', None, '文号',
      t.ev('D2', '《行政处罚决定书》（〔2024〕9 号）'))
results.append(t.write(
    'TX_000070', 'P2_TX_000070_PENALTY',
    'P2-C 确认实验任务。零变化型（与ST东洋同型）：9主体2350万+3人分级禁入（10/8/6年）D1=D2；决定书收到日UNKNOWN。',
    '特发信息信息披露违法案：终罚各主体金额？合计？拟罚合计？D1到D2有何变化？蒋勤俭、陈传荣、易宗湘市场禁入措施？2019年特发东智虚增营业收入？立案、告知书日期？决定书收到日期能否确定？决定书文号？',
    '2024-07-08',
    '关于收到《行政处罚及市场禁入事先告知书》的公告（2024-05-10收到，〔2024〕9号）',
    '关于收到《行政处罚决定书》的公告（2024-07-08公告，〔2024〕9号）',
    dict(final_lines_D2=[['特发信息', 800], ['蒋勤俭', 400], ['陈传荣', 350], ['易宗湘', 200], ['杨洪宇、李增民', 150], ['张大军、王凌、刘颖', 100]],
         proposed_lines_D1='与final_lines_D2完全一致',
         final_total_wan=2350, proposed_total_wan=2350, changes='无',
         market_bans=dict(ten_year=['蒋勤俭'], eight_year=['陈传荣'], six_year=['易宗湘'], proposed_identical=True),
         aliases=[dict(canonical='深圳市特发信息股份有限公司', variants=['特发信息', '公司'], where='both docs'),
                  dict(canonical='深圳特发东智科技有限公司', variants=['特发东智'], where='both docs')]),
    [dict(issue='告知书与决定书均编号〔2024〕9号（深圳局两类文书分别编号）', handling='文号槽仅取决定书，并在文书标题中注明'),
     dict(issue='池内notice_1716375680000（【2024】238号）为另一文书', handling='不纳入'),
     dict(issue='决定书收到日仅"近日"', handling='F16标UNKNOWN')],
    800 + 400 + 350 + 200 + 300 + 300 == 2350))

print('ALL OK' if all(results) else 'FAILURES PRESENT')
sys.exit(0 if all(results) else 1)
