# JOINT_VERIFY_CONFIRMATORY_READINESS — decision package for the 60-task confirmatory experiment

Micro-pilot PASS (`f2b70c7`); this package closes its two calibration
notes zero-call and states the GO conditions. NO real execution is
authorized or started by this document.

## 1. The two pilot calibration notes — root cause + fix (landed)

Pilot log decomposition (per task, per arm):
- **Wall T is dominated by shared switch walls + batch queue**: in the
  SS cell the first task carried ~354 s of switch walls and the others
  ~353 s of queue — neither is a property of the task's own policy.
  Under that T, tight/medium tiers were unreachable for EVERY task in
  every arm (all on-time-correct = 0 except wide-tier cells), i.e. the
  deadline dimension would have measured batching, not scheduling.

**Frozen T convention (refined by the 4c941fc closeout; code + T12
assertions)**: the reward's T = **the task's own INCREMENTAL service
time** — the sum of the arm's OWN physical-call latencies only (cached
shared-base replay excluded — it is not a recovery action; queue and
switch walls excluded — environment properties). The episode wall is
preserved as `T_wall_reference`, and `R_wall_deployment_view`,
`switch_wall_s`, `switch_count` are reported per task (never hidden). Rationale and consistency: (a) the G3 D-anchor is
already service-mean × multiplier (switches excluded by design), so T
and D now share one convention; (b) batching queue and shared switch
walls are properties of the serial executor environment, reported per
arm as cell-level wall + switch counts, identical in distribution
across arms under task-order rotation; (c) the pilot's own numbers
under the new convention become meaningful: e.g. SS t1 service 4.8 s
vs D_tight 68 s → on-time where its policy actually executed, and the
tiers discriminate on RECOVERY-CAUSED service (an r-retry + v adds
seconds, not shared walls).

Verified zero-call: T12 now asserts T == per-task own service sum,
T_wall_reference preserved, and both rewards recomputed consistently.

## 2. The q̂-belief degradation note (documented, no action)

DS/SD/DD degraded on natural e-failures because the stub-prior q̂
beliefs (strict parse rates) make e-recovery candidates q-infeasible.
This is the mechanism behaving as designed under its declared beliefs.
The confirmatory experiment measures REAL terminal outcomes; the
degradation rates per arm are part of the reported behavior (and are
themselves an answer to "when should the policy decline to recover").
No belief recalibration is performed (would require its own frozen
version; explicitly out of scope).

## 3. Budget re-estimate for n=60 (cell-batched, cache-isolated)

From pilot actuals (29 physical / 10,449 tokens / ~450 s for 3 tasks ×
6 arms + base), scaling calls/tokens linearly and wall sub-linearly
(switches amortize over larger cells):
- requests ≈ 60 × 9.7 ≈ **580** (+20% retry reserve ≈ 700)
- tokens ≈ 60 × 3,483 ≈ **209K** (+20% ≈ 250K)
- wall ≈ 20× call time + fixed switches ≈ **8,000–10,000 s**
PROPOSED caps (approval required, not auto-raised): **800 requests /
300K tokens / 11,000 s**. Primary contrast ΔR = R_DD − R_SS on
R_conditional (service-T convention); interaction reported with the
n=60 underpowering caveat (non-significant ⇒ "not established").

## 4. GO conditions (operator's call)

1. Approve the FROZEN primary endpoint as closed out on `a9cd4dd`:
   R_conditional(q=v2.1 terminal, C=arm incremental physical tokens,
   T=arm incremental service time, D=multiplier x independent-FIT
   service mean) — service-latency mechanism comparison, NO end-to-end
   wall-latency claim; per-arm decision budgets identical (constant
   allocation); G3 multipliers 15/25/50.
2. Approve the P3-60 panel as frozen (sha b04ffb29) with the
   tier/fault draws in `JOINT_VERIFY_P3_FREEZE.json`.
3. Approve the caps in §3.
4. Fail-stop acknowledged (one run; any failure → INCOMPLETE → report;
   no in-round repair).
5. At GO: the launcher extends `micropilot_launch.py`'s gate pattern
   (code-clean binding + both freeze hashes + GPU lock + unique dir +
   GO flag) to the 60-task panel — a small, testable addition, not a
   new development phase.

**Status: stopped. No real execution without the explicit written GO
above.**
