# M6_ERRATA — final acceptance-test hardening (operator review of a7b7334)

Baseline: commit a7b7334. Authorization: targeted test fixes only — no
algorithm redesign, no real model calls. Phase-3 formal acceptance,
production integration, net-benefit, and real-model experiments remain
HOLD. Both mandated tasks closed; M6 suite **22/22**; full regression
**207/207** (actually counted, not hardcoded).

## Task 1 — statistical-guarantee test fixed (was vacuous)

Reproduced: `m6_calibre_tags` ended with `or True` — the check could
never fail; it verified only field presence. **Removed.** Replaced by
checks whose EXPECTED tags are computed independently of the product's
labeling logic:

- `m6_calibre_tags_independent`: for the V1-S1 table (which provably
  contains rows on BOTH sides of μ — asserted), every row's
  `p_conservative` must equal the independently derived expectation
  (quantile_sum: True iff d_remain ≥ mu_e2e, i.e. the conditional
  lower bound holds only at-or-right-of the mean; False for every
  D<μ row).
- `m6_calibre_variance_exact`: a variance-mode run tags all rows
  `p_conservative=True` (exact under the declared independent-normal
  family).
- `m6_contention_heuristic_declared`: the cross-task contention appears
  ONLY as an explicit additive seconds field in every row — never
  inside the probability or its tag — the structural assertion that it
  is a declared heuristic, not a probability guarantee.
- **Reverse tests** (`m6_reverse_wrong_tag_detected{,_2}`): a
  deliberately mislabeled row (True→False on a D≥μ row; False→True on
  a D<μ row) makes the independent checker FAIL — proving the checker
  itself has teeth. Both directions pinned.

## Task 2 — causality hardening (structural + counterfactual)

- **Structural whitelists** (keyword scanning was insufficient):
  `m6_structural_whitelist` — every decision-table row carries EXACTLY
  the audited field set (16 fields; any foreign key under any name
  fails); π maps only DAG nodes to menu models; deficits/kinds shape
  checked. `m6_event_whitelist` — decision events carry exactly the
  audited envelope (9 fields), chosen/violations nested shapes checked.
- **Counterfactual invariance** (identical legal observation history;
  hidden world varied; canonicalized candidates/feasibility/scores/
  selection/degradation must be IDENTICAL):
  - `m6_counterfactual_gold_invariant`: hidden task answer changed
    4.0→999.0 — decision signature unchanged AND the settlement DID
    change (q=0.0): gold affects settlement only, never generation/
    prediction/selection.
  - `m6_counterfactual_future_invariant`: the server's unseen future
    outputs changed — decision signature unchanged.
  - `m6_counterfactual_faultreg_invariant`: an extra hidden fault
    entry keyed on a (node, model) this episode never calls
    (e1@medium) — decision signature unchanged. (First attempt keyed
    it on e1@large, which FIRES during stage A and legitimately changes
    the legal history — that is a different world, not a counterfactual;
    documented and re-keyed.)
- The legacy keyword scan is retained as defense-in-depth.

## Task 3 — regression (counted, not hardcoded)

All golden closed-form reconciliations unchanged and passing (V1-S1
choose B, V1-S2 EARLY_STOP, V8 λc flip, V10 policy time sensitivity).
Full zero-call regression, counted from the actual outputs:

| Suite | Result |
|---|---|
| M1 stub engine | 21/21 |
| M2 scheduler state | 24/24 |
| M3 closure & reuse | 37/37 |
| M4 recovery + T3a/T3b | 28/28 |
| M5 reassignment | 24/24 |
| **M6 acceptance (this errata)** | **22/22** |
| M5+M6 policy suite | 18/18 |
| phase-3 consistency | 19/19 |
| boundary audit | 14/14 |
| **TOTAL (counted)** | **207/207, 0 failed** |

Zero real model calls; socket-blocked; frozen Formal/net-benefit
evidence untouched. Evidence: `evidence/M6_EVIDENCE.json` (incl. the
counterfactual signatures and calibre detail), ledgers under
`evidence/m6_runs/`.

**Status: M6 acceptance-test hardening complete; paused for the formal
sign-off. Phase-3 formal acceptance, production integration,
net-benefit, and real-model experiments remain HOLD.**
