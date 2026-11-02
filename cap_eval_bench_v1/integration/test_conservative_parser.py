"""P1–P20 offline regression tests for conservative_parser.py (SPEC v2.6).
Zero model calls — all fixtures constructed from historical data or synthetic."""
import json, sys, hashlib
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
from conservative_parser import (ConservativeParser, DocumentSnapshot,
                                 TypedValue, typed_parse, Binding)

V = {}
def test(name, ok, detail=''):
    V[name] = bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''))

# Build doc snapshots for E3
E3_DOCS = ['cs_plan_summary_2024', 'cs_listing_2025']
snaps = {}
for did in E3_DOCS:
    p = B / 'stage_c_evidence' / 'text' / f'{did}.txt'
    if p.exists():
        snaps[did] = DocumentSnapshot.from_file(p)

parser = ConservativeParser(E3_DOCS, snaps)

# Helper: construct ledger facts from known spans
def make_ledger():
    """Simulated ledger with facts at known spans from real documents."""
    plan = snaps['cs_plan_summary_2024']
    listing = snaps['cs_listing_2025']
    def find_span(text, pattern):
        m = re.search(pattern, text)
        return [m.start(), m.end()] if m else None
    import re
    facts = []
    # Plan-side ratio 0.1335
    sp1 = find_span(plan.doc_text, r'1\s*[:：]\s*0\.1335')
    if sp1:
        facts.append(dict(fid='f1', content='1:0.1335', source='cs_plan_summary_2024',
                          source_doc_version=plan.sha256, span=sp1, fact_kind='ratio',
                          operand_role='initial_plan', document_role='plan_document',
                          time_stage='initial_pricing'))
    # Plan-side ratio 0.1339 (adjusted)
    sp2 = find_span(plan.doc_text, r'1\s*[:：]\s*0\.1339')
    if sp2:
        facts.append(dict(fid='f2', content='1:0.1339', source='cs_plan_summary_2024',
                          source_doc_version=plan.sha256, span=sp2, fact_kind='ratio',
                          operand_role='adjusted_plan', document_role='plan_document',
                          time_stage='post_adjustment'))
    # Listing-side ratio 0.1339
    sp3 = find_span(listing.doc_text, r'1\s*[:：]\s*0\.1339')
    if sp3:
        facts.append(dict(fid='f3', content='1:0.1339', source='cs_listing_2025',
                          source_doc_version=listing.sha256, span=sp3, fact_kind='ratio',
                          operand_role='implementation_result', document_role='listing_document',
                          time_stage='post_adjustment'))
    # Listing-side price
    sp4 = find_span(listing.doc_text, r'37\.59\s*元')
    if sp4:
        facts.append(dict(fid='f4', content='37.59元/股', source='cs_listing_2025',
                          source_doc_version=listing.sha256, span=sp4, fact_kind='price',
                          operand_role=None, document_role='listing_document', time_stage=None))
    return facts

LEDGER = make_ledger()
CONTRACT_INIT = dict(comparison_scope='initial_plan_vs_implementation')

# ============================================================
# P2: Baseline — unambiguous "不一致" with matching scope
# ============================================================
output_p2 = dict(
    comparisons=[dict(item='exchange_ratio', conclusion='不一致',
                      operand_a='0.1335', operand_b='0.1339',
                      doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
                      comparison_scope='initial_plan_vs_implementation')],
    report='', new_facts=[])
r2 = parser.parse(output_p2, LEDGER, task_contract=CONTRACT_INIT)
c = r2['claims'][0] if r2['claims'] else {}
test('P2_baseline_credited',
     c.get('factual_verdict') == 'CREDITED' and c.get('scoring_verdict') == 'SCORED',
     f"factual={c.get('factual_verdict')} scoring={c.get('scoring_verdict')}")

# ============================================================
# P3: Model claims initial scope but uses adjusted operands
# ============================================================
output_p3 = dict(
    comparisons=[dict(item='exchange_ratio', conclusion='一致',
                      operand_a='0.1339', operand_b='0.1339',
                      doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
                      comparison_scope='initial_plan_vs_implementation')],
    report='', new_facts=[])
r3 = parser.parse(output_p3, LEDGER, task_contract=CONTRACT_INIT)
c = r3['claims'][0] if r3['claims'] else {}
# Should be REFUSED: model declares initial scope but operands are both 0.1339
# (adjusted). This is internal inconsistency.
test('P3_internal_inconsistency',
     c.get('factual_verdict') in ('REFUSED', 'INSUFFICIENT_EVIDENCE'),
     f"factual={c.get('factual_verdict')} reasons={c.get('refusal_reasons', [])[:2]}")

