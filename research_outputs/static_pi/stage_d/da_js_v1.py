
#!/usr/bin/env python3
"""Deadline-Aware Joint Scheduling v1: Candidate-action search + Q/C/L selection.

Decision rule (frozen):
1. Detect anomaly type: transient (retry may work) vs persistent (same model will fail again)
2. Generate feasible candidates: {NONE, LOCAL_R, LOCAL_pi, Z2_split_R}
3. Filter by constraints: C_hat <= B_rem AND L_hat <= D_rem
4. Among feasible, select argmax Q_hat; tie-break by min C, then min L
5. If anomaly type unknown, treat as transient first (optimistic), escalate to persistent after R fails
"""
import json

from pathlib import Path as _P
TABLE = json.load(open(_P(__file__).parent / 'QCL_ESTIMATION_TABLE_V1.json'))

def decide(anomaly_type, D_rem_s, B_rem_calls, current_model='qwen', node_type='merge'):
    """Return the optimal action given current execution state.

    Args:
        anomaly_type: 'none' | 'transient' | 'persistent'
        D_rem_s: remaining deadline in seconds
        B_rem_calls: remaining budget in calls
        current_model: model that failed ('qwen' or 'deepseek')
        node_type: type of failed node
    Returns:
        dict with selected action, expected Q/C/L, and all feasible candidates
    """
    candidates = []

    # NONE: keep current output. Q_hat depends on whether anomaly degraded the output.
    # If anomaly exists and node output is empty/degraded, NONE Q_hat = degraded_q (typically 0)
    # If no anomaly, NONE Q_hat = natural baseline Q
    none_q = TABLE['NONE']['Q_hat'] if anomaly_type == 'none' else 0.0
    candidates.append({
        'action': 'NONE', 'Q_hat': none_q,
        'C_hat': 0, 'L_hat': 0, 'expected_Q': none_q,
        'note': 'accept current output'
    })

    if anomaly_type == 'none':
        return {'selected': 'NONE', 'reason': 'no anomaly', 'candidates': candidates}

    # R: same-model retry
    r_lat = TABLE['LOCAL_R']['L_hat_s'].get(
        'ds' if current_model == 'deepseek' else 'qwen', 10)
    r_success = TABLE['LOCAL_R']['success_rate'].get(anomaly_type, 0)
    if r_success > 0 and B_rem_calls >= 1 and D_rem_s >= r_lat:
        candidates.append({
            'action': 'LOCAL_R',
            'Q_hat': TABLE['LOCAL_R']['Q_hat'],
            'C_hat': 1, 'L_hat': r_lat,
            'success_rate': r_success,
            'expected_Q': TABLE['LOCAL_R']['Q_hat'] * r_success
        })

    # π: model switch
    pi_lat = TABLE['LOCAL_pi']['L_hat_s'].get(
        'ds' if current_model == 'qwen' else 'qwen', 10)
    # Switch model: if current is qwen, fallback is ds (and vice versa)
    if B_rem_calls >= 1 and D_rem_s >= pi_lat:
        candidates.append({
            'action': 'LOCAL_pi',
            'Q_hat': TABLE['LOCAL_pi']['Q_hat'],
            'C_hat': 1, 'L_hat': pi_lat,
            'success_rate': TABLE['LOCAL_pi']['success_rate'].get(anomaly_type, 0),
            'expected_Q': TABLE['LOCAL_pi']['Q_hat'] *
                TABLE['LOCAL_pi']['success_rate'].get(anomaly_type, 0)
        })

    # Z2: structural split
    z_lat = TABLE['Z2_split_R']['L_hat_s'].get('ds', 15)
    if B_rem_calls >= 3 and D_rem_s >= z_lat:
        candidates.append({
            'action': 'Z2_split_R',
            'Q_hat': TABLE['Z2_split_R']['Q_hat'],
            'C_hat': 3, 'L_hat': z_lat,
            'success_rate': TABLE['Z2_split_R']['success_rate'].get(anomaly_type, 0),
            'expected_Q': TABLE['Z2_split_R']['Q_hat'] *
                TABLE['Z2_split_R']['success_rate'].get(anomaly_type, 0)
        })

    # Filter feasible (already filtered by construction)
    # Select: argmax expected_Q, tie-break min C, then min L
    best = max(candidates, key=lambda c: (c.get('expected_Q', c['Q_hat']), -c['C_hat'], -c['L_hat']))

    # If R is feasible but π gives higher expected_Q, and we have budget for both,
    # recommend R first (cheaper probe) then escalate
    if anomaly_type == 'transient' and best['action'] != 'LOCAL_R':
        r_cand = next((c for c in candidates if c['action'] == 'LOCAL_R'), None)
        if r_cand and B_rem_calls >= 2:
            # Try R first; if fails, escalate
            return {
                'selected': 'LOCAL_R',
                'fallback': best['action'],
                'reason': 'transient: try cheap R first, escalate to {} if R fails'.format(best['action']),
                'candidates': candidates
            }

    return {
        'selected': best['action'],
        'reason': f'argmax expected_Q={best.get("expected_Q", best["Q_hat"]):.3f} among {len(candidates)} feasible',
        'candidates': candidates
    }
