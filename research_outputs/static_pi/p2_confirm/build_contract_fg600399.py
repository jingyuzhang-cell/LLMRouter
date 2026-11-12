#!/usr/bin/env python3
"""ST抚钢 (600399) Gold contract builder — the most complex P2-C task.
46 penalized parties, 7-year financial fraud, 2 stage adjustments, 6 market bans."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
OUT.mkdir(parents=True, exist_ok=True)
D1 = (RAW / '600399_notice_fraud_1562630400000.pdf.txt').read_text('utf-8')
D2 = (RAW / '600399_decision_1577376000000.pdf.txt').read_text('utf-8')
D1_META = json.loads((RAW / '600399_notice_fraud_1562630400000.pdf.meta.json').read_text())
D2_META = json.loads((RAW / '600399_decision_1577376000000.pdf.txt.meta.json').read_text()) if (RAW / '600399_decision_1577376000000.pdf.txt.meta.json').exists() else json.loads((RAW / '600399_decision_1577376000000.pdf.meta.json').read_text())

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
D1N = norm(re.sub(r'\s*\d{1,3}\s*\x0c', '', D1))
D2N = norm(re.sub(r'\s*\d{1,3}\s*\x0c', '', D2))

def ev(doc, quote):
    q = norm(quote); t = D2N if doc == 'D2' else D1N
    # Try exact, then flip comma variant (D1 uses ，, D2 may use ,)
    if q not in t:
        q2 = q.replace(',', '，') if ',' in q else q.replace('，', ',')
        if q2 in t: q = q2
        else: raise ValueError(f'NOT VERBATIM in {doc}: {quote[:60]}')
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

# ===== PENALTY (D2 final) =====
add('F1','抚顺特殊钢股份有限公司','行政处罚罚款金额','60','number',True,['D2'],'amount','抚顺','罚款',
    ev('D2','对抚顺特殊钢股份有限公司责令改正，给予警告，并处以60万元的罚款'),unit='万元')
add('F2','赵明远等7人','单人行政处罚罚款金额','30','number',True,['D2'],'amount','赵明远','罚款',
    ev('D2','对赵明远、单志强、董事、孙启、张晓军、王勇、姜臣宝给予警告,并分别处以30万元的罚款'),unit='万元',
    derivation=dict(names=['赵明远','单志强','董事','孙启','张晓军','王勇','姜臣宝'],count=7))
add('F3','邵福群等22人','单人行政处罚罚款金额','10','number',False,['D2'],'amount','邵福群','罚款',
    ev('D2','朴文浩、张力、唐丽、李刚给予警告,并分别处以10万元罚款'),unit='万元',
    derivation=dict(count=22))
add('F4','徐庆祥等15人','单人行政处罚罚款金额','5','number',False,['D2'],'amount','徐庆祥','罚款',
    ev('D2','姚殿礼、赵光晨、权日纯给予警告,并分别处以5万元罚款'),unit='万元',
    derivation=dict(count=15))
add('F5','国长虹','行政处罚罚款金额','3','number',False,['D2'],'amount','国长虹','罚款',
    ev('D2','对国长虹给予警告，并处以3万元罚款'),unit='万元',
    derivation=dict(note='D1拟罚5万→D2终罚3万，申辩被部分采纳后单独成组'))

# ===== TOTALS =====
add('F6','全部当事人','罚款合计','568','number',False,['D2'],'penalty_line_sum',None,'罚款',
    ev('D2','对抚顺特殊钢股份有限公司责令改正，给予警告，并处以60万元的罚款')+
    ev('D2','对赵明远、单志强、董事、孙启、张晓军、王勇、姜臣宝给予警告,并分别处以30万元的罚款'),
    unit='万元', derivation=dict(rule='60+30×7+10×22+5×15+3=568万',parties=46))
add('F7','全部当事人','拟处罚罚款合计','575','number',False,['D1'],'penalty_line_sum',None,'罚款',
    ev('D1','对抚顺特殊钢股份有限公司责令改正，给予警告，并处以六十万元的罚款')+
    ev('D1','对赵明远、单志强、董事、孙启、张晓军、王勇、姜臣宝给予警告,并分别处以三十万元的罚款'),
    unit='万元', derivation=dict(rule='60+30×7+10×23+5×15=575万',parties=46,
        note='D1拟罚575万，D2终罚F6=568万，差7万来自赵光晨(10→5)与国长虹(5→3)'))

# ===== STAGE CHANGES =====
add('F8','赵光晨','拟处罚罚款金额（终罚：5万元）','10','number',True,['D1','D2'],'amount','赵光晨','罚款',
    ev('D1','朴文浩、张力、唐丽、李刚、赵光晨给予警告,并分别处以十万元罚款')+
    ev('D2','姚殿礼、赵光晨、权日纯给予警告,并分别处以5万元罚款'),
    unit='万元', dual_stage=dict(d1_proposed='10万元',d2_final='5万元',change='reduced_10_to_5',
        note='D1在10万组→D2移至5万组，申辩"因身体原因参与度低"被部分采纳'))
add('F9','国长虹','拟处罚罚款金额（终罚：3万元）','5','number',True,['D1','D2'],'amount','国长虹','罚款',
    ev('D1','李延喜、高岩、姚殿礼、权日纯给予警告,并分别处以五万元罚款')+
    ev('D2','对国长虹给予警告，并处以3万元罚款'),
    unit='万元', dual_stage=dict(d1_proposed='5万元',d2_final='3万元',change='reduced_5_to_3',
        note='D1在5万组→D2单独成3万组，申辩"签字时客观事实"被部分采纳'))

# ===== FINANCIAL FRAUD (key facts) =====
add('F10','抚顺特钢2010年度','虚增利润总额','7100.23','number',True,['D1','D2'],'amount',None,'利润总额',
    ev('D2','2010年虚增利润总额71,002,264.30元'),unit='万元',
    derivation=dict(original_yuan='71,002,264.30',standard_wan='7100.23',ratio='175.87%',loss_to_profit=True))
add('F11','抚顺特钢2011年度','虚增利润总额','48792.12','number',True,['D1','D2'],'amount',None,'利润总额',
    ev('D2','2011年虚增利润总额487,921,246.00元'),unit='万元',
    derivation=dict(original_yuan='487,921,246.00',standard_wan='48792.12',ratio='1322.84%',loss_to_profit=True))
add('F12','抚顺特钢2012年度','虚增利润总额','55985.19','number',True,['D1','D2'],'amount',None,'利润总额',
    ev('D2','2012年虚增利润总额559,851,922.00元'),unit='万元',
    derivation=dict(original_yuan='559,851,922.00',standard_wan='55985.19',ratio='1794.71%',loss_to_profit=True))
add('F13','抚顺特钢2010-2017累计','虚增利润总额','190194.53','number',True,['D1','D2'],'amount',None,'利润总额',
    ev('D2','累计虚增利润总额1,901,945,340.86元'),unit='万元',
    derivation=dict(original_yuan='1,901,945,340.86',standard_wan='190194.53',years='2010-2017.9'))
add('F14','抚顺特钢2010-2017累计','虚增存货','198934.00','number',False,['D1','D2'],'amount',None,'存货',
    ev('D2','累计虚增存货1,989,340,046.30元'),unit='万元',
    derivation=dict(original_yuan='1,989,340,046.30',standard_wan='198934.00'))
add('F15','由盈转亏年度数','追溯调整后亏损年度','6','number',False,['D1','D2'],'amount',None,'亏损',
    ev('D1','2010年至2014年以及2016年（追溯调整前）共计6个年度，抚顺特钢由盈利转为亏损'),
    derivation=dict(years=['2010','2011','2012','2013','2014','2016']))

# ===== DATES =====
add('F16','抚顺特钢','调查通知书收到日期','2018-03-21','date',True,['D1','D2'],'date',None,'调查通知书',
    ev('D2','沈稽局调查通字[2018]251号'))
add('F17','抚顺特钢','事先告知书收到日期','2019-07-08','date',True,['D1','D2'],'date',None,'告知书',
    ev('D2','处罚字[2019]87号'))
add('F18','抚顺特钢','行政处罚决定书收到日期','2019-12-26','date',True,['D2'],'date',None,'决定书',
    ev('D2','[2019]147号'))

# ===== DOC NUMBERS =====
add('F19','调查通知书','编号','沈稽局调查通字[2018]251号','text',False,['D1','D2'],'doc_number',None,'调查通',
    ev('D2','沈稽局调查通字[2018]251号'))
add('F20','事先告知书','文号','处罚字【2019】87号','text',False,['D1','D2'],'doc_number',None,'告知书',
    ev('D1','处罚字【2019】87号'))
add('F21','行政处罚决定书','文号','[2019]147号','text',False,['D2'],'doc_number',None,'决定书',
    ev('D2','[2019]147号'))

# ===== TITLES =====
add('F22','赵明远','职务','董事长','text',True,['D1','D2'],'title_set','赵明远',None,
    ev('D2','赵明远作为时任董事长'))

# ===== MARKET BANS =====
add('F23','赵明远','市场禁入措施','终身','text',True,['D1','D2'],'text','赵明远','禁入',
    ev('D2','赵明远、单志强分别采取终身市场禁入措施'))
add('F24','单志强','市场禁入措施','终身','text',True,['D1','D2'],'text','单志强','禁入',
    ev('D2','赵明远、单志强分别采取终身市场禁入措施'))
add('F25','王勇','市场禁入措施','10年','text',False,['D1','D2'],'text','王勇','禁入',
    ev('D2','对王勇采取10年市场禁入措施'))

CONTRACT = dict(
    task_id='P2_FG_600399_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-C 确认实验任务。最复杂案例：46处罚主体、7年连续财务造假、2人处罚调整、6人市场禁入。',
    question='抚顺特钢信息披露违法违规案：证监会对公司及46名责任人员的终罚金额分别是多少？合计多少？拟罚合计多少？赵光晨和国长虹的拟罚与终罚各多少？2010-2012年度虚增利润总额各是多少？累计虚增利润和存货各多少？几个年度由盈转亏？调查通知书、告知书、决定书各于何日收到？编号各是什么？赵明远职务？哪些人被终身禁入？王勇禁入几年？',
    cutoff='2019-12-26',
    source_documents=dict(
        D1=dict(title='关于收到〈行政处罚及市场禁入事先告知书〉的公告（2019-07-09，处罚字【2019】87号）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到〈行政处罚决定书〉和〈市场禁入决定书〉的公告（2019-12-27，[2019]147号）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['抚顺特钢',60],['赵明远等7人',30],['邵福群等22人',10],['徐庆祥等15人',5],['国长虹',3]],
        proposed_lines_D1=[['抚顺特钢',60],['赵明远等7人',30],['邵福群等23人(含赵光晨)',10],['徐庆祥等15人(含国长虹)',5]],
        final_total_wan=568, proposed_total_wan=575,
        changes=[dict(party='赵光晨',d1=10,d2=5,reason='身体原因参与度低，部分采纳'),
                 dict(party='国长虹',d1=5,d2=3,reason='签字时客观事实，部分采纳')],
        market_bans=dict(
            lifetime=['赵明远','单志强','董事','孙启','张晓军'],
            ten_year=['王勇','姜臣宝']),
        aliases=[dict(canonical='抚顺特殊钢股份有限公司',variants=['抚顺特钢','公司'],where='both docs')],
    ),
    scoring=dict(primary='Q_all = TP / N (N=25)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal','E_literal'],scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF（巨潮资讯），pdftotext',model_calls=0,
                    independence='DAG-line independent; 未参与本DAG调度实验线'),
    known_issues=[
        dict(issue='原D1(处罚字【2018】157号)是迟披露案件，非本案；已替换为正确D1(处罚字【2019】87号)',
             handling='已修复，Gold使用正确的D1'),
        dict(issue='D2处罚名单中"董事"作为人名出现（原名可能为特定中文姓名，文档中仅显示"董事"）',
             handling='照录原文，不猜测实际姓名'),
        dict(issue='6个年度亏损披露为盈利是本案例最显著的财务事实',handling='F15记录年度数'),
    ],
)

out = OUT / 'TASK_CONTRACT_FG_600399_v1_DRAFT.json'
out.write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=1) + '\n', 'utf-8')
print('sha256:', hashlib.sha256(out.read_bytes()).hexdigest())
print(f'slots: {len(F)}, critical: {sum(1 for f in F if f.get("critical"))}')
for f in F:
    for e in f['source_evidence']:
        if norm(e['quote']) not in (D2N if e['doc_id']=='D2' else D1N):
            print(f'  FAIL {f["fact_id"]} in {e["doc_id"]}: {e["quote"][:50]}'); break
    else: continue
    break
else: print('self-check: all quotes verbatim ✓')
# Verify totals
d2_total = 60 + 30*7 + 10*22 + 5*15 + 3
d1_total = 60 + 30*7 + 10*23 + 5*15
assert d2_total == 568 and d1_total == 575, f'mismatch: {d2_total}/{d1_total}'
print(f'totals: D2={d2_total}万(46人), D1={d1_total}万(46人) ✓')
