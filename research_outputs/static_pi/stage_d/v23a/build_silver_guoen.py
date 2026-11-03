"""GUOEN (国恩股份 002768 收购中氟能80%股权) silver facts — Phase V2.3-A."""
import sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
from silver_builder_v23a import build

DOCS = {'ACQUISITION': 'docs/GUOEN/ACQUISITION.txt', 'CLOSING': 'docs/GUOEN/CLOSING.txt'}
A = 'ACQUISITION'

FACTS = [
  dict(fact_id='A1', subject='国恩股份收购交易', predicate='交易对方', value='赖明贵',
       value_kind='text', critical=True,
       quote='公司于2026 年10 月11 日与赖明贵（以下简称', doc_id=A, bucket='交易主体'),
  dict(fact_id='A2', subject='国恩股份收购交易', predicate='标的', value='四川中氟能新材料科技有限公司80%股权',
       value_kind='text', critical=True,
       quote='持有的中氟能80%股权（以下简称“标的股权”），交易价格为人民币',
       doc_id=A, bucket='交易主体'),
  dict(fact_id='A3', subject='国恩股份收购交易', predicate='总对价', value='150400.00万元',
       value_kind='number', critical=True,
       quote='150,400.00 万元。本次交易完成后，标的公司将成为公司合并报表范围内的控',
       doc_id=A, bucket='交易主体'),
  dict(fact_id='A4', subject='国恩股份收购交易', predicate='董事会审议日期', value='2026-10-10',
       value_kind='date',
       quote='公司于2026 年10 月10 日召开的第六届董事会第四次会议，审议通过了',
       doc_id=A, bucket='交易主体'),
  # 付款安排 (target field)
  dict(fact_id='B1', subject='国恩股份收购交易', predicate='第一期交易价款', value='11000.00万元',
       value_kind='number', critical=True,
       quote='（1）第一期交易价款。甲方应在本协议生效后支付第一期交易价款，支付',
       doc_id=A, bucket='付款安排') if False else dict(
       fact_id='B1', subject='国恩股份收购交易', predicate='第一期交易价款', value='11000.00万元',
       value_kind='number', critical=True,
       quote='金额为人民币11,000.00 万元。', doc_id=A, bucket='付款安排'),
  dict(fact_id='B2', subject='国恩股份收购交易', predicate='定金及归属', value='1000.00万元定金自动转为第一期交易价款一部分',
       value_kind='text', critical=True,
       quote='民币1,000.00 万元定金，自动转为第一期交易价款的一部分；甲方应于本协议',
       doc_id=A, bucket='付款安排'),
  dict(fact_id='B3', subject='国恩股份收购交易', predicate='第二期交易价款', value='79240.00万元',
       value_kind='number', critical=True,
       quote='付第二期交易价款，支付金额为人民币79,240.00 万元。', doc_id=A, bucket='付款安排'),
  dict(fact_id='B4', subject='国恩股份收购交易', predicate='第三期交易价款(共管账户)', value='60160.00万元',
       value_kind='number', critical=True,
       quote='的共管账户中汇入第三期交易价款，支付金额为人民币60,160.00 万元。',
       doc_id=A, bucket='付款安排'),
  dict(fact_id='B5', subject='国恩股份收购交易', predicate='第一二期合计支付比例', value='60%',
       value_kind='percent', critical=True,
       quote='乙方指定账户，第一期、第二期交易价款合计支付比例为60%；第三期交易价',
       doc_id=A, bucket='付款安排'),
  dict(fact_id='B6', subject='国恩股份收购交易', predicate='第二期付款时点', value='交割日后5个工作日内',
       value_kind='text', quote='（2）第二期交易价款。甲方应于交割日后5 个工作日内向乙方指定账户支',
       doc_id=A, bucket='付款安排'),
  dict(fact_id='B7', subject='国恩股份收购交易', predicate='第三期付款时点', value='交割日后15个工作日内汇入共管账户',
       value_kind='text', quote='（3）第三期交易价款。甲方应于交割日后15 个工作日内，向本协议约定',
       doc_id=A, bucket='付款安排'),
  # 交割状态 (CLOSING doc)
  dict(fact_id='C1', subject='国恩股份收购交易', predicate='交割完成情况',
       value='已完成交割：已支付第一期价款、完成变更登记/备案，公司持有标的80%股权并纳入合并报表',
       value_kind='text', critical=True,
       quote='价款；交易对方及标的公司已按照协议约定修改公司章程，并完成市场监督管',
       doc_id='CLOSING', bucket='交割状态'),
  dict(fact_id='C2', subject='国恩股份收购交易', predicate='交割公告所述已付款期数', value='仅第一期',
       value_kind='text', critical=True,
       quote='根据交易各方签署的《股权收购协议》，公司已按照约定支付第一期交易',
       doc_id='CLOSING', bucket='交割状态'),
]

UNKNOWNS = [
  dict(item_id='U1', question='第二期、第三期交易价款截至交割公告日是否已实际支付（两份文书均未披露）'),
  dict(item_id='U2', question='第三期价款自共管账户向乙方释放是否已发生（需专项审核报告等后续公告）'),
]

META = dict(
    task_id='V23A_GUOEN_ACQUISITION_CLOSING',
    question='国恩股份收购中氟能80%股权：交易对方、标的与总对价各是什么？交易价款的分期安排如何——'
             '第一期金额与定金归属、第二期金额与付款时点、第三期金额与共管账户安排、前两期合计支付比例分别是多少？'
             '交割完成公告披露了哪几期价款已支付？仅凭两份公告能否证明全部交易价款已付清？无法判定的付款状态作为未知项列出。',
    cutoff='2026-10-15',
    nature='两份公告：收购公告(2026-055)与交割完成公告(2026-057)（cninfo 原始 PDF，逐页文本与 SHA256 见 SOURCES.json）',
    target_field='payment_schedule',
    target_slots=['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7'],
    e_node_of_target='E_收购公告(ACQUISITION)',
)

if __name__ == '__main__':
    path, facts, problems = build('GUOEN', DOCS, FACTS, UNKNOWNS, META,
                                  '/root/research_outputs/static_pi/stage_d/v23a/tasks')
    print('wrote', path, '| facts', len(facts), '| problems', problems)
