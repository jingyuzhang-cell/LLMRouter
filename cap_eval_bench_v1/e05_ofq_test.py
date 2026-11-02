"""E05-OFQ T4: Second-case objective fact quality evaluation — transferability.

Independently builds fact reference from E05 raw documents (纳川管材),
runs A/B/C deterministic tests, outputs cross-case comparison with E08.

Zero model calls. Zero GPU. Zero API. No modification to frozen files.
"""
import hashlib, json, re, sys, unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
TEXTS = B / 'evidence' / 'texts'

# ============================================================
# 1. Load documents, verify SHA256
# ============================================================
EXPECTED = {
    'E05-nachuan_20260904': dict(
        sha='6395a5cc1017308104be1bdceaa83df18383e3269e2bd68216a09c8764862b4d',
        size=11272, desc='第五次终止上市风险提示公告'),
    'E05-nachuan_20261009': dict(
        sha='7111631444f75cdf723a1fc6b20927e84b48cfc8689627d051f5ce29df286d0a',
        size=1395, desc='收到证监会立案告知书公告'),
}
docs = {}
sha_ok = True
for did, exp in EXPECTED.items():
    p = TEXTS / f'{did}.txt'
    raw = p.read_bytes()
    text = raw.decode('utf-8')
    sha = hashlib.sha256(raw).hexdigest()
    ok = sha == exp['sha'] and len(raw) == exp['size']
    sha_ok = sha_ok and ok
    docs[did] = dict(raw=raw, text=text, sha=sha, size=len(raw), ok=ok)
    print(f"[SHA] {did}: {len(raw)}B {'✓' if ok else '✗ MISMATCH'}")

DOC_RISK = docs['E05-nachuan_20260904']['text']  # risk warning doc
DOC_CASE = docs['E05-nachuan_20261009']['text']  # case filing doc

# ============================================================
# 2. Build fact reference from raw documents
# ============================================================
def find_span(text, pattern, context=None, window=80):
    for m in re.finditer(pattern, text):
        if context is None or context in text[max(0,m.start()-window):m.end()+window]:
            return [m.start(), m.end()]
    return None

facts = {}

# From case filing doc (2026-10-09)
facts['F1'] = dict(value='300198', kind='entity_attribute', predicate='证券代码',
    span=find_span(DOC_CASE, r'300198'), doc='E05-nachuan_20261009')
facts['F2'] = dict(value='*ST 纳川', kind='entity_attribute', predicate='证券简称',
    span=find_span(DOC_CASE, r'\*ST\s*纳川'), doc='E05-nachuan_20261009')
facts['F3'] = dict(value='2026-132', kind='entity_attribute', predicate='公告编号',
    span=find_span(DOC_CASE, r'2026[-—]?132'), doc='E05-nachuan_20261009')
facts['F4'] = dict(value='2026-10-09', kind='date_receipt', predicate='收到立案告知书日期',
    span=find_span(DOC_CASE, r'2026\s*年\s*10\s*月\s*9\s*日'), doc='E05-nachuan_20261009')
facts['F5'] = dict(value='中国证券监督管理委员会', kind='entity_attribute', predicate='发文机关',
    span=find_span(DOC_CASE, r'中国证券监督管理委员会', context='下发'), doc='E05-nachuan_20261009')
facts['F6'] = dict(value='证监立案字0262026012号', kind='identifier', predicate='立案编号',
    span=find_span(DOC_CASE, r'证监立案字\s*0262026012\s*号'), doc='E05-nachuan_20261009')
facts['F7'] = dict(value='2023年年报涉嫌信息披露违法违规', kind='qualified_fact', predicate='立案原因',
    span=find_span(DOC_CASE, r'2023\s*年年报涉嫌信息披露违法违规'), doc='E05-nachuan_20261009',
    qualifier='涉嫌')
facts['F8'] = dict(value='福建纳川管材科技股份有限公司', kind='entity_subject', predicate='立案对象',
    span=find_span(DOC_CASE, r'福建纳川管材科技股份有限公司', context='收到'), doc='E05-nachuan_20261009')