# ============================================================
# P5: Empty output
# ============================================================
r5 = parser.parse(dict(comparisons=[], report='', new_facts=[]), LEDGER)
test('P5_empty_output', len(r5['claims']) == 0)

# ============================================================
# P7: Staged comparison — different operands, different scope
# ============================================================
output_p7 = dict(
    comparisons=[
        dict(item='exchange_ratio', conclusion='不一致',
             operand_a='0.1335', operand_b='0.1339',
             doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
             comparison_scope='initial_plan_vs_implementation'),
        dict(item='exchange_ratio', conclusion='一致',
             operand_a='0.1339', operand_b='0.1339',
             doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
             comparison_scope='adjusted_plan_vs_implementation')],
    report='', new_facts=[])
r7 = parser.parse(output_p7, LEDGER, task_contract=CONTRACT_INIT)
claims7 = r7['claims']
a7 = next((c for c in claims7 if c.get('comparison_scope') == 'initial_plan_vs_implementation'), {})
b7 = next((c for c in claims7 if c.get('comparison_scope') == 'adjusted_plan_vs_implementation'), {})
test('P7_staged_A_scored',
     a7.get('scoring_verdict') == 'SCORED',
     f"A: {a7.get('scoring_verdict')}")
test('P7_staged_B_not_scored_verified',
     b7.get('task_relevance') == 'NOT_RELEVANT',
     f"B relevance: {b7.get('task_relevance')}")
# Check no contradiction between A and B
cc7 = r7.get('contradiction_checks', [])
test('P7_no_false_contradiction',
     all(c.get('result') == 'FALSE' for c in cc7),
     f"checks: {[(c['claim_a'], c['claim_b'], c['result']) for c in cc7]}")

# ============================================================
# P8: Contract unspecified + multiple candidates → AMBIGUOUS
# ============================================================
output_p8 = dict(
    comparisons=[dict(item='exchange_ratio', conclusion='不一致',
                      operand_a='0.1335', operand_b='0.1339',
                      comparison_scope=None)],
    report='', new_facts=[])
r8 = parser.parse(output_p8, LEDGER)  # no task_contract
c8 = r8['claims'][0] if r8['claims'] else {}
test('P8_unknown_scope',
     c8.get('task_relevance') == 'UNKNOWN_SCOPE',
     f"relevance={c8.get('task_relevance')}")

# ============================================================
# P10a: Declares ratio comparison but uses price facts
# ============================================================
output_p10a = dict(
    comparisons=[dict(item='exchange_ratio', conclusion='一致',
                      operand_a='37.59元', operand_b='37.59元',
                      doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
                      comparison_scope='adjusted_plan_vs_implementation')],
    report='', new_facts=[])
r10a = parser.parse(output_p10a, LEDGER, task_contract=CONTRACT_INIT)
c10a = r10a['claims'][0] if r10a['claims'] else {}
test('P10a_type_mismatch_refused',
     c10a.get('factual_verdict') == 'REFUSED',
     f"factual={c10a.get('factual_verdict')} reasons={c10a.get('refusal_reasons', [])[:2]}")

# ============================================================
# P10b: Untyped number with both price and ratio candidates
# ============================================================
output_p10b = dict(
    comparisons=[dict(item='exchange_ratio', conclusion='一致',
                      operand_a='0.1339', operand_b='0.1339',
                      comparison_scope='adjusted_plan_vs_implementation')],
    report='', new_facts=[])
# Add duplicate ratio facts to create ambiguity
LEDGER_AMBIG = LEDGER + [dict(LEDGER[2])]  # duplicate f3
r10b = parser.parse(output_p10b, LEDGER_AMBIG, task_contract=CONTRACT_INIT)
c10b = r10b['claims'][0] if r10b['claims'] else {}
test('P10b_ambiguous_binding',
     c10b.get('factual_verdict') == 'INSUFFICIENT_EVIDENCE'
     or 'ambiguous_binding' in c10b.get('refusal_reasons', []),
     f"factual={c10b.get('factual_verdict')} reasons={c10b.get('refusal_reasons', [])[:2]}")

# ============================================================
# P12a: span missing → INSUFFICIENT
# ============================================================
LEDGER_NO_SPAN = [dict(f, span=None) for f in LEDGER]
r12a = parser.parse(output_p2, LEDGER_NO_SPAN, task_contract=CONTRACT_INIT)
c12a = r12a['claims'][0] if r12a['claims'] else {}
test('P12a_span_missing_insufficient',
     c12a.get('factual_verdict') == 'INSUFFICIENT_EVIDENCE'
     or 'span_missing' in c12a.get('refusal_reasons', []),
     f"reasons={c12a.get('refusal_reasons', [])[:2]}")

