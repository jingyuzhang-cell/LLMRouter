"""Build the frozen task set + PRIVATE scoring references for cap_eval_bench_v1.

PUBLIC  -> tasks/tasks_frozen.jsonl : question, cutoff, evidence doc_ids, deliverable
           schema, UNKNOWN boundary, per-task budgets/deadline (identical for all systems)
PRIVATE -> tasks/tasks_private.jsonl + scoring/silver/*.json : silver facts (verbatim
           quotes, deterministic grounding enforced here), branch descriptors (expected
           multi-branch evidence fusion — NEVER exposed to planners/selectors).
Silver = machine-built, auto-verified. Gold requires human adjudication (see gold/).
"""
import json
import re
from pathlib import Path

from pilot_common import norm  # reuse normaliser from the frozen pilot (read-only import)

BENCH = Path('/root/cap_eval_bench_v1')
TEXTS = BENCH / 'evidence' / 'texts'

# ---------------- silver fact tables (doc_id, quote, answer, type) ----------------
SHUNTIAN_VERIFIED = [  # ported from capital_opinion_pilot/facts_silver.json (verified tier)
    ('date', '公司收到证监会《立案告知书》的日期', '2022-11-04', 'st_announce_2024_020',
     '于2022年11月4日收到中国证券监督管理委员会下发的《立案告知书》'),
    ('date', '公司收到《行政处罚及市场禁入事先告知书》（处罚字〔2023〕37号）的日期', '2023-06-30',
     'st_advance_notice_2023', '2023年6月30日，公司收到中国证券监督管理委员会出具的《行政处罚及市场禁入事先告知书》'),
    ('amount', '2009年至2021年年度报告共计虚增营业收入的金额', '10,333,448,392.98元', 'csrc_penalty_2024_41',
     '2009年至2021年年度报告共计虚增营业收入10,333,448,392.98元'),
    ('text', '江苏舜天参与的专网通信业务被认定为何种性质', '隋某力主导的专网通信虚假自循环业务，无商业实质',
     'csrc_penalty_2024_41', '实质是合同、资金、票据流转构成闭环的虚假自循环业务,无商业实质'),
    ('date', '公司股票实施其他风险警示前的停牌日期', '2024-07-08', 'st_announce_2024_021', '停牌日期为2024年7月8日'),
    ('date', '公司股票实施其他风险警示的起始日期', '2024-07-09', 'st_announce_2024_021', '实施其他风险警示的起始日：2024年7月9日'),
    ('text', '实施其他风险警示后公司A股简称变更为', 'ST舜天', 'st_announce_2024_021', 'A股股票简称由“江苏舜天”变更为“ST舜天”'),
    ('amount', '实施其他风险警示后日涨跌幅限制', '5%', 'st_announce_2024_021', '实施其他风险警示后股票价格的日涨跌幅限制为5%'),
]
KDX = [  # ported from v3_evidence/A_kangdexin/facts_seed.json
    ('date', '康得新公司及实控人收到《行政处罚决定书》的日期', '2020-09-27', 'kdx_penalty_2020',
     '2020年9月27日，公司及公司实际控制人钟玉先生收到了证监会下发的'),
    ('amount', '处罚决定书对康得新公司处以的罚款金额', '60万元', 'kdx_penalty_2020',
     '对康得新复合材料集团股份有限公司责令改正，给予警告，并处以60万元罚款'),
    ('amount', '2015年年度报告虚增利润总额', '2,242,745,642.37元', 'kdx_penalty_2020',
     '虚增利润总额分别为2,242,745,642.37元、2,943,420,778.01元'),
    ('text', '康得新财务造假的主要方式', '虚构销售业务、虚构采购、生产、研发、产品运输费用', 'kdx_penalty_2020',
     '通过虚构销售业务、虚构采购、生产、研发、产品运输费用等方式'),
    ('text', '2015-2018年年报中哪类银行相关数据被认定虚假记载', '银行存款余额', 'kdx_penalty_2020',
     '2015年至2018年年度报告中披露的银行存款余额存在虚假记载'),
    ('text', '徐曙、张丽雄被采取的市场禁入年限', '10年', 'kdx_penalty_2020', '对徐曙、张丽雄分别采取10年证券市场禁入措施'),
    ('text', '公司自查发现北京银行《现金管理业务合作协议》未经哪些机构批准', '董事会和股东大会',
     'kdx_inquiry_2018', '北京银行签订《现金管理业务合作协议》的行为，未经公司董事会和股东大会的批准'),
]
KDX_D2_EXTRA = [
    ('amount', '2019年年报问询中披露的北京银行西单支行账户显示金额与实际余额', '显示122.09亿元，实际余额101.17元',
     'kdx_inquiry_2019', '存放于北京银行西单支行的金额122.09亿元，而该金额为银行归集金额，实际余额仅为101.17元'),
    ('text', '康得新2019年年报问询函的文号', '中小板年报问询函【2020】第364号', 'kdx_inquiry_2019',
     '《关于对康得新复合材料集团股份有限公司2019年年报的问询函》（中小板年报问询函【2020】第364号）'),
]
YJT = [  # ported from v3_evidence/B_yujingangshi/facts_seed.json
    ('text', '豫金刚石《行政处罚及市场禁入事先告知书》文号', '处罚字〔2021〕65号', 'yjt_notice_2021',
     '《行政处罚及市场禁入事先告知书》（处罚字〔2021〕65号）'),
    ('date', '豫金刚石收到事先告知书的日期', '2021-08-13', 'yjt_notice_2021', '于2021年8月13日收到'),
    ('date', '豫金刚石收到证监会立案相关文书的日期', '2020-04-07', 'yjt_notice_2021', '于2020年4月7日收到'),
    ('text', '拟对郭留希采取的市场禁入措施', '终身市场禁入', 'yjt_notice_2021', '对郭留希采取终身市场禁'),
    ('text', '被拟采取10年市场禁入的责任人员（任一）', '刘永奇', 'yjt_notice_2021', '对刘永奇采取10年市场禁入措施'),
    ('text', '告知书查明的涉嫌违法事实核心（2019年末）', '虚增净资产', 'yjt_notice_2021', '2019年末虚增净资产'),
]
SJZG = [  # ported from v3_evidence/C_shijuezhongguo/facts_seed.json
    ('date', '视觉中国公告中网友举报/网信办约谈对应日期', '2019-04-11', 'sjzg_suspend_2019', '2019年4月11日，经网友举报'),
    ('text', '责令视觉中国网站整改的监管主体', '天津市互联网信息办公室', 'sjzg_suspend_2019',
     '天津市互联网信息办公室依法约谈公司网站负责人'),
    ('text', '股票异常波动涉及的两个交易日', '2019-04-15与2019-04-16', 'sjzg_abnormal_2019',
     '连续两个交易日内（2019年4月15日、4月16日）跌幅偏离值累计达到20%以上'),
    ('amount', '子公司汉华易美被处的行政罚款金额', '三十万元', 'sjzg_resume_2019', '接受罚款三十万元的行政处罚'),
    ('text', '收到天津市网信办行政处罚决定书的子公司', '汉华易美(天津)图像技术有限公司', 'sjzg_resume_2019',
     '公司全资子公司汉华易美(天津)图像技术有限公司收到天津市互联网信息办公室行政处罚决定书'),
    ('text', '对汉华易美的行政处罚决定书文号', '津网信罚决字【2019】第1号', 'sjzg_resume_2019', '《津网信罚决字【2019】第1号》'),
]
MD = [
    ('date', '美的集团收到证监会核准批复的日期', '2019-03-12', 'md_approval_2019', '于2019年3月12日收到中国证券监督管理委员会'),
    ('text', '证监会核准批复的文号', '证监许可[2019]352号', 'md_approval_2019',
     '《关于核准美的集团股份有限公司吸收合并无锡小天鹅股份有限公司的批复》（证监许可[2019]352号）'),
    ('amount', '核准发行用于吸收合并的股份数量', '342,130,784股', 'md_approval_2019',
     '核准公司发行342,130,784股股份吸收合并无锡小天鹅股份有限公司'),
    ('text', '本次合并初始A股换股比例', '1:1.2110', 'md_listing_2019', '美的集团与小天鹅A的换股比例为1:1.2110'),
    ('text', '2018年度利润分配实施后A股调整换股比例', '1:1.15144821', 'md_ratio_adj_2019',
     '小天鹅A股股票的换股比例调整为1:1.15144821'),
    ('date', '小天鹅B股被深交所摘牌的日期', '2019-05-27', 'md_listing_2019',
     '深圳证券交易所在2019年5月27日对小天鹅B股股票予以摘牌'),
    ('date', '美的本次新增股份上市日期', '2019-06-21', 'md_listing_2019', '上市日期2019年6月21日'),
    ('amount', '美的集团本次换股吸收合并的发行价格基准', '42.04元/股', 'md_listing_2019',
     '美的集团于定价基准日前20个交易日股票交易均价为42.04元/股'),
]
ST_CORR = [
    ('text', '舜天本次会计差错更正的收入确认方法调整', '由“总额法”调整为“净额法”', 'st_correction_2022',
     '将通讯器材业务的收入确认方法由“总额法”调整为“净额法”'),
    ('text', '本次更正涉及的报表范围', '2009年度至2020年度财务报表及2021年第三季度合并报表', 'st_correction_2022',
     '涉及2009年度至2020年度合并财务报表及母公司财务报表'),
    ('text', '本次更正对利润类科目的影响', '均无影响', 'st_correction_2022',
     '对公司总资产、归属于上市公司股东的净资产、利润总额、净利润、归属于上市公司股东的净利润均无影响'),
    ('amount', '2015年度合并利润表营业收入调减金额', '1,367,440,895.74元', 'st_correction_2022',
     '营业收入5,840,595,229.28-1,367,440,895.74'),
    ('text', '舜天会计差错更正公告的编号', '临2022-008', 'st_correction_2022', '编号：临2022-008'),
]

