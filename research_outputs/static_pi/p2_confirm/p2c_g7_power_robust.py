#!/usr/bin/env python3
"""G7 robust power simulation (zero-call) — operator-mandated additions before freezing n.
Semantics (v2, corrected):
- rho = ELIMINATION probability of G6 mismatches under G7 (rho=1.0 -> complete elimination);
  heterogeneous scenario: rho_i = 1.0 on a random 60% of tasks, 0.0 on the rest.
- mismatch primary endpoint: shared-failed reps are NOT evaluable -> both-fail tasks excluded
  (runtime G-9 semantics: no terminal to cite); rate diff per task = (m6 - m7) / stage-sensitive slots.
- Q_all non-inferiority: P2-C M3 semantics -> shared-fail reps score 0 for both arms,
  so per-task dQ is multiplied by rep-survival fraction (zero-dilution, consistent with P2-C primary tests).
- Q gain model: 38/40 G6 mismatch facts are LOC_WRONG (value correct, citation wrong) ->
  each eliminated mismatch converts to TP with factor c_conv*F_LW; over-suppression eps_q on
  clean slots removes facts (Q loss); task noise sigma (0.104 = G6-G5 task-diff SD, conservative).
Output: p2c_analysis/P2C_G7_POWER_ROBUST.json"""
import json
import numpy as np
from pathlib import Path

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
rng = np.random.default_rng(20261110)
B = json.loads((HERE / 'p2c_analysis/P2C_G7_ENDPOINT_BASELINE.json').read_text())

tasks = []
for t, reps in B['baseline'].items():
    ok = [r for r in reps.values() if r.get('state') == 'ok']
    if not ok:
        continue
    sens = ok[0]['n_stage_sensitive']
    m6 = np.mean([r['mismatch']['G6'] for r in ok])
    tasks.append((sens, m6, ok[0]['N']))
tasks = np.array(tasks, float)
K = len(tasks)
F_LW = 38 / 40
B_SIM, FLIPS = 2500, 400


def power(n, b, rho, hetero, delta, c_conv, eps_q, sigma, margin):
    rej = ni = joint = 0
    for _ in range(B_SIM):
        idx = rng.integers(0, K, n)
        sens, m6b, Nb = tasks[idx].T
        m6 = rng.binomial(sens.astype(int), np.clip(b * m6b / np.maximum(sens, 1), 0, 1))
        rho_i = np.where(rng.random(n) < 0.6, 1.0, 0.0) if hetero else np.full(n, rho)
        fixed = rng.binomial(m6.astype(int), rho_i)
        new_mm = rng.binomial((sens - m6).astype(int), delta)
        m7 = (m6 - fixed) + new_mm
        ok_reps = (rng.random((n, 2)) > 0.23)
        keep = ok_reps.any(1)                       # 双失效任务：错配终点不可评价，剔除
        d = (m6 - m7)[keep] / np.maximum(sens[keep], 1)
        T = d.sum()
        if T > 0:
            S = (rng.integers(0, 2, (FLIPS, len(d))) * 2 - 1) @ d
            p = (1 + (S >= T).sum()) / (FLIPS + 1)
        else:
            p = 1.0
        surv = ok_reps.sum(1) / 2                   # Q：M3 置零稀释
        dq = ((c_conv * F_LW * fixed) / Nb
              - rng.binomial((Nb - m6).astype(int), eps_q) / Nb
              + rng.normal(0, sigma, n)) * surv
        ni_pass = dq.mean() >= -margin + 1.645 * dq.std(ddof=1) / np.sqrt(n)
        rej += p <= 0.05
        ni += ni_pass
        joint += (p <= 0.05) and ni_pass
    return rej / B_SIM, ni / B_SIM, joint / B_SIM


SC = [  # (标签, n, b基线倍率, rho消除率, 异质, delta新错配, c_conv转化, eps_q过压制, sigma, margin)
    ('中心:50%消除',        26, 1.0, 0.5, False, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('中心:50%消除',        30, 1.0, 0.5, False, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('严格界值-0.032',      26, 1.0, 0.5, False, 0.01, 0.5, 0.02, 0.104, 0.032),
    ('低基线x0.5',          26, 0.5, 0.5, False, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('高基线x1.5',          26, 1.5, 0.5, False, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('异质(60%全修/40%无)', 26, 1.0, 1.0, True, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('完全消除',            26, 1.0, 1.0, False, 0.01, 0.5, 0.02, 0.104, 0.05),
    ('低转化+小σ',          26, 1.0, 0.5, False, 0.01, 0.25, 0.02, 0.06, 0.05),
    ('高过压制5%+低转化',   26, 1.0, 0.5, False, 0.01, 0.25, 0.05, 0.104, 0.05),
    ('最差组合(n=30)',      30, 0.5, 0.5, True, 0.02, 0.25, 0.05, 0.104, 0.032),
]
rows = []
print(f'{"场景":20s} n   主终点   Q非劣   联合')
for tag, n, b, rho, het, dl, cc, eq, sg, mg in SC:
    p1, p2, pj = power(n, b, rho, het, dl, cc, eq, sg, mg)
    rows.append(dict(scenario=tag, n=n, base_scale=b, elim_prob=rho, heterogeneous=het, delta=dl,
                     c_conv=cc, eps_q=eq, sigma=sg, margin=mg,
                     power_primary=round(p1, 3), power_ni=round(p2, 3), power_joint=round(pj, 3)))
    print(f'{tag:20s} {n}  {p1:.3f}   {p2:.3f}   {pj:.3f}')
(HERE / 'p2c_analysis/P2C_G7_POWER_ROBUST.json').write_text(
    json.dumps(dict(version='v2-corrected', seed=20261110, B=B_SIM, flips=FLIPS, F_LW=F_LW,
                    endpoint_note='mismatch=exclusion semantics; Q=M3 zero-dilution semantics',
                    rows=rows), ensure_ascii=False, indent=1))
print('written P2C_G7_POWER_ROBUST.json')
