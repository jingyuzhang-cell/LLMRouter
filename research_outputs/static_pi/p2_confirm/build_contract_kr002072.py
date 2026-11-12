#!/usr/bin/env python3
"""凯瑞德 (002072) Gold contract builder.

Correct pairing (verified 2026-11-08):
  D1 = 处罚字〔2019〕114号《行政处罚及市场禁入事先告知书》(公告2019-08-16)
  D2 = 【2020】26号《行政处罚决定书》(2020-06-17收到)
Same case: 立案 2016-10-31 鲁证调查字2016020号, 杰之盟股权转让关联交易未披露案.
NOTE: raw pool also holds 【2019】119号 (2019-11, 另案-年报违法) and 2025年决定 (2023立案另案)
— both are DIFFERENT cases and are excluded.
Stage: 5 parties all REDUCED (酌情减免, 因119号已就同期年报违法处罚) + 15人×3万组D2未再载明
+ 吴联模5年禁入D2未载(终局UNKNOWN).
"""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
D1F = '002072_notice_1566144000000.pdf.txt'
D2F = '002072_decision_1592496000000.pdf.txt'
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

# ---- D2 FINAL PENALTY (5 parties) ----
add('F1', '凯瑞德控股股份有限公司', '行政处罚罚款金额', '30', 'number', True, ['D2'], 'amount', '凯瑞德控股', '罚款',
    ev('D2', '一、对凯瑞德控股股份有限公司给予警告，并处以 30 万元的罚款'), unit='万元',
    dual_stage=dict(d1_proposed='60万元', d2_final='30万元', change='reduced'))
add('F2', '吴联模', '行政处罚罚款金额', '60', 'number', True, ['D2'], 'amount', '吴联模', '罚款',
    ev('D2', '二、对吴联模给予警告，并处以 60 万元的罚款，其中作为直接负责的主管人员罚款 20 万元，作为实际控制人罚款 40 万元'),
    unit='万元',
    derivation=dict(note='构成变化: D1=主管30万+实控人60万 → D2=主管20万+实控人40万'),
    dual_stage=dict(d1_proposed='90万元(30+60)', d2_final='60万元(20+40)', change='reduced'))
add('F3', '刘书艳', '行政处罚罚款金额', '10', 'number', True, ['D2'], 'amount', '刘书艳', '罚款',
    ev('D2', '三、对刘书艳给予警告，并处以 10 万元的罚款'), unit='万元',
    dual_stage=dict(d1_proposed='15万元', d2_final='10万元', change='reduced'))
add('F4', '张彬', '行政处罚罚款金额', '5', 'number', False, ['D2'], 'amount', '张彬', '罚款',
    ev('D2', '四、对张彬给予警告，并处以 5 万元的罚款'), unit='万元',
    dual_stage=dict(d1_proposed='10万元', d2_final='5万元', change='reduced'))
add('F5', '刘滔', '行政处罚罚款金额', '3', 'number', False, ['D2'], 'amount', '刘滔', '罚款',
    ev('D2', '五、对刘滔给予警告，并处以 3 万元的罚款'), unit='万元',
    dual_stage=dict(d1_proposed='5万元', d2_final='3万元', change='reduced'))

# ---- TOTALS ----
add('F6', '全部当事人', '罚款合计', '108', 'number', True, ['D2'], 'penalty_line_sum', None, '罚款',
    ev('D2', '依据 2005年《证券法》第一百九十三条第一款、第三款的规定，我会决定：'), unit='万元',
    derivation=dict(rule='30+60+10+5+3=108万', parties=5))
add('F7', '全部当事人', '拟处罚罚款合计', '225', 'number', True, ['D1'], 'penalty_line_sum', None, '罚款',
    ev('D1', '依据《证券法》第一'), unit='万元',
    derivation=dict(rule='60+90+15+10+5+15×3=225万', parties=20,
                    note='差117万=5人下调合计(30+30+5+5+2)+D2未再载明的15人×3万组(45万)；实际 225-108=117'))

# ---- STAGE CHANGES (explicit dual-stage slots) ----
add('F8', '凯瑞德控股股份有限公司', '拟处罚罚款金额（终罚：30万元）', '60', 'number', True, ['D1', 'D2'], 'amount', '凯瑞德控股', '罚款',
    ev('D1', '一、   对凯瑞德控股股份有限公司给予警告，并处以 60 万元的罚款') +
    ev('D2', '一、对凯瑞德控股股份有限公司给予警告，并处以 30 万元的罚款'),
    unit='万元', dual_stage=dict(d1_proposed='60万元', d2_final='30万元', change='reduced'))