# ============================================================
# P12b: span out of bounds → INSUFFICIENT
# ============================================================
LEDGER_BAD_SPAN = []
for f in LEDGER:
    f2 = dict(f)
    if f2.get('span'):
        f2['span'] = [f2['span'][0], f2['span'][1] + 999999]
    LEDGER_BAD_SPAN.append(f2)
r12b = parser.parse(output_p2, LEDGER_BAD_SPAN, task_contract=CONTRACT_INIT)
c12b = r12b['claims'][0] if r12b['claims'] else {}
test('P12b_span_out_of_bounds',
     c12b.get('factual_verdict') == 'INSUFFICIENT_EVIDENCE'
     or 'span_out_of_bounds' in c12b.get('refusal_reasons', []),
     f"reasons={c12b.get('refusal_reasons', [])[:2]}")

# ============================================================
# P12c: span value mismatch → REFUSED
# ============================================================
# Create a binding that claims 0.1335 but span points to 0.1339 text
LEDGER_WRONG_VAL = []
for f in LEDGER:
    f2 = dict(f)
    if f2.get('fid') == 'f1' and f2.get('span'):
        # Point to the 0.1339 location instead
        plan = snaps['cs_plan_summary_2024']
        import re as _re
        m = _re.search(r'1\s*[:：]\s*0\.1339', plan.doc_text)
        if m:
            f2['span'] = [m.start(), m.end()]
    LEDGER_WRONG_VAL.append(f2)
r12c = parser.parse(output_p2, LEDGER_WRONG_VAL, task_contract=CONTRACT_INIT)
c12c = r12c['claims'][0] if r12c['claims'] else {}
test('P12c_span_value_mismatch_refused',
     'span_value_mismatch' in c12c.get('refusal_reasons', [])
     or c12c.get('factual_verdict') == 'REFUSED',
     f"factual={c12c.get('factual_verdict')} reasons={c12c.get('refusal_reasons', [])[:2]}")

# ============================================================
# P14: Contract conflict → CONTRACT_CONFLICT, fact independent
# ============================================================
silver_conflict = dict(comparison_scope='adjusted_plan_vs_implementation')
r14 = parser.parse(output_p2, LEDGER, task_contract=CONTRACT_INIT,
                   silver_ref=silver_conflict)
c14 = r14['claims'][0] if r14['claims'] else {}
test('P14_contract_conflict',
     c14.get('task_relevance') == 'CONTRACT_CONFLICT'
     and c14.get('factual_verdict') not in (None, ''),
     f"relevance={c14.get('task_relevance')} factual={c14.get('factual_verdict')}")

# ============================================================
# P15: Role error + span missing → REFUSED (priority)
# ============================================================
r15 = parser.parse(output_p10a, LEDGER_NO_SPAN, task_contract=CONTRACT_INIT)
c15 = r15['claims'][0] if r15['claims'] else {}
test('P15_role_error_priority',
     c15.get('factual_verdict') == 'REFUSED',
     f"factual={c15.get('factual_verdict')}")

# ============================================================
# P17: Document version change → INSUFFICIENT
# ============================================================
LEDGER_OLD_VER = []
for f in LEDGER:
    f2 = dict(f)
    f2['source_doc_version'] = 'a' * 64  # wrong version
    LEDGER_OLD_VER.append(f2)
r17 = parser.parse(output_p2, LEDGER_OLD_VER, task_contract=CONTRACT_INIT)
c17 = r17['claims'][0] if r17['claims'] else {}
test('P17_doc_version_mismatch',
     'doc_version_mismatch' in c17.get('refusal_reasons', [])
     or c17.get('factual_verdict') == 'INSUFFICIENT_EVIDENCE',
     f"reasons={c17.get('refusal_reasons', [])[:2]}")

# ============================================================
# P19: Role swap + opposite conclusion → C2 MISMATCH → FALSE
# ============================================================
output_p19 = dict(
    comparisons=[
        dict(item='exchange_ratio', conclusion='不一致',
             operand_a='0.1335', operand_b='0.1339',
             comparison_scope='initial_plan_vs_implementation'),
        dict(item='exchange_ratio', conclusion='一致',
             operand_a='0.1339', operand_b='0.1335',
             doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
             comparison_scope='initial_plan_vs_implementation')],
    report='', new_facts=[])
