# P3_A_AUDIT_REPORT — independent zero-call correctness & statistics audit

Operator authorization: phase-3 P3-A (2026-10-11, baseline 6ac5b3d).
READ-ONLY over the implementation; expectations computed with standalone
math and isolated fixtures (never by invoking the audited functions to
prove themselves); no algorithm changes; zero real model calls; frozen
Formal/net-benefit evidence untouched.

**Verdict: PASS 15 · CONDITIONAL 4 · FAIL 0. Recommendation: proceed to
P3-B with a 3-item targeted fix list (1 documentation, 2 minor code/test
items). No MAJOR findings. All authoritative accounting (requests,
tokens, budget, settlement) reconciles exactly.**

## Test-count reconciliation (mandated item 2)

Counted live (not from any report): M1 21 · M2 24 · M3 37 · M4 28 ·
M5 24 · M6 **22** · M5+M6 18 · phase-3 19 · boundary 14 = **207/207,
0 failed**. The 8-check delta vs the 199 written in M6_ACCEPTANCE §6:
that section was authored at a7b7334 (M6=14) and not refreshed after
commit 0f7cb46 grew the M6 suite 14→22 (3 calibre-independence + 2
reverse-tag + 2 structural-whitelist + 3 counterfactual checks, minus
the removed vacuous check; net +8). **Documentation staleness only —
no evidence conflict.** Fix in P3-B: refresh §6.

## Independent golden re-derivations (item 3) — ALL PASS

Computed entirely in the audit script (standalone E1 + Ê[R_task]):
- **V1-S1**: P̂_A=1.5e-7 (on_time-infeasible), P̂_B=0.999940 /
  score +0.737328 (feasible), P̂_C≈1 but q̂=0.60 (q_min-infeasible) →
  **choose B**. Matches engine tables to 1e-5.
- **V1-S2**: P̂_B(p90=21)=0.831774 < 0.90 → feasible set EMPTY →
  **EARLY_STOP**. Matches.
- **V8**: score diff A−B = +0.0625 (λc=0.5 → A) / −0.0500 (λc=2.0 →
  B). Matches.
- **V9**: budget arithmetic (1500−600−900=0 → degrade; 1350−600=750 →
  affordable-B chosen) consistent.
- **V10** (per-call switch bound, real priors): μ_B=23.5, μ_A=31.0;
  at d_remain 25.5 → B feasible, A not; at 28.5 → both, A wins on
  score. Matches the committed decisive windows.

## Statistical boundaries (item 4) — PASS + 2 carried CONDITIONALs

- **B1 point masses** PASS: (μ=p90, D>μ) → (1.0, 0.0) exactly;
  (μ=p90, D<μ) → (0.0, μ−D) exactly.
- **B2 D=μ** PASS: P̂=0.5 exactly and E_late=σ·φ(0) — re-derived with
  the correct σ-scaled expectation (the audit's own first expectation
  was mis-scaled and was corrected BEFORE recording the verdict; the
  implementation was right).
- **B3 expected_tag side-branch** CONDITIONAL (carried, MINOR): the
  acceptance-test helper's `p_on_time ∈ {0,1}` branch can tag a D<μ
  row conservative; the PRODUCT rule is the pure D≥μ comparison. A
  grid scan found no conflicting row in the golden tables (both
  directions independently verified), but the helper must be unified
  in P3-B (already a carried mandatory item from the M6 sign-off).
- **B4 family conditionality** CONDITIONAL (NOTE): E1 exactness holds
  only under the declared normal family; synthetic validation is NOT
  real-model calibration (frozen claim discipline — binding).

## Contention sensitivity (item 6) — ALL PASS (the carried sign-off item)

Real policy driven with the co-task's remaining-work estimate
artificially set to 0 / 6 / 12 s (audit-local injection, no
implementation change):
- **C1**: μ_E2E and p90 shift by EXACTLY the injected seconds
  (deterministic addend, both moments).
- **C2**: p_on_time strictly decreases with the estimate.
- **C3**: the ACTION moves — at 0 s the candidate is chosen; at 12 s
  the same candidate becomes infeasible and the decision degrades.
- **C4**: monotone conservative direction — larger estimate ⇒ never
  larger p̂. Estimation-error direction: the estimate only ever
  SUBTRACTS from feasibility; its error cannot silently admit an
  infeasible candidate unless the true co-task work EXCEEDS the
  estimate (documented condition for the bound).

## Time calibre (item 7) — CONDITIONAL (reconciles, recorded)

Ledger E2E (release→termination) = 13.60 s = service 1.00 + switch
12.00 + queue/other 0.60; the three quantities are recorded separately
and sum-exact. Critical-path and contention are PREDICTION-side calibres
only and never enter the ledger E2E. CONDITIONAL because per-quantity
upper-bound guarantees (queue under adversarial scheduling) are not
claimed and not tested.

## Event conservation (item 8) — exact on all authoritative fields;
one genuine MINOR defect found

- **E2 settlement**: Σ per-task c_full == Σ physical tokens == budget
  actual_tokens. EXACT.
- **E1**: `requests` and `tokens_total` reconcile EXACTLY per event.
  **Genuine MINOR defect (P3-B fix): `session_summary.calls`**
  double-counts corruption-after-metering calls — it computes
  requests+cached+injected, but injected calls are ALREADY inside
  requests (the underlying call is real and charged; only the answer
  was replaced). Observed: calls=10 vs 9 call events (injected
  subset=1). No budget/reward/accounting consumes this convenience
  field; authoritative fields unaffected. Recommended fix:
  `calls = requests + cached`.

## Static equivalence, closure, FAILED/RUNNING/cache, counterfactuals
## (items 9–10) — PASS

- X2: M4 T3a/T3b suite (28) and M3 closure suite (37) re-run green
  inside the live count above.
- X1: committed counterfactual evidence re-verified: hidden gold /
  future outputs / never-fired fault registry leave decisions
  IDENTICAL; gold changes settlement only.

## Findings list (severity, id)

| Sev | Id | Disposition |
|---|---|---|
| DOC | R2_acceptance_doc_stale (199→207) | P3-B: refresh M6_ACCEPTANCE §6 |
| MINOR | E1_calls_field_double_count | P3-B: `calls = requests + cached` (one line) + regression pin |
| MINOR | B3_expected_tag_branch | P3-B: unify helper with the product rule (already a carried mandatory item) |
| NOTE | B4_family_conditionality | binding claim boundary — no code change |
| NOTE | T1_time_calibre | quantities reconcile; no untested upper-bound claims made |

## Recommendation

**Proceed to P3-B** with exactly the two MINOR code/test items + the
one DOC item above; nothing else requires change. After P3-B re-runs
the full regression, phase-3 final acceptance can be requested. No
real-model experiment, production integration, or net-benefit work is
authorized by this audit; the claim boundary stands: mechanism
implemented and independently verified at zero-call level — no
real-world superiority claim.

Evidence: `evidence/P3A_EVIDENCE.json` (verdicts, findings, live
counts, contention triples), run ledgers under `evidence/p3a_runs/`.
Audit script: `audit_p3a.py` (idempotent, socket-free by construction —
no network imports).
