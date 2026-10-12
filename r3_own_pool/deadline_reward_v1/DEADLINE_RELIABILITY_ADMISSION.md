# DEADLINE_RELIABILITY_ADMISSION — executable gates, drills, PASS/FAIL evidence

Operator mandate 2026-10-12 (baseline 27b240b). Everything below is
zero-real-call and independently reproducible from the repository.

## 1. Executable gates (the GO-day checklist)

| gate | check | command (zero-call unless marked GO) |
|---|---|---|
| G1 statistics frozen | reliability_stats.py hash bound; 14/14 exact-verification tests | `python3 -m deadline_reward_v1.test_reliability_stats` |
| G2 panels frozen | disjoint fit/screen/validate + spare; seeds + SHA-256; isolation rules | re-derive `RELIABILITY_PANEL_FREEZE.json` seeds; compare hashes |
| G3 P0 plumbing live | decision rows complete, persisted pre-execution, oracle-free | `python3 -m deadline_reward_v1.test_m5_closure_fix` (25/25) |
| G4 M-suite regression | M1–M6 + phase-3 + boundary + smoke + repairs + admission check | each `test_*` module; admission check ALL GATES PASS |
| G5 budget closed | stage caps ≤ global 1200/600K/14400 with headroom | DEADLINE_RELIABILITY_BUDGET_AUDIT.md arithmetic |
| G6 D-tier replay drill | synthetic-ledger replay: decomposition, tier discrimination, acceptance regions, decision_id join | part D of G1 |
| G7 operator GO | explicit authorization naming the freeze hashes | — (not automatable by design) |

## 2. Drill evidence (this round)

- **G1 — 14/14 PASS** (`evidence/RELIABILITY_TOOLKIT.json`): CP bounds
  vs closed forms (29/29 → 0.9019 = 0.05^(1/29); n=28 insufficient;
  CP(17,20)=0.65634 vs scipy); Poisson–binomial DP vs exhaustive
  enumeration (3-node exact match); uniform-case region sanity; range
  guards; joint acceptance rule (PASS/CONDITIONAL/FAIL + missing-cell
  FAIL); the frozen sample-size table {29, 61, 116, 298};
  exploratory-band-never-admits (24/30 → FAIL).
- **G6 — replay drill PASS**: synthetic 6-task ledger, hand-computed
  E2E = service + switch + queue = [4.2, 4.35, 4.5, 4.65, 4.8, 5.9];
  tiers 4.6/5.5/20.0 discriminate 3/5/6 on-time; tight tier correctly
  FAILS the exact acceptance region [4,6] (predicted 0.9 ×6); medium/
  wide PASS; decision_id join verified; cell-coverage pipeline returns
  FAIL at 5/6 point coverage (0.833 → CP-LB ≈ 0.44).
- **G2 — panel freeze**: fit(24)/screen(12)/validate(90)/spare(24) from
  the 150-task pool; pairwise intersections 0; validate disjoint from
  evaluation + calibration + supplementary panels; five seeds
  re-derived and asserted equal before writing; SHA-256 per panel.
- **G3/G4**: unchanged from the P0 round — test_m5_closure_fix 25/25;
  full M-suite green; admission check ALL GATES PASS (re-verified at
  the final commit of this round).

## 3. PASS / CONDITIONAL / FAIL table

| item | verdict | evidence |
|---|---|---|
| Statistical rules frozen, exact, direction-fixed | **PASS** | reliability_stats.py + 14/14; frozen table 29/61/116/298 |
| Panels frozen, disjoint, isolation rules explicit | **PASS** | RELIABILITY_PANEL_FREEZE.json |
| Sample unit + cache/retry counting rules | **PASS** | protocol V3 §1 |
| Joint multi-cell acceptance rule | **PASS** | joint PASS ⟺ all cells CP-LB ≥ .90; CONDITIONAL path defined |
| Budget closed vs 1200/600K/14400 | **PASS** | 922 / 307K / ~10,000 s with stage caps + INCOMPLETE gates |
| Reuse vs required-request split | **PASS** | budget audit §"Reuse vs REQUIRED" |
| P0-B rows persisted pre-execution, oracle-free, joinable | **PASS** | G3; ordering + no-oracle assertions |
| Fixed-path vs dynamic-decision validation separated | **PASS** | V3 §3 (dynamic arm exploratory at n=9/tier; formal role stays with V2.3) |
| D-tier replay statistics + interfaces | **PASS** | G6 drill |
| D-tier separation from V2.3 P40/P60/P80 | **PASS** | V3 §5; separate frozen documents |
| Quality-proxy impact on dynamic validation | **CONDITIONAL** (recorded limitation) | e2|large q̂=0.25 ⇒ dynamic e-recovery largely infeasible; dynamic arm exploratory; Q_min untouched |
| Real measurement execution | **NOT STARTED** | awaiting explicit GO (gate G7) |

## 4. Hash manifest for independent review

Bound at this round's final commit (see git log; the supplementary
preflight's freeze-manifest mechanism extends to the reliability
runner when it is implemented — the runner itself is NOT part of this
round):

- deadline_reward_v1/reliability_stats.py
- deadline_reward_v1/test_reliability_stats.py
- deadline_reward_v1/RELIABILITY_PANEL_FREEZE.json
- deadline_reward_v1/DEADLINE_RELIABILITY_PROTOCOL_V3.md
- deadline_reward_v1/DEADLINE_RELIABILITY_BUDGET_AUDIT.md
- deadline_reward_v1/DEADLINE_RELIABILITY_ADMISSION.md
- evidence: RELIABILITY_TOOLKIT.json, reliability_replay/REPLAY.jsonl

## 5. Stop statement

Zero-call testing and the admission package are complete. No real
model measurement, no modification of formal experiment protocols, no
strategy-comparison experiment has been started. The next step
(reliability runner implementation + real execution) requires a new
explicit authorization.
