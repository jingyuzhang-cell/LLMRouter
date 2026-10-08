"""P2 executor audit: successor-refresh defect + latency calculation issues (zero calls).

Identifies and documents the two issues the paper-review report flagged in
fault30_run.py, in preparation for P2 protocol design.
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/p2_executor_audit'
OUT.mkdir(parents=True, exist_ok=True)

src = (ROOT / 'collab_scheduler_v1/fault30_run.py').read_text()

issues = {}

# Issue 1: successor-refresh defect
# R2 fires r-refresh when ANY e-fb key exists — but it doesn't check whether
# the e-fb actually CHANGED the facts (an fb that returned the same facts
# shouldn't trigger downstream re-execution)
issues['successor_refresh'] = dict(
    location='fault30_run.py:283-298 (R2 stage) and :331-345 (V2 stage)',
    description=(
        'R2 triggers r-refresh when any ":fb" key exists in the task\'s key list. '
        'However, it does NOT check whether the fb call actually produced '
        'DIFFERENT facts than the original e-call. If an fb reroute returns '
        'identical facts (e.g., the alternate model extracts the same values), '
        'the r node is still re-executed unnecessarily, wasting calls. More '
        'critically, if the fb is INEFFECTIVE (same model = same persistent '
        'fault), the "refreshed" r sees the same empty facts and may produce '
        'the same wrong output, but the code treats it as a fresh execution.'),
    impact=(
        'Unnecessary r/v re-executions inflate C and L for LOCAL_REROUTE arms. '
        'Ineffective fb reroutes create phantom "refresh" stages. '
        'The fault30 analyzer already accounts for this via paired analysis, '
        'but the P2 protocol should add an explicit facts-changed check.'),
    fix_proposal=(
        'Add a facts-comparison check before R2: only trigger r-refresh if '
        'parse_facts_safe(fb_answer) != parse_facts_safe(original_answer). '
        'Same for V2: only v-refresh if the r output (expression) actually changed.'),
    severity='medium',
)

# Issue 2: latency calculation
# Line 391-392: l = max(lats) + sum(rkeys) + sum(vkeys)
# This sums ALL r-keys (including esc/fbd) and ALL v-keys serially, which
# assumes all recovery calls happen sequentially on the critical path.
# But e-fb recovery happens in PARALLEL with the other e node's first execution.
# The max(lats) correctly takes max of e-latencies, but the r/v sums include
# ALL retries serially even when they may have been conceptually parallel.
issues['latency_calculation'] = dict(
    location='fault30_run.py:368-395 (scoring section)',
    description=(
        'The critical-path L calculation is: '
        'l = max(e_lats) + sum(all_r_keys) + sum(all_v_keys). '
        'Issues: (1) sum(all_r_keys) includes the ORIGINAL r call plus ALL '
        'recovery r calls (fbd, esc) as if they were sequential — but the '
        'original r call is superseded by the esc call, so only the LAST '
        'successful r call plus the failed attempts should be on the critical '
        'path. (2) sum(all_v_keys) has the same issue with v-fbd and v-esc. '
        '(3) In practice, all calls execute serially (single GPU), so '
        'wall-clock IS the sum — but the "critical-path" label is misleading '
        'if it includes superseded calls.'),
    impact=(
        'L is inflated for recovery arms (counts superseded calls on the '
        'critical path). The absolute L values for LOCAL_REROUTE are '
        'overestimates of what a truly parallel execution would achieve. '
        'However, for the SERIAL execution used in P2, this equals wall-clock '
        'minus inter-call gaps, so it is a valid upper bound.'),
    fix_proposal=(
        'Option A (honest serial): rename to "serial_execution_L" and note it '
        'includes all attempts. Option B (true critical path): only count the '
        'LAST r key and LAST v key on the path, with earlier attempts as '
        '"wasted time" reported separately. P2 protocol should use Option A '
        'since execution is actually serial on a single GPU.'),
    severity='low-medium',
)

# Issue 3 (new finding): fb target vs fault model
# The e-fb reroute (stage E in LOCAL_REROUTE) tries coder first, then medium.
# But if the fault model IS large (the planned model), rerouting to coder/medium
# is correct (different model escapes the fault). However, if the fault model
# is coder or medium, the fb may reroute to the SAME model (ineffective).
issues['fb_target_effectiveness'] = dict(
    location='fault30_run.py:260-282 (E stage)',
    description=(
        'e-fb memory rule: first failure → coder, subsequent → medium. '
        'If the planned e model is ALREADY coder or medium, the fb target '
        'may be the same model, making the reroute ineffective (persistent '
        'fault survives). The code handles this implicitly (the answer is '
        'the same failing text), but does not log it as "ineffective_reroute".'),
    impact='Ineffective reroutes consume budget without recovery benefit.',
    fix_proposal='Add an explicit ineffective_reroute marker to the task log.',
    severity='low',
)

report = dict(
    audit_target='collab_scheduler_v1/fault30_run.py',
    issues=issues,
    recommendation=(
        'All three issues are documentation/accuracy improvements, not '
        'blocking defects. The successor-refresh issue (medium) should be '
        'fixed before P2 to avoid inflating recovery-arm costs. The latency '
        'labeling issue should be resolved by renaming to serial_execution_L. '
        'The fb-target issue is minor and can be logged for awareness.'),
    p2_protocol_impact=(
        'P2 should: (1) add facts-changed check before descendant refresh, '
        '(2) use serial_execution_L as the honest latency metric, '
        '(3) log ineffective reroutes explicitly. These are protocol-level '
        'fixes that do not change the DAG Patch mechanism verified in P1-B.'),
)

(OUT / 'P2_EXECUTOR_AUDIT.json').write_text(json.dumps(report, indent=1))
print(json.dumps({k: dict(severity=v['severity'], location=v['location'][:40])
                  for k, v in issues.items()}, indent=1))
print('recommendation:', report['recommendation'][:100])
