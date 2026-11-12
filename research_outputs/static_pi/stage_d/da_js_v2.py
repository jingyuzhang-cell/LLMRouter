#!/usr/bin/env python3
"""Deadline-Aware Joint Scheduling v2: corrected table + prior-based VoI probe policy.

Design facts grounding this version (RQ_DAJF_V1 + archives):
1. Single-shot signature diagnosis is IMPOSSIBLE for transient-vs-persistent: all
   prior batches injected identical truncation for both classes; only recurrence
   on retry differs. -> fault class is a hidden state; use a prior + online update.
2. With corrected estimates, on multi-branch merge nodes Z2 dominates the R probe
   in Q (0.545 vs 0.394) AND L (15s vs 35s); the probe wins only C. R is chosen
   only when Z2 is infeasible (call-scarce / deadline-tight / single-branch node).
3. The R probe, when taken, is an information action: its outcome updates the
   (model, node) persistence posterior used by later executions.

Objective (frozen): maximize expected terminal Q subject to (B_rem, D_rem)
feasibility, with EPSILON-DOMINANCE cost tie-break: among candidates within
EPS=0.02 expected-Q of the maximum, select min C, then min L.

Rationale: pure Q-first argmax would probe R even as p_transient->0 (R success-Q
0.394 > pi 0.334), i.e. burn 1 call + 35s on a near-doomed probe for a marginal
expected-Q gain. EPS-dominance makes the probe conditional: it is taken only when
its expected-Q edge exceeds EPS, which induces the analytic VoI threshold
(probe iff p_transient >~ 1/3) that W2 requires. On multi-branch merge nodes Z2
(0.545) beats the probe path by 0.151·p >= EPS for all p, so Z2 is selected
regardless of prior there ("prior-free decision").
"""
import json
from pathlib import Path as _P

TABLE = json.load(open(_P(__file__).parent / 'QCL_ESTIMATION_TABLE_V2.json'))
EPS = 0.02


class PersistencePosterior:
    """Beta(1,1) online posterior of P(transient) per (model, node_type).

    R success -> transient evidence; R failure -> persistent evidence.
    Z2/pi outcomes carry no class information (they never retry the faulted call).
    """

    def __init__(self, alpha=1.0, beta=1.0):
        self.alpha, self.beta = alpha, beta

    def p_transient(self):
        return self.alpha / (self.alpha + self.beta)

    def update(self, r_success: bool):
        if r_success:
            self.alpha += 1
        else:
            self.beta += 1


def _pi_q(current_model, node_type):
    key = 'qwen_to_ds' if current_model == 'qwen' else 'ds_to_qwen'
    return TABLE['LOCAL_pi']['Q_hat_by_direction'][key]


def candidates(D_rem_s, B_rem_calls, current_model='qwen', node_type='merge',
               p_transient=None, multi_branch=True):
    """Feasible candidates with expected Q/C/L under the persistence prior."""
    post = PersistencePosterior() if p_transient is None else None
    p = post.p_transient() if post else p_transient
    r_lat = TABLE['LOCAL_R']['L_hat_s']['ds' if current_model == 'deepseek' else 'qwen']
    pi_lat = TABLE['LOCAL_pi']['L_hat_s']['ds' if current_model == 'qwen' else 'qwen']
    z_lat = TABLE['Z2_split_R']['L_hat_s']['ds']
    pi_q = _pi_q(current_model, node_type)
    z_q = TABLE['Z2_split_R']['Q_hat']
    r_q = TABLE['LOCAL_R']['Q_hat']

    cands = [{'action': 'NONE', 'Q': 0.0, 'C': 0, 'L': 0}]

    # direct pi (works for both classes)
    if B_rem_calls >= 1 and D_rem_s >= pi_lat:
        cands.append({'action': 'LOCAL_pi', 'Q': pi_q * 1.0, 'C': 1, 'L': pi_lat})

    # direct Z2 (multi-branch nodes only)
    if multi_branch and B_rem_calls >= 3 and D_rem_s >= z_lat:
        cands.append({'action': 'Z2_split_R', 'Q': z_q, 'C': 3, 'L': z_lat})

    # R probe path: probe, then escalate to best persistent recovery on failure.
    # Feasibility requires headroom for the worst case (probe + escalation).
    esc_q, esc_c, esc_lat = (z_q, 3, z_lat) if (multi_branch and B_rem_calls - 1 >= 3) \
        else (pi_q, 1, pi_lat)
    if B_rem_calls >= 1 + esc_c and D_rem_s >= r_lat + esc_lat:
        cands.append({
            'action': 'R_PROBE_THEN_ESCALATE', 'C': 1 + (1 - p) * esc_c,
            'L': r_lat + (1 - p) * esc_lat,
            'Q': p * r_q + (1 - p) * esc_q, 'p_transient': round(p, 3)})

    return cands