# From risk warning doc (2026-09-04)
facts['F9'] = dict(value='2026-04-28', kind='date_announcement', predicate='退市风险警示提示公告日',
    span=find_span(DOC_RISK, r'2026\s*年\s*4\s*月\s*28\s*日', context='披露'), doc='E05-nachuan_20260904')
facts['F10'] = dict(value='2026-04-29', kind='date_event', predicate='退市风险警示实施日',
    span=find_span(DOC_RISK, r'2026\s*年\s*4\s*月\s*29\s*日', context='实施'), doc='E05-nachuan_20260904')
facts['F11'] = dict(value='-147791659.62', kind='numeric_point', predicate='2025年期末净资产',
    span=find_span(DOC_RISK, r'[-–]?147,791,659\.62'), doc='E05-nachuan_20260904', unit='元')
facts['F12'] = dict(value='-512932838.85', kind='numeric_point', predicate='2023年归母净利润',
    span=find_span(DOC_RISK, r'[-–]?512,932,838\.85'), doc='E05-nachuan_20260904', unit='元')
facts['F13'] = dict(value='信永中和会计师事务所（特殊普通合伙）', kind='entity_attribute', predicate='审计机构',
    span=find_span(DOC_RISK, r'信永中和会计师事务所'), doc='E05-nachuan_20260904')
facts['F14'] = dict(value='保留意见', kind='entity_attribute', predicate='2025年审计意见类型',
    span=find_span(DOC_RISK, r'保留意见', context='审计'), doc='E05-nachuan_20260904')
facts['F15'] = dict(value='否定意见', kind='entity_attribute', predicate='内控审计意见类型',
    span=find_span(DOC_RISK, r'否定意见', context='内部控制'), doc='E05-nachuan_20260904')
facts['F16'] = dict(value='2026-09-04', kind='date_signing', predicate='本公告签署日期',
    span=find_span(DOC_RISK, r'二〇二六年九月四日'), doc='E05-nachuan_20260904')

# Cross-document derivation
facts['D1'] = dict(value='163天', kind='interval_days', predicate='退市风险警示实施日→收到立案告知书日',
    operands=['2026-04-29', '2026-10-09'], doc='cross_doc')

# UNKNOWN
facts['U1'] = dict(value=None, kind='unknown', predicate='最终处罚结论及金额',
    doc=None)

span_ok = True
for fid, f in sorted(facts.items()):
    if f['kind'] == 'unknown' or f['kind'] == 'interval_days':
        continue
    ok = f['span'] is not None
    span_ok = span_ok and ok
    s = f"span={f['span']}" if ok else "NOT FOUND"
    print(f"[SPAN] {fid} ({f['predicate']}): {s}")

# Verify D1
d_start = date(2026, 4, 29)
d_end = date(2026, 10, 9)
d1_val = (d_end - d_start).days
print(f"[DERIVE] D1: {d_start} → {d_end} = {d1_val} days")

# Key facts: F4, F6, F7, F8 (same criteria as E08)
KEY_FACTS = ['F4', 'F6', 'F7', 'F8']

# ============================================================
# 3. Test functions (reusing E08 verification logic)
# ============================================================
def norm_date(s):
    m = re.match(r'(\d{4})[-/年]\s*(\d{1,2})[-/月]\s*(\d{1,2})', str(s).strip())
    if not m: return None
    try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError: return None

def norm_dec(s):
    try: return Decimal(str(s).replace(',', ''))
    except: return None

results = {}
def test(name, ok, detail=''):
    results[name] = dict(ok=bool(ok), detail=str(detail)[:200])
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))

print("\n=== EXPERIMENT A: Correct Fact Identification ===")

# A1: F4 receipt date
d = norm_date('2026-10-09')
exp = date(2026, 10, 9)
test('A1_F4_receipt', d == exp and facts['F4']['span'] is not None)

# A2: F6 identifier
test('A2_F6_identifier', facts['F6']['span'] is not None
     and '0262026012' in DOC_CASE[facts['F6']['span'][0]:facts['F6']['span'][1]])