# ---------------- task definitions ----------------
def T(tid, cls, question, docs, cutoff, deliverable, unknown_boundary, branches, silver_src, deadline_s=1800):
    return {'task_id': tid, 'class': cls, 'question': question, 'evidence_doc_ids': docs,
            'information_cutoff': cutoff, 'deliverable_schema': deliverable,
            'unknown_boundary': unknown_boundary, 'deadline_s': deadline_s,
            'branches_PRIVATE': branches, 'silver_source_PRIVATE': silver_src}


TASKS = [
 T('T-P1', 'regulatory_penalty',
   '调查江苏舜天（600287）信息披露违法违规事件的监管处罚全过程：追溯立案、事先告知、行政处罚决定的'
   '关键日期与文号，核实公司罚款与责任主体，梳理风险警示安排（停牌日、实施日、简称变更、涨跌幅限制）。'
   '输出结构化调查结论并引用证据文档；证据未覆盖的事项必须标注UNKNOWN。',
   ['csrc_penalty_2024_41', 'st_advance_notice_2023', 'st_announce_2024_020', 'st_announce_2024_021'],
   '2024-07-10',
   [{'field': 'investigation_timeline', 'type': 'timeline', 'required': True},
    {'field': 'company_fine', 'type': 'amount', 'required': False},
    {'field': 'fraud_nature', 'type': 'text', 'required': True},
    {'field': 'risk_warning', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['社交媒体热度与股价因果影响（本证据集不含此类数据，必须标注UNKNOWN而非猜测）'],
   {'branch_docs': {'regulatory_line': ['csrc_penalty_2024_41', 'st_advance_notice_2023'],
                    'company_line': ['st_announce_2024_020', 'st_announce_2024_021']},
    'fusion_points': ['处罚决定×公司公告的日期一致性', '违法事实×风险警示触发条件']},
   'shuntian_verified'),
 T('T-P2', 'regulatory_penalty',
   '调查康得新（002450）跨年度财务造假案的监管过程：对照2018/2019两轮年报问询回复与最终行政处罚决定，'
   '核实虚增利润、银行存款虚假记载、造假方式、市场禁入安排，梳理涉及主体与关键日期。'
   '证据未覆盖的事项必须标注UNKNOWN。',
   ['kdx_inquiry_2018', 'kdx_inquiry_2019', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020'],
   '2021-06-30',
   [{'field': 'investigation_timeline', 'type': 'timeline', 'required': True},
    {'field': 'fraud_amounts', 'type': 'amounts', 'required': True},
    {'field': 'fraud_methods', 'type': 'text', 'required': True},
    {'field': 'market_bans', 'type': 'text', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['退市整理期及之后事项（超出截止日）'],
   {'branch_docs': {'inquiry_line': ['kdx_inquiry_2018', 'kdx_inquiry_2019'],
                    'penalty_line': ['kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020']},
    'fusion_points': ['问询自查口径×处罚认定的对照', '跨年度虚增口径一致性']},
   'kdx'),
 T('T-P3', 'regulatory_penalty',
   '调查豫金刚石（300064）多主体资金占用与违规担保案：核实行政处罚及市场禁入事先告知的文号与日期、'
   '责任主体与禁入安排、跨年度（2020/2021）资金占用与担保的专项核查口径、深交所与河南证监局关注函的'
   '监管要求。证据未覆盖的事项必须标注UNKNOWN。',
   ['yjt_occupy_2020', 'yjt_henan_reply', 'yjt_notice_2021', 'yjt_reply_2021', 'yjt_occupy_2021'],
   '2022-06-30',
   [{'field': 'regulatory_letters', 'type': 'structured', 'required': True},
    {'field': 'penalty_notice', 'type': 'structured', 'required': True},
    {'field': 'occupy_guarantee_years', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['最终行政处罚决定书内容（证据集中只有事先告知书）'],
   {'branch_docs': {'occupation_line': ['yjt_occupy_2020', 'yjt_occupy_2021'],
                    'notice_line': ['yjt_notice_2021'],
                    'letters_line': ['yjt_henan_reply', 'yjt_reply_2021']},
    'fusion_points': ['占用年度数据×告知书认定', '两家监管方要求×公司回复']},
   'yjt'),
 T('T-D1', 'disclosure_change',
   '调查江苏舜天（600287）信息披露状态的演变：从2022年会计差错更正（总额法改净额法、涉及年度范围、'
   '对利润的影响）到2024年行政处罚认定（虚增总额、业务定性）再到风险警示实施（停牌与ST安排），'
   '说明三者在时间与口径上的对应关系。证据未覆盖的事项必须标注UNKNOWN。',
   ['st_correction_2022', 'st_board_note_2022', 'csrc_penalty_2024_41', 'st_announce_2024_021'],
   '2024-07-10',
   [{'field': 'correction_scope', 'type': 'structured', 'required': True},
    {'field': 'correction_vs_penalty', 'type': 'text', 'required': True},
    {'field': 'risk_warning', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['更正公告中各年度具体调减金额的完整表格数值（按需引用，未核验项标UNKNOWN）'],
   {'branch_docs': {'correction_line': ['st_correction_2022', 'st_board_note_2022'],
                    'penalty_line': ['csrc_penalty_2024_41'],
                    'risk_line': ['st_announce_2024_021']},
    'fusion_points': ['更正涉及年度×处罚认定虚增年度', '更正方法×业务定性']},
   'st_correction_plus_cross'),
 T('T-D2', 'disclosure_change',
   '调查康得新（002450）在2018与2019两轮年报问询中关于银行存款的披露口径演变：从2018年问询中公司'
   '自查披露的《现金管理业务合作协议》未经批准，到2019年问询中披露的北京银行西单支行账户显示金额与'
   '实际余额差异，再到处罚决定对银行存款虚假记载的最终认定。证据未覆盖的事项必须标注UNKNOWN。',
   ['kdx_inquiry_2018', 'kdx_inquiry_2019', 'kdx_penalty_2020'],
   '2021-06-30',
   [{'field': 'inquiry_2018_positions', 'type': 'text', 'required': True},
    {'field': 'inquiry_2019_positions', 'type': 'text', 'required': True},
    {'field': 'final_penalty_position', 'type': 'text', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['银行归集业务的完整资金流水（证据未含）'],
   {'branch_docs': {'y2018_line': ['kdx_inquiry_2018'], 'y2019_line': ['kdx_inquiry_2019'],
                    'penalty_line': ['kdx_penalty_2020']},
    'fusion_points': ['两轮问询口径对比', '问询自查×最终处罚认定']},
   'kdx_d2'),
 T('T-M1', 'ma_restructuring',
   '调查美的集团换股吸收合并小天鹅（2018-2019）的全过程：深交所重组问询的回复要点、证监会核准批复的'
   '日期文号与发行数量、2018年度利润分配后换股价格与换股比例的调整、小天鹅终止上市与美的新增股份'
   '上市安排。证据未覆盖的事项必须标注UNKNOWN。',
   ['md_ask_reply_2018', 'md_approval_2019', 'md_ratio_adj_2019', 'md_listing_2019'],
   '2019-07-31',
   [{'field': 'approval', 'type': 'structured', 'required': True},
    {'field': 'exchange_ratios', 'type': 'structured', 'required': True},
    {'field': 'delisting_and_listing', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['问询函回复的完整问题清单数值细节（长文档，未检索到的具体问答条目标UNKNOWN）'],
   {'branch_docs': {'inquiry_line': ['md_ask_reply_2018'], 'approval_line': ['md_approval_2019'],
                    'implementation_line': ['md_ratio_adj_2019', 'md_listing_2019']},
    'fusion_points': ['初始换股比例×调整后比例', '核准数量×实际新增股份', '问询要点×实施条件']},
   'md'),
 T('T-R1', 'event_market_reaction',
   '调查视觉中国（000681）2019年黑洞照片事件的舆情发酵与多方回应链：网友举报与网信办约谈、公司网站'
   '暂停与恢复、子公司行政处罚、股票交易异常波动。梳理事件时间线、监管主体与市场反应的对应关系。'
   '证据未覆盖的事项必须标注UNKNOWN。',
   ['sjzg_suspend_2019', 'sjzg_abnormal_2019', 'sjzg_resume_2019'],
   '2019-06-30',
   [{'field': 'event_timeline', 'type': 'timeline', 'required': True},
    {'field': 'regulator_actions', 'type': 'structured', 'required': True},
    {'field': 'market_reaction', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['社交媒体传播热度、舆情情感倾向（证据集不含，必须标注UNKNOWN）'],
   {'branch_docs': {'opinion_line': ['sjzg_suspend_2019'], 'market_line': ['sjzg_abnormal_2019'],
                    'remedy_line': ['sjzg_resume_2019']},
    'fusion_points': ['约谈时间×暂停公告×异动交易日的时间对应', '整改完成×恢复公告×子公司处罚']},
   'sjzg'),
 T('T-R2', 'event_market_reaction',
   '调查江苏舜天（600287）收到行政处罚决定书前后的公司披露与市场处置安排：立案到处罚的披露时间线、'
   '停牌一日安排、其他风险警示（ST）实施与简称变更、涨跌幅限制变化。证据未覆盖的事项必须标注UNKNOWN。',
   ['csrc_penalty_2024_41', 'st_announce_2024_020', 'st_announce_2024_021'],
   '2024-07-10',
   [{'field': 'disclosure_timeline', 'type': 'timeline', 'required': True},
    {'field': 'trading_arrangements', 'type': 'structured', 'required': True},
    {'field': 'report', 'type': 'text_with_citations', 'required': True}],
   ['实际股价走势数据（证据集不含，必须标注UNKNOWN）'],
   {'branch_docs': {'penalty_line': ['csrc_penalty_2024_41'],
                    'company_line': ['st_announce_2024_020', 'st_announce_2024_021']},
    'fusion_points': ['处罚认定×风险警示触发', '停牌日×实施日×涨跌幅限制的衔接']},
   'shuntian_r2'),
]

SILVER_MAP = {
 'shuntian_verified': SHUNTIAN_VERIFIED,
 'kdx': KDX,
 'yjt': YJT,
 'sjzg': SJZG,
 'md': MD,
 'st_correction_plus_cross': ST_CORR + [SHUNTIAN_VERIFIED[2], SHUNTIAN_VERIFIED[5]],
 'kdx_d2': [KDX[6], KDX[4], KDX[0]] + KDX_D2_EXTRA,
 'shuntian_r2': [SHUNTIAN_VERIFIED[0], SHUNTIAN_VERIFIED[4], SHUNTIAN_VERIFIED[5],
                 SHUNTIAN_VERIFIED[6], SHUNTIAN_VERIFIED[7]],
}


def ground(f):
    try:
        full = ''.join((TEXTS / f"{f['evidence_doc']}.txt").read_text().split())
        return norm(f['quote']) in norm(full)
    except FileNotFoundError:
        return False


def main():
    (BENCH / 'tasks').mkdir(exist_ok=True)
    (BENCH / 'scoring' / 'silver').mkdir(parents=True, exist_ok=True)
    pub_f, priv_f = [], []
    for t in TASKS:
        silver_src = SILVER_MAP[t.pop('silver_source_PRIVATE')]
        branches = t.pop('branches_PRIVATE')
        facts, dropped = [], []
        for i, (typ, q, a, doc, quote) in enumerate(silver_src):
            f = {'fact_id': f"{t['task_id']}-S{i+1}", 'answer_type': typ, 'question': q, 'answer': a,
                 'evidence_doc': doc, 'quote': quote, 'label': 'SILVER (machine-built, auto-grounded; NOT gold)'}
            if t['task_id'].split('-')[1] in ('P1',) or doc in t['evidence_doc_ids']:
                (facts if ground(f) else dropped).append(f)
        assert len(facts) >= 4, f"{t['task_id']}: too few grounded facts ({len(facts)})"
        priv = {'task_id': t['task_id'], 'silver': facts,
                'branch_descriptor': branches, 'dropped_ungrounded': [f['fact_id'] for f in dropped]}
        sf = BENCH / 'scoring' / 'silver' / f"{t['task_id']}.silver.json"
        sf.write_text(json.dumps(priv, ensure_ascii=False, indent=1))
        priv['silver_file'] = str(sf.relative_to(BENCH))
        priv_f.append({k: priv[k] for k in ('task_id', 'branch_descriptor', 'dropped_ungrounded', 'silver_file')})
        t['n_silver_reference'] = len(facts)          # count only; facts stay private
        t['evidence_index_note'] = 'see evidence/index.json; retrieval API is the ONLY sanctioned access path'
        pub_f.append(t)
        print(f"{t['task_id']} class={t['class']:22s} docs={len(t['evidence_doc_ids'])} "
              f"silver_grounded={len(facts)} dropped={len(dropped)}")
    (BENCH / 'tasks' / 'tasks_frozen.jsonl').write_text(
        '\n'.join(json.dumps(t, ensure_ascii=False) for t in pub_f))
    (BENCH / 'tasks' / 'tasks_private.jsonl').write_text(
        '\n'.join(json.dumps(t, ensure_ascii=False) for t in priv_f))
    print('tasks written: public', len(pub_f), 'private', len(priv_f))


if __name__ == '__main__':
    main()
