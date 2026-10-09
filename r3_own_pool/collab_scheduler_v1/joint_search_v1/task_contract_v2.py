"""Task adaptation and scoring contract v2 (zero-call versioned fix).

PRESERVES original answer, scale, and derivation from TAT-QA source data,
replacing the lossy eval(derivation) conversion that dropped percent scale.

Contract v2 rules:
  R1  native_answer: the original TAT-QA answer string, stored verbatim
  R2  native_scale: the original TAT-QA scale field (e.g., 'percent', 'million')
  R3  raw_derivation: the original derivation expression string
  R4  derived_value: eval(raw_derivation) — the same computation as v1, kept
      for backward compatibility but NEVER used as gold when native_scale
      indicates a unit mismatch
  R5  gold: the primary scoring reference. Rules:
      - If native_scale == 'percent': gold = native_answer (the ORIGINAL
        percentage value, e.g., 517.5), NOT derived_value (e.g., 5.175)
      - If native_scale is None/empty/other: gold = derived_value (v1 behavior)
      - If native_answer and derived_value differ by ~100x AND scale is percent,
        this is a KNOWN conversion artifact — gold uses native_answer
  R6  rounding: scoring uses the existing close() tolerance (abs diff ≤
      max(1e-4, 1e-4*|gold|)), which handles floating-point noise; no
      additional rounding applied to gold or model output
  R7  output_unit: the model is prompted to output in the same unit as the
      original answer. The existing VPROMPT already says "percentages as
      ratios x100", which produces e.g., 517.5 for a percent answer. Under
      v2, this is the CORRECT behavior (matches native_answer).
  R8  conflicting derivation: if raw_derivation and native_answer disagree
      (e.g., different year's data), the conflict is RECORDED as
      `derivation_conflict=True`; gold uses native_answer (the original
      annotation takes precedence); the task is flagged for review but
      NOT excluded or modified

Old results frozen — no historical Q values modified. New gold values
only apply to future evaluations under this contract version.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from static_dag_v0.multidag_dynamic import close  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/task_contract_v2'
OUT.mkdir(exist_ok=True)

TATQA = ROOT / 'data/tatqa/tatqa_dataset_train.json'


def load_native_answers():
    """Load original TAT-QA answers with scale info."""
    rows = json.loads(TATQA.read_text())
    native = {}
    for para in rows:
        for q in para['questions']:
            uid = q['uid']
            d = (q.get('derivation') or '').strip()
            if q.get('answer_from') != 'table-text':
                continue
            if q.get('answer_type') != 'arithmetic' or not d \
                    or not re.search(r'[+\-*/]', d):
                continue
            native[uid] = dict(
                native_answer=q.get('answer'),
                native_scale=q.get('scale'),
                raw_derivation=d,
                para_uid=para.get('uid', ''))
    return native


def contract_v2_gold(native_answer, native_scale, raw_derivation):
    """Apply v2 gold selection rules."""
    try:
        derived = float(eval(raw_derivation, {'__builtins__': {}}, {}))
    except Exception:
        derived = None

    na = None
    try:
        na = float(native_answer)
    except (TypeError, ValueError):
        pass

    conflict = False
    if na is not None and derived is not None:
        ratio = abs(na / derived) if abs(derived) > 1e-12 else float('inf')
        if ratio > 50 or ratio < 0.02:  # ~100x mismatch
            conflict = True

    if native_scale == 'percent' and na is not None:
        gold = na
        gold_source = 'native_answer (percent scale)'
    elif na is not None and conflict:
        gold = na
        gold_source = 'native_answer (derivation conflict, native takes precedence)'
    elif derived is not None:
        gold = derived
        gold_source = 'derived_value (no scale conflict)'
    elif na is not None:
        gold = na
        gold_source = 'native_answer (derivation unparseable)'
    else:
        gold = None
        gold_source = 'UNRESOLVABLE'

    return dict(gold=gold, gold_source=gold_source,
                native_answer=na, derived_value=derived,
                native_scale=native_scale, raw_derivation=raw_derivation,
                derivation_conflict=conflict)


def upgrade_pool():
    """Generate v2 task pool with preserved native fields."""
    from static_dag_v0.multidag_dynamic import hybrid_pool, ctx_table, ctx_text
    native = load_native_answers()
    pool = hybrid_pool()  # v1 pool (for UIDs and basic filtering)
    upgraded = []
    changes = 0
    conflicts = 0
    for t in pool:
        uid = t['uid']
        nat = native.get(uid, {})
        v1_gold = t['answer']  # eval(derivation) from hybrid_pool
        v2 = contract_v2_gold(nat.get('native_answer'),
                              nat.get('native_scale'),
                              nat.get('raw_derivation', t['derivation']))
        if v2['gold'] != v1_gold:
            changes += 1
        if v2['derivation_conflict']:
            conflicts += 1
        upgraded.append(dict(
            uid=uid, question=t['question'], para=t['para'],
            derivation=t['derivation'],
            # v1 fields (frozen reference)
            v1_answer=v1_gold,
            # v2 fields (new contract)
            v2_gold=v2['gold'], v2_gold_source=v2['gold_source'],
            native_answer=v2['native_answer'],
            native_scale=v2['native_scale'],
            derived_value=v2['derived_value'],
            derivation_conflict=v2['derivation_conflict']))
    return upgraded, changes, conflicts


def run_tests():
    """Zero-call validation of the v2 contract."""
    checks = {}

    # T1: percent-scale task keeps native answer (not 100x-smaller derived)
    r1 = contract_v2_gold('517.5', 'percent', '(24.7-4)/4')
    checks['t1_percent_uses_native'] = r1['gold'] == 517.5
    checks['t1_percent_not_derived'] = r1['gold'] != 5.175
    checks['t1_conflict_detected'] = r1['derivation_conflict'] is True

    # T2: no-scale task uses derived (v1 compatible)
    r2 = contract_v2_gold('4.0', None, '1.5+2.5')
    checks['t2_no_scale_uses_derived'] = r2['gold'] == 4.0
    checks['t2_no_conflict'] = r2['derivation_conflict'] is False

    # T3: percent scale without conflict (derivation already in percent units)
    r3 = contract_v2_gold('25.0', 'percent', '20.0*1.25')
    checks['t3_percent_no_conflict'] = r3['gold'] == 25.0
    checks['t3_no_false_conflict'] = r3['derivation_conflict'] is False

    # T4: unparseable derivation falls back to native
    r4 = contract_v2_gold('123.0', None, 'garbage')
    checks['t4_unparseable_falls_back'] = r4['gold'] == 123.0

    # T5: scale the full pool
    upgraded, changes, conflicts = upgrade_pool()
    checks['t5_pool_nonempty'] = len(upgraded) > 0
    checks['t5_changes_counted'] = changes >= 0
    checks['t5_conflicts_counted'] = conflicts >= 0

    # T6: close() tolerance works with both gold conventions
    checks['t6_close_percent'] = close(517.5, 517.5) is True \
        or close(517.5, 517.5) == True
    checks['t6_close_derived'] = close(4.0, 4.00001) is True \
        or close(4.0, 4.00001) == True

    all_pass = bool(all(checks.values()))
    out = dict(
        contract='task_adaptation_and_scoring_v2',
        rules=dict(
            R1='native_answer stored verbatim from TAT-QA',
            R2='native_scale stored (percent/million/etc.)',
            R3='raw_derivation stored unmodified',
            R4='derived_value = eval(raw_derivation), backward compatible',
            R5='gold: percent scale → native_answer; no scale → derived; '
               'conflict → native takes precedence',
            R6='close() tolerance: abs diff ≤ max(1e-4, 1e-4*|gold|)',
            R7='model outputs in same unit as native answer',
            R8='derivation conflicts recorded, not hidden or excluded'),
        tests=checks, all_pass=all_pass,
        pool_stats=dict(
            total=len(upgraded), gold_changed=changes,
            derivation_conflicts=conflicts),
        frozen='v1 answers preserved as v1_answer; no historical Q modified',
        zero_model_calls=True)
    (OUT / 'CONTRACT_V2_TEST.json').write_text(json.dumps(out, indent=1))
    (OUT / 'POOL_V2_SAMPLE.json').write_text(json.dumps(
        upgraded[:10], indent=1, default=str))
    print(f'Pool: {len(upgraded)} tasks, {changes} gold changes, '
          f'{conflicts} derivation conflicts')
    print(json.dumps(checks, indent=1))
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run_tests()
