#!/usr/bin/env python3
"""ST东洋 (002086) Gold contract builder.

D1 = 【2021】13号《行政处罚及市场禁入事先告知书》(2021-11-30收到)
D2 = [2022]1号《行政处罚决定书》+《市场禁入决定书》(2022-01-19收到)
Same case: 2020-07-31立案披露, 非经营性占用资金关联交易未披露案.
ZERO stage change: D1拟罚与D2终罚逐项一致 (130/120/120/60/50/25/20/20/10万, 合计555万),
禁入一致 (车轼终身, 于雁冰10年). 与凯瑞德(全下调型)互补的"零变化"情景.

KNOWN TRAP: D1 raw text item 一 = "并处以 130\n<page-footer 6>\n万元罚款" —
normalized D1 contains the artifact "并处以1306万元罚款"; the "6" is a PDF page number.
Gold = 130万元 (verified from D2 clean text + identical structure of remaining items).
"""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
D1F = '002086_notice_1638288000000.pdf.txt'
D2F = '002086_decision_1642608000000.pdf.txt'
D1 = (RAW / D1F).read_text('utf-8')
D2 = (RAW / D2F).read_text('utf-8')
D1_META = json.loads((RAW / D1F.replace('.txt', '.meta.json')).read_text())
D2_META = json.loads((RAW / D2F.replace('.txt', '.meta.json')).read_text())

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
D1N = norm(D1); D2N = norm(D2)

def ev(doc, quote):
    q = norm(quote); t = D2N if doc == 'D2' else D1N
    if q not in t: raise ValueError(f'NOT VERBATIM in {doc}: {quote[:60]}')
    return [dict(doc_id=doc, page=1, quote=quote,
                 pdf_sha256=D2_META['sha256'] if doc == 'D2' else D1_META['sha256'])]

F = []
def add(fid, subj, pred, val, kind, crit, docs, rule, sa, pa, quotes, unit=None, **kw):
    f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
             critical=crit, evidence_required=True, value_kind=kind, subject=subj, predicate=pred,
             value=val, allowed_citation_docs=docs, source_evidence=quotes,
             grounding=dict(rule=rule, subject_anchor=sa, predicate_anchor=pa))
    if unit: f['unit'] = unit
    for k in ('derivation', 'dual_stage'):
        if k in kw: f[k] = kw[k]
    F.append(f)

# ---- D2 FINAL PENALTY (9 parties, identical to D1 proposal) ----
add('F1', '山东东方海洋科技股份有限公司', '行政处罚罚款金额', '130', 'number', True, ['D1', 'D2'], 'amount', '东方海洋科技', '罚款',
    ev('D2', '一、对山东东方海洋科技股份有限公司责令改正，给予警告，并处以 130 万元罚款'),
    unit='万元',
    derivation=dict(note='D1同项=130万（D1原文该项被PDF页码"6"截断为"130/6/万元"，勿读作1306；D2干净文本确证130）'),
    dual_stage=dict(d1_proposed='130万元', d2_final='130万元', change='unchanged'))
add('F2', '山东东方海洋集团有限公司', '行政处罚罚款金额', '120', 'number', True, ['D1', 'D2'], 'amount', '东方海洋集团', '罚款',
    ev('D2', '二、对山东东方海洋集团有限公司处以 120 万元罚款') + ev('D1', '二、对山东东方海洋集团有限公司处以 120 万元罚款'),
    unit='万元', dual_stage=dict(d1_proposed='120万元', d2_final='120万元', change='unchanged'))
add('F3', '车轼', '行政处罚罚款金额', '120', 'number', True, ['D1', 'D2'], 'amount', '车轼', '罚款',
    ev('D2', '对车轼给予警告，并处以 120 万元罚款，其中作为东方海洋直接负责的主管人员罚款 60 万元，作为东方海洋集团直接负责的主管人员罚款 60 万元'),
    unit='万元',
    derivation=dict(note='构成：东方海洋主管60万+东方海洋集团主管60万'),
    dual_stage=dict(d1_proposed='120万元(60+60)', d2_final='120万元(60+60)', change='unchanged'))
add('F4', '于雁冰', '行政处罚罚款金额', '60', 'number', True, ['D1', 'D2'], 'amount', '于雁冰', '罚款',
    ev('D2', '四、对于雁冰给予警告，并处以 60 万元罚款'), unit='万元',
    dual_stage=dict(d1_proposed='60万元', d2_final='60万元', change='unchanged'))
