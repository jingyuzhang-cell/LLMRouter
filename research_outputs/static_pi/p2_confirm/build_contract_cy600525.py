#!/usr/bin/env python3
"""Build 长园集团 (600525) Gold contract DRAFT from source texts (zero model calls)."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT.mkdir(parents=True, exist_ok=True)
D1_FILE = next(RAW.glob('600525_notice_*.txt'))
D2_FILE = next(RAW.glob('600525_decision_*.txt'))
D1 = D1_FILE.read_text('utf-8')
D2 = D2_FILE.read_text('utf-8')
D1_META = json.loads(next(RAW.glob('600525_notice_*.meta.json')).read_text())
D2_META = json.loads(next(RAW.glob('600525_decision_*.meta.json')).read_text())

def norm(x): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))
PAGE_MARK = re.compile(r'\s*\d{1,3}\s*\x0c')
D1N = norm(PAGE_MARK.sub('', D1))
D2N = norm(PAGE_MARK.sub('', D2))

def ev(doc, quote):
    q = norm(quote)
    target = D2N if doc == 'D2' else D1N
    if q not in target: raise ValueError(f'NOT VERBATIM in {doc}: {quote[:60]}...')
    pos = target.find(q)
    sha = D2_META['sha256'] if doc == 'D2' else D1_META['sha256']
    return [dict(doc_id=doc, page=1, quote=quote, char_start=pos, pdf_sha256=sha)]

F = []
def add(fid, subj, pred, val, kind, critical, docs, rule, s_anchor, p_anchor, quotes, unit=None, **kwargs):
    f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
             critical=critical, evidence_required=True, value_kind=kind,
             subject=subj, predicate=pred, value=val,
             allowed_citation_docs=docs, source_evidence=quotes,
             grounding=dict(rule=rule, subject_anchor=s_anchor, predicate_anchor=p_anchor))
    if unit: f['unit'] = unit
    for k in ('derivation', 'dual_stage'):
        if k in kwargs: f[k] = kwargs[k]
    F.append(f)

# ===== F1-F5: D2 final penalties =====
add('F1', '长园集团', '行政处罚罚款金额', '50', 'number', True, ['D2'], 'amount', '长园', '罚款',
    ev('D2', '一、对长园集团给予警告,并处以 50 万元的罚款'), unit='万元')
add('F2', '尹智勇', '行政处罚罚款金额', '30', 'number', True, ['D2'], 'amount', '尹智勇', '罚款',
    ev('D2', '二、对尹智勇给予警告,并处以 30 万元罚款'), unit='万元')
add('F3', '史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华（6人）', '单人行政处罚罚款金额', '20', 'number', True, ['D2'], 'amount', '史忻', '罚款',
    ev('D2', '三、对史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华给予警告,并分别处以 20 万元罚款'), unit='万元')
add('F4', '徐成斌', '行政处罚罚款金额', '5', 'number', False, ['D2'], 'amount', '徐成斌', '罚款',
    ev('D2', '四、对徐成斌给予警告,并处以 5 万元罚款'), unit='万元')
add('F5', '隋淑静、姚太平、贺勇（3人）', '单人行政处罚罚款金额', '3', 'number', False, ['D2'], 'amount', '隋淑静', '罚款',
    ev('D2', '五、对隋淑静、姚太平、贺勇给予警告，并分别处以 3 万元罚款'), unit='万元')

# ===== F6-F10: fraud facts (D2 summary) =====
add('F6', '长园集团2016年度', '虚增营业收入', '14971.27', 'number', True, ['D1', 'D2'], 'amount', None, '营业收入',
    ev('D2', '2016年度合并利润表虚增营业收入14,971.27万元'), unit='万元',
    derivation=dict(original_wan='14,971.27', standard_wan='14971.27', precision=2, ratio='2.56%'))
add('F7', '长园集团2016年度', '虚增利润总额', '12300.38', 'number', True, ['D1', 'D2'], 'amount', None, '利润总额',
    ev('D2', '虚增利润总额12,300.38万元'), unit='万元',
    derivation=dict(original_wan='12,300.38', standard_wan='12300.38', precision=2, ratio='15.21%'))
add('F8', '长园集团2017年度', '虚增营业收入', '20958.78', 'number', True, ['D1', 'D2'], 'amount', None, '营业收入',
    ev('D2', '2017年度合并利润表虚增营业收入20,958.78万元'), unit='万元',
    derivation=dict(original_wan='20,958.78', standard_wan='20958.78', precision=2, ratio='2.82%'))
add('F9', '长园集团2017年度', '虚增利润总额', '17989.83', 'number', True, ['D1', 'D2'], 'amount', None, '利润总额',
    ev('D2', '虚增利润总额17,989.83万元'), unit='万元',
    derivation=dict(original_wan='17,989.83', standard_wan='17989.83', precision=2, ratio='14.85%'))
add('F10', '长园集团2016-2017年度', '虚增期末应收账款', '870.41', 'number', False, ['D1', 'D2'], 'amount', None, '应收账款',
    ev('D2', '虚增 2016 年度、2017 年度期末应收账款 870.41 万元'), unit='万元')

# ===== F11-F13: dates =====
add('F11', '长园集团', '调查通知书收到日期', '2019-05-31', 'date', True, ['D1', 'D2'], 'date', None, '调查通知书',
    ev('D2', '于 2019 年 5 月 31 日收到中国证券监督管理委员会《调查通知书》（深证调查通字【2019】114 号）'))
add('F12', '长园集团', '事先告知书收到日期', '2020-06-12', 'date', True, ['D1', 'D2'], 'date', None, '告知书',
    ev('D2', '2020 年 6 月 12 日，公司收到中国证券监督管理委员会深圳监管局《行政处罚及市场禁入事先告知书》（[2020]4 号）'))
add('F13', '长园集团', '行政处罚决定书收到日期', '2020-10-23', 'date', True, ['D2'], 'date', None, '决定书',
    ev('D2', '2020 年 10 月 23 日，公司收到中国证券监督管理委员会深圳监管局'))
add('F15', '事先告知书', '文号', '[2020]4号', 'text', False, ['D1', 'D2'], 'doc_number', None, '告知书',
    ev('D2', '《行政处罚及市场禁入事先告知书》（[2020]4 号）'))
add('F16', '行政处罚决定书', '文号', '[2020]7号', 'text', False, ['D2'], 'doc_number', None, '决定书',
    ev('D2', '《行政处罚决定书》（[2020]7 号）'))

# ===== F17: title =====
add('F17', '许晓文', '职务', '董事长', 'text', True, ['D1', 'D2'], 'title_set', '许晓文', None,
    ev('D2', '许晓文，男，1958 年 6 月出生，时任长园集团董事长'))

# ===== F18-F19: totals =====
add('F18', '全部当事人', '罚款合计', '214', 'number', False, ['D2'], 'penalty_line_sum', None, '罚款',
    ev('D2', '一、对长园集团给予警告,并处以 50 万元的罚款') +
    ev('D2', '二、对尹智勇给予警告,并处以 30 万元罚款') +
    ev('D2', '三、对史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华给予警告,并分别处以 20 万元罚款') +
    ev('D2', '四、对徐成斌给予警告,并处以 5 万元罚款') +
    ev('D2', '五、对隋淑静、姚太平、贺勇给予警告，并分别处以 3 万元罚款'),
    unit='万元',
    derivation=dict(rule='50 + 30 + 20×6 + 5 + 3×3 = 214万元', parties=12))
add('F19', '全部当事人', '拟处罚罚款合计', '219', 'number', False, ['D1'], 'penalty_line_sum', None, '罚款',
    ev('D1', '一、对长园集团给予警告,并处以 50 万元的罚款') +
    ev('D1', '二、对尹智勇给予警告,并处以 30 万元罚款') +
    ev('D1', '三、对史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华给予警告,并分别处以 20 万元罚款') +
    ev('D1', '四、对徐成斌给予警告,并处以 10 万元罚款') +
    ev('D1', '五、对隋淑静、姚太平、贺勇给予警告，并分别处以 3 万元罚款'),
    unit='万元',
    derivation=dict(rule='50 + 30 + 20×6 + 10 + 3×3 = 219万元', parties=12,
                    note='D1 拟罚合计，终罚合计见 F18=214万，差 5万来自徐成斌下调'))

# ===== F20: dual-stage change (徐成斌) =====
add('F20', '徐成斌', '拟处罚罚款金额（终罚：5万元）', '10', 'number', True, ['D1', 'D2'], 'amount', '徐成斌', '罚款',
    ev('D1', '四、对徐成斌给予警告,并处以 10 万元罚款') +
    ev('D2', '四、对徐成斌给予警告,并处以 5 万元罚款'),
    unit='万元',
    dual_stage=dict(d1_proposed='10万元', d1_evidence_doc='D1',
                    d2_final='5万元', d2_evidence_doc='D2',
                    change='reduced_10_to_5',
                    note='模型须引 D1 证明拟罚 10万；D2 显示终罚降为 5万。'))

# ===== F21-F23: market bans =====
add('F21', '尹智勇', '市场禁入年限', '10年', 'text', False, ['D1', 'D2'], 'text', '尹智勇', '市场禁入',
    ev('D2', '对尹智勇采取 10 年证券市场禁入措施'))
add('F22', '刘瑞', '市场禁入年限', '3年', 'text', True, ['D2'], 'text', '刘瑞', '市场禁入',
    ev('D2', '对刘瑞采取 3 年证券市场禁入措施'))
add('F23', '史忻', '市场禁入年限', '5年', 'text', False, ['D1', 'D2'], 'text', '史忻', '市场禁入',
    ev('D2', '对史忻采取 5 年证券市场禁入措施'))

CONTRACT = dict(
    task_id='P2_CY_600525_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-B 试点任务 2/3（替代 ST华铁）。Gold 由规则从原文构建。',
    question='长园集团信息披露违法违规案：深圳证监局最终对公司及各责任人员分别处以多少罚款？全部合计多少？拟罚合计多少？徐成斌拟罚与终罚各多少？尹智勇和刘瑞市场禁入各多少年？史忻的拟禁入与终罚状态？2016和2017年度虚增营业收入和利润总额各是多少？虚增应收账款？调查通知书、告知书、决定书各于何日收到？编号/文号？许晓文职务？',
    cutoff='2020-10-23',
    source_documents=dict(
        D1=dict(title='关于收到深圳监管局〈行政处罚及市场禁入事先告知书〉的公告（2020-06-13）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到深圳监管局〈行政处罚决定书〉的公告（2020-10-23）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['长园集团',50],['尹智勇',30],['史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华',20],['徐成斌',5],['隋淑静、姚太平、贺勇',3]],
        proposed_lines_D1=[['长园集团',50],['尹智勇',30],['史忻、刘瑞、许晓文、鲁尔兵、黄永维、倪昭华',20],['徐成斌',10],['隋淑静、姚太平、贺勇',3]],
        final_total_wan=214, proposed_total_wan=219,
        market_ban=dict(
            d1=dict(尹智勇='10年', 史忻='5年', 刘瑞='5年'),
            d2=dict(尹智勇='10年', 史忻='5年', 刘瑞='3年'),
            changes=['刘瑞：拟禁5年→终禁3年（缩短）']),
        aliases=[dict(canonical='长园集团股份有限公司', variants=['长园集团', '公司'], where='both docs'),
                 dict(canonical='长园和鹰智能科技有限公司', variants=['长园和鹰'], where='subsidiary referenced throughout')],
    ),
    scoring=dict(primary='Q_all = TP / N (N=23)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext 文本层；Gold 值与证据跨度由本脚本按规则从原文读取',
                    model_calls=0, independence='zero hits on code/names/parties/doc numbers'),
    known_issues=[
        dict(issue='D2 penalty line 3 (史忻等6人) and line 5 (隋淑静等3人) both use "分别" consistently with D1', handling='verified ✓'),
        dict(issue='市场禁入三人全部在D2中保留：尹智勇10年、史忻5年（不变）、刘瑞5→3年（缩短）', handling='F22=刘瑞终禁3年（关键槽），F23=史忻终禁5年（非关键，无变化）'),
        dict(issue='D1 market ban: 刘瑞拟禁5年 → D2 reduced to 3年', handling='captured in entity_correspondence and F22'),
    ],
)

out = OUT / 'TASK_CONTRACT_CY_600525_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('draft sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')

# Self-check
for f in F:
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id']=='D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); break
    else: continue
    break
else: print('self-check: all quotes verbatim ✓')

total_d2 = 50+30+20*6+5+3*3
total_d1 = 50+30+20*6+10+3*3
assert total_d2 == 214 and total_d1 == 219, f'mismatch: {total_d2}/{total_d1}'
print(f'totals: D2={total_d2}万, D1={total_d1}万 ✓')
