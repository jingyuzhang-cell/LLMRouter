"""Frozen scoring contract v2.1: unit conversion + rounding + evaluator integration.

Freezes the scoring rules so rounding_compatible and close() are ALIGNED:
  close(a, b) = |a-b| ≤ max(1e-4, 1e-4*|b|)  — primary
  rounding_ok(a, b) = |round(a,2) - round(b,2)| ≤ 0.01  — 2dp rounding from TAT-QA spec
  score(a, gold) = close(a, gold) OR rounding_ok(a, gold)

This means 1.0274 vs 1.03 now PASSES (rounding_ok: round(1.0274,2)=1.03 == round(1.03,2)=1.03).
And -38.5 vs -38.54 also PASSES (rounding_ok: -38.5 vs -38.54 → round both to 2dp: -38.5 vs -38.54 → diff=0.04 > 0.01... wait: round(-38.5,2)=-38.5, round(-38.54,2)=-38.54, diff=0.04. So NOT rounding_ok.

Actually the correct 2dp rule: if |a-b| ≤ 0.01 (one unit in the last reported place at 2dp). -38.5 vs -38.54: |diff|=0.04 > 0.01 → NOT rounding compatible. The model output -38.5 is imprecise by more than 2dp rounding.

Revised rounding_ok: |a - b| ≤ 0.01 + 1e-6 (absolute tolerance for 2-decimal-place rounding).

Fixtures verify: percent, rounding, negative, parse failure, boundary cases.
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2'
OUT.mkdir(exist_ok=True)


# ==== Frozen scoring rules (v2.1) ====
def close_v21(a, b):
    """Primary tolerance: relative + absolute floor."""
    if a is None or b is None:
        return False
    return abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def rounding_ok_v21(a, b):
    """2-decimal-place rounding compatibility (from TAT-QA financial spec).
    |a-b| ≤ 0.01 means the values agree to within one unit in the last
    significant digit at the data's native 2dp precision."""
    if a is None or b is None:
        return False
    return abs(a - b) <= 0.01 + 1e-6


def score_v21(model_answer, gold):
    """Unified scoring: close OR rounding_ok."""
    return close_v21(model_answer, gold) or rounding_ok_v21(model_answer, gold)


# ==== Unit conversion (from contract v2) ====
def resolve_gold(native_answer, native_scale, raw_derivation):
    """Apply v2 gold resolution (bidirectional unit check)."""
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import contract_v2_gold
    return contract_v2_gold(native_answer, native_scale, raw_derivation)


# ==== Independent fixtures (zero calls) ====
FIXTURES = [
    # (name, model_answer, gold, expected_score, comment)
    ('exact_match', 4.0, 4.0, True, 'identical values'),
    ('percent_scale', 517.5, 517.5, True, 'percent value matches native'),
    ('percent_ratio_wrong', 5.175, 517.5, False, 'ratio vs percent — should fail'),
    ('rounding_2dp_ok', 1.0274, 1.03, True, 'within 2dp rounding (0.0026 diff)'),
    ('rounding_2dp_fail', 1.05, 1.10, False, 'beyond 2dp rounding (0.05 diff)'),
    ('negative_exact', -38.54, -38.54, True, 'negative exact'),
    ('negative_rounding', -38.5, -38.54, False, '0.04 diff > 0.01 — NOT 2dp rounding'),
    ('negative_rounding_ok', -38.53, -38.54, True, '0.01 diff = 2dp boundary'),
    ('close_relative', 1000.0, 1000.05, True, 'relative tolerance at scale'),
    ('none_answer', None, 5.0, False, 'unparseable model answer'),
    ('zero_vs_nonzero', 0.0, 0.001, True, 'within absolute tolerance'),
    ('large_percent', 300.0, 300.0, True, 'large percent exact'),
    ('percent_negative', -25.0, -25.0, True, 'negative percent'),
    ('small_diff', 0.8969, 0.9, True, '0.0031 diff — 2dp rounding'),
    ('boundary_01', 1.0099, 1.01, True, '0.0001 diff — well within rounding'),
    ('boundary_011', 1.0, 1.011, False, '0.011 diff — beyond both close and rounding tolerance'),
]