add('F5', '马兆山', '行政处罚罚款金额', '50', 'number', False, ['D1', 'D2'], 'amount', '马兆山', '罚款',
    ev('D2', '五、对马兆山给予警告，并处以 50 万元罚款'), unit='万元')
add('F6', '车志远', '行政处罚罚款金额', '25', 'number', False, ['D1', 'D2'], 'amount', '车志远', '罚款',
    ev('D2', '六、对车志远给予警告，并处以 25 万元罚款'), unit='万元')
add('F7', '赵玉山', '行政处罚罚款金额', '20', 'number', False, ['D1', 'D2'], 'amount', '赵玉山', '罚款',
    ev('D2', '七、对赵玉山给予警告，并处以 20 万元罚款'), unit='万元')
add('F8', '于深基', '行政处罚罚款金额', '20', 'number', False, ['D1', 'D2'], 'amount', '于深基', '罚款',
    ev('D2', '八、对于深基给予警告，并处以 20 万元罚款'), unit='万元')
add('F9', '于善福', '行政处罚罚款金额', '10', 'number', False, ['D1', 'D2'], 'amount', '于善福', '罚款',
    ev('D2', '九、对于善福给予警告，并处以 10 万元罚款'), unit='万元')

# ---- TOTALS ----
add('F10', '全部当事人', '罚款合计', '555', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
    ev('D2', '一、对山东东方海洋科技股份有限公司责令改正，给予警告，并处以 130 万元罚款'), unit='万元',
    derivation=dict(rule='130+120+120+60+50+25+20+20+10=555万', parties=9))
add('F11', '全部当事人', '拟处罚罚款合计', '555', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
    ev('D1', '二、对山东东方海洋集团有限公司处以 120 万元罚款'), unit='万元',
    derivation=dict(rule='130+120+120+60+50+25+20+20+10=555万（与D2终罚逐项一致）', parties=9))

# ---- STAGE CHANGE (explicit zero-change slot) ----
add('F12', '全部处罚事项', 'D1拟罚→D2终罚阶段变化', '无变化（9项罚款金额、主体、2项市场禁入均逐项一致）', 'text', True, ['D1', 'D2'], 'text', None, '阶段变化',
    ev('D1', '三、对车轼给予警告，并处以 120 万元罚款，其中作为东方海洋直接负责的主管人员罚款 60 万元，作为东方海洋集团直接负责的主管人员罚款 60 万元') +
    ev('D2', '三、对车轼给予警告，并处以 120 万元罚款，其中作为东方海洋直接负责的主管人员罚款 60 万元，作为东方海洋集团直接负责的主管人员罚款 60 万元'),
    dual_stage=dict(d1_proposed='555万+2项禁入', d2_final='555万+2项禁入', change='none'))

# ---- MARKET BANS ----
add('F13', '车轼', '市场禁入措施', '终身证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '车轼', '禁入',
    ev('D2', '车轼采取终身证券市场禁入措施') + ev('D1', '对车轼采取终身证券市场禁入措施'))
add('F14', '于雁冰', '市场禁入措施', '10年证券市场禁入', 'text', True, ['D1', 'D2'], 'text', '于雁冰', '禁入',
    ev('D2', '对于雁冰采取 10 年证券市场禁入措施') + ev('D1', '对于雁冰采取十年证券市场禁入措施'))

# ---- VIOLATION FACT ----
add('F15', '东方海洋与东方海洋集团', '非经营性占用资金关联交易金额合计', '13709.55', 'number', True, ['D1', 'D2'], 'amount', '东方海洋', '占用资金',
    ev('D2', '与东方海洋集团非经营性占用资金关联交易金额合计 13,709.55 万元'), unit='万元',
    derivation=dict(original_yuan_text='13,709.55万元', standard_wan='13709.55'))

# ---- DATES ----
add('F16', '东方海洋', '立案调查披露日期', '2020-07-31', 'date', True, ['D1', 'D2'], 'date', '东方海洋', '立案',
    ev('D2', '公司于 2020 年 7 月 31 日披露了关于收到') + ev('D1', '公司于 2020 年 7 月 31 日披露了关于收到'),
    derivation=dict(note='两文书均以披露日表述（公告2020-057），未给出收到调查通知书的具体日期'))
