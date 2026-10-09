# ADMISSION PACKAGE V1 (2026-10-09)

**Status: assembled for review — this package is NOT execution authorization.**

Staged approval: Stage 1 = FULL small-scale real validation (envelope A, already
authorized for 1h; finish the 3 remaining calibration tasks). Stage 2 = formal
search (envelope B) decided ONLY from stage-1 measurements. No blanket release.

## 1. Cross-state production closed loop (the two admission gaps, closed)

Evidence: `review/TRACK_B_EVIDENCE.json` (v2, **15/15 ALL PASS**).

- **Gap 1 (cache deduction)**: replaced node+model matching with the COMPLETE
  identity chain per (state, task): e=(node,model); r=(m_e1,m_e2,m_r);
  v=(m_e1,m_e2,m_r,m_v)+Z-context in fault30 (recovery changes v's realized
  input). Verified against the executor's own TRAJECTORY hit records:
  **precision = 1.0 for all six methods** (predicted hit ⇒ actual hit; the
  incremental estimate never underestimates new search tokens), e/r recall = 1.0,
  v recall 0.40–0.57 conservative by design — recovery-driven cache population
  (escalation/replay) is output-dependent and outside the searcher's information
  boundary; unpredicted hits are charged as new. Recovery charged conditionally:
  E[new tokens] = overhead × P_fire(state), frozen params, measured fire counts
  reported.
- **Gap 2 (clean-only loop)**: the SAME loop now evaluates every selection on
  clean + fault30 with a real fault panel. Fault30 Q is Z-dependent inside the
  loop (NONE=0, LOCAL/FULL recover); per-state acquisition scores non-degenerate
  from pure evaluator observations; the state ablation diverges WITHIN this loop
  (state-aware vs blind pick sequences differ); state-blind search is label-
  invariant (swapping state labels does not change its picks).
- **Gap 3 (C/L determinism)**: evaluated units use ACTUAL evaluator C/L;
  candidates use frozen ex-ante predictions; all six methods share the identical
  information boundary. Calibration Spearman(est, actual C) = 0.798.

Known limit (registered): stub-backed quality structure is uniform in clean
(Q=1.0); this is wiring admission, not performance evidence.

## 2. FULL validation v2 (envelope A)

Protocol `FULL_VALIDATION_PROTOCOL_V2.json`: 4 frozen calibration tasks
(content-hashed), scenarios S1→S4→S2→S3, single global budget
**30 requests / 30,000 tokens / 1800s** (authorized 1h variant: 3600s wall),
command `P1B_FULLVAL_EXECUTE=1 python3 -m collab_scheduler_v1.joint_search_v1.fullval_runner --execute`.

Execution state (authorized run `fullval_authorized_1h_01`): 1/4 tasks executed.
Mechanism findings on real models: **S4 cache reuse = 0 new requests**
(full-prompt identity reuse verified); S2 LOCAL = 2 new requests with billing
separation; S3 FULL = 5 new requests / 8 logical calls with replay billing.
Remaining: 3 calibration tasks inside the already-authorized envelope.

## 3. Resource envelopes (separate; incomplete-reporting rules attached)

### Envelope A — FULL real validation (AUTHORIZED, partially executed)
30 req / 30k tok / 1800–3600s global. Incomplete → `VALIDATION_INCOMPLETE`,
partial ledger preserved, no retry. Minimum completion: S1+S4 must, S2 should,
S3 may be partial.

### Envelope B — formal search (PENDING stage-1 measurements)
18 sessions = 6 methods × 3 seeds; per-session caps per SEARCH_BUDGET_V1;
task panel = SEARCH8 from TASK_PANEL_V1.json. **Caveat: caps are ceilings, not
completion guarantees** — the 330-request scenario reference under the 400 cap
does not ensure completion with new configs and FULL; results reported as
measured on common budget support; no extension to equalize completed counts.

### Envelope B — TEST16 confirmation sub-envelope (PENDING)
Recomputed at the FULL call ceiling (not the optimistic mean-token estimate):
- max logical calls = 6 methods × 2 states × 16 tasks × 12 cap = **2304**
- hard upper bound: **2304 new requests / 18,874,368 tokens**
  (reservation basis; failed calls retain full reservation), wall ≈ 15,366s
- realistic estimate ≈ 862,764 tokens (mean 374 tok/req)
- Declared for approval: the HARD bound; settlement at actuals.
- **Positioning: small-scale independent confirmation only.** MDE(TEST16) ≈ 0.24
  on paired marginal delta — cannot exclude small differences, cannot support
  equivalence claims.

## 4. Non-claims

- Budget-fit ≠ completion guarantee.
- TEST16 ≠ equivalence evidence.
- Cross-state loop = wiring admission (stub), not performance evidence.


## 5. Stage-1 execution outcome (2026-10-09, appended)

**Stage 1 COMPLETE — minimum scope exceeded.** run01 (30 req / 11,713 tok /
1,457 s, 11 cells, stopped by request budget) + continuation (9 req / 3,985 tok
/ 450 s, 4 t4 cells, `39 requests combined`).

- S1+S4 must-scope MET: all 4 tasks; **S4 = 0 new requests on every task**
  (full-prompt cache identity reuse verified 4/4 with alias provenance).
- S2 should-scope EXCEEDED (4/4); S3 optional 3/4 (t1, t2, t4 FULL_PATH_VERIFIED).
- **Recovery mechanism proven on real models**: on t4 (the one task with a
  correct clean chain), r-corruption was detected and BOTH strategies restored
  Q to 1.0 — LOCAL with a single new request (5 cache hits), FULL with 8
  logical calls / 4 new requests. Injection replaces the metered answer; source
  usage retained in C.
- Quality: clean Q = 0/0/0/1 across tasks. Scoring chain verified correct —
  t1 percent-convention mismatch (frozen RPROMPT x100 vs raw-ratio gold), t2/t3
  genuine extraction/arithmetic errors. Real Q is low but variable: the formal
  search condition, not a blocker.
- L-scale calibration recorded from first S1 (rule honored, not re-frozen).

Full detail: `FULLVAL_STAGE1_REPORT.json`.
