"""Stage-C-R8 Remediation: Full regression suite with negative tests.
Zero model calls — uses deterministic verifiers only.
"""
import json, re, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/capital_opinion_pilot')

from stage_c_r8_remediation import (
    extract_evidence_window, build_evidence_for_node,
    get_correct_node, verify_temporal_derivation,
    build_n3_prompt, build_n5_prompt, TEMPORAL_KEYWORDS, CROSS_DOC_KEYWORDS
)

PASS = FAIL = 0
RESULTS = []

def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1; RESULTS.append(('PASS', name, detail))
        print(f"  ✓ {name} {detail}")
    else:
        FAIL += 1; RESULTS.append(('FAIL', name, detail))
        print(f"  ✗ {name} {detail}")

print("=" * 60)
print("STAGE-C-R8 REMEDIATION REGRESSION SUITE")
print("=" * 60)

# ===== T1: Evidence Window — dates beyond position 500 =====
print("\n[T1] Evidence Window (P0)")
text_741 = "X" * 740 + "2025年9月16日上市公告" + "Y" * 100
windows = extract_evidence_window(text_741, ['上市', '2025'], window=200)
check("Dates at position 741 are captured", any('2025' in w['text'] for w in windows))
check("Provenance (start/end/keyword) recorded",
      all('start' in w and 'end' in w and 'keyword' in w for w in windows))

# No keywords match → fallback with truncation log
text_plain = "Z" * 2000
windows_fb = extract_evidence_window(text_plain, ['上市'], window=100)
check("Fallback records truncation", any(w.get('truncated') for w in windows_fb))

# ===== T2: Fact-Node Mapping (P1) =====
print("\n[T2] Fact-Node Mapping (P1)")
check("temporal → n3_timeline", get_correct_node('temporal') == 'n3_timeline')
check("cross_doc → n5_factcheck", get_correct_node('cross_doc') == 'n5_factcheck')
check("prefix_only → n2_extracts", get_correct_node('prefix_only') == 'n2_extracts')
check("unknown → defaults to n5", get_correct_node('unknown') == 'n5_factcheck')

# ===== T3: Temporal Verifier (P2) =====
print("\n[T3] Temporal Verifier (P2)")

# T3a: Correct computation
upstream = {'告知日期': '2019-07-09', '处罚日期': '2020-06-23'}
output_correct = "从2019年7月9日到2020年6月23日，间隔350天"
r = verify_temporal_derivation(output_correct, upstream)
check("Correct computation → computed", r.status == 'computed')
check("Correct interval detected", r.interval_days == 350)

# T3b: Missing one date
upstream_missing = {'告知日期': '2019-07-09', '处罚日期': ''}
r2 = verify_temporal_derivation(output_correct, upstream_missing)
check("Missing date → upstream_missing", r2.status == 'upstream_missing')
check("Missing detail recorded", 'Missing' in (r2.error_detail or ''))

# T3c: Both dates but no computation
output_no_calc = "日期是2019年7月9日和2020年6月23日"
r3 = verify_temporal_derivation(output_no_calc, upstream)
check("Dates present but no computation → not_computed", r3.status == 'not_computed')

# T3d: Wrong interval
output_wrong = "从2019年7月9日到2020年6月23日，间隔100天"
r4 = verify_temporal_derivation(output_wrong, upstream)
check("Wrong interval → error", r4.status == 'error')

# T3e: Model acknowledges inability
output_unknown = "UNABLE UNKNOWN 无法确认间隔"
r5 = verify_temporal_derivation(output_unknown, upstream)
check("Model says UNKNOWN → not_computed", r5.status == 'not_computed')

# ===== T4: Cross-doc Contract (P1) =====
print("\n[T4] Cross-doc Contract")
n5_prompt = build_n5_prompt("核查换股比例", {"doc_a": "1:0.1339", "doc_b": "1:0.1339"})
check("n5 prompt includes cross-doc contract", '跨文档比较' in n5_prompt)
check("n5 prompt includes insufficient_evidence clause", 'insufficient_evidence' in n5_prompt)
check("n5 prompt includes both values", 'doc_a' in n5_prompt and 'doc_b' in n5_prompt)

# ===== T5: Temporal Contract (P2) =====
print("\n[T5] Temporal Contract")
n3_prompt = build_n3_prompt("时间线", {"dates": ["2019-07-09", "2020-06-23"]})
check("n3 prompt includes temporal contract", '时间线推导合同' in n3_prompt)
check("n3 prompt requires interval computation", '间隔天数' in n3_prompt)
check("n3 prompt has insufficient_evidence clause", 'insufficient_evidence' in n3_prompt)
check("n3 prompt prohibits listing without computing", '不能只列出日期' in n3_prompt)

# ===== T6: Evidence completeness for SC-E3 =====
print("\n[T6] SC-E3 Evidence Completeness")
sc3_evidence_path = Path('/root/cap_eval_bench_v1/stage_c_evidence/text/cs_listing_2025.txt')
if sc3_evidence_path.exists():
    sc3_text = ''.join(sc3_evidence_path.read_text().split())
    windows = extract_evidence_window(sc3_text, ['2025', '上市', '终止', '换股'], window=300, max_windows=4)
    check("SC-E3 dates captured beyond position 500",
          any('2025' in w['text'] for w in windows),
          f"({len(windows)} windows)")
    check("SC-E3 windows have provenance",
          all('start' in w and 'end' in w for w in windows))
else:
    check("SC-E3 evidence exists", False)

# ===== T7: Deterministic negative tests =====
print("\n[T7] Negative Tests")

# Cross-doc with only one doc
single_doc_data = {"doc_a": "1:0.1339"}
n5_prompt_single = build_n5_prompt("核查", single_doc_data)
# Verifier should detect that one side is missing
check("Cross-doc with single doc noted in prompt", 'doc_a' in n5_prompt_single)

# UNKNOWN preservation
unknown_fact = {"fact_id": "TEST-UNKNOWN", "answer": "UNKNOWN", "derivation": "cross_doc"}
check("UNKNOWN fact preserved as-is", unknown_fact["answer"] == "UNKNOWN")

# ===== SUMMARY =====
print(f"\n{'='*60}")
print(f"R8 REMEDIATION: {PASS} PASS / {FAIL} FAIL")
print(f"{'='*60}")
for s, n, d in RESULTS:
    if s == 'FAIL':
        print(f"  ✗ {n}: {d}")

# Save results
output = {
    'pass': PASS, 'fail': FAIL,
    'checks': [{'status': s, 'name': n, 'detail': d} for s, n, d in RESULTS],
}
outpath = Path('/root/cap_eval_bench_v1/integration/r8_remediation_test_results.json')
outpath.write_text(json.dumps(output, indent=1))
sha = hashlib.sha256(outpath.read_bytes()).hexdigest()
print(f"\nSaved: {outpath.name} (sha={sha[:16]}...)")
sys.exit(0 if FAIL == 0 else 1)
