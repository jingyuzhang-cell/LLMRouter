# M6_ACCEPTANCE — reward-driven two-stage decision, formally accepted

Authorization: operator M6 GO (2026-10-11, baseline 72273d0). Scope:
formal acceptance of the EXISTING implementation + necessary fixes only.
Phase-3 formal acceptance, production integration, net-benefit, and
real-model experiments remain HOLD. Zero real model calls throughout.

## 1. Modules reviewed (no redesign)

| Module | Role | Status |
|---|---|---|
| `reassign.py` (M5) | legal (Z,R,π) generation, M3-adjudicated | accepted at M5 |
| `policy.py` | two-stage decision: filter (q̂≥Q_min, P̂≥1−ε, ΔC≤B_remain) → argmax Ê[R_task]; EARLY_STOP; episode driver | audited here |
| `predictor.py` | per-action q̂ / ΔC / service (μ,p90); corrected E1; profile legality | audited here |
| `compensator.py` | d_remain / b_remain live; per-call switch bound (structural); contention estimate | audited here |
| `reward.py` | Ê[R_task] (C_new, D_total normalization) + realized R_task (C_full, ledger-only); session terminal (correct+on-time+not-degraded) | audited here |

## 2. Independent expected-value reconciliation (mandated item 3)

A dedicated acceptance suite (`test_m6.py`, **14/14**) re-derives every
golden scenario CLOSED-FORM (E1 + the frozen Ê[R_task] expansion with
lam_t normalized by D_total) and compares against the engine's decision
tables, the actual selection, and the executed ledger:

**V1-S1 (choose B), hand vs engine:**
| Candidate | Hand P̂ | Engine P̂ | Hand score | Engine score | Feasible |
|---|---|---|---|---|---|
| A (r large, v large) | 1.5e-7 | 0.000000 | −2.350000 | −2.350000 | NO (on_time) |
| **B (r large, v coder)** | **0.999940** | **0.999940** | **+0.737328** | **+0.737328** | **YES** |
| C (r medium, v coder) | 1.0 | 1.000000 | +0.512500 | +0.512500 | NO (q_min) |

Selection = argmax over feasible = B (the engine's chosen arm is LOCAL
or a FULL_DYNAMIC row with the SAME r/v assignment — an exact-score
tie); executed ledger: r retry on large, v on coder.

**V1-S2 (EARLY_STOP):** hand P̂(B, p90=21) = 0.831774 < 0.90; A
time-infeasible; C quality-infeasible → feasible set EMPTY → degraded,
zero further calls (ledger-verified), every candidate's violation vector
recorded.

**V8 (cost sensitivity):** hand score difference A−B at D=60:
λc=0.5 → **+0.0625 (A wins)**; λc=2.0 → **−0.0500 (B wins)** — engine
selections match under both regimes.

**V10 (time sensitivity through the REAL policy):** same fault, same
legal history; only the deadline changes (39 → 31; the per-call switch
BOUND makes A's μ=31.0 vs B's 23.5). Rich: A feasible (P=0.9993),
score 0.7993 > B 0.7375 → **v=large**; tight: A infeasible, B P=0.9948
→ **v=coder**. Ledger v-call models match the chosen π in both runs.
This is the M6-completion of the M5 capability: the POLICY — not a
test rule — changes downstream node models by remaining time.

## 3. Mandated checks 4–7

- **Predicted vs actual separation** (`m6_predicted_vs_actual_separated`):
  decision row ΔC=900 (PREDICTED, synthetic priors) vs settlement
  c_full=500, q=1, T from the LEDGER — settlement never uses predicted
  values.
- **Statistical calibre** (three-way, in every row): `p_conservative`
  tag (quantile_sum ⇒ conservative lower bound on P̂ only while D ≥ μ;
  variance mode ⇒ exact under the declared independent-normal family;
  D<μ rows explicitly tagged non-conservative — the reviewer's
  counterexample 15.9% vs 25.2% is pinned in the boundary suite);
  per-call switch = STRUCTURAL bound (provable from the serial-executor
  model, prior-independent); cross-task contention = DECLARED HEURISTIC
  estimate from synthetic priors (conditional bound only; never claimed
  as a general guarantee). No heuristic is presented as a guarantee.
- **EARLY_STOP** (`m6_v1s2_*`): violations preserved per candidate;
  zero post-decision calls for the degraded task; settlement flagged.
- **Causality** (`m6_no_illegal_payloads`): decision tables carry no
  gold / fault / future payloads; gold enters only settlement (M2/M3
  firewall suites re-run green).

## 4. Defects found during this acceptance

One test-authoring defect (fixed in-suite, no production change): the
first V10 decisive window (24.6/60) ignored the per-call switch BOUND's
effect on μ (A=31.0, B=23.5 under real priors) and the 5.5 s
clock-at-decision, putting the "tight" run inside B's own infeasible
region → the M5+M6-era V10 check had passed only via a different
configuration. The window is now (rich 39 / tight 31) with the full
arithmetic documented in-suite; the ORIGINAL test_policy V10 (zero
switch, golden priors) remains valid and unchanged.

## 5. Claim boundaries (binding)

- **Synthetic-prior stub pass ≠ real-model efficacy.** All quality /
  latency / cost predictions come from declared synthetic priors;
  14/14+18/18+… prove DECISION-LOGIC and accounting correctness, not
  empirical performance or superiority over static recovery.
- The on-time probability is exact only under the declared
  independent-normal family (variance mode) and a conservative lower
  bound under quantile_sum when D ≥ μ; real-distribution guarantees
  require the separately gated calibration.
- Not covered: real distribution drift, multi-episode persistence,
  production executor integration.

## 6. Full regression (mandated item 9)

M1 21/21 · M2 24/24 · M3 37/37 · M4 28/28 · M5 24/24 · **M6 14/14 (new)**
· M5+M6 18/18 · phase-3 19/19 · boundary 14/14 = **199 checks, ALL
PASS**, zero real model calls, socket-blocked. Evidence:
`evidence/M6_EVIDENCE.json` (hand-reconciliation tables), run ledgers
under `evidence/m6_runs/`.

## Formal sign-off (operator, 2026-10-11, commit 0f7cb46)

M6 engineering acceptance SIGNED OFF — the phase-2 stub implementation
(M1–M6) is complete. Two statistical-calibre reservations are carried
into phase 3 as mandatory items (not defects in this sign-off):

1. `p_conservative` is NOT an unconditional on-time-probability
   guarantee: variance-mode "exact" and quantile_sum conditional
   conservatism both rest on the DECLARED distribution/aggregation
   assumptions; the expected-tag helper's `p_on_time in (0.0, 1.0)`
   side-branch must be unified with the formal rule next round to
   remove boundary ambiguity.
2. Cross-task contention time enters μ_E2E and the p90 and therefore
   DOES influence p_on_time; the current tests prove only field
   presence/non-negativity. Phase 3 must independently calibrate and
   bound its estimation error against the probability guarantee.

**Status: M1–M6 SIGNED OFF (phase-2 engineering complete). The frozen
mainline — fault → remaining time/budget → joint (Z,R,π) with
quality/on-time/cost filtering → argmax Ê[R_task] → execution →
settlement — is verified end-to-end at zero-call level. Phase-3
independent statistical/correctness acceptance, production
integration, net-benefit, and real-model experiments remain HOLD
pending separate authorization. No claim of real-world superiority
over static scheduling is supported by any of this evidence.**