def decide_v2(D_rem_s, B_rem_calls, current_model='qwen', node_type='merge',
              p_transient=0.5, multi_branch=True):
    """Select recovery action. Returns dict(selected, reason, candidates, p)."""
    cands = candidates(D_rem_s, B_rem_calls, current_model, node_type,
                       p_transient, multi_branch)
    qmax = max(c['Q'] for c in cands)
    front = [c for c in cands if c['Q'] >= qmax - EPS]
    best = min(front, key=lambda c: (c['C'], c['L']))
    return {'selected': best['action'], 'p_transient': p_transient,
            'reason': f'eps-front(Q>={qmax - EPS:.3f}) min-C -> {best["action"]} '
                      f'(E[Q]={best["Q"]:.3f} C={best["C"]:.2f} L={best["L"]:.0f}s)',
            'candidates': cands}


def policy_map(d_grid=(8, 12, 16, 20, 40, 60, 100, 200),
               b_grid=(1, 2, 3, 5, 30), p_grid=(0.0, 0.33, 0.5, 0.67, 1.0)):
    """Zero-call sensitivity artifact: selected action over (D_rem, B_rem, p)."""
    out = {}
    for p in p_grid:
        rows = {}
        for b in b_grid:
            rows[f'B={b}'] = {f'D={d}': decide_v2(d, b, p_transient=p)['selected']
                              for d in d_grid}
        out[f'p={p}'] = rows
    return out


if __name__ == '__main__':
    # Regression: V1 realized scenarios
    tests = [
        # (D_rem, B_rem, p, expected, label)
        (188, 140, 0.5, 'Z2_split_R', 'V1 persistent escalate point (was R-probe in v1)'),
        (8, 140, 0.5, 'LOCAL_pi', 'very tight deadline: only pi fits'),
        (60, 2, 0.8, 'R_PROBE_THEN_ESCALATE', 'call-scarce + transient-dominant prior'),
        (60, 2, 0.2, 'LOCAL_pi', 'call-scarce + persistent prior: skip doomed probe'),
        (60, 2, 0.5, 'R_PROBE_THEN_ESCALATE', 'call-scarce + uncertain prior: probe allowed'),
        (60, 2, 0.3, 'LOCAL_pi', 'VoI boundary p=0.30 (<~1/3): skip'),
        (60, 2, 0.4, 'R_PROBE_THEN_ESCALATE', 'VoI boundary p=0.40 (>~1/3): probe'),
        (16, 30, 1.0, 'Z2_split_R', 'even p=1.0: Z2 wins Q by 0.151 (>EPS)'),
        (10, 30, 0.5, 'LOCAL_pi', 'Z2 infeasible at D=10'),
        (200, 1, 0.5, 'LOCAL_pi', 'only 1 call left'),
        (200, 0, 0.5, 'NONE', 'no budget'),
    ]
    ok = 0
    for d, b, p, exp, label in tests:
        got = decide_v2(d, b, p_transient=p)['selected']
        status = 'PASS' if got == exp else 'FAIL'
        ok += got == exp
        print(f'[{status}] {label:55} -> {got}')
    # single-branch node: Z2 undefined -> posterior decides probe vs pi
    for p, exp in ((0.9, 'R_PROBE_THEN_ESCALATE'), (0.2, 'LOCAL_pi')):
        got = decide_v2(200, 30, p_transient=p, multi_branch=False)['selected']
        ok += got == exp
        print(f"[{'PASS' if got == exp else 'FAIL'}] "
              f"{'single-branch node, p=' + str(p):55} -> {got}")
    print(f'\n{ok}/{len(tests) + 2} passed')
    print('\npolicy map (p=0.5):')
    print(json.dumps(policy_map()['p=0.5'], indent=0))