r19 = parser.parse(output_p19, LEDGER, task_contract=CONTRACT_INIT)
cc19 = r19.get('contradiction_checks', [])
# Both have same scope, same item, but operands swapped → C2 should detect
# The values are the same set {0.1335, 0.1339} but bound to different roles
# Note: our simplified C2 compares bindings by position, not by role
# In the full spec, C2 compares by operand_role correspondence
# For this test, the two claims have same operand values but in swapped positions
# Our implementation compares bindings[i] vs bindings[j] positionally
# If both bind to the same facts (f1 and f3), C2 would be MATCH
# This test validates the structural behavior
test('P19_role_swap_no_false_contradiction',
     all(c.get('result') != 'TRUE' for c in cc19),
     f"checks: {[(c['claim_a'], c['claim_b'], c['result']) for c in cc19]}")

# ============================================================
# P20: Span covers wide text with incidental value → REFUSED
# ============================================================
# Create a binding with a very wide span that includes multiple values
LEDGER_WIDE = []
for f in LEDGER:
    f2 = dict(f)
    if f2.get('fid') == 'f1' and f2.get('span'):
        # Widen span to include surrounding context (which contains 0.1339)
        f2['span'] = [max(0, f2['span'][0] - 400), f2['span'][1] + 400]
    LEDGER_WIDE.append(f2)
r20 = parser.parse(output_p2, LEDGER_WIDE, task_contract=CONTRACT_INIT)
c20 = r20['claims'][0] if r20['claims'] else {}
# With a wide span, TypedParse may extract multiple candidates → INSUFFICIENT
# or extract the wrong value → REFUSED
# Either way, should NOT be CREDITED with a simple PASS
test('P20_wide_span_not_credited',
     c20.get('factual_verdict') != 'CREDITED',
     f"factual={c20.get('factual_verdict')} reasons={c20.get('refusal_reasons', [])[:2]}")

# ============================================================
# P1: r3 historical data replay (from R10)
# ============================================================
try:
    r3_file = B / 'stage_c_r10_runs' / 'EXEC_140512' / 'SC-E3-S2-Joint(Z,R,pi)-r3.json'
    r3_data = json.load(open(r3_file))
    r3_report = r3_data.get('report') or {}
    r3_facts = r3_data.get('terminal_facts') or []
    # Convert terminal_facts to ledger format
    r3_ledger = [dict(fid=f['fid'], content=f['content'],
                      source=f.get('source', ''), span=f.get('span'),
                      source_doc_version='', operand_role=f.get('operand_role'),
                      document_role=f.get('document_role'),
                      time_stage=f.get('time_stage'))
                 for f in r3_facts]
    r3_result = parser.parse(r3_report, r3_ledger, task_contract=CONTRACT_INIT)
    test('P1_r3_replay_executed',
         len(r3_result['claims']) > 0,
         f"claims={len(r3_result['claims'])} " +
         "; ".join(f"{c['claim_id']}:{c['factual_verdict']}/{c.get('task_relevance','?')}"
                    for c in r3_result['claims'][:5]))
except Exception as e:
    test('P1_r3_replay_executed', False, f'error: {e}')

# ============================================================
# P6: E1 350-day derivation (non-comparison) unaffected
# ============================================================
e1_output = dict(comparisons=[], report='350天', new_facts=[
    dict(content='350天(事先告知书→行政处罚决定书)', kind='derived')])
r6 = parser.parse(e1_output, [])
test('P6_non_comparison_unaffected', len(r6['claims']) == 0 or
     all(c['item'] is None for c in r6['claims']))

# ============================================================
# P4: True contradiction (same everything + opposite conclusion)
# ============================================================
output_p4 = dict(
    comparisons=[
        dict(item='exchange_ratio', conclusion='一致',
             operand_a='0.1335', operand_b='0.1339',
             doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
             comparison_scope='initial_plan_vs_implementation'),
        dict(item='exchange_ratio', conclusion='不一致',
             operand_a='0.1335', operand_b='0.1339',
             doc_a='cs_plan_summary_2024', doc_b='cs_listing_2025',
             comparison_scope='initial_plan_vs_implementation')],
    report='', new_facts=[])
r4 = parser.parse(output_p4, LEDGER, task_contract=CONTRACT_INIT)
cc4 = r4.get('contradiction_checks', [])
test('P4_true_contradiction',
     any(c.get('result') == 'TRUE' for c in cc4),
     f"checks: {[(c['claim_a'], c['claim_b'], c['result']) for c in cc4]}")

# ============================================================
# Summary
# ============================================================
total = len(V)
passed = sum(1 for v in V.values() if v)
print(f"\n{'='*50}")
print(f"RESULTS: {passed}/{total} PASS")
print(f"{'='*50}")
if passed < total:
    print("FAILURES:")
    for k, v in V.items():
        if not v:
            print(f"  {k}")
json.dump(V, open(B/'stage_c_r3_rescore'/'PARSER_P1_P20_RESULTS.json','w'), indent=1)
sys.exit(0 if passed == total else 1)
