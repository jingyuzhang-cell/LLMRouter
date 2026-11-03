"""ZEDA (泽达易盛 688555) silver facts — Phase V2.3-A."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

DOCS = {d: f"docs/ZEDA/ZEDA_{d}.txt"
        for d in ('2022-05-12', '2022-07-13', '2022-11-19', '2023-04-22', '2023-07-01')}
PEN = '2023-04-22'

FACTS = [
  dict(fact_id='A1', subject='泽达易盛公司立案', predicate='立案告知书编号', value='证监立案字03720220019号',
       value_kind='text', critical=True,
       quote='案告知书》（编号：证监立案字 03720220019 号），因公司涉嫌信息披露违法违', doc_id='2022-05-12', bucket='立案链'),
  dict(fact_id='A2', subject='林应(实控人)立案', predicate='立案告知书编号', value='证监立案字03720220020号',
       value_kind='text', critical=True,
       quote='发的《立案告知书》（编号：证监立案字 03720220020 号），因林应女士涉嫌信', doc_id='2022-07-13', bucket='立案链'),
  dict(fact_id='B1', subject='泽达易盛2016-2019累计', predicate='虚增营业收入', value='342296307.13',
       value_kind='number', critical=True,
       quote='2016 年-2019 年累计虚增营业收入 342,296,307.13 元，虚增利润 186,735,305.01', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B1b', subject='泽达易盛2016-2019累计', predicate='虚增利润', value='186735305.01',
       value_kind='number', quote='元。其中 2016 年虚增营业收入 35,573,659.95 元，占当年收入的 49.28%，虚增利',
       doc_id=PEN, bucket='虚增金额') if False else dict(
       fact_id='B1b', subject='泽达易盛2016-2019累计', predicate='虚增利润', value='186735305.01',
       value_kind='number', quote='元，虚增利润 186,735,305.01',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B2', subject='泽达易盛2016年度', predicate='虚增利润占当年利润比例', value='104.72%',
       value_kind='percent', quote='润 22,438,194.83 元，占当年利润的 104.72%；2017 年虚增营业收入 73,888,825.78',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B3', subject='泽达易盛2019年度', predicate='虚增营业收入', value='114794784.45',
       value_kind='number', quote='2019 年虚增营业收入 114,794,784.45', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='C1', subject='隋某力股权代持', predicate='代持合计持股', value='870万股(占13.96%)',
       value_kind='text', critical=True,
       quote='某力通过梅某持有泽达易盛 600 万股，通过杨某持有 270 万股，合计持有 870', doc_id=PEN, bucket='股权代持'),
  dict(fact_id='C2', subject='泽达易盛2020年年度报告', predicate='虚增营业收入', value='152168610.58',
       value_kind='number', quote='虚增营业收入 152,168,610.58 元，', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='C3', subject='泽达易盛2021年年度报告', predicate='虚增在建工程', value='36320600.00',
       value_kind='number', quote='虚增在建工程 36,320,600.00', doc_id=PEN, bucket='虚增金额'),
  # 处罚金额 (target field)
  dict(fact_id='D1', subject='泽达易盛(公司)', predicate='欺诈发行罚款(募集资金20%)', value='81000440元',
       value_kind='text', critical=True,
       quote='一、对泽达易盛处以非法所募资金金额 40,500.22 万元的 20%，即 81,000,440', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D2', subject='泽达易盛(公司)', predicate='合计罚款', value='86000440元',
       value_kind='text', critical=True,
       quote='86,000,440 元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D3', subject='林应', predicate='合计罚款', value='3800万元',
       value_kind='text', critical=True, quote='二、对林应给予警告，并处以 3,800 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D4', subject='应岚', predicate='合计罚款', value='1300万元',
       value_kind='text', critical=True, quote='三、对应岚给予警告，并处以 1,300 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D5', subject='王晓亮', predicate='合计罚款', value='300万元',
       value_kind='text', quote='四、对王晓亮给予警告，并处以 300 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D6', subject='姜亚莉', predicate='合计罚款', value='250万元',
       value_kind='text', quote='五、对姜亚莉给予警告，并处以 250 万元罚款。', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='E1', subject='泽达易盛股票', predicate='终止上市日期', value='2023-07-07',
       value_kind='date', critical=True,
       quote='公司股票将于 2023 年 7 月 7 日被上海证券交易所终止上市暨摘牌。', doc_id='2023-07-01', bucket='退市'),
  dict(fact_id='E2', subject='泽达易盛股票', predicate='终止上市决定日期', value='2023-05-31',
       value_kind='date', quote='4、终止上市决定日期：2023 年 5 月 31 日', doc_id='2023-07-01', bucket='退市'),
]

UNKNOWNS = [dict(item_id='U1', question='隋某力、梅某、杨某的真实全名（文书中以化名披露，无法从本组文书确定）')]

META = dict(
    task_id='V23A_ZEDA_FRAUD_CHAIN',
    question='泽达易盛：公司立案与实际控制人林应立案的编号分别是什么？2016-2019 年累计虚增营业收入与利润各多少？'
             '股权代持合计多少股、占比多少？2020/2021 年报虚增营业收入/在建工程各多少？行政处罚对各当事人合计罚款'
             '分别是多少？股票何时终止上市？',
    cutoff='2023-07-01',
    nature='五份公告：公司立案、实控人立案、事先告知书、行政处罚决定书、终止上市（cninfo 原始 PDF，SHA256 见 NEW_EVENT_DOCS_MANIFEST）',
    target_field='penalty_amounts',
    target_slots=['D1', 'D2', 'D3', 'D4', 'D5', 'D6'],
    e_node_of_target='E_处罚决定书(2023-04-22)',
)

if __name__ == '__main__':
    path, facts, problems = build('ZEDA', DOCS, FACTS, UNKNOWNS, META,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
    print('wrote', path, '| facts', len(facts), '| problems', problems)