add('F9', '吴联模', '拟处罚罚款金额（终罚：60万元）', '90', 'number', True, ['D1', 'D2'], 'amount', '吴联模', '罚款',
    ev('D1', '二、   对吴联模给予警告，并处以 90 万元的罚款，其中作为直接负责的主管人员罚款 30 万元，作为实际控制人罚款 60 万元') +
    ev('D2', '二、对吴联模给予警告，并处以 60 万元的罚款'),
    unit='万元', dual_stage=dict(d1_proposed='90万元', d2_final='60万元', change='reduced'))
add('F10', '刘书艳', '拟处罚罚款金额（终罚：10万元）', '15', 'number', True, ['D1', 'D2'], 'amount', '刘书艳', '罚款',
    ev('D1', '三、   对刘书艳给予警告，并处以 15 万元的罚款') +
    ev('D2', '三、对刘书艳给予警告，并处以 10 万元的罚款'),
    unit='万元', dual_stage=dict(d1_proposed='15万元', d2_final='10万元', change='reduced'))
add('F11', '袁皓等15人', '拟处罚记录与D2载明情况', 'D1拟各3万元；D2未再载明对应处罚', 'text', True, ['D1', 'D2'], 'text', '袁皓', '罚款',
    ev('D1', '袁皓、吴春喜、刘俊青、刘海英、陆仁忠、张林剑、赵伟、赵发平、张福运、饶大程、程万超、何亚军、王柱、张鑫鑫、谢曙给予警告') +
    ev('D2', '五、对刘滔给予警告，并处以 3 万元的罚款。上述当事人应自收到本处罚决定书之日起 15 日内'),
    dual_stage=dict(d1_proposed='15人各3万元(合计45万)', d2_final='D2未再载明（决定书仅列五项，全文不出现该15人，未作说明；不认定为撤销，不计为0）', change='not_restated_in_D2'))
add('F12', '吴联模', '拟市场禁入措施', '5年证券市场禁入', 'text', True, ['D1'], 'text', '吴联模', '禁入',
    ev('D1', '中国证监会拟决定：对吴联模采取 5 年证券市场禁入措施'))
add('F13', '本案当事人（整体）', '减免原因', '因〔2019〕119号决定书已就2015年报、2016半年报违法作出处罚，本案酌情减免', 'text', True, ['D2'], 'text', None, '减免',
    ev('D2', '我会作出的〔2019〕119 号行政处罚决定书已对凯瑞德《2015年年度报告》与《2016年半年度报告》信息披露违法作出行政处罚。综合上述情况，我会决定对本案当事人酌情减免罚款处罚'))

# ---- VIOLATION FACTS ----
add('F14', '凯瑞德', '违法行为定性', '未将出售子公司股权事项披露为关联交易', 'text', True, ['D1', 'D2'], 'text', '凯瑞德', '关联交易',
    ev('D2', '1.未将出售子公司股权事项披露为关联交易'))
add('F15', '杰之盟100%股权转让', '转让价格', '11700', 'number', True, ['D1', 'D2'], 'amount', '杰之盟', '转让价格',
    ev('D2', '股权以 11,700 万元的价格转让给浙江亿富') + ev('D1', '股权以 11,700 万元的价格转让给浙江亿富'),
    unit='万元', derivation=dict(original_yuan_text='11,700万元', standard_wan='11700'))

# ---- DATES ----
add('F16', '凯瑞德', '立案调查收到日期', '2016-10-31', 'date', True, ['D1', 'D2'], 'date', '凯瑞德', '立案',
    ev('D1', '于 2016 年 10 月 31 日 收到中国证券监督管理委员会') + ev('D2', '2016 年 10 月 31 日，公司收到中国证监会《调查通知书》（编号：鲁证调'))
add('F17', '凯瑞德', '事先告知书收到日期', '2019-08', 'date', True, ['D1', 'D2'], 'date', '凯瑞德', '告知书',
    ev('D2', '2019 年 8 月，公司收到中国证监会下发的关于立案事项（鲁证调查字 2016020'),
    derivation=dict(note='精确到月：D2表述"2019年8月"；D1公告落款2019-08-16为披露日而非收到日，不作为收到日'))
add('F18', '凯瑞德', '行政处罚决定书收到日期', '2020-06-17', 'date', True, ['D2'], 'date', '凯瑞德', '决定书',
    ev('D2', '2020 年 6 月 17 日收到中国证券监督管理委员会'))

# ---- DOC NUMBERS ----
add('F19', '行政处罚及市场禁入事先告知书', '文号', '处罚字〔2019〕114号', 'text', False, ['D1'], 'doc_number', None, '文号',
    ev('D1', '《行政处罚及市场禁入事先告知书》（编号：处罚字〔2019〕114 号）'))
add('F20', '行政处罚决定书', '文号', '【2020】26号', 'text', False, ['D2'], 'doc_number', None, '文号',
    ev('D2', '【2020】26 号《行政处罚决定书》'))
