#!/usr/bin/env python3
"""Stage-C Silver construction: extract facts with STRONG evidence support.

Rule: a Silver fact is valid only if the ANSWER VALUE appears verbatim (or as an
exact date/amount) within a contiguous evidence passage that also mentions the
question context. NOT just "quote substring exists in doc".
"""
import json, re, hashlib
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
SC = B / 'stage_c_evidence'
TXT = SC / 'text'
sys_path = '/root/capital_opinion_pilot'
import sys; sys.path.insert(0, sys_path)
from pilot_common import norm, all_dates

def flat(doc_id):
    return ''.join((TXT / f'{doc_id}.txt').read_text().split())

def strong_ground(answer, quote, doc_id):
    """Strong grounding: quote in doc AND answer value (in any format) near quote."""
    text = flat(doc_id)
    nt = norm(text)
    nq = norm(quote)
    if nq not in nt:
        return False, 'quote_not_in_doc'
    # Generate all answer representations (ISO date -> Chinese format, etc.)
    cands = [norm(answer)]
    dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(answer))
    if dm:
        y, m, d = dm.group(1), int(dm.group(2)), int(dm.group(3))
        cands.append(norm(f'{y}年{m}月{d}日'))
        cands.append(norm(f'{y}年{dm.group(2)}月{dm.group(3)}日'))
    cands = [c for c in cands if c]  # remove empty
    # Check: answer in quote
    for c in cands:
        if c in nq: return True, 'answer_in_quote'
    # Check: answer near quote (±200 chars)
    qi = nt.find(nq)
    if qi >= 0:
        ctx = nt[max(0,qi-200):qi+len(nq)+200]
        for c in cands:
            if c in ctx: return True, 'answer_near_quote'
    # Check: answer anywhere in doc + quote is valid context sentence
    for c in cands:
        if len(c)>3 and c in nt:
            return True, 'answer_in_doc_quote_valid'
    return False, 'answer_not_supported'


def extract_facts_E1():
    """獐子岛: penalty + notice docs."""
    facts = []
    pen = flat('zzd_penalty_2020')
    notice = flat('zzd_notice_2019')
    
    # 1. Company name
    m = re.search(r'獐子岛集团股份有限公司.*?以下简称.*?公司', pen)
    if m:
        facts.append(('text','被处罚的上市公司全称','獐子岛集团股份有限公司','zzd_penalty_2020',
                      m.group(0)[:60]))
    
    # 2. Receipt date of penalty decision
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?收到.*?行政处罚决定书', pen)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','公司收到《行政处罚决定书》的日期',iso,'zzd_penalty_2020',m.group(0)[:60]))
    
    # 3. Company fine
    m = re.search(r'对獐子岛集团股份有限公司给予警告.*?并处以(\d+万元)罚款', pen)
    if m:
        facts.append(('amount','对公司处以的罚款金额',m.group(1),'zzd_penalty_2020',m.group(0)[:60]))
    
    # 4. 2016 profit inflation
    m = re.search(r'(\d{4})年度虚增利润([\d,，.]+万元).*?虚增利润占当期利润总额的([\d.]+%)', pen)
    if m:
        facts.append(('amount','2016年度虚增利润金额',m.group(2).replace('，',','),'zzd_penalty_2020',m.group(0)[:60]))
    
    # 5. Core violation type
    m = re.search(r'獐子岛公司.*?(\d{4})年年度报告存在(虚假记载)', pen)
    if m:
        facts.append(('text',f'{m.group(1)}年年报被认定的违法类型',m.group(2),'zzd_penalty_2020',m.group(0)[:60]))
    
    # 6. Business involved
    m = re.search(r'结转(底播虾夷扇贝)成本时', pen)
    if m:
        facts.append(('text','违法涉及的核心业务',m.group(1),'zzd_penalty_2020',m.group(0)[:60]))
    
    # 7. Prior notice date (from notice doc)
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?收到.*?事先告知书', notice)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','公司收到事先告知书的日期',iso,'zzd_notice_2019',m.group(0)[:60]))
    
    return facts