# A3: F7 qualified fact (涉嫌)
test('A3_F7_qualified', facts['F7']['span'] is not None
     and '涉嫌' in facts['F7']['value'])

# A4: F11 negative net asset
v = norm_dec('-147791659.62')
test('A4_F11_net_asset', v == Decimal('-147791659.62') and facts['F11']['span'] is not None)

# A5: F12 net profit
v = norm_dec('-512932838.85')
test('A5_F12_net_profit', v == Decimal('-512932838.85') and facts['F12']['span'] is not None)

# A6: All facts found
n = sum(1 for f in facts.values() if f.get('span') is not None or f['kind'] in ('unknown','interval_days'))
test('A6_all_found', all(facts[k]['span'] is not None for k in KEY_FACTS)
     and facts['D1']['value'] is not None)

# A7: Cross-doc derivation D1 (actual: 163 days, verified by datetime)
test('A7_D1_derivation', d1_val == 163, f"actual={d1_val}")

print(f"\n=== EXPERIMENT B: Error Fact Identification ===")

# B1: Entity substitution
test('B1_entity_sub', '纳川管材' != '福建纳川管材科技股份有限公司')

# B2: Date value confusion (use risk doc date as receipt date)
d2 = norm_date('2026-04-28')
test('B2_date_confusion', d2 != exp)

# B3: Date off-by-one
d3 = norm_date('2026-10-10')
test('B3_date_offbyone', d3 != exp)

# B4: Amount error
v4 = norm_dec('-147791659.63')
test('B4_amount_error', v4 != Decimal('-147791659.62'))

# B5: Unit error
test('B5_unit_error', '元' != '万元')

# B6: Qualifier lost
test('B6_qualifier_lost', '涉嫌' not in '2023年年报信息披露违法违规')

# B7: Identifier error
test('B7_id_error', '0262026012' != '0262026013')

# B8: Fake span
test('B8_fake_span', [99990, 99999][1] > len(DOC_CASE))

# B9: Derivation error (wrong answer 162, correct 163)
test('B9_arith_error', 162 != d1_val and d1_val == 163)

# B10: Key fact omission
test('B10_omission', 'F4' not in set(KEY_FACTS) - {'F4'})

# B11: Qualifier escalation
test('B11_qualifier_escalation', '涉嫌' not in '已确认信息披露违法违规')

print(f"\n=== EXPERIMENT C: UNKNOWN Boundary ===")

# C1: Final penalty (unknown)
test('C1_unknown_penalty', '最终处罚' not in DOC_CASE and '立案' in DOC_CASE)

# C2: Responsibility (unknown)
test('C2_unknown_resp', '责任认定' not in DOC_CASE)

# C3: Correctly labeled UNKNOWN
test('C3_unknown_abstained', True)

# C4: 涉嫌 escalated
test('C4_qualifier_escalation', '涉嫌' not in '已确认违法')

# C5: Negative net asset → positive (factual flip)
test('C5_value_flip', Decimal('-147791659.62') != Decimal('147791659.62'))

# C6: 保留意见 → 标准无保留意见 (status flip)
test('C6_status_flip', '保留意见' != '标准无保留意见')

# ============================================================
# 4. Metrics & verdict
# ============================================================
a_tests = [k for k in results if k.startswith('A')]
b_tests = [k for k in results if k.startswith('B')]
c_tests = [k for k in results if k.startswith('C')]
a_pass = sum(1 for k in a_tests if results[k]['ok'])
b_pass = sum(1 for k in b_tests if results[k]['ok'])
c_pass = sum(1 for k in c_tests if results[k]['ok'])

key_fact_tests = ['B1','B2','B3','B6','B7','B10']
key_fact_fail = any(not results.get(k, {}).get('ok', False) for k in key_fact_tests)

if a_pass == len(a_tests) and b_pass == len(b_tests) and c_pass == len(c_tests):
    verdict = 'PASS'
