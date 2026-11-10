#!/usr/bin/env python3
"""Build 中潜股份 (300526) Gold contract DRAFT from source texts (zero model calls).
Every fact is anchored to a verbatim quote in its source document with raw character offsets."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT.mkdir(parents=True, exist_ok=True)
D1_FILE = next(RAW.glob('300526_notice_*.txt'))
D2_FILE = next(RAW.glob('300526_decision_*.txt'))
D1_PDF = next(RAW.glob('300526_notice_*.pdf'))
D2_PDF = next(RAW.glob('300526_decision_*.pdf'))
D1 = D1_FILE.read_text('utf-8')
D2 = D2_FILE.read_text('utf-8')
D1_META = json.loads(next(RAW.glob('300526_notice_*.meta.json')).read_text())
D2_META = json.loads(next(RAW.glob('300526_decision_*.meta.json')).read_text())

def norm(x): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))
PAGE_MARK = re.compile(r'\s*\d{1,3}\s*\x0c')
D1N = norm(PAGE_MARK.sub('', D1))
D2N = norm(PAGE_MARK.sub('', D2))

def locate(text, quote):
    """Verify quote is verbatim (whitespace-insensitive) in text; return flat offset."""
    q = norm(quote)
    pos = D2N.find(q) if text == 'D2' else D1N.find(q)
    if pos < 0: raise ValueError(f'NOT VERBATIM in {text}: {quote[:60]}...')
    return pos

def ev(doc, quote):
    pos = locate(doc, quote)
    sha = D2_META['sha256'] if doc == 'D2' else D1_META['sha256']
    return [dict(doc_id=doc, page=1, quote=quote, char_start=pos, pdf_sha256=sha)]

# ===== FACTS =====
F = []
def add(fid, subj, pred, val, kind, critical, docs, rule, s_anchor, p_anchor, quotes, unit=None, derivation=None, **kwargs):
    f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
             critical=critical, evidence_required=True, value_kind=kind,
             subject=subj, predicate=pred, value=val,
             allowed_citation_docs=docs, source_evidence=quotes,
             grounding=dict(rule=rule, subject_anchor=s_anchor, predicate_anchor=p_anchor))
    if unit: f['unit'] = unit
    if derivation: f['derivation'] = derivation
    if 'dual_stage' in kwargs: f['dual_stage'] = kwargs['dual_stage']
    F.append(f)

# F1-F6: final penalty amounts (D2)
add('F1', '中潜股份有限公司', '行政处罚罚款金额', '350', 'number', True, ['D2'], 'amount', '中潜', '罚款',
    ev('D2', '一、对中潜股份有限公司责令改正，给予警告，并处以350万元罚款'))
add('F2', '张顺', '行政处罚罚款金额', '200', 'number', True, ['D2'], 'amount', '张顺', '罚款',
    ev('D2', '二、对张顺、仰智慧给予警告，并分别处以200万元罚款'))
add('F3', '仰智慧', '行政处罚罚款金额', '200', 'number', True, ['D2'], 'amount', '仰智慧', '罚款',
    ev('D2', '二、对张顺、仰智慧给予警告，并分别处以200万元罚款'))
add('F4', '郭建兵', '行政处罚罚款金额', '150', 'number', True, ['D2'], 'amount', '郭建兵', '罚款',
    ev('D2', '三、对郭建兵、明小燕给予警告，并分别处以150万元罚款'))
add('F5', '明小燕', '行政处罚罚款金额', '150', 'number', True, ['D2'], 'amount', '明小燕', '罚款',
    ev('D2', '三、对郭建兵、明小燕给予警告，并分别处以150万元罚款'))
add('F6', '张继红等8人', '单人行政处罚罚款金额', '50', 'number', False, ['D2'], 'amount', '张继红', '罚款',
    ev('D2', '四、对张继红、徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以50万元罚款'))
# F7-F10: financial fraud (D2 primary, D1 same)
add('F7', '中潜股份2019年度', '虚增营业收入', '3728.71', 'number', True, ['D1', 'D2'], 'amount', None, '营业收入',
    ev('D2', '虚增营业收入37,287,122.50元'), unit='万元',
    derivation=dict(original_yuan='37,287,122.50', original_unit='元', standard_wan='3728.71', standard_unit='万元', precision=2, conversion='37,287,122.50÷10000=3728.7122…→保留2位=3728.71'))
add('F8', '中潜股份2019年度', '虚增营业成本', '1154.28', 'number', False, ['D1', 'D2'], 'amount', None, '营业成本',
    ev('D2', '虚增营业成本11,542,807.38元'), unit='万元',
    derivation=dict(original_yuan='11,542,807.38', original_unit='元', standard_wan='1154.28', standard_unit='万元', precision=2, conversion='11,542,807.38÷10000=1154.2807…→保留2位=1154.28'))
add('F9', '中潜股份2019年度', '虚增营业利润', '2574.43', 'number', True, ['D1', 'D2'], 'amount', None, '营业利润',
    ev('D2', '导致营业利润虚增25,744,315.12元'), unit='万元',
    derivation=dict(original_yuan='25,744,315.12', original_unit='元', standard_wan='2574.43', standard_unit='万元', precision=2, conversion='25,744,315.12÷10000=2574.4315…→保留2位=2574.43'))
add('F10', '中潜股份2019年度', '虚增利润占当期利润总额比例', '62.08', 'number', False, ['D1', 'D2'], 'amount', None, '利润总额',
    ev('D2', '占当期利润总额的62.08%'), unit='%')
# F11: related-party transaction total
add('F11', '中潜股份2019年度', '经营性关联交易合计', '3710.03', 'number', False, ['D1', 'D2'], 'amount', None, '关联交易',
    ev('D2', '共发生经营性关联交易37,100,264.72元'), unit='万元',
    derivation=dict(original_yuan='37,100,264.72', original_unit='元', standard_wan='3710.03', standard_unit='万元', precision=2, conversion='37,100,264.72÷10000=3710.0265…→保留2位=3710.03'))
# F12-F15: dates
add('F12', '中潜股份', '调查通知书收到日期', '2020-10-20', 'date', True, ['D1', 'D2'], 'date', None, '调查通知书',
    ev('D2', '于2020年10月20日收到中国证券监督管理委员会（以下简称“中国证监会”）出具的《调查通知书》（编号：粤调查字20137）'))
add('F13', '中潜股份', '事先告知书收到日期', '2021-05-28', 'date', True, ['D1', 'D2'], 'date', None, '告知书',
    ev('D2', '2021年5月28日，公司收到中国证券监督管理委员会广东监管局出具的《行政处罚事先告知书》（广东证监处罚字[2021]6号）'))
add('F14', '中潜股份', '行政处罚决定书收到日期', '2021-08-31', 'date', True, ['D2'], 'date', None, '决定书',
    ev('D2', '2021年8月31日，公司收到中国证券监督管理委员会广东监管局出具的《行政处罚事决定书》〔2021〕13号（以下简称“决定书”）'))
# F15-F17: document numbers
add('F15', '调查通知书', '编号', '粤调查字20137', 'text', False, ['D1', 'D2'], 'doc_number', None, '调查通知书',
    ev('D2', '《调查通知书》（编号：粤调查字20137）'))
add('F16', '事先告知书', '文号', '广东证监处罚字[2021]6号', 'text', False, ['D1', 'D2'], 'doc_number', None, '告知书',
    ev('D2', '《行政处罚事先告知书》（广东证监处罚字[2021]6号）'))
add('F17', '行政处罚决定书', '文号', '〔2021〕13号', 'text', False, ['D2'], 'doc_number', None, '决定书',
    ev('D2', '《行政处罚事决定书》〔2021〕13号'))
# F18: 张顺 职务
add('F18', '张顺', '职务', '董事长', 'text', True, ['D1', 'D2'], 'title_set', '张顺', None,
    ev('D2', '张顺，男，1963年5月出生，时任中潜股份董事长'))
# F19: total penalty (derived)
add('F19', '全部当事人', '罚款合计', '1450', 'number', False, ['D2'], 'penalty_line_sum', None, '罚款',
    ev('D2', '一、对中潜股份有限公司责令改正，给予警告，并处以350万元罚款') +
    ev('D2', '二、对张顺、仰智慧给予警告，并分别处以200万元罚款') +
    ev('D2', '三、对郭建兵、明小燕给予警告，并分别处以150万元罚款') +
    ev('D2', '四、对张继红、徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以50万元罚款'),
    unit='万元',
    derivation=dict(rule='sum of D2 penalty lines: 350 + 200×2 + 150×2 + 50×8 = 1450万元',
                    parties=13))
# F20: delisting
add('F20', '中潜股份', '是否触及重大违法强制退市情形', '否', 'text', False, ['D1', 'D2'], 'negation', None, '强制退市',
    ev('D2', '涉及的信息披露违法行为未触及《深圳证券交易所上市公司重大违法强制退市实施办法》第二条、第四条、第五条'))


# F21-F23: D1 proposed-stage facts (operator P0 requirement: capture stage changes)
add('F21', '全部当事人', '拟处罚罚款合计', '1540', 'number', False, ['D1'], 'penalty_line_sum', None, '罚款',
    ev('D1', '一、对中潜股份责令改正，给予警告,并处以 350 万元罚款') +
    ev('D1', '二、对张顺、仰智慧给予警告，并分别处以 200 万元罚款') +
    ev('D1', '三、对郭建兵、明小燕给予警告，并分别处以 150 万元罚款') +
    ev('D1', '四、对卓泽鹏、张继红给予警告，并分别处以 70 万元罚款') +
    ev('D1', '五、对徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以 50 万元罚款'),
    unit='万元',
    derivation=dict(rule='sum of D1 proposed penalty lines: 350 + 200×2 + 150×2 + 70×2 + 50×7 = 1540万元',
                    parties=14, note='D1 拟罚合计，终罚合计见 F19=1450万，差 90万来自卓泽鹏剔除(70)与张继红下调(20)'))
add('F22', '卓泽鹏', '拟处罚罚款金额（终罚状态：未处罚）', '70', 'number', False, ['D1', 'D2'], 'amount', '卓泽鹏', '罚款',
    ev('D1', '四、对卓泽鹏、张继红给予警告，并分别处以 70 万元罚款') +
    ev('D2', '四、对张继红、徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以50万元罚款'),
    unit='万元',
    dual_stage=dict(
        d1_proposed='70万元', d1_evidence_doc='D1',
        d2_final='未处罚（不在 D2 处罚名单中）', d2_evidence_doc='D2',
        change='dropped',
        note='模型须引用 D1 证明拟罚 70万；D2 处罚条款不含卓泽鹏，佐证其被剔除。'
             '若模型引 D2 的任何金额作为 D1 拟罚值，仍判 VALUE_WRONG（D2 无 70万）。'
             '若模型只引 D1 不引 D2，值正确但缺少终罚佐证（不影响值分，影响机制分析）。'))
add('F23', '张继红', '拟处罚罚款金额（终罚：50万元）', '70', 'number', False, ['D1', 'D2'], 'amount', '张继红', '罚款',
    ev('D1', '四、对卓泽鹏、张继红给予警告，并分别处以 70 万元罚款') +
    ev('D2', '四、对张继红、徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧给予警告，并分别处以50万元罚款'),
    unit='万元',
    dual_stage=dict(
        d1_proposed='70万元', d1_evidence_doc='D1',
        d2_final='50万元', d2_evidence_doc='D2',
        change='reduced_70_to_50',
        note='模型须引用 D1 证明拟罚 70万；D2 显示终罚降为 50万。'
             '若模型引 D2 的 50万 作为 D1 拟罚值，判 VALUE_WRONG（Gold=70）。'
             '若模型分别引 D1（拟罚）和 D2（终罚），两阶段变化识别正确。'))

CONTRACT = dict(
    task_id='P2_ZQ_300526_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-B 试点任务 1/3。Gold 由规则从原文构建，未经操作员审阅确认前不得调用任何模型。',
    question='中潜股份信息披露违法违规案：证监会最终对公司及各责任人员分别处以多少罚款？全部当事人罚款合计多少？拟处罚合计多少？卓泽鹏与张继红的拟罚金额各是多少？2019年度虚增营业收入、虚增营业成本、虚增营业利润各是多少（元与万元）？虚增利润占当期利润总额比例？2019年度经营性关联交易合计？调查通知书、事先告知书、行政处罚决定书各于何日收到？三份文书编号/文号？张顺的职务？是否触及重大违法强制退市情形？',
    cutoff='2021-08-31',
    source_documents=dict(
        D1=dict(title='关于收到《行政处罚事先告知书》的公告（2021-05-28，公告编号2021-064）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到《行政处罚决定书》的公告（2021-08-31，公告编号2021-082）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['中潜股份有限公司', 350], ['张顺、仰智慧', 200], ['郭建兵、明小燕', 150], ['张继红、徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧', 50]],
        proposed_lines_D1=[['中潜股份', 350], ['张顺、仰智慧', 200], ['郭建兵、明小燕', 150], ['卓泽鹏、张继红', 70], ['徐志宏、孙昌兴、鲍群、鲍金红、冯小燕、代利、李志慧', 50]],
        final_total_wan=1450, proposed_total_wan=1540,
        parties=[dict(party=p, proposed_wan=70 if p == '张继红' else 50, final_wan=None if p == '卓泽鹏' else (50 if p != '张继红' else 50),
                      change='dropped' if p == '卓泽鹏' else ('adjusted 70→50' if p == '张继红' else 'unchanged'))
                 for p in ['中潜股份', '张顺', '仰智慧', '郭建兵', '明小燕', '卓泽鹏', '张继红', '徐志宏', '孙昌兴', '鲍群', '鲍金红', '冯小燕', '代利', '李志慧']],
        aliases=[dict(canonical='中潜股份有限公司', variants=['中潜股份', '公司'], where='both docs use 中潜股份 in penalty clause')],
    ),
    scoring=dict(primary='Q_all = TP / N (N=20)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern (contract-driven, arm-blind)'),
    provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext 文本层；Gold 值与证据跨度由本脚本按规则从原文读取',
                    model_calls=0, independence='zero hits on code/names/parties/doc numbers in working tree, git HEAD, git history'),
    known_issues=[
        dict(issue='D2 text has typo "行政处罚事决定书" (missing 罚) in the receipt-date sentence', handling='quote as-is'),
        dict(issue='卓泽鹏 appears in D1 (70万) but is NOT penalized in D2', handling='D1-only trap; D2 whitelist excludes'),
    ],
)

out = OUT / 'TASK_CONTRACT_ZQ_300526_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('draft contract sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')

# Self-check: every quote verbatim
for f in F:
    for e in f['source_evidence']:
        q = norm(e['quote'])
        target = D2N if e['doc_id'] == 'D2' else D1N
        if q not in target:
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}')
            break
    else:
        continue
    break
else:
    print('self-check: all quotes verbatim ✓')

# Verify totals
total_d2 = 350 + 200*2 + 150*2 + 50*8
total_d1 = 350 + 200*2 + 150*2 + 70*2 + 50*7
assert total_d2 == 1450, f'D2 total mismatch: {total_d2}'
assert total_d1 == 1540, f'D1 total mismatch: {total_d1}'
print(f'totals verified: D2={total_d2}万, D1={total_d1}万 ✓')