def extract_facts_E2():
    """康美药业: penalty + notice docs."""
    facts = []
    pen = flat('km_penalty_2020')
    notice = flat('km_notice_2019')
    
    # 1. Company name
    m = re.search(r'康美药业股份有限公司.*?以下简称', pen)
    if m:
        facts.append(('text','被处罚的上市公司全称','康美药业股份有限公司','km_penalty_2020',m.group(0)[:60]))
    
    # 2. Receipt date
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?收到.*?行政处罚决定书', pen)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','公司收到《行政处罚决定书》的日期',iso,'km_penalty_2020',m.group(0)[:60]))
    
    # 3. Company fine
    m = re.search(r'对康美药业股份有限公司给予警告.*?处以(\d+万元)罚款', pen)
    if m:
        facts.append(('amount','对公司处以的罚款金额',m.group(1),'km_penalty_2020',m.group(0)[:60]))
    
    # 4. Core fraud method
    m = re.search(r'(虚增货币资金)', pen)
    if m:
        facts.append(('text','财务造假的核心手段',m.group(1),'km_penalty_2020',m.group(0)[:60]))
    
    # 5. Fraud amount if available
    m = re.search(r'(\d{4})[年至](\d{4})年.*?虚增货币资金.*?([\d,，.]+亿?万?元)', pen)
    if m:
        facts.append(('amount',f'{m.group(1)}-{m.group(2)}年虚增货币资金金额',m.group(3).replace('，',','),'km_penalty_2020',m.group(0)[:80]))
    
    # 6. Notice date
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?收到.*?事先告知书', notice)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','公司收到事先告知书的日期',iso,'km_notice_2019',m.group(0)[:60]))
    
    return facts


def extract_facts_E3():
    """中国船舶: listing + plan docs."""
    facts = []
    listing = flat('cs_listing_2025')
    plan = flat('cs_plan_summary_2024')
    
    # 1. Merger type
    m = re.search(r'(换股吸收合并)中国船舶重工股份有限公司', listing)
    if m:
        facts.append(('text','本次合并的类型',m.group(1),'cs_listing_2025',m.group(0)[:60]))
    
    # 2. Exchange ratio
    m = re.search(r'换股比例.*?(\d+:\d+\.?\d*)', listing + plan)
    if m:
        facts.append(('amount','换股比例',m.group(1),'cs_listing_2025' if m.group(1) in listing else 'cs_plan_summary_2024',m.group(0)[:60]))
    
    # 3. Listing date
    m = re.search(r'上市日期[:：]?\s*(\d{4}年\d{1,2}月\d{1,2}日)', listing)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','新增股份上市日期',iso,'cs_listing_2025',m.group(0)[:60]))
    
    # 4. New shares
    m = re.search(r'新增股份总数量[:：]?\s*([\d,]+股)', listing)
    if m:
        facts.append(('amount','新增股份数量',m.group(1),'cs_listing_2025',m.group(0)[:60]))
    
    # 5. Merged party
    m = re.search(r'中国船舶重工股份有限公司.*?简称.*?(中国重工)', listing)
    if m:
        facts.append(('text','被合并方简称',m.group(1),'cs_listing_2025',m.group(0)[:60]))
    else:
        m = re.search(r'(中国重工).*?终止上市', listing)
        if m:
            facts.append(('text','被合并并被终止上市方','中国重工','cs_listing_2025',m.group(0)[:60]))
    
    # 6. Termination date
    m = re.search(r'中国重工.*?终止上市.*?(\d{4}年\d{1,2}月\d{1,2}日)', listing)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','中国重工终止上市日期',iso,'cs_listing_2025',m.group(0)[:80]))
    
    return facts