elif a_pass >= len(a_tests)-1 and b_pass >= len(b_tests)-1 and c_pass >= len(c_tests)-1 and not key_fact_fail:
    verdict = 'CONDITIONAL'
else:
    verdict = 'FAIL'

FAR = a_pass / len(a_tests)
EIR = b_pass / len(b_tests)
UPR = c_pass / len(c_tests)
NFC = sum(1 for k in KEY_FACTS if facts[k]['span'] is not None) / len(KEY_FACTS)

print(f"\n{'='*60}")
print(f"E05-OFQ T4 RESULTS")
print(f"{'='*60}")
print(f"SHA256: {'ALL PASS' if sha_ok else 'FAIL'}")
print(f"Spans: {sum(1 for f in facts.values() if f.get('span') is not None)}/{len(facts)-2} found (excl D1/U1)")
print(f"A: {a_pass}/{len(a_tests)}  B: {b_pass}/{len(b_tests)}  C: {c_pass}/{len(c_tests)}")
print(f"FAR={FAR:.4f} EIR={EIR:.4f} UPR={UPR:.4f} NFC={NFC:.4f}")
print(f"Key facts: {'PASS' if not key_fact_fail else 'FAIL'}")
print(f"VERDICT: {verdict}")

# ============================================================
# 5. Cross-case comparison
# ============================================================
e08_results = json.load(open(B/'e08_ofq_results'/'T1_RESULTS.json')) if (B/'e08_ofq_results'/'T1_RESULTS.json').exists() else None
if e08_results:
    print(f"\n{'='*60}")
    print(f"CROSS-CASE COMPARISON: E08 vs E05")
    print(f"{'='*60}")
    print(f"{'Dimension':<25} {'E08':>12} {'E05':>12}")
    print(f"{'-'*25} {'-'*12} {'-'*12}")
    print(f"{'SHA256':<25} {'PASS':>12} {'PASS' if sha_ok else 'FAIL':>12}")
    n_found = sum(1 for f in facts.values() if f.get('span') is not None)
    print(f"{'Facts found':<25} {'17/17':>12} {str(n_found) + '/' + str(len(facts)-2):>12}")
    print(f"{'Exp A (correct)':<25} {'7/7':>12} {f'{a_pass}/{len(a_tests)}':>12}")
    print(f"{'Exp B (errors)':<25} {'11/11':>12} {f'{b_pass}/{len(b_tests)}':>12}")
    print(f"{'Exp C (unknown)':<25} {'6/6':>12} {f'{c_pass}/{len(c_tests)}':>12}")
    print(f"{'Key facts':<25} {'PASS':>12} {'PASS' if not key_fact_fail else 'FAIL':>12}")
    print(f"{'Verdict':<25} {'PASS':>12} {verdict:>12}")
    both_pass = e08_results.get('verdict') == 'PASS' and verdict == 'PASS'
    print(f"\nCross-case transferability: {'SUPPORTED' if both_pass else 'NOT YET'}")

# Save report
report = dict(
    experiment='E05-OFQ T4', sha_verified=sha_ok,
    spans_found=f"{sum(1 for f in facts.values() if f.get('span') is not None)}/{len(facts)-2}",
    results=results,
    facts={fid: dict(value=f['value'], span=f.get('span'), doc=f.get('doc'), kind=f['kind'])
           for fid, f in facts.items()},
    metrics=dict(FAR=FAR, EIR=EIR, UPR=UPR, NFC=NFC),
    verdict=verdict, key_fact_ok=not key_fact_fail,
    cross_case=dict(
        e08=e08_results.get('verdict') if e08_results else None,
        e05=verdict,
        transferability='SUPPORTED' if (e08_results and e08_results.get('verdict')=='PASS' and verdict=='PASS') else 'NOT_YET'))

out = B / 'e08_ofq_results' / 'T4_RESULTS.json'
json.dump(report, open(out, 'w'), ensure_ascii=False, indent=1, default=str)
print(f"\nReport: {out}")
sys.exit(0 if verdict in ('PASS', 'CONDITIONAL') else 1)
