#!/usr/bin/env python3
"""*ST昆机 (600806) Gold contract builder."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
D1 = (RAW / '600806_notice_1510848000000.pdf.txt').read_text('utf-8')
D2 = (RAW / '600806_decision_1518451200000.pdf.txt').read_text('utf-8')
D1_META = json.loads((RAW / '600806_notice_1510848000000.pdf.meta.json').read_text())
D2_META = json.loads((RAW / '600806_decision_1518451200000.pdf.meta.json').read_text())

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
D1N = norm(re.sub(r'\s*\d{1,3}\s*\x0c', '', D1))
D2N = norm(re.sub(r'\s*\d{1,3}\s*\x0c', '', D2))

def ev(doc, quote):
    q = norm(quote); t = D2N if doc == 'D2' else D1N
    if q not in t:
        q2 = q.replace(',', '，') if ',' in q else q.replace('，', ',')
        if q2 not in t: raise ValueError(f'NOT VERBATIM in {doc}: {quote[:60]}')
    sha = D2_META['sha256'] if doc == 'D2' else D1_META['sha256']
    return [dict(doc_id=doc, page=1, quote=quote, pdf_sha256=sha)]

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

# PENALTY (D2 final)
add('F1','沈机集团昆明机床股份有限公司','行政处罚罚款金额','60','number',True,['D2'],'amount','昆明机床','罚款',
    ev('D2','对昆明机床责令改正，给予警告，并处以60万元罚款'),unit='万元')
add('F2','王兴、常宝强、金晓峰（3人）','单人行政处罚罚款金额','30','number',True,['D2'],'amount','王兴','罚款',
    ev('D2','对王兴、常宝强、金晓峰给予警告，并分别处以30万元罚款'),unit='万元')
add('F3','李红宁','行政处罚罚款金额','10','number',True,['D2'],'amount','李红宁','罚款',
    ev('D2','对李红宁给予警告，并处以10万元罚款'),unit='万元')
add('F4','张泽顺等5人','单人行政处罚罚款金额','7','number',False,['D2'],'amount','张泽顺','罚款',
    ev('D2','张泽顺、张晓毅、朱祥、叶农、邵里给予警告，并分别处以7万元罚款'),unit='万元')
add('F5','彭梁锋等8人','单人行政处罚罚款金额','5','number',False,['D2'],'amount','彭梁锋','罚款',
    ev('D2','蔡哲民、周国兴给予警告，并分别处以5万元罚款'),unit='万元')
add('F6','杨雄胜等5人','单人行政处罚罚款金额','3','number',False,['D2'],'amount','杨雄胜','罚款',
    ev('D2','杨雄胜、刘岩、刘海洁、蒋晶瑛、刘强给予警告，并分别处以3万元罚款'),unit='万元')

# TOTALS
add('F7','全部当事人','罚款合计','250','number',False,['D2'],'penalty_line_sum',None,'罚款',
    ev('D2','对昆明机床责令改正，给予警告，并处以60万元罚款'),
    unit='万元',derivation=dict(rule='60+30×3+10+7×5+5×8+3×5=250万',parties=23))
add('F8','全部当事人','拟处罚罚款合计','278','number',False,['D1'],'penalty_line_sum',None,'罚款',
    ev('D1','对昆明机床责令改正，给予警告，并处以60万元罚款'),
    unit='万元',derivation=dict(rule='60+30×3+10×2+7×4+5×10+4×3+3×6=278万',parties=29,
        note='D1拟罚278万(29人)→D2终罚250万(23人)，差28万来自6人D2未再载明对应处罚+5人下调'))

# STAGE CHANGES (most significant)
add('F9','张泽顺','拟处罚罚款金额（终罚：7万元）','10','number',True,['D1','D2'],'amount','张泽顺','罚款',
    ev('D1','对张泽顺、李红宁给予警告，并分别处以10万元罚款')+
    ev('D2','张泽顺、张晓毅、朱祥、叶农、邵里给予警告，并分别处以7万元罚款'),
    unit='万元',dual_stage=dict(d1_proposed='10万元',d2_final='7万元',change='reduced_10_to_7'))
add('F10','杨雄胜','拟处罚罚款金额（终罚：3万元）','5','number',True,['D1','D2'],'amount','杨雄胜','罚款',
    ev('D1','许昆平、彭梁锋、罗涛、张涛、杨雄胜、陈富生、唐春胜、樊宏、蔡哲民、周国兴给予警告，并分别处以5万元罚款')+
    ev('D2','杨雄胜、刘岩、刘海洁、蒋晶瑛、刘强给予警告，并分别处以3万元罚款'),
    unit='万元',dual_stage=dict(d1_proposed='5万元',d2_final='3万元',change='reduced_5_to_3'))
add('F11','刘岩','拟处罚罚款金额（终罚：3万元）','4','number',True,['D1','D2'],'amount','刘岩','罚款',
    ev('D1','对刘岩、刘海洁、蒋晶瑛给予警告，并分别处以4万元罚款')+
    ev('D2','杨雄胜、刘岩、刘海洁、蒋晶瑛、刘强给予警告，并分别处以3万元罚款'),
    unit='万元',dual_stage=dict(d1_proposed='4万元',d2_final='3万元',change='reduced_4_to_3'))
add('F12','许昆平','拟处罚罚款金额（D2载明情况：未再载明）','5','number',True,['D1'],'amount','许昆平','罚款',
    ev('D1','许昆平、彭梁锋、罗涛、张涛、杨雄胜、陈富生、唐春胜、樊宏、蔡哲民、周国兴给予警告，并分别处以5万元罚款'),
    unit='万元',dual_stage=dict(d1_proposed='5万元',d2_final='D2未再载明对应处罚（D2未作说明；不等于法律意义上的撤销，不计为0）',change='not_restated_in_D2'))

# FINANCIAL FRAUD
add('F13','昆明机床2013-2015累计','虚增收入','48308.02','number',True,['D1','D2'],'amount',None,'收入',
    ev('D2','虚增收入483,080,163.99元'),unit='万元',
    derivation=dict(original_yuan='483,080,163.99',standard_wan='48308.02',years='2013-2015'))
add('F14','昆明机床2013-2015累计','虚增利润','22810.11','number',True,['D1','D2'],'amount',None,'利润',
    ev('D2','虚增利润228,101,078.73元'),unit='万元',
    derivation=dict(original_yuan='228,101,078.73',standard_wan='22810.11'))

# DATES
add('F15','昆明机床','调查通知书收到日期','2017-03-22','date',True,['D1','D2'],'date',None,'调查',
    ev('D2','2017年3月22日收到中国证券监督管理委员会'))
add('F16','昆明机床','事先告知书收到日期','2017-11-16','date',True,['D1','D2'],'date',None,'告知书',
    ev('D2','2017年11月16日在《中国证券报》'))
# Decision date: D2 only says "近日"，no specific date
add('F17','昆明机床','行政处罚决定书收到日期',None,'date',False,['D2'],'date',None,'决定书',
    [], derivation=None)
# Mark as unknown_slots
F[-1]['grounding'] = dict(rule='date', subject_anchor=None, predicate_anchor='决定书')
F[-1]['source_evidence'] = []
F[-1]['value'] = None
F[-1]['status'] = 'GOLD_DRAFT_UNKNOWN'

# DOC NUMBERS
add('F18','事先告知书','文号','处罚字[2017]122号','text',False,['D1','D2'],'doc_number',None,'告知书',
    ev('D1','处罚字[2017]122号'))

# TITLE
add('F19','王兴','职务','董事长','text',True,['D1','D2'],'title_set','王兴',None,
    ev('D2','王兴时任昆明机床董事长'))

# MARKET BANS
add('F20','王兴','市场禁入措施','终身','text',True,['D1','D2'],'text','王兴','禁入',
    ev('D1','对王兴采取终身证券市场禁入措施'))
add('F21','常宝强、金晓峰','市场禁入措施','5年','text',False,['D1','D2'],'text','常宝强','禁入',
    ev('D1','对常宝强、金晓峰采取5年证券市场禁入措施'))

CONTRACT = dict(
    task_id='P2_KJ_600806_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-C 确认实验任务。23处罚主体（D2载明）、6人D2未再载明、5人下调、3年虚增收入。',
    question='昆明机床信息披露违法违规案：终罚各主体金额？合计？拟罚合计？张泽顺、杨雄胜、刘岩、许昆平的拟罚与终罚各多少？2013-2015累计虚增收入和虚增利润各多少？调查通知书、告知书各于何日收到？告知书文号？王兴职务？市场禁入措施？',
    cutoff='2018-02-13',
    source_documents=dict(
        D1=dict(title='关于收到〈行政处罚及市场禁入事先告知书〉的公告（2017-11-16，处罚字[2017]122号）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于证监会下发〈行政处罚决定书〉的公告（2018-02，从证监会网站获知）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical') and f.get('status') != 'GOLD_DRAFT_UNKNOWN'],
    unknown_items=[dict(fact_id='F17', reason='D2仅载"近日"，无具体决定书收到日期')],
    entity_correspondence=dict(
        final_lines_D2=[['昆明机床',60],['王兴等3人',30],['李红宁',10],['张泽顺等5人',7],['彭梁锋等8人',5],['杨雄胜等5人',3]],
        proposed_lines_D1=[['昆明机床',60],['王兴等3人',30],['张泽顺、李红宁',10],['张晓毅等4人',7],['许昆平等10人',5],['刘岩等3人',4],['关欣等6人',3]],
        final_total_wan=250, proposed_total_wan=278,
        changes=[
            dict(party='张泽顺',d1=10,d2=7,reason='申辩后减罚'),
            dict(party='杨雄胜',d1=5,d2=3,reason='申辩后减罚'),
            dict(party='刘岩',d1=4,d2=3,reason='申辩后减罚'),
            dict(party='刘海洁',d1=4,d2=3,reason='申辩后减罚'),
            dict(party='蒋晶瑛',d1=4,d2=3,reason='申辩后减罚'),
            dict(party='许昆平',d1=5,d2=None,reason='D2未再载明对应处罚'),
            dict(party='关欣',d1=3,d2=None,reason='D2未再载明对应处罚'),
            dict(party='高明辉',d1=3,d2=None,reason='D2未再载明对应处罚'),
            dict(party='周东红',d1=3,d2=None,reason='D2未再载明对应处罚'),
            dict(party='于成廷',d1=3,d2=None,reason='D2未再载明对应处罚'),
            dict(party='秦建中',d1=3,d2=None,reason='D2未再载明对应处罚'),
        ],
        market_bans=dict(lifetime=['王兴'], five_year=['常宝强','金晓峰']),
        aliases=[dict(canonical='沈机集团昆明机床股份有限公司',variants=['昆明机床','公司'],where='both docs')],
    ),
    scoring=dict(primary='Q_all = TP / N (N=20, excluding F17 UNKNOWN)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal','E_literal'],scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext',model_calls=0,
                    independence='DAG-line independent'),
    known_issues=[
        dict(issue='D2未载明确的决定书收到日期（仅"近日"）',handling='F17标记为UNKNOWN'),
        dict(issue='D2为公司在证监会网站看到后公告的，非直接收到决定书',handling='如实记录'),
        dict(issue='6人D1列入拟处罚、D2未再载明对应处罚且未作说明（许昆平、关欣、高明辉、周东红、于成廷、秦建中）',handling='F12记录代表性1人；表述为D2未再载明，不认定为撤销，终罚不计为0'),
    ],
)

out = OUT / 'TASK_CONTRACT_KJ_600806_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {len(CONTRACT["critical_fact_ids"])}')
for f in F:
    if f['fact_id'] == 'F17': continue
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id']=='D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); break
    else: continue
    break
else: print('self-check: all quotes verbatim ✓')
d2t = 60+90+10+35+40+15; d1t = 60+90+20+28+50+12+18
assert d2t == 250 and d1t == 278, f'mismatch: {d2t}/{d1t}'
print(f'totals: D2={d2t}万(23人), D1={d1t}万(29人) ✓')