def run_fixtures():
    checks = {}
    for name, ma, gold, expected, comment in FIXTURES:
        got = score_v21(ma, gold)
        checks[name] = got == expected
        status = 'PASS' if got == expected else 'FAIL'
        print(f'  {name:22s}: score({ma}, {gold})={got} '
              f'expected={expected} [{status}] — {comment}')
    return checks


def version_search8_test16():
    """Version-label SEARCH8/TEST16 without generating performance results."""
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        contract_v2_gold, load_native_answers)
    native = load_native_answers()

    # SEARCH8 / TEST16 task UIDs would come from their respective freeze files
    # For now, record that they are versioned under contract v2.1
    # without scoring or filtering
    out = dict(
        search8=dict(
            status='LABELS_VERSIONED_UNDER_V2.1',
            note='labels versioned; no performance results generated; '
                 'no task filtering based on changes'),
        test16=dict(
            status='LABELS_VERSIONED_UNDER_V2.1',
            note='labels versioned; no performance results generated; '
                 'no task filtering based on changes'),
        contract_version='v2.1',
        scoring_rules=dict(
            primary='close_v21: |a-b| <= max(1e-4, 1e-4*|b|)',
            rounding='rounding_ok_v21: |a-b| <= 0.01 + 1e-6',
            unified='score_v21 = close_v21 OR rounding_ok_v21',
            source='TAT-QA 2dp financial data spec'))
    return out


def integrate_into_evaluator():
    """Document how v2.1 integrates into the formal JointEvaluator scoring path."""
    integration = dict(
        file='collab_scheduler_v1/joint_search_v1/evaluator.py',
        function='_evaluate → final quality check',
        current='uses close() from multidag_dynamic',
        v21_change='replace close() with score_v21() in the final quality check',
        gold_source='v2 contract gold (native_answer for percent; derived for no-scale)',
        old_behavior='close(model_val, eval(derivation)) — v1 gold, v1 tolerance',
        new_behavior='score_v21(model_val, resolve_gold(native, scale, derivation).gold)',
        search8_test16='versioned labels; evaluator uses v2.1 when scoring these panels',
        breaking_change='yes — historical Q values computed under v1 are frozen; '
                        'new evaluations use v2.1; results not comparable across versions')
    return integration


def run():
    print('=== Scoring Contract v2.1 Fixtures ===\n')
    checks = run_fixtures()
    all_pass = all(checks.values())

    search8_test16 = version_search8_test16()
    integration = integrate_into_evaluator()

    out = dict(
        contract='scoring_contract_v2.1',
        rules=dict(
            primary='close_v21(a,b) = |a-b| <= max(1e-4, 1e-4*|b|)',
            rounding='rounding_ok_v21(a,b) = |a-b| <= 0.01 + 1e-6 (from TAT-QA 2dp spec)',
            unified='score_v21(a, gold) = close_v21(a,gold) OR rounding_ok_v21(a,gold)',
            unit_conversion='bidirectional percent check (from v2)'),
        fixtures=dict(
            total=len(FIXTURES), passed=sum(checks.values()),
            failed=len(FIXTURES) - sum(checks.values()),
            details={name: 'PASS' if ok else 'FAIL' for name, ok in checks.items()}),
        search8_test16=search8_test16,
        evaluator_integration=integration,
        all_pass=all_pass,
        zero_model_calls=True)
    (OUT / 'SCORING_CONTRACT_V21.json').write_text(json.dumps(out, indent=1))
    print(f'\nFixtures: {sum(checks.values())}/{len(checks)} PASS')
    print(f'{"ALL PASS — CONTRACT v2.1 FROZEN" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
