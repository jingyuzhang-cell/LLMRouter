#!/usr/bin/env python3
"""Build ST索菱 (002766) Gold contract DRAFT from source texts (zero model calls).
Note: this is the most complex pilot task — 4 individuals' penalties changed D1→D2, and the
text contains 黃/黄 and 責/责 variant characters."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT.mkdir(parents=True, exist_ok=True)
D1_FILE = next(RAW.glob('002766_notice_*.txt'))
D2_FILE = next(RAW.glob('002766_decision_*.txt'))
D1 = D1_FILE.read_text('utf-8')
D2 = D2_FILE.read_text('utf-8')
D1_META = json.loads(next(RAW.glob('002766_notice_*.meta.json')).read_text())
D2_META = json.loads(next(RAW.glob('002766_decision_*.meta.json')).read_text())

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
def add(fid, subj, pred, val, kind, critical, docs, rule, s_anchor, p_anchor, quotes, unit=None, **kw):
    f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
             critical=critical, evidence_required=True, value_kind=kind,
             subject=subj, predicate=pred, value=val,
             allowed_citation_docs=docs, source_evidence=quotes,
             grounding=dict(rule=rule, subject_anchor=s_anchor, predicate_anchor=p_anchor))
    if unit: f['unit'] = unit
    for k in ('derivation', 'dual_stage'):
        if k in kw: f[k] = kw[k]
    F.append(f)

# ===== F1-F7: D2 final penalties =====
add('F1', '深圳市索菱实业股份有限公司', '行政处罚罚款金额', '60', 'number', True, ['D2'], 'amount', '索菱', '罚款',
    ev('D2', '一、责令索菱股份改正，给予警告，并处以 60 万元的罚款'), unit='万元')
add('F2', '肖行亦', '行政处罚罚款金额', '90', 'number', True, ['D2'], 'amount', '肖行亦', '罚款',
    ev('D2', '二、对肖行亦给予警告，并处以 90 万元的罚款'), unit='万元',
    derivation=dict(note='含主管人员30万+实际控制人60万，合并罚款90万'))
add('F3', '叶玉娟、钟贵荣、王大威（3人）', '单人行政处罚罚款金额', '30', 'number', True, ['D2'], 'amount', '叶玉娟', '罚款',
    ev('D2', '三、对叶玉娟、钟贵荣、王大威给予警告，并分别处以 30 万元的罚款'), unit='万元')
add('F4', '郭小宝、黃子龙（2人）', '单人行政处罚罚款金额', '20', 'number', True, ['D2'], 'amount', '郭小宝', '罚款',
    ev('D2', '四、对郭小宝、黃子龙给予警告，并分别处以 20 万元的罚款'), unit='万元',
    derivation=dict(note='D2 原文用繁体「黃」；D1 用简体「黄」'))
add('F5', '童方义、吴文兴、邓庆明、林晓罡（4人）', '单人行政处罚罚款金额', '15', 'number', False, ['D2'], 'amount', '童方义', '罚款',
    ev('D2', '五、对童方义、吴文兴、邓庆明、林晓罡给予警告，并分别处以 15 万元的罚款'), unit='万元')
add('F6', '郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超（6人）', '单人行政处罚罚款金额', '8', 'number', False, ['D2'], 'amount', '郑晓明', '罚款',
    ev('D2', '六、对郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超给予警告，并分别处以 8 万元的罚款'), unit='万元')
add('F7', '魏有国', '行政处罚罚款金额', '3', 'number', False, ['D2'], 'amount', '魏有国', '罚款',
    ev('D2', '七、对魏有国给予警告，并处以 3 万元的罚款'), unit='万元')

# ===== F8-F9: fraud (most impactful) =====
add('F8', '索菱股份2016年度', '虚增利润总额', '27908.94', 'number', True, ['D1', 'D2'], 'amount', None, '利润总额',
    ev('D2', '虚增利润总额279,089,447.97元'), unit='万元',
    derivation=dict(original_yuan='279,089,447.97', standard_wan='27908.94', precision=2, ratio='344.78%'))
add('F9', '索菱股份2017年度', '虚增利润总额', '35031.13', 'number', True, ['D1', 'D2'], 'amount', None, '利润总额',
    ev('D2', '虚增利润总额350,311,279.11元'), unit='万元',
    derivation=dict(original_yuan='350,311,279.11', standard_wan='35031.13', precision=2, ratio='208.13%'))

# ===== F10-F12: dates =====
add('F10', '索菱股份', '调查通知书收到日期', '2019-04-26', 'date', True, ['D1', 'D2'], 'date', None, '调查通知书',
    ev('D2', '于 2019 年4 月 26 日收到了中国证券监督管理委员会《立案调查通知书》（深证调查通字【2019】096 号）'))
add('F11', '索菱股份', '事先告知书收到日期', '2020-04-10', 'date', True, ['D1', 'D2'], 'date', None, '告知书',
    ev('D2', '2020 年 4 月 10 日，公司收到中国证监会下发的《行政处罚及市场禁入事先告知书》（处罚字【2020】9 号）'))
add('F12', '索菱股份及相关当事人', '行政处罚决定书收到日期', '2020-12-10', 'date', True, ['D2'], 'date', None, '决定书',
    ev('D2', '2020 年 12 月 10 日，公司及相关当事人收到中国证券监督管理委员会下发的《行政处罚决定书》（【2020】105 号）'))

# ===== F13-F15: doc numbers =====
add('F13', '立案调查通知书', '编号', '深证调查通字【2019】096号', 'text', False, ['D1', 'D2'], 'doc_number', None, '调查通',
    ev('D2', '《立案调查通知书》（深证调查通字【2019】096 号）'))
add('F14', '事先告知书', '文号', '处罚字【2020】9号', 'text', False, ['D1', 'D2'], 'doc_number', None, '告知书',
    ev('D2', '《行政处罚及市场禁入事先告知书》（处罚字【2020】9 号）'))
add('F15', '行政处罚决定书', '文号', '【2020】105号', 'text', False, ['D2'], 'doc_number', None, '决定书',
    ev('D2', '《行政处罚决定书》（【2020】105 号）'))

# ===== F16: title =====
add('F16', '肖行亦', '职务', '董事长兼总经理', 'text', True, ['D1', 'D2'], 'title_set', '肖行亦', None,
    ev('D2', '肖行亦，男，1964 年 3 月出生，时任索菱股份实际控制人，董事长兼总经理、法定代表人'))

# ===== F17-F18: totals =====
add('F17', '全部当事人', '罚款合计', '391', 'number', False, ['D2'], 'penalty_line_sum', None, '罚款',
    ev('D2', '一、责令索菱股份改正，给予警告，并处以 60 万元的罚款') +
    ev('D2', '二、对肖行亦给予警告，并处以 90 万元的罚款') +
    ev('D2', '三、对叶玉娟、钟贵荣、王大威给予警告，并分别处以 30 万元的罚款') +
    ev('D2', '四、对郭小宝、黃子龙给予警告，并分别处以 20 万元的罚款') +
    ev('D2', '五、对童方义、吴文兴、邓庆明、林晓罡给予警告，并分别处以 15 万元的罚款') +
    ev('D2', '六、对郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超给予警告，并分别处以 8 万元的罚款') +
    ev('D2', '七、对魏有国给予警告，并处以 3 万元的罚款'),
    unit='万元',
    derivation=dict(rule='60+90+30×3+20×2+15×4+8×6+3=391万', parties=18))
add('F18', '全部当事人', '拟处罚罚款合计', '417', 'number', False, ['D1'], 'penalty_line_sum', None, '罚款',
    ev('D1', '一、责令索菱股份改正,给予警告,并处以 60 万元的罚款') +
    ev('D1', '二、对肖行亦给予警告,并处以 90 万元的罚款') +
    ev('D1', '三、对叶玉娟、钟贵荣、王大威给予警告，并分别处以 30 万元的罚款') +
    ev('D1', '四、对郭小宝、黄子龙、童方义给予警告，并分别处以 20 万元的罚款') +
    ev('D1', '五、对吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎给予警告，并分') +
    ev('D1', '六、对邓先海、蔡春喜、谌勇超给予警告,并分别处以 8 万元的罚款') +
    ev('D1', '七、对魏有国给予警告,并处以 3 万元的罚款'),
    unit='万元',
    derivation=dict(rule='60+90+30×3+20×3+15×6+8×3+3=417万', parties=18,
                    note='D1 拟罚合计，终罚 F17=391万，差26万来自4人下调'))

# ===== F19-F22: dual-stage changes (4 individuals) =====
add('F19', '童方义', '拟处罚罚款金额（终罚：15万元）', '20', 'number', True, ['D1', 'D2'], 'amount', '童方义', '罚款',
    ev('D1', '四、对郭小宝、黄子龙、童方义给予警告，并分别处以 20 万元的罚款') +
    ev('D2', '五、对童方义、吴文兴、邓庆明、林晓罡给予警告，并分别处以 15 万元的罚款'),
    unit='万元',
    dual_stage=dict(d1_proposed='20万元', d1_evidence_doc='D1', d2_final='15万元', d2_evidence_doc='D2',
                    change='reduced_20_to_15',
                    note='D1 中童方义在20万组（与郭小宝、黄子龙同组）；D2 中移至15万组'))
add('F20', '郑晓明', '拟处罚罚款金额（终罚：8万元）', '15', 'number', True, ['D1', 'D2'], 'amount', '郑晓明', '罚款',
    ev('D1', '五、对吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎给予警告，并分') +
    ev('D2', '六、对郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超给予警告，并分别处以 8 万元的罚款'),
    unit='万元',
    dual_stage=dict(d1_proposed='15万元', d1_evidence_doc='D1', d2_final='8万元', d2_evidence_doc='D2',
                    change='reduced_15_to_8'))
add('F21', '苏奇木', '拟处罚罚款金额（终罚：8万元）', '15', 'number', True, ['D1', 'D2'], 'amount', '苏奇木', '罚款',
    ev('D1', '五、对吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎给予警告，并分') +
    ev('D2', '六、对郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超给予警告，并分别处以 8 万元的罚款'),
    unit='万元',
    dual_stage=dict(d1_proposed='15万元', d1_evidence_doc='D1', d2_final='8万元', d2_evidence_doc='D2',
                    change='reduced_15_to_8'))
add('F22', '魏丙奎', '拟处罚罚款金额（终罚：8万元）', '15', 'number', True, ['D1', 'D2'], 'amount', '魏丙奎', '罚款',
    ev('D1', '五、对吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎给予警告，并分') +
    ev('D2', '六、对郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超给予警告，并分别处以 8 万元的罚款'),
    unit='万元',
    dual_stage=dict(d1_proposed='15万元', d1_evidence_doc='D1', d2_final='8万元', d2_evidence_doc='D2',
                    change='reduced_15_to_8'))

# ===== F23: market ban =====
add('F23', '肖行亦', '市场禁入措施', '终身市场禁入', 'text', False, ['D1', 'D2'], 'text', '肖行亦', '禁入',
    ev('D2', '对肖行亦采取终身证券市场禁入措施'))

CONTRACT = dict(
    task_id='P2_SL_002766_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-B 试点任务 3/3。最复杂案例：4人处罚金额D1→D2下调、黃/黄异体字、三年财务造假。',
    question='索菱股份信息披露违法违规案：证监会最终对公司及各责任人员分别处以多少罚款？全部合计多少？拟罚合计多少？童方义、郑晓明、苏奇木、魏丙奎的拟罚与终罚各多少？2016和2017年度虚增利润总额各是多少？调查通知书、告知书、决定书各于何日收到？编号/文号？肖行亦职务？是否终身市场禁入？',
    cutoff='2020-12-10',
    source_documents=dict(
        D1=dict(title='关于收到〈行政处罚及市场禁入事先告知书〉的公告（2020-04-10）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到〈行政处罚决定书〉及〈市场禁入决定书〉的公告（2020-12-10）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['索菱股份',60],['肖行亦',90],['叶玉娟、钟贵荣、王大威',30],['郭小宝、黃子龙',20],
                        ['童方义、吴文兴、邓庆明、林晓罡',15],['郑晓明、苏奇木、魏丙奎、邓先海、蔡春喜、谌勇超',8],['魏有国',3]],
        proposed_lines_D1=[['索菱股份',60],['肖行亦',90],['叶玉娟、钟贵荣、王大威',30],['郭小宝、黄子龙、童方义',20],
                           ['吴文兴、邓庆明、郑晓明、苏奇木、林晓罡、魏丙奎',15],['邓先海、蔡春喜、谌勇超',8],['魏有国',3]],
        final_total_wan=391, proposed_total_wan=417,
        changes=[
            dict(party='童方义', d1=20, d2=15, change='reduced'),
            dict(party='郑晓明', d1=15, d2=8, change='reduced'),
            dict(party='苏奇木', d1=15, d2=8, change='reduced'),
            dict(party='魏丙奎', d1=15, d2=8, change='reduced'),
        ],
        unchanged_count=14,
        aliases=[
            dict(canonical='深圳市索菱实业股份有限公司', variants=['索菱股份', '公司'], where='both docs'),
            dict(canonical='黄子龙', variants=['黃子龙'], where='D1 uses 黄(simplified), D2 uses 黃(traditional)'),
            dict(canonical='负责', variants=['負責'], where='D1 uses 責(traditional), D2 uses 责(simplified)'),
        ],
        market_ban=dict(d1=dict(肖行亦='终身'), d2=dict(肖行亦='终身')),
    ),
    scoring=dict(primary='Q_all = TP / N (N=23)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext 文本层', model_calls=0,
                    independence='zero hits on code/names/parties/doc numbers'),
    known_issues=[
        dict(issue='公司罚款使用"责令...改正,给予警告"句式，预筛正则遗漏了该行，导致预筛数据 D1=357/D2=331 均错误', handling='本合同人工修正为 D1=417/D2=391'),
        dict(issue='D2 处罚条款用繁体「黃」子龙，但 D2 市场禁入条款用简体「黄」子龙；D1 全部用简体「黄」', handling='F4 引文按 D2 处罚条款使用「黃」'),
        dict(issue='D1 用「直接負責」（繁体責），D2 用「直接负责」（简体责）', handling='引文照录原文'),
        dict(issue='D2 文中 2017 年虚增营业收入印为 338,220,675,31 元（逗号应为小数点 338,220,675.31）', handling='按原文 338,220,675,31 处理'),
        dict(issue='4 人处罚金额 D1→D2 下调：童方义 20→15、郑晓明/苏奇木/魏丙奎 15→8', handling='F19-F22 双阶段槽'),
    ],
)

out = OUT / 'TASK_CONTRACT_SL_002766_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('draft sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')

for f in F:
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id']=='D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); break
    else: continue
    break
else: print('self-check: all quotes verbatim ✓')

total_d2 = 60+90+30*3+20*2+15*4+8*6+3
total_d1 = 60+90+30*3+20*3+15*6+8*3+3
assert total_d2 == 391 and total_d1 == 417, f'mismatch: {total_d2}/{total_d1}'
print(f'totals: D2={total_d2}万, D1={total_d1}万 ✓ (预筛曾错报为331/357)')