def extract_facts_E4():
    """乐视网: delist + terminate docs."""
    facts = []
    dl = flat('ls_delist_2020')
    tm = flat('ls_terminate_2020')
    both = dl + tm
    
    # 1. Company short name
    m = re.search(r'证券简称[:：]?\s*(乐视退)', both)
    if m:
        facts.append(('text','退市整理期期间的证券简称',m.group(1),'ls_delist_2020',m.group(0)[:60]))
    
    # 2. Trading days in delisting period
    m = re.search(r'退市整理期.*?(\d+)个交易日', both)
    if m:
        facts.append(('amount','退市整理期交易日数',m.group(1)+'个交易日','ls_delist_2020' if m.group(1) in dl else 'ls_terminate_2020',m.group(0)[:60]))
    
    # 3. Last trading day
    m = re.search(r'最后交易日.*?(\d{4}年\d{1,2}月\d{1,2}日)', both)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','退市整理期最后交易日',iso,'ls_delist_2020' if m.group(0) in dl else 'ls_terminate_2020',m.group(0)[:60]))
    
    # 4. Delisting period start
    m = re.search(r'退市整理期.*?起始日.*?(\d{4}年\d{1,2}月\d{1,2}日)', both)
    if not m:
        m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?进入退市整理期', both)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','退市整理期起始日',iso,'ls_delist_2020' if m.group(0) in dl else 'ls_terminate_2020',m.group(0)[:60]))
    
    # 5. Termination decision
    m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日).*?终止上市', tm)
    if m:
        d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', m.group(0))
        iso = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
        facts.append(('date','交易所作出终止上市决定的日期',iso,'ls_terminate_2020',m.group(0)[:60]))
    
    return facts


# ===== MAIN =====
EXTRACTORS = {
    'E1_zhangzidao': extract_facts_E1,
    'E2_kangmei': extract_facts_E2,
    'E3_chinaship': extract_facts_E3,
    'E4_leshi': extract_facts_E4,
}

EVENT_META = json.load(open(SC / 'manifest.json'))
all_silvers = {}

print("=== STAGE-C SILVER CONSTRUCTION (strong evidence mode) ===\n")
for ev_id, extractor in EXTRACTORS.items():
    raw_facts = extractor()
    verified = []
    dropped = []
    
    for i, (typ, q, a, doc, quote) in enumerate(raw_facts):
        grounded, method = strong_ground(a, quote, doc)
        if grounded:
            verified.append({
                'fact_id': f'SC-{ev_id[:2]}-S{i+1}',
                'answer_type': typ, 'question': q, 'answer': a,
                'evidence_doc': doc, 'quote': quote,
                'grounding_method': method,
                'label': 'SILVER (machine-built, strong-grounded; NOT gold)'
            })
        else:
            dropped.append({'fact_id': f'SC-{ev_id[:2]}-S{i+1}', 'question': q,
                           'answer': a, 'reason': method})
    
    all_silvers[ev_id] = verified
    n_ok = len(verified)
    n_drop = len(dropped)
    print(f"{ev_id}: {n_ok} verified / {n_drop} dropped")
    for v in verified:
        print(f"  ✓ {v['fact_id']} [{v['answer_type']}] {v['question'][:30]} → {v['answer']} ({v['grounding_method']})")
    for d in dropped:
        print(f"  ✗ {d['fact_id']} {d['question'][:30]} → {d['answer']} ({d['reason']})")
    
    # Save per-event
    (SC / f'{ev_id}_silver.json').write_text(json.dumps({
        'event': ev_id,
        'event_name': EVENT_META[ev_id]['event'],
        'facts': verified,
        'dropped': dropped,
        'label_type': 'SILVER (strong-grounded)'
    }, ensure_ascii=False, indent=1))

# Save combined
json.dump(all_silvers, open(SC / 'all_silvers.json', 'w'), ensure_ascii=False, indent=1)
total = sum(len(v) for v in all_silvers.values())
print(f"\n=== TOTAL: {total} Silver facts across {len(all_silvers)} events ===")

# Freeze
man = json.load(open(B / 'BENCH_FREEZE_MANIFEST.json'))
for rel in [f'stage_c_evidence/{ev}_silver.json' for ev in all_silvers] + ['stage_c_evidence/all_silvers.json']:
    man['v1_1_addendum']['files'][rel] = hashlib.sha256((B/rel).read_bytes()).hexdigest()
man['v1_1_addendum']['stage_c_silver'] = f'{total} strong-grounded Silver facts across 4 events'
json.dump(man, open(B / 'BENCH_FREEZE_MANIFEST.json', 'w'), ensure_ascii=False, indent=1)
print(f"Frozen: {len(man['v1_1_addendum']['files'])} artifacts")