add('F21', '吴联模', '市场禁入措施终局结果', None, 'text', False, ['D2'], 'text', None, None,
    ev('D2', '五、对刘滔给予警告，并处以 3 万元的罚款。上述当事人应自收到本处罚决定书之日起 15 日内'))
F[-1]['status'] = 'GOLD_DRAFT_UNKNOWN'

CONTRACT = dict(
    task_id='P2_KR_002072_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-C 确认实验任务。全下调型阶段变化：5主体罚款全部酌减+15人组D2未再载明+5年拟禁入终局UNKNOWN（减免依据=119号决定书一事不再罚）。D1-D2配对曾错选2025年决定书，本版已核实修正。',
    question='凯瑞德信息披露违法案（2016立案）：终罚5主体各多少？合计多少？拟罚合计多少？公司、吴联模、刘书艳的拟罚与终罚各多少？袁皓等15人拟罚结果与终局？吴联模拟禁入与终局？减免原因？杰之盟股权转让价多少？立案、告知书、决定书日期？两文书文号？',
    cutoff='2020-06-17',
    source_documents=dict(
        D1=dict(title='关于收到行政处罚及市场禁入事先告知书的公告（2019-08-16，处罚字〔2019〕114号）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到中国证券监督管理委员会〈行政处罚决定书〉的公告（2020-06-17，【2020】26号）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical') and f['status'] != 'GOLD_DRAFT_UNKNOWN'],
    unknown_items=[dict(fact_id='F21', reason='D2为《行政处罚决定书》公告，未载市场禁入决定；池内无单独市场禁入决定书，终局是否采取无法由D1/D2确认')],
    entity_correspondence=dict(
        final_lines_D2=[['凯瑞德控股', 30], ['吴联模', 60], ['刘书艳', 10], ['张彬', 5], ['刘滔', 3]],
        proposed_lines_D1=[['凯瑞德控股', 60], ['吴联模', 90], ['刘书艳', 15], ['张彬', 10], ['刘滔', 5], ['袁皓等15人', '各3万']],
        final_total_wan=108, proposed_total_wan=225,
        changes=[dict(party='凯瑞德控股', d1=60, d2=30), dict(party='吴联模', d1=90, d2=60),
                 dict(party='刘书艳', d1=15, d2=10), dict(party='张彬', d1=10, d2=5),
                 dict(party='刘滔', d1=5, d2=3),
                 dict(party='袁皓等15人', d1='各3万(45万)', d2=None, note='D2未再载明对应处罚'),
                 dict(party='吴联模禁入', d1='5年', d2='UNKNOWN', note='D2为处罚决定书，未载禁入；池内无单独禁入决定书')],
        market_bans=dict(proposed=['吴联模5年'], final='UNKNOWN'),
        aliases=[dict(canonical='凯瑞德控股股份有限公司', variants=['凯瑞德', '公司'], where='both docs'),
                 dict(canonical='吴联模', variants=['实际控制人'], where='both docs')]),
    scoring=dict(primary='Q_all = TP / N (N=20, excluding F21 UNKNOWN)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF', model_calls=0, independence='DAG-line independent'),
    known_issues=[
        dict(issue='raw池中有三个决定书：119号(2019-11,另案-年报违法)、26号(2020-06,本案D2)、2025年决定(2023立案另案)；早期抽取误用2025年决定书', handling='本合同D2=26号决定书，已核实与114号告知书同案（鲁证调查字2016020）'),
        dict(issue='初期扫描表合计113万与逐条核实108万不符（扫描正则近似）', handling='以逐条核实的108万为准'),
        dict(issue='D1罚款项"一、"与"对凯瑞德…"之间有多个全角空格', handling='ev匹配经空白归一化，不受影响'),
        dict(issue='袁皓等15人D1列入拟处罚，D2全文未出现且未作说明', handling='F11表述为"D2未再载明对应处罚"，不认定为法律意义上的撤销，终罚不计为0（操作员批2裁决口径）'),
        dict(issue='吴联模D1拟5年禁入，D2处罚决定书未载禁入', handling='F12仅记D1拟禁入；终局另设F21=UNKNOWN，不推断为未采取（与登云股份F15同口径）'),
    ],
)

out = OUT / 'TASK_CONTRACT_KR_002072_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')
bad = 0
for f in F:
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id'] == 'D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); bad += 1
print('self-check:', 'all quotes verbatim ✓' if bad == 0 else f'{bad} FAILURES')
d2t = 30 + 60 + 10 + 5 + 3; d1t = 60 + 90 + 15 + 10 + 5 + 15 * 3
print(f'totals: D2={d2t}万, D1={d1t}万 {"✓" if d2t == 108 and d1t == 225 else "MISMATCH"}')
