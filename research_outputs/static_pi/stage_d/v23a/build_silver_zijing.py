"""ZIJING (紫晶存储 688086) silver facts — Phase V2.3-A.
All quotes verbatim from the event's documents (see NEW_EVENT_DOCS_MANIFEST)."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

DOCS = {d: f"docs/ZIJING/ZIJING_{d}.txt"
        for d in ('2022-02-12', '2022-06-25', '2022-11-19', '2023-04-22', '2023-07-01')}
PEN = '2023-04-22'   # 处罚决定书 doc: carries the penalty-amount target field

FACTS = [
  # 立案链 (3 docs)
  dict(fact_id='A1', subject='紫晶存储公司立案', predicate='立案告知书编号', value='证监立案字0062022005号',
       value_kind='text', critical=True, quote='《立案告知书》（编号：证监立案字 0062022005 号）',
       doc_id='2022-02-12', bucket='立案链'),
  dict(fact_id='A2', subject='紫晶存储公司立案', predicate='立案事由', value='涉嫌信息披露违法违规',
       value_kind='text', quote='因公司涉嫌信息披露违法违规', doc_id='2022-02-12', bucket='立案链'),
  dict(fact_id='A3', subject='紫晶存储实控人', predicate='立案对象', value='郑穆、罗铁威(两名实际控制人)',
       value_kind='text', critical=True,
       quote='实际控制人郑穆先生、罗铁威先生于 2022 年 6 月 24 日收到中国证券监督管理委员会',
       doc_id='2022-06-25', bucket='立案链'),
  dict(fact_id='A4', subject='紫晶存储实控人立案', predicate='立案告知书编号',
       value='证监立案字0062022012号、0062022013号', value_kind='text',
       quote='（编号：证监立案字 0062022012 号、证监立案字', doc_id='2022-06-25', bucket='立案链'),
  # 欺诈发行金额 (招股书阶段)
  dict(fact_id='B1', subject='紫晶存储2017年度', predicate='虚增营业收入', value='43497313.43',
       value_kind='number', critical=True,
       quote='2017 年，紫晶存储通过开展虚假业务，虚增营业收入合计', doc_id=PEN, bucket='虚增金额') if False else dict(
       fact_id='B1', subject='紫晶存储2017年度', predicate='虚增营业收入', value='43497313.43',
       value_kind='number', critical=True,
       quote='43,497,313.43 元，占当年营业收入的 13.9%，虚增利润合计', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B1b', subject='紫晶存储2017年度', predicate='虚增利润', value='21627070.35',
       value_kind='number', quote='43,497,313.43 元，占当年营业收入的 13.9%，虚增利润合计',
       doc_id=PEN, bucket='虚增金额') if False else dict(
       fact_id='B1b', subject='紫晶存储2017年度', predicate='虚增利润', value='21627070.35',
       value_kind='number', quote='虚增利润合计 21,627,070.35 元，占当年利润总额的',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B2', subject='紫晶存储2018年度', predicate='虚增营业收入', value='111457882.74',
       value_kind='number', critical=True, quote='虚增营业收入合计 111,457,882.74 元，占当年营业收入的',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B2b', subject='紫晶存储2018年度', predicate='虚增利润', value='39036333.51',
       value_kind='number', quote='27.75%，虚增利润合计 39,036,333.51 元，占当年利润总额的',
       doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='B3', subject='紫晶存储招股说明书', predicate='未按规定披露对外担保余额(2016末/2017末/2019H1末)',
       value='1000万元、1000万元、7500.12万元', value_kind='text',
       quote='年末以及 2019 年上半年末对外担保余额分别为 1,000 万元、', doc_id=PEN, bucket='违规担保'),
  # 上市后继续造假
  dict(fact_id='C1', subject='紫晶存储2019年年度报告', predicate='虚增营业收入', value='270871411.88',
       value_kind='number', quote='虚增营业收入 270,871,411.88 元，占当期报告', doc_id=PEN, bucket='虚增金额'),
  dict(fact_id='C2', subject='紫晶存储2020年年度报告', predicate='虚增营业收入', value='327797330.95',
       value_kind='number', quote='虚增营业收入 327,797,330.95 元，占当期报告', doc_id=PEN, bucket='虚增金额'),
  # 处罚金额 (target field)
  dict(fact_id='D1', subject='紫晶存储(公司)', predicate='欺诈发行罚款(募集资金3%)', value='3068.52万元',
       value_kind='text', critical=True,
       quote='资金的 3%，即 3,068.52 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D2', subject='紫晶存储(公司)', predicate='合计罚款', value='3668.52万元',
       value_kind='text', critical=True,
       quote='警告，并处以 3,668.52 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D3', subject='郑穆', predicate='合计罚款', value='2164.26万元',
       value_kind='text', critical=True, quote='二、对郑穆给予警告，并处以 2,164.26 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D4', subject='罗铁威', predicate='合计罚款', value='1803.55万元',
       value_kind='text', critical=True, quote='三、对罗铁威给予警告，并处以 1,803.55 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D5', subject='钟国裕、李燕霞', predicate='合计罚款(每人)', value='220万元',
       value_kind='text', quote='四、对钟国裕、李燕霞给予警告，并分别处以 220 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D6', subject='黄美珊、焦仕志', predicate='合计罚款(每人)', value='160万元',
       value_kind='text', quote='五、对黄美珊、焦仕志给予警告，并分别处以 160 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D7', subject='魏强等五人(魏强/杨思维/王炜/林海忠/丁杰)', predicate='合计罚款(每人)',
       value='105万元', value_kind='text', quote='六、对魏强、杨思维、王炜、林海忠、丁杰给予警',
       doc_id=PEN, bucket='处罚金额') if False else dict(
       fact_id='D7', subject='魏强等五人(魏强/杨思维/王炜/林海忠/丁杰)', predicate='合计罚款(每人)',
       value='105万元', value_kind='text', quote='别处以 105 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  # 退市
  dict(fact_id='E1', subject='紫晶存储股票', predicate='终止上市日期', value='2023-07-07',
       value_kind='date', critical=True, quote='公司股票将于 2023 年 7 月 7 日被上海证券交易所终止上市暨摘牌',
       doc_id='2023-07-01', bucket='退市'),
  dict(fact_id='E2', subject='紫晶存储股票', predicate='终止上市决定日期', value='2023-05-31',
       value_kind='date', quote='（四）终止上市决定日期：2023 年 5 月 31 日', doc_id='2023-07-01', bucket='退市'),
]

UNKNOWNS = [dict(item_id='U1', question='先行赔付专项基金的具体总额及赔付完成情况（本组文书中未披露，需另行公告）')]

META = dict(
    task_id='V23A_ZIJING_FRAUD_CHAIN',
    question='紫晶存储：公司立案与两名实际控制人立案的编号、对象与事由分别是什么？《招股说明书》阶段'
             '2017/2018 年虚增营业收入与利润各是多少？上市后 2019/2020 年年报虚增营业收入各是多少？'
             '行政处罚对各当事人分别处以多少罚款（含欺诈发行与信息披露违法两部分的合计）？股票何时被决定终止上市、何时摘牌？',
    cutoff='2023-07-01',
    nature='五份公告：公司立案、实控人立案、事先告知书、行政处罚决定书、终止上市（cninfo 原始 PDF，SHA256 见 NEW_EVENT_DOCS_MANIFEST）',
    target_field='penalty_amounts',
    target_slots=['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7'],
    e_node_of_target='E_处罚决定书(2023-04-22)',
)

if __name__ == '__main__':
    path, facts, problems = build('ZIJING', DOCS, FACTS, UNKNOWNS, META,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
    print('wrote', path, '| facts', len(facts), '| problems', problems)
