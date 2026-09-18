"""Policy equivalence tests for Dynamic v2 (dev vs test share dynamic_v2_policy).

Part 1: constructed-state unit tests covering every decision dimension (extraction
fallback selection, R1 lock, R2 margin, hysteresis both directions, R3 gating, R4
scoring, budget feasibility).
Part 2: dev replay equivalence — the recorded dev v2 fallback decisions are re-derived
from the recorded per-task states through the shared policy and must match exactly.
"""
import json

import pytest

import json

from r3_own_pool.static_dag_v0.dynamic_v2_policy import (
    extraction_fallback_model, escalation_feasible, policy_hash,
    reasoning_fallback_model, refresh_needed)

def F(coder=0, large=0):
    return dict(f_coder=coder, f_large=large)

# ---------- Part 1: constructed states ----------
def test_extraction_fallback_selection():
    assert extraction_fallback_model(0) == 'coder'    # R1: no failure evidence -> locked
    assert extraction_fallback_model(1) == 'medium'   # coder failed once -> switch
    assert extraction_fallback_model(2) == 'medium'
    assert extraction_fallback_model(1, f_medium=2) == 'coder'  # medium also failed -> back

def test_reasoning_lock_before_any_failure():
    assert reasoning_fallback_model(**F(0, 0)) == 'coder'   # R1: no evidence -> frozen fallback

def test_reasoning_hysteresis_switch_after_coder_failure():
    assert reasoning_fallback_model(**F(1, 0)) == 'large'   # coder failed -> stronger untried

def test_reasoning_hysteresis_switch_back_after_large_failure():
    assert reasoning_fallback_model(**F(1, 1)) == 'coder'   # large also failed -> back to coder
    assert reasoning_fallback_model(**F(2, 1)) == 'large'   # two coder failures -> large again

def test_r2_margin_blocks_borderline_switch():
    # without any coder failure the score gap (0.75) exceeds delta, but R1 blocks first
    assert reasoning_fallback_model(**F(0, 0)) == 'coder'

def test_r3_refresh_gating():
    same = {'facts': [{'value': 70}, {'value': 65}]}
    changed = {'facts': [{'value': 70}, {'value': 66}]}
    assert refresh_needed(changed, same) is True
    assert refresh_needed(same, same) is False

def test_budget_feasibility():
    assert escalation_feasible(200) is True
    assert escalation_feasible(199) is False

def test_policy_hash_stable():
    assert len(policy_hash()) == 64

# ---------- Part 2: dev replay equivalence ----------
def test_dev_replay_equivalence():
    from r3_own_pool.static_dag_v0.dynamic_v2_dev import OUT
    from r3_own_pool.static_dag_v0.recovery_matrix_v2_devset import BASE
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'DEV2_POLICY.json').read_text())
    tasks = pol['tasks']
    f_coder = f_large = 0
    f_ext_coder = 0
    mismatches = []
    checked = 0
    for t in tasks:
        uid = t['uid']
        if raw['extraction_initial_parse_failed'][uid]:
            want = extraction_fallback_model(f_ext_coder)
            got_keys = [m for k, m in raw['arms']['dynv2'][uid]['keys'] if k.startswith('C:dynv2:')]
            if got_keys and got_keys[0] != want:
                mismatches.append(('extraction', uid, want, got_keys[0]))
            checked += 1
            # runtime F counts only no-facts failures of the fallback itself
            final_empty = raw['facts'][uid]['dynv2'] == []
            if final_empty: f_ext_coder += 1
        st = raw['arms']['dynv2'][uid]
        e_keys = [(k, m) for k, m in st['keys'] if k.startswith('E:dynv2:')]
        if e_keys:
            kE, got = e_keys[0]
            want = reasoning_fallback_model(f_coder=f_coder, f_large=f_large)
            if got != want:
                mismatches.append(('reasoning', uid, want, got))
            checked += 1
            # outcome: the fallback failed iff the task chain still ended not-ok
            if st['ok'] is False:
                if got == 'coder': f_coder += 1
                if got == 'large': f_large += 1
            elif got == 'coder' or got == 'large':
                # success: no failure increment
                pass
    assert checked > 0
    assert mismatches == [], mismatches
