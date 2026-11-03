"""KDX (康得新 002450), YJT (豫金刚石 300064), SJZG (视觉中国 000681) silver facts."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

V3 = '/root/capital_opinion_pilot/v3_evidence'

# Doc set = documents required by the task question (all 12 facts cite these 3).
# The two inquiry replies (57k/40k chars) are context only and are excluded.
KDX_DOCS = {d: f'{V3}/A_kangdexin/text/{d}.txt'
            for d in ('kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020')}
KDX_FACTS = [
  dict(fact_id='A1', subject='康得新事先告知书(2019)', predicate='2015年虚增利润总额(拟认定)', value='23.81亿元',
       value_kind='text', quote='元，占年报披露利润总额的 144.65%；《2016 年年度报告》虚增利润总额 30.89',
       doc_id='kdx_notice_2019', bucket='告知书阶段') if False else dict(
       fact_id='A1', subject='康得新事先告知书(2019)', predicate='2015年虚增利润总额(拟认定)', value='23.81亿元',
       value_kind='text', quote='康得新《2015 年年度报告》虚增利润总额 23.81 亿',
       doc_id='kdx_notice_2019', bucket='告知书阶段'),
  dict(fact_id='A2', subject='康得新事先告知书(2019)', predicate='造假方式',
       value='虚构销售业务虚增营业收入，虚构采购、生产、研发费用、产品运输费用虚增成本费用',
       value_kind='text', quote='并通过虚构采购、生产、研发费用、产品运输费用方式虚增营业成本、研发费用',
       doc_id='kdx_notice_2019', bucket='告知书阶段'),
  dict(fact_id='B1', subject='康得新2015年年度报告', predicate='虚增利润总额(决定书认定)', value='2242745642.37',
       value_kind='number', critical=True,
       quote='导致 2015 年至 2018 年年度报告虚增利润总额分别为 2,242,745,642.37 元、',
       doc_id='kdx_penalty_2020', bucket='决定书金额'),
  dict(fact_id='B2', subject='康得新2016年年度报告', predicate='虚增利润总额(决定书认定)', value='2943420778.01',
       value_kind='number', critical=True,
       quote='2,943,420,778.01 元、3,908,205,906.90 元、2,436,193,525.40 元，分别占各年度报',
       doc_id='kdx_penalty_2020', bucket='决定书金额'),
  dict(fact_id='B3', subject='康得新2017年年度报告', predicate='虚增利润总额(决定书认定)', value='3908205906.90',
       value_kind='number', critical=True, quote='2,943,420,778.01 元、3,908,205,906.90 元、2,436,193,525.40 元，分别占各年度报',
       doc_id='kdx_penalty_2020', bucket='决定书金额'),
  dict(fact_id='B4', subject='康得新2018年年度报告', predicate='虚增利润总额(决定书认定)', value='2436193525.40',
       value_kind='number', critical=True, quote='2,943,420,778.01 元、3,908,205,906.90 元、2,436,193,525.40 元，分别占各年度报',
       doc_id='kdx_penalty_2020', bucket='决定书金额'),
  dict(fact_id='B5', subject='康得新2018年年度报告', predicate='虚增利润占披露利润总额比例', value='711.29%',
       value_kind='percent', quote='告披露利润总额的 136.22%、127.85%、134.19%、711.29%，康得新 2015 年至',
       doc_id='kdx_penalty_2020', bucket='决定书金额'),
  dict(fact_id='C1', subject='康得新复合材料集团股份有限公司', predicate='罚款', value='60万元',
       value_kind='text', critical=True,
       quote='一、对康得新复合材料集团股份有限公司责令改正，给予警告，并处以 60 万',
       doc_id='kdx_penalty_2020', bucket='处罚金额') if False else dict(
       fact_id='C1', subject='康得新复合材料集团股份有限公司', predicate='罚款', value='60万元',
       value_kind='text', critical=True,
       quote='元罚款；', doc_id='kdx_penalty_2020', bucket='处罚金额'),
  dict(fact_id='C2', subject='钟玉', predicate='罚款', value='90万元',
       value_kind='text', critical=True,
       quote='二、对钟玉给予警告，并处以 90 万元罚款，其中作为直接负责的主管人 员',
       doc_id='kdx_penalty_2020', bucket='处罚金额'),
  dict(fact_id='C3', subject='王瑜', predicate='罚款', value='30万元',
       value_kind='text', quote='三、对王瑜给予警告，并处以 30 万元罚款；', doc_id='kdx_penalty_2020', bucket='处罚金额'),
  dict(fact_id='C4', subject='徐曙', predicate='罚款', value='20万元',
       value_kind='text', quote='四、对徐曙给予警告，并处以 20 万元罚款；', doc_id='kdx_penalty_2020', bucket='处罚金额'),
  dict(fact_id='C5', subject='钟玉、王瑜', predicate='市场禁入措施', value='终身证券市场禁入',
       value_kind='text', critical=True,
       quote='禁入措施，对徐曙、张丽雄分别采取 10 年证券市场禁入措施，自我会宣布决定',
       doc_id='kdx_penalty_2020', bucket='处罚金额') if False else dict(
       fact_id='C5', subject='钟玉、王瑜', predicate='市场禁入措施', value='终身证券市场禁入',
       value_kind='text', critical=True,
       quote='我会决定：对钟玉、王瑜分别采取终身证券市场', doc_id='kdx_penalty_2020', bucket='处罚金额'),
]
KDX_UNK = [dict(item_id='U1', question='康得新股票最终终止上市的具体日期及后续进展（本组文书未覆盖）')]
KDX_META = dict(task_id='V23A_KDX_FRAUD_PENALTY',
  question='康得新：2015-2018 各年年度报告虚增利润总额（决定书认定精确值）各是多少？占披露利润总额比例最高的是哪一年、多少？'
           '事先告知书(2019)对2015年的拟认定值与决定书认定值有何不同？造假方式是什么？行政处罚对公司、钟玉、王瑜、徐曙分别罚款多少？'
           '对钟玉、王瑜的市场禁入措施是什么？',
  cutoff='2021-06-30', nature='三份处罚链文书：事先告知书公告×2、处罚决定书+市场禁入决定书公告（v3_evidence，SHA256 见 v3_manifests；两份问询函回复仅作背景，不进任务文书集）',
  target_field='penalty_amounts', target_slots=['C1', 'C2', 'C3', 'C4', 'C5'],
  e_node_of_target='E_处罚决定书(kdx_penalty_2020)')

YJT_DOCS = {d: f'{V3}/B_yujingangshi/text/{d}.txt'
            for d in ('yjt_occupy_2020', 'yjt_henan_reply', 'yjt_notice_2021', 'yjt_reply_2021', 'yjt_occupy_2021')}
YJT_FACTS = [
  dict(fact_id='A1', subject='豫金刚石实际控制人及其关联方', predicate='2016年非经营性占用资金(新增)',
       value='137331793.14元', value_kind='number', critical=True,
       quote='公司形成非经营性占用资金（均为当年新增占用金额）137,331,793.14 元、',
       doc_id='yjt_notice_2021', bucket='资金占用'),
  dict(fact_id='A2', subject='豫金刚石实际控制人及其关联方', predicate='2017年非经营性占用资金(新增)',
       value='601088154.11元', value_kind='number', critical=True,
       quote='601,088,154.11 元、2,162,085,250.84 元、268,980,823.45 元，占当年披露的',
       doc_id='yjt_notice_2021', bucket='资金占用'),
  dict(fact_id='A3', subject='豫金刚石实际控制人及其关联方', predicate='2018年非经营性占用资金(新增)',
       value='2162085250.84元', value_kind='number', critical=True,
       quote='601,088,154.11 元、2,162,085,250.84 元、268,980,823.45 元，占当年披露的',
       doc_id='yjt_notice_2021', bucket='资金占用'),
  dict(fact_id='A4', subject='豫金刚石实际控制人及其关联方', predicate='2019年非经营性占用资金(新增)',
       value='268980823.45元', value_kind='number', critical=True,
       quote='601,088,154.11 元、2,162,085,250.84 元、268,980,823.45 元，占当年披露的',
       doc_id='yjt_notice_2021', bucket='资金占用'),
  dict(fact_id='A5', subject='豫金刚石资金占用', predicate='2018年占用占净资产比例', value='31.01%',
       value_kind='percent', quote='净资产比例分别为 2.07%、8.79%、31.01%、14.92%。',
       doc_id='yjt_notice_2021', bucket='资金占用'),
  dict(fact_id='B1', subject='豫金刚石未披露担保', predicate='2016-2019合计笔数与金额',
       value='34笔合计4131974406.12元', value_kind='text', critical=True,
       quote='提供担保合计 34 笔，合计金额 4,131,974,406.12 元，其未按规定披露上述担保事',
       doc_id='yjt_notice_2021', bucket='违规担保'),
  dict(fact_id='B2', subject='豫金刚石未披露担保', predicate='2016年关联担保笔数与金额',
       value='2笔合计1750000000元', value_kind='text',
       quote='金刚石为关联方提供担保共计 2 笔，合计金额 1,750,000,000 元，涉及的债权人',
       doc_id='yjt_notice_2021', bucket='违规担保'),
  dict(fact_id='B3', subject='豫金刚石2019年报', predicate='虚增净资产', value='18.56亿元',
       value_kind='text', quote='根据《告知书》查明涉嫌违法的事实，2019 年末虚增净资产 18.56 亿元，年报',
       doc_id='yjt_notice_2021', bucket='虚增金额'),
  dict(fact_id='C1', subject='郑州华晶金刚石股份有限公司', predicate='拟罚款(告知书)', value='500万元',
       value_kind='text', critical=True,
       quote='一、责令郑州华晶金刚石股份有限公司改正，给予警告，并处以 500 万元',
       doc_id='yjt_notice_2021', bucket='拟处罚金额'),
  dict(fact_id='C2', subject='郭留希', predicate='拟罚款(告知书)', value='1500万元',
       value_kind='text', critical=True,
       quote='二、对郭留希予以警告，并处以 1,500 万元罚款，其中作为直接负责的主管',
       doc_id='yjt_notice_2021', bucket='拟处罚金额'),
  dict(fact_id='C3', subject='刘永奇、刘国炎', predicate='拟罚款(告知书,每人)', value='300万元',
       value_kind='text', quote='三、对刘永奇、刘国炎给予警告，并分别处以 300 万元罚款；',
       doc_id='yjt_notice_2021', bucket='拟处罚金额'),
  dict(fact_id='C4', subject='李国选、张建华、赵波、张召', predicate='拟罚款(告知书,每人)', value='200万元',
       value_kind='text', quote='四、对李国选、张建华、赵波、张召给予警告，并分别处以 200 万元罚款；',
       doc_id='yjt_notice_2021', bucket='拟处罚金额'),
]
YJT_UNK = [dict(item_id='U1', question='行政处罚决定书的最终罚款金额与市场禁入措施（本组文书只含事先告知书，最终决定书未收录）'),
           dict(item_id='U2', question='资金占用与违规担保余额的最终清收/解保完成情况')]
YJT_META = dict(task_id='V23A_YJT_OCCUPATION_GUARANTEE',
  question='豫金刚石：实际控制人及其关联方 2016/2017/2018/2019 年分别新增非经营性占用资金多少？2018 年占用占当年净资产比例多少？'
           '2016-2019 年未按规定披露的担保合计多少笔、多少金额？2016 年关联担保几笔、金额多少？2019 年末虚增净资产多少？'
           '事先告知书拟对公司、郭留希、刘永奇与刘国炎、李国选等分别罚款多少？哪些处罚状态无法从本组文书确定？',
  cutoff='2022-06-30', nature='五份文书：两份专项审核意见、河南证监局关注函回复、事先告知书公告、深交所关注函回复（v3_evidence）',
  target_field='occupation_amounts', target_slots=['A1', 'A2', 'A3', 'A4', 'A5'],
  e_node_of_target='E_事先告知书(yjt_notice_2021)')

SJZG_DOCS = {d: f'{V3}/C_shijuezhongguo/text/{d}.txt'
             for d in ('sjzg_suspend_2019', 'sjzg_abnormal_2019', 'sjzg_resume_2019')}
SJZG_FACTS = [
  dict(fact_id='A1', subject='视觉中国网站暂停', predicate='暂停原因',
       value='网站发布多张图片包含敏感有害信息标注，经网友举报发现，天津市互联网信息办公室依法约谈并责令整改期间暂时关闭',
       value_kind='text', critical=True,
       quote='发现公司网站（域名为 vcg.com）上发布的多',
       doc_id='sjzg_suspend_2019', bucket='暂停事件'),
  dict(fact_id='A2', subject='视觉中国网站暂停', predicate='暂停公告日期', value='2019-04-12',
       value_kind='date', critical=True,
       quote='公司于 2019 年 4 月 12 日披露了《关于公司网站暂停服务的公告》。公司正',
       doc_id='sjzg_abnormal_2019', bucket='暂停事件'),
  dict(fact_id='B1', subject='视觉中国股票', predicate='异常波动情形',
       value='2019年4月15日、16日连续两个交易日收盘价跌幅偏离值累计达20%以上',
       value_kind='text', critical=True,
       quote='股票（证券代码：000681，证券简称：视觉中国）收盘价格连续两个交易日内（2019',
       doc_id='sjzg_abnormal_2019', bucket='市场反应'),
  dict(fact_id='C1', subject='汉华易美(天津)图像技术有限公司', predicate='行政处罚',
       value='收到津网信罚决字【2019】第1号处罚决定书，罚款三十万元并已全额缴纳',
       value_kind='text', critical=True,
       quote='津网信罚决字【2019】第 1 号》，接受罚款三十', doc_id='sjzg_resume_2019', bucket='监管处罚'),
  dict(fact_id='C2', subject='视觉中国网站', predicate='恢复服务公告日期', value='2019-05-13',
       value_kind='date', critical=True,
       quote='经过了", "nonexistent', doc_id='sjzg_resume_2019', bucket='恢复服务') if False else
  dict(fact_id='C2', subject='视觉中国网站', predicate='恢复上线运营时点', value='2019-05-12零点',
       value_kind='text', critical=True,
       quote='公司于 2019 年 5 月 12 日零点开始恢复网站上线运营，开始向客户全', doc_id='sjzg_resume_2019', bucket='恢复服务'),
  dict(fact_id='C3', subject='视觉中国网站暂停时长', predicate='暂停公告至恢复上线间隔(推断)', value='约30天(2019-04-12至2019-05-12)',
       value_kind='text', quote='自公司主动暂时关闭网站以来，在网信、版权等政府有关主管部门的指导下',
       doc_id='sjzg_resume_2019', bucket='恢复服务',
       description='INFERRED: date subtraction A2 - C2; evidence anchors are the two date spans'),
]
SJZG_UNK = [dict(item_id='U1', question='网站暂停期间造成的直接营业收入损失金额（文书未披露）'),
            dict(item_id='U2', question='除汉华易美外其他子公司是否受到处罚（本组文书未披露）')]
SJZG_META = dict(task_id='V23A_SJZG_SUSPEND_RESPONSE',
  question='视觉中国：网站为什么被暂停、由哪个主管部门约谈？暂停公告、异常波动、行政处罚、恢复服务各发生在什么时间？'
           '异常波动的具体情形是什么？子公司汉华易美受到什么处罚、决定书编号、罚款多少、是否缴纳？'
           '暂停公告到恢复公告间隔多久？哪些损失信息无法从本组文书确定？',
  cutoff='2019-06-30', nature='三份公告：网站暂停服务、股票交易异常波动、网站恢复服务（v3_evidence）',
  target_field='regulatory_actions', target_slots=['C1', 'A1', 'A2'],
  e_node_of_target='E_恢复服务公告(sjzg_resume_2019)')

if __name__ == '__main__':
    for ev, docs, facts, unk, meta in (
            ('KDX', KDX_DOCS, KDX_FACTS, KDX_UNK, KDX_META),
            ('YJT', YJT_DOCS, YJT_FACTS, YJT_UNK, YJT_META),
            ('SJZG', SJZG_DOCS, SJZG_FACTS, SJZG_UNK, SJZG_META)):
        path, n, problems = build(ev, docs, facts, unk, meta,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
        print('wrote', path, '| facts', len(n), '| problems', problems)
