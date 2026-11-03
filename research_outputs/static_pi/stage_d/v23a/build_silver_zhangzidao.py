"""ZHANGZIDAO (獐子岛 002069) silver facts — Phase V2.3-A."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

DOCS = {d: f"docs/ZHANGZIDAO/ZHANGZIDAO_{d}.txt"
        for d in ('2019-01-08', '2019-07-11', '2020-06-25')}
PEN = '2020-06-25'

FACTS = [
  dict(fact_id='A1', subject='獐子岛公司立案调查', predicate='调查通知书编号', value='连调查字[2018]001号',
       value_kind='text', critical=True,
       quote='《调查通知书》（编号：连调查字[2018]001 号）。', doc_id='2019-01-08', bucket='立案链'),
  dict(fact_id='A2', subject='獐子岛公司', predicate='收到事先告知书日期', value='2019-07-09',
       value_kind='date', quote='2019 年 7 月 9 日，獐子岛集团股份有限公司（以下简称“公司”）收到中国证监会',
       doc_id='2019-07-11', bucket='立案链'),
  dict(fact_id='B1', subject='獐子岛2016年度', predicate='虚减营业成本', value='6002.99万元',
       value_kind='text', critical=True,
       quote='年度虚减营业成本 6,002.99 万元。', doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B2', subject='獐子岛2016年度', predicate='虚减营业外支出', value='7111.78万元',
       value_kind='text', quote='由此，獐子岛公司 2016 年度虚减了营业外支出 7,111.78 万元。',
       doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B3', subject='獐子岛2016年度', predicate='虚增利润', value='13114.77万元',
       value_kind='text', critical=True,
       quote='综上，受虚减营业成本 和营业外支出 的影响，獐子岛 公司 2016 年度虚增 利润',
       doc_id=PEN, bucket='造假金额') if False else dict(
       fact_id='B3', subject='獐子岛2016年度', predicate='虚增利润', value='13114.77万元',
       value_kind='text', critical=True,
       quote='13,114.77 万元，虚增利润占当期利润总额的 158.11%', doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B3b', subject='獐子岛2016年度', predicate='虚增利润占当期利润总额比例', value='158.11%',
       value_kind='percent', quote='13,114.77 万元，虚增利润占当期利润总额的 158.11%',
       doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B4', subject='獐子岛2016年度', predicate='账面结转捕捞面积较实际少', value='13.93万亩',
       value_kind='text',
       quote='公司 2016 年度账面结转捕捞面积较实际捕捞面积少 13.93 万亩', doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B5', subject='獐子岛2017年度', predicate='虚增营业成本', value='6159.03万元',
       value_kind='text', quote='獐子岛公司 2017 年度虚增营业成本 6,159.03 万元。',
       doc_id=PEN, bucket='造假金额'),
  dict(fact_id='B6', subject='獐子岛2017年度', predicate='合计虚增营业外支出', value='20595.54万元',
       value_kind='text', quote='综上，2017 年度獐子岛公司合计虚增营业外支出 20,595.54 万元。',
       doc_id=PEN, bucket='造假金额'),
  dict(fact_id='C1', subject='獐子岛造假手法', predicate='成本结转依据',
       value='以当月虾夷扇贝捕捞区域(采捕坐标)作为成本结转的依据；捕捞区域由人工填报且缺乏船只航海日志予以佐证',
       value_kind='text', quote='作为成本结转的依据，捕捞区域系由人工填报且缺乏船只航海日志予以佐证',
       doc_id=PEN, bucket='手法'),
  # 处罚与禁入 (target field)
  dict(fact_id='D1', subject='獐子岛集团股份有限公司', predicate='罚款', value='60万元',
       value_kind='text', critical=True,
       quote='一、对獐子岛集团股份有限公司给予警告，并处以 60 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D2', subject='吴厚刚、梁峻', predicate='罚款(每人)', value='30万元',
       value_kind='text', critical=True,
       quote='二、对吴厚刚、梁峻给予警告，并分别处以 30 万元罚款；', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D3', subject='孙福君、勾荣', predicate='罚款(每人)', value='20万元',
       value_kind='text', quote='三、对孙福君、勾荣给予警告，并分别处以 20 万元罚款；',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D4', subject='吴厚刚', predicate='市场禁入措施', value='终身市场禁入',
       value_kind='text', critical=True,
       quote='我会决定：对吴厚刚采取终身市场禁入措施。', doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D5', subject='梁峻', predicate='市场禁入措施', value='10年市场禁入',
       value_kind='text', quote='我会决定：对梁峻采取 10 年市场禁入措施，对勾荣、孙福君',
       doc_id=PEN, bucket='处罚金额'),
  dict(fact_id='D6', subject='勾荣、孙福君', predicate='市场禁入措施(每人)', value='5年证券市场禁入',
       value_kind='text', quote='分别采取 5 年证券市场禁入措施。', doc_id=PEN, bucket='处罚金额'),
]

UNKNOWNS = [dict(item_id='U1', question='獐子岛是否触及重大违法强制退市情形（决定书认定不触及，但公司后续股票命运需其他文书确认）')]

META = dict(
    task_id='V23A_ZHANGZIDAO_FRAUD_PENALTY',
    question='獐子岛：立案调查通知书的编号是什么？2016 年度虚减营业成本、虚减营业外支出、虚增利润各多少、'
             '虚增利润占当期利润总额比例多少？2017 年度虚增营业成本、合计虚增营业外支出各多少？造假手法中成本结转的'
             '依据是什么？行政处罚对公司、吴厚刚与梁峻、孙福君与勾荣分别罚款多少？市场禁入对吴厚刚、梁峻、勾荣与孙福君'
             '分别是什么措施？',
    cutoff='2020-06-25',
    nature='三份文书：立案进展公告、事先告知书公告、行政处罚决定书+市场禁入决定书公告（cninfo 原始 PDF，SHA256 见 NEW_EVENT_DOCS_MANIFEST）',
    target_field='penalty_amounts',
    target_slots=['D1', 'D2', 'D3', 'D4', 'D5', 'D6'],
    e_node_of_target='E_处罚决定书(2020-06-25)',
)

if __name__ == '__main__':
    path, facts, problems = build('ZHANGZIDAO', DOCS, FACTS, UNKNOWNS, META,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
    print('wrote', path, '| facts', len(facts), '| problems', problems)
