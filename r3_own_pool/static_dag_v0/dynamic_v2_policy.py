"""Dynamic v2 scheduling policy — the single source of truth.

This module encapsulates the decisions that were ACTUALLY in effect during the dev
iteration (dynamic_v2_dev.py) and is the ONLY implementation allowed in any test run
(dev and test must import these functions; no policy logic may be duplicated).

Rules (frozen; iteration closed):
R1 positive-evidence lock: the frozen second-best fallback (coder) is kept unless it has
   accumulated at least one failure (F>=1) in the current run — failure memory may not
   override a choice with no failure evidence.
R2 switch margin: a switch additionally requires score(alt) > score(cur) + delta.
R3 affected-descendant gating: a recovered upstream output triggers a successor refresh
   only if the recovered fact values materially differ from the failed attempt's.
R4 capability-profile scoring: score(m) = rank(type, m) - gamma * failures(m), with frozen
   ranks from the node benchmark (reasoning: medium 1.0 > coder 0.75 > large 0.0;
   extraction: large 1.0 > coder 0.5 > medium 0.0), gamma = 1.0, delta = 0.1.
Extraction fallback: coder is locked (R1) unless coder itself has accumulated an
extraction-fallback failure (F>=1), in which case it switches to medium — same
positive-evidence lock and hysteresis structure as the reasoning fallback.
Hysteresis note: the coder->large switch branch is part of the dev-frozen policy but its
switch path was never exercised by dev data (dev coder fallbacks all succeeded); it is
retained as defined, with this limitation recorded.
"""
import hashlib

GAMMA = 1.0
DELTA = 0.1
MIN_CALL_TOKENS = 200
RANK = {'reasoning': {'medium': 1.0, 'coder': 0.75, 'large': 0.0},
        'extraction': {'large': 1.0, 'coder': 0.5, 'medium': 0.0}}
FROZEN_FALLBACK = {'reasoning': 'coder', 'extraction': 'coder'}

def policy_hash():
    return hashlib.sha256(open(__file__, 'rb').read()).hexdigest()

def extraction_fallback_model(f_coder, f_medium=0):
    """R1+R4 (extraction): coder locked until it fails; then medium by score hysteresis."""
    s_coder = RANK['extraction']['coder'] - GAMMA * f_coder
    s_medium = RANK['extraction']['medium'] - GAMMA * f_medium
    if f_coder >= 1 and s_medium > s_coder + DELTA:
        return 'medium'
    return FROZEN_FALLBACK['extraction']

def refresh_needed(recovered_facts, failed_facts):
    """R3: is the recovered output materially different from the failed attempt's?"""
    old = sorted(f['value'] for f in failed_facts['facts'])
    new = sorted(f['value'] for f in recovered_facts['facts'])
    return old != new

def reasoning_fallback_model(f_coder, f_large):
    """R1+R2+R4: frozen fallback coder, locked until it fails; switch to large only when
    coder has failed and score(large) > score(coder) + delta (hysteresis, both ways)."""
    s_coder = RANK['reasoning']['coder'] - GAMMA * f_coder
    s_large = RANK['reasoning']['large'] - GAMMA * f_large
    if f_coder >= 1 and s_large > s_coder + DELTA:
        return 'large'
    return FROZEN_FALLBACK['reasoning']

def escalation_feasible(remaining_budget):
    """Budget feasibility for one escalation call (frozen floor)."""
    return remaining_budget >= MIN_CALL_TOKENS
