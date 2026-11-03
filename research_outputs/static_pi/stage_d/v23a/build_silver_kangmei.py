"""KANGMEI (康美药业 600518) silver facts — Phase V2.3-A."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

DOCS = {d: f"docs/KANGMEI/KANGMEI_{d}.txt"
        for d in ('2018-12-29', '2019-08-17', '2020-05-15')}
PEN = '2020-05-15'

FACTS = [
  dict(fact_id='A1', subject='康美药业立案调查', predicate='调查通知书编号', value='粤证调查通字180199号',
       value_kind='text', critical=True,
       quote='证调查通字 180199 号）：“因你公司涉嫌信息披露违法违规，根据《中华人民',
       doc_id='2018-12-29', bucket='立案链'),
  dict(fact_id='A2', subject='康美药业', predicate='事先告知书收到时点', value='2019年8月（调查完毕后拟处罚）',
       value_kind='text', quote='康美药业涉嫌信息披露违法违规一案，已由我会调查完毕，我会依法拟对你们',
       doc_id='2019-08-17', bucket='立案链'),
  dict(fact_id='B1', subject='康美药业2016年年度报告', predicate='虚增营业收入', value='89.99亿元',
       value_kind='text', critical=True,
       quote='《2016 年年度报告》虚增营业收入 89.99 亿元，多计利息收入 1.51 亿元，虚',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B2', subject='康美药业2017年年度报告', predicate='虚增营业收入', value='100.32亿元',
       value_kind='text', critical=True,
       quote='报告》 虚增营业收入 100.32 亿元，多计利息收入 2.28 亿元，虚增营业利润 12.51',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B3', subject='康美药业2016年年度报告', predicate='虚增货币资金', value='22548513485.42元',
       value_kind='number', critical=True,
       quote='22，548，513，485.42 元，占公司披露总资产的 41.13%和净资产的 76.74%；《2017',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B4', subject='康美药业2017年年度报告', predicate='虚增货币资金', value='29944309821.45元',
       value_kind='number', critical=True,
       quote='年年度报告》虚增货币资金 29，944，309，821.45 元，占公司披露总资产的 43.57%',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B5', subject='康美药业2018年半年度报告', predicate='虚增货币资金', value='36188038359.50元',
       value_kind='number',
       quote='《2018 年半年度报告》虚增货币资金 36,188,038,359.50 元，', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B6', subject='康美药业2018年年度报告', predicate='虚增固定资产/在建工程/投资性房地产',
       value='11.89亿元/4.01亿元/20.15亿元', value_kind='text',
       quote='产 11.89 亿元，虚增在建工程 4.01 亿元，虚增投资性房地产 20.15 亿元。',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='C1', subject='康美药业虚增货币资金手法', predicate='方式',
       value='财务不记账、虚假记账，伪造、变造大额定期存单或银行对账单，配合营业收入造假伪造销售回款',
       value_kind='text',
       quote='伪造、变造大额定期存单或银行对账单，配合营业收入造假伪造销售回款等方式，',
       doc_id=PEN, bucket='手法'),
  # 处罚与禁入 (target field)
  dict(fact_id='D1', subject='康美药业股份有限公司', predicate='罚款', value='60万元',
       value_kind='text', critical=True,
       quote='一、对康美药业股份有限公司责令改正，给予警告，并处以 60 万元的罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D2', subject='马兴田、许冬瑾', predicate='罚款(每人)', value='90万元',
       value_kind='text', critical=True,
       quote='二、对马兴田、许冬瑾给予警告，并分别处以 90 万元的罚款，其中作为直接',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D3', subject='邱锡伟', predicate='罚款', value='30万元',
       value_kind='text', quote='三、对邱锡伟给予警告，并处以 30 万元的罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D4', subject='庄义清、温少生、马焕洲', predicate='罚款(每人)', value='25万元',
       value_kind='text', quote='四、对庄义清、温少生、马焕洲给予警告，并分别处以 25 万元的罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D5', subject='马兴田、许冬瑾、邱锡伟', predicate='市场禁入措施',
       value='终身证券市场禁入', value_kind='text', critical=True,
       quote='终身证券市场禁入措施，自我会宣布决定之日起，在禁入期间内，除不得继续在原',
       doc_id=PEN, bucket='处罚金额'),
]

UNKNOWNS = [dict(item_id='U1', question='康美药业相关证券虚假陈述民事赔偿诉讼的最终赔付总额（本组文书中未披露）')]

META = dict(
    task_id='V23A_KANGMEI_FRAUD_PENALTY',
    question='康美药业：立案调查通知书编号是什么？2016/2017 年年报虚增营业收入各多少？2016 年报、2017 年报、'
             '2018 半年报虚增货币资金各多少？2018 年报虚增固定资产/在建工程/投资性房地产各多少？虚增货币资金的手法是什么？'
             '行政处罚对公司、马兴田与许冬瑾、邱锡伟、庄义清等分别罚款多少？对马兴田、许冬瑾、邱锡伟的市场禁入措施是什么？',
    cutoff='2020-05-15',
    nature='三份公告：立案调查通知、事先告知书、行政处罚决定书+市场禁入决定书（cninfo 原始 PDF，SHA256 见 NEW_EVENT_DOCS_MANIFEST）',
    target_field='penalty_amounts',
    target_slots=['D1', 'D2', 'D3', 'D4', 'D5'],
    e_node_of_target='E_处罚决定书(2020-05-15)',
)

if __name__ == '__main__':
    path, facts, problems = build('KANGMEI', DOCS, FACTS, UNKNOWNS, META,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
    print('wrote', path, '| facts', len(facts), '| problems', problems)