add('F17', '东方海洋', '事先告知书收到日期', '2021-11-30', 'date', True, ['D1', 'D2'], 'date', '东方海洋', '告知书',
    ev('D2', '2021 年 11 月 30 日，公司及相关当事人收到中国证监会《行政处罚及市场禁入事先告知书》（【2021】13 号）') +
    ev('D1', '2021 年 11 月 30 日，公司及相关当事人收到中国证监会《行政处罚及市场禁人事先告知书》（【2021】13 号）'),
    derivation=dict(note='D1原文此处"禁入"误排为"禁人"，引文照录原文字形'))
add('F18', '东方海洋', '行政处罚决定书收到日期', '2022-01-19', 'date', True, ['D2'], 'date', '东方海洋', '决定书',
    ev('D2', '2022 年 1 月 19 日收到中国证券监督管理委员会'))

# ---- DOC NUMBERS ----
add('F19', '行政处罚决定书', '文号', '[2022]1号', 'text', False, ['D2'], 'doc_number', None, '文号',
    ev('D2', '《行政处罚决定书》（[2022]1 号）'))
add('F20', '行政处罚及市场禁入事先告知书', '文号', '【2021】13号', 'text', False, ['D1'], 'doc_number', None, '文号',
    ev('D1', '《行政处罚及市场禁入事先告知书》（【2021】13 号）'))

CONTRACT = dict(
    task_id='P2_DY_002086_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-C 确认实验任务。零变化型：D1拟罚与D2终罚完全一致（9主体555万+车轼终身/于雁冰10年禁入），与凯瑞德（全下调+撤销型）构成阶段变化谱系两端。附D1文本"130/6/万元"页码陷阱。',
    question='东方海洋信息披露违法案：终罚9主体各多少？合计多少？拟罚合计多少？D1拟罚到D2终罚有何变化？车轼和于雁冰市场禁入措施？非经营性占用资金关联交易金额合计？立案披露、告知书、决定书日期？两文书文号？',
    cutoff='2022-01-19',
    source_documents=dict(
        D1=dict(title='关于收到〈行政处罚及市场禁入事先告知书〉的公告（2021-11-30收到，【2021】13号）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到〈行政处罚决定书〉及〈市场禁入决定书〉的公告（2022-01-19收到，[2022]1号）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['东方海洋科技', 130], ['东方海洋集团', 120], ['车轼', 120], ['于雁冰', 60],
                        ['马兆山', 50], ['车志远', 25], ['赵玉山', 20], ['于深基', 20], ['于善福', 10]],
        proposed_lines_D1='与final_lines_D2完全一致',
        final_total_wan=555, proposed_total_wan=555,
        changes='无（9项罚款+2项禁入逐项一致）',
        market_bans=dict(lifetime=['车轼'], ten_year=['于雁冰'], proposed_identical=True),
        aliases=[dict(canonical='山东东方海洋科技股份有限公司', variants=['东方海洋', '公司'], where='both docs'),
                 dict(canonical='山东东方海洋集团有限公司', variants=['东方海洋集团'], where='both docs')]),
    scoring=dict(primary='Q_all = TP / N (N=20)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF', model_calls=0, independence='DAG-line independent'),
    known_issues=[
        dict(issue='D1原文罚款项一"并处以130"与"万元罚款"之间插入PDF页码"6"，归一化文本含"1306万元"伪影', handling='gold=130万，以D2干净文本逐项确证；该陷阱已写入F1 derivation'),
        dict(issue='立案日期仅有披露日表述（2020-07-31，公告2020-057），无收到日', handling='槽位定义为"立案调查披露日期"'),
        dict(issue='D2法律依据为2005证券法193条+证券法197条第一款并用（违法行为跨新旧法）', handling='未设槽，不影响处罚金额事实'),
    ],
)

out = OUT / 'TASK_CONTRACT_DY_002086_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')
bad = 0
for f in F:
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id'] == 'D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); bad += 1
print('self-check:', 'all quotes verbatim ✓' if bad == 0 else f'{bad} FAILURES')
d2t = 130 + 120 + 120 + 60 + 50 + 25 + 20 + 20 + 10
print(f'totals: D2={d2t}万 {"✓" if d2t == 555 else "MISMATCH"}')
print('trap-check: "1306" in normalized D1:', '并处以1306万元' in D1N)
