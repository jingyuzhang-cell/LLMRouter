#!/usr/bin/env python3
"""*ST广道 (839680) Gold contract builder."""
import hashlib, json, re, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
D1 = (RAW / '839680_notice_1749744000000.pdf.txt').read_text('utf-8')
D2 = (RAW / '839680_decision_1757606400000.pdf.txt').read_text('utf-8')
D1_META = json.loads((RAW / '839680_notice_1749744000000.pdf.meta.json').read_text())
D2_META = json.loads((RAW / '839680_decision_1757606400000.pdf.meta.json').read_text())

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
D1N = norm(D1); D2N = norm(D2)

def ev(doc, quote):
    q = norm(quote); t = D2N if doc == 'D2' else D1N
    if q not in t: raise ValueError(f'NOT VERBATIM in {doc}: {quote[:60]}')
    return [dict(doc_id=doc, page=1, quote=quote, pdf_sha256=D2_META['sha256'] if doc=='D2' else D1_META['sha256'])]

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
add('F1','深圳市广道数字技术股份有限公司','行政处罚罚款金额','1000','number',True,['D2'],'amount','广道','罚款',
    ev('D2','对深圳市广道数字技术股份有限公司责令改正,给予警告,并处以1,000万元'),unit='万元')
add('F2','金文明','行政处罚罚款金额','1500','number',True,['D2'],'amount','金文明','罚款',
    ev('D2','对金文明给予警告,并处以1,500万元'),unit='万元')
add('F3','赵璐','行政处罚罚款金额','500','number',True,['D2'],'amount','赵璐','罚款',
    ev('D2','对赵璐给予警告,并处以500万元'),unit='万元')
add('F4','宋凯','行政处罚罚款金额','250','number',False,['D2'],'amount','宋凯','罚款',
    ev('D2','对宋凯给予警告,并处以250万元'),unit='万元')
add('F5','邹璧鸿','行政处罚罚款金额','110','number',True,['D2'],'amount','邹璧鸿','罚款',
    ev('D2','对邹璧鸿给予警告,并处以110万元'),unit='万元',
    derivation=dict(note='D1拟罚120万→D2终罚110万'))
add('F6','WANG,YANG(王洋)等4人','单人行政处罚罚款金额','50','number',False,['D2'],'amount','王洋','罚款',
    ev('D2','WANG,YANG(王洋)、杨彬、陈曦、周绍鑫给予警告,并分别处以50万元'),unit='万元')

# TOTALS
add('F7','全部当事人','罚款合计','4020','number',False,['D2'],'penalty_line_sum',None,'罚款',
    ev('D2','对深圳市广道数字技术股份有限公司责令改正'),unit='万元',
    derivation=dict(rule='1000+1500+500+250+150×2+110+100+60+50×4=4020万',parties=12))
add('F8','全部当事人','拟处罚罚款合计','4050','number',False,['D1'],'penalty_line_sum',None,'罚款',
    ev('D1','对深圳市广道数字技术股份有限公司责令改正'),unit='万元',
    derivation=dict(rule='1000+1500+500+250+150×2+120+100+60×3+50×2=4050万',parties=12,
        note='差30万来自邹璧鸿(120→110)+杨彬(60→50)+王洋(60→50)'))

# STAGE CHANGES
add('F9','邹璧鸿','拟处罚罚款金额（终罚：110万元）','120','number',True,['D1','D2'],'amount','邹璧鸿','罚款',
    ev('D1','对邹璧鸿给予警告,并处以120万元')+ev('D2','对邹璧鸿给予警告,并处以110万元'),
    unit='万元',dual_stage=dict(d1_proposed='120万元',d2_final='110万元',change='reduced'))
add('F10','杨彬','拟处罚罚款金额（终罚：50万元）','60','number',True,['D1','D2'],'amount','杨彬','罚款',
    ev('D1','对安秀梅、杨彬、WANG,YANG(王洋)给予警告,并分别处以60万元')+
    ev('D2','WANG,YANG(王洋)、杨彬、陈曦、周绍鑫给予警告,并分别处以50万元'),
    unit='万元',dual_stage=dict(d1_proposed='60万元',d2_final='50万元',change='reduced'))

# FINANCIAL FRAUD
add('F11','广道数字','虚增营业收入','14297.39','number',True,['D1','D2'],'amount',None,'营业收入',
    ev('D2','虚增营业收入142,973,927.21元'),unit='万元',
    derivation=dict(original_yuan='142,973,927.21',standard_wan='14297.39'))

