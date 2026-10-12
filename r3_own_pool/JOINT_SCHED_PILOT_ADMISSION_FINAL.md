# JOINT_SCHED_PILOT_ADMISSION_FINAL — the one-shot admission package for the real micro-pilot

Baseline `da3904b`; this round closed every blocker the operator named.
Zero real model calls, zero GPU, named-file staging only. This document
is the COMPLETE basis for a go/no-go decision on the 3-task × 6-arm
micro-pilot; no further audit rounds are spawned from it.

## 1. Operator blockers → fixes (all landed, all tested)

| # | blocker (operator finding) | fix | test |
|---|---|---|---|
| 1 | MONO defined but the REAL path never used its prompt (real engine built the v-node prompt) | `RealServer.build_prompt(node, kind, uid)` dispatches `kind=='mono'` on node v to `mono_prompt(task)` (full context: question + table + passages); MONO jobs carry kind='mono' (initial and fallback) | **T6**: request-level fake-transport asserts the FINAL sent prompt equals `mono_prompt` and differs from the v-node prompt; fallback+scoring unchanged (T1) |
| 2 | Cross-arm cache unfairness (later arms inherit earlier arms' caches) | `run_shared_base` executes planned e1/e2/r ONCE (faults active); each arm gets a FRESH engine seeded with a COPY of that snapshot; arm cells REPLAY the base stages (pure cache hits, 0 physical) so observers rebuild identical state incl. the D3 corruption; arm-private recovery/v calls are physical and can never leak across arms | **T7**: both arms' base replay = 0 physical; identical v identity is physical in EACH arm (no cross-arm hit); faulted task's r=FAILED re-derived identically |
| 3 | Unfinished tasks settled with first-event time (fake low latency) | `realized_row` REFUSES any task without a completion_time (fail-loud ValueError; no fallback) | **T8** |
| 4 | Same dir could hold INCOMPLETE then COMPLETE | `write_results`: a run that ever wrote `*_INCOMPLETE.json` can NEVER be marked COMPLETE; neither file ever overwritten | **T5/T9** |
| 5 | D-tiers must not be reverse-engineered from confirmatory results | D_i = pre-registered multiplier × planned-path SERVICE mean from the INDEPENDENT reliability FIT binding (multipliers tight/medium/wide = **15/25/50**; switches excluded from the anchor — they are candidate-side costs); per-task tier by frozen seed | **T10**: stub-verified discrimination — one-switch LOCAL recovery infeasible at tight / feasible at medium+; three-switch FULL replay feasible only at wide |
| 6 | P3 fresh panel | `JOINT_VERIFY_P3_FREEZE.json`: 60 tasks drawn (seed 20261101) from a **1,430-task never-used pool** (TAT-QA train, frozen200 eligibility filters, all evaluation/calibration/supplementary/reliability uids excluded, native v2.1 gold present for all); fault draws 18/60 @30% (seed 20261102); tiers 20/20/20 (seed 20261103); deterministic re-derivation asserted | **T11** |

## 2. Power and budget (corrected per ruling #7)

- **No double discount**: sample size uses the paired-difference SD that
  already CONTAINS zero-difference tasks; the earlier ÷0.45 step is
  WITHDRAWN. E6 fault-condition paired SD (M5-confounded, planning
  reference only): ΔR 0.283 → n ≈ 49/77/197 at Δ = 0.10/0.08/0.05
  (one-sided α=.05, 80% power); interaction SD 0.340 → n ≈ 71/112/286.
  Re-estimate at micro-pilot.
- **Physical budget under cache isolation** (worst legal case): shared
  base 3/task + per-arm physical ≈ SS 2.7 / DS 1.1 / SD 2.2 / DD 2.5 /
  NONE 1.9 / MONO 1.3 ≈ **12.7/task-total**; n=60 → ~760 base +
  retry/switch-affected worst case +30% → **~990 requests**; tokens
  ~990 × 450 ≈ **445K**; wall: base + 6 arm cells ×(2–5 switches×65 s)
  + calls ≈ **6–8 ks**. **Micro-pilot worst case (3 tasks × 6 arms):
  ≤ 45 requests / 25K tokens / 1,800 s.**
- Confirmatory proposed caps (require approval): **1,100 requests /
  500K tokens / 12,000 s**.

## 3. Execution-entry status

- The real entry (budget, GPU lock, manifest, stage states, results
  guards) reuses the audited supplementary machinery; the six-arm
  driver + shared-base + settlement are wired in
  `joint_verification_runner.py`. The execution flag remains DISABLED
  by default (`JOINT_VERIFY_EXECUTE` does not exist yet — it will be
  added only inside the pilot authorization, mirroring the reliability
  runner's gate pattern).
- Fail-stop (binding): any failure → STOP, preserve ledgers, write
  INCOMPLETE, report; no in-round repair, no auto-restart, no fifth
  reliability-style loop.

## 4. PASS/FAIL table

| item | verdict |
|---|---|
| MONO real prompt (request-level verified) | **PASS** (T6) |
| Cross-arm cache fairness (symmetric snapshot + per-arm engines) | **PASS** (T7) |
| Settlement refusal for unfinished tasks | **PASS** (T8) |
| INCOMPLETE can never become COMPLETE | **PASS** (T5/T9) |
| Six-arm end-to-end recording incl. realized R | **PASS** (T1) |
| Reward manual verification incl. T==D boundary | **PASS** (T2) |
| Gold isolation (decisions blind to gold) | **PASS** (T3) |
| Fault isolation both directions | **PASS** (T4×2) |
| D-tier rule frozen from independent data only + discrimination | **PASS** (T10; multipliers 15/25/50) |
| P3 panel frozen, pristine, gold-backed | **PASS** (T11; sha b04ffb29…) |
| Power/budget re-derived without double discount | **PASS** (§2) |
| Full M-suite regression at this commit | **PASS** (15 suites + admission check) |

## 5. Conditions for the micro-pilot GO (operator's call)

1. Approve this package (hashes: P3 freeze sha256 in-file; code at this
   commit).
2. Approve the micro-pilot worst-case budget: ≤45 requests / 25K
   tokens / 1,800 s; 3 tasks × 6 arms; purpose = complete execution +
   correct records ONLY (never quoted as effectiveness).
3. Fail-stop acknowledged: one failure ends the pilot; analysis and
   report only.

**Real execution remains NO-GO until an explicit written GO.**