# DATES
add('F12','广道数字','调查通知书收到日期','2024-12-04','date',True,['D1','D2'],'date',None,'调查',
    ev('D2','2024年12月4日'))
add('F13','广道数字','事先告知书收到日期','2025-06-17','date',True,['D1','D2'],'date',None,'告知书',
    ev('D1','2025年6月17日'))
add('F14','广道数字','行政处罚决定书收到日期','2025-09-12','date',True,['D2'],'date',None,'决定书',
    ev('D2','2025年9月12日'))

# DOC NUMBERS
add('F15','行政处罚决定书','文号','〔2025〕9号','text',False,['D2'],'doc_number',None,'决定书',
    ev('D2','〔2025〕9号'))

# MARKET BAN
add('F16','金文明、赵璐','市场禁入措施','终身证券市场禁入','text',True,['D1','D2'],'text','金文明','禁入',
    ev('D2','金文明、赵璐分别采取终身证券市场禁入措施'))

CONTRACT = dict(
    task_id='P2_GD_839680_PENALTY', contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
    positioning='P2-C 确认实验任务。12主体、大额处罚（公司1000万+个人1500万）、3人下调、终身禁入。',
    question='广道数字信息披露违法违规案：终罚各主体金额？合计？拟罚合计？邹璧鸿和杨彬的拟罚与终罚各多少？虚增营业收入多少？调查通知书、告知书、决定书各于何日收到？决定书文号？金文明市场禁入措施？',
    cutoff='2025-09-12',
    source_documents=dict(
        D1=dict(title='关于收到〈行政处罚及市场禁入事先告知书〉的公告（2025-06-17）',
                url=D1_META['url'], retrieved_at=D1_META['retrieved_at'], pdf_sha256=D1_META['sha256']),
        D2=dict(title='关于收到〈行政处罚决定书〉的公告（2025-09-12，[2025]9号）',
                url=D2_META['url'], retrieved_at=D2_META['retrieved_at'], pdf_sha256=D2_META['sha256'])),
    source_pages=dict(
        D1=dict(raw_sha256=D1_META['sha256'], pages={'1': dict(text=D1, page_sha256=hashlib.sha256(D1.encode()).hexdigest())}),
        D2=dict(raw_sha256=D2_META['sha256'], pages={'1': dict(text=D2, page_sha256=hashlib.sha256(D2.encode()).hexdigest())})),
    required_facts=F, critical_fact_ids=[f['fact_id'] for f in F if f.get('critical')], unknown_items=[],
    entity_correspondence=dict(
        final_lines_D2=[['广道数字',1000],['金文明',1500],['赵璐',500],['宋凯',250],['刘海军、陈友志',150],['邹璧鸿',110],['李威',100],['安秀梅',60],['WANG,YANG等4人',50]],
        proposed_lines_D1=[['广道数字',1000],['金文明',1500],['赵璐',500],['宋凯',250],['刘海军、陈友志',150],['邹璧鸿',120],['李威',100],['安秀梅、杨彬、王洋',60],['陈曦、周绍鑫',50]],
        final_total_wan=4020, proposed_total_wan=4050,
        changes=[dict(party='邹璧鸿',d1=120,d2=110),dict(party='杨彬',d1=60,d2=50),dict(party='王洋',d1=60,d2=50)],
        market_bans=dict(lifetime=['金文明']),
        aliases=[dict(canonical='深圳市广道数字技术股份有限公司',variants=['广道数字','公司'],where='both docs')]),
    scoring=dict(primary='Q_all = TP / N (N=16)', safety='error_rate (None when nothing asserted)',
                 auxiliary=['Q_terminal','E_literal'],scorer='qs_scorer.py pattern'),
    provenance=dict(nature='两份公告 PDF',model_calls=0,independence='DAG-line independent'),
    known_issues=[dict(issue='D2用WANG,YANG(王洋)英文名+中文名双语标识',handling='照录原文')],
)

out = OUT / 'TASK_CONTRACT_GD_839680_v1_DRAFT.json'
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
d2t = 1000+1500+500+250+300+110+100+60+200; d1t = 1000+1500+500+250+300+120+100+180+100
print(f'totals: D2={d2t}万, D1={d1t}万 {"✓" if d2t==4020 and d1t==4050 else "MISMATCH"}')
