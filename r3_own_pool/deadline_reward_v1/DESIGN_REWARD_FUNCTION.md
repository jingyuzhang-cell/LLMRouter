# DESIGN_REWARD_FUNCTION — Phase 1 deliverable 2/4 (deadline_reward_v1)

Status: DRAFT v0.2 (revision A) for phase-1 review. This revision follows the
reviewer's ruling of 2026-10-10: **R0 — the finalized task-level reward with
its conditional expectation as the online action score — is the PRIMARY
scheme.** The v0.1 incremental form is retained only as candidate R1 and is
not used in any decision path until the R0↔R1 relationship is stated and an
ablation design exists (§5). Zero model calls in all phases through 3.

Buddy docs: `AUDIT_EXISTING_CODE.md` (facts, cited as AUDIT §n — wall-clock
verdict in §2.9), `DESIGN_DYNAMIC_SCHEDULER.md`, `DESIGN_PREDICTOR_INTERFACE.md`,
`VERIFICATION_PLAN.md`.

## 1. Purpose

Fix the reward definition the deadline-aware scheduler optimizes: a task-level
terminal reward R0 with deadline indicator terms, an online decision score
equal to its conditional expectation given legally held history, and — as a
diagnostic only — a per-step accounting reward R1.

## 2. Legal inputs (fixed by AUDIT §2.2/§2.4; executable leakage tests in VERIFICATION_PLAN L1–L6)

| Signal | Source | Legal? |
|---|---|---|
| `objectives.Q/C/L` per reveal | SearchSession observations | YES |
| `search_spend.new_requests/new_tokens/new_latency_s, observed_wall_s` | observations | YES |
| Budget state (attempts, charged, elapsed wall) | Budget held by the driver, threaded via scheduler_state wrapper only | YES |
| MODEL_SWITCH wall_s history of the CURRENT stub session | own session's MODEL_SWITCH.jsonl | YES |
| Predictor outputs (q̂, Ĉ, T̂, P̂(T≤D)) | DESIGN_PREDICTOR_INTERFACE | YES |
| Fault panel, states registry, task gold, internal `row['ok']` | — | **NO — leakage** |
| Other sessions' / Formal campaign artifacts | — | NO until the phase-4 provenance gate |

The reward module is a pure function of a frozen `state_view` dataclass
assembled exclusively from the legal table. It never receives evaluator,
ledger, tasks, or faults objects.

## 3. R0 — primary scheme (finalized formula, restated verbatim)

```
R = 1(T ≤ D)·q − λ_c·(C/C₀) − λ_t·(T−D)₊/D − λ_f·1(T > D)        (T−D)₊ = max(0, T−D)
```

**Instantiation in the campaign context** (each item is a definition; the
unit choice itself is OPEN-D5, default = evaluation cell):

| Symbol | Meaning | Default instantiation (per evaluation cell = one config×state reveal) |
|---|---|---|
| q | realized quality | the reveal's `objectives.Q` (v2.1 contract, evaluator-computed) |
| C | realized cost | the reveal's `search_spend.new_tokens` (physical, crash-honest by reserve/settle) |
| C₀ | cost normalization | per-session cap `new_total_tokens` (frozen protocol constant) |
| T | realized completion time | the reveal's `search_spend.observed_wall_s` — chosen because per-cell wall is RECONSTRUCTABLE, unlike per-task E2E (AUDIT §2.9) |
| D | deadline | **allocated** by deadline_compensator inside the G2 work window: `D = D̂(c) = wall_cap − 60 − elapsed − predicted_switch_overhead − safety_margin` (AUDIT §2.9 double-gate resolution; G2 SIGALRM stays the unconditional backstop) |

Weights λ_c, λ_t, λ_f: frozen constants in PRIORS.json, values set at
phase-1/2 review (OPEN-D3). R0 is evaluated at cell completion (terminal for
that cell) and at session end aggregated as the cell-mean R0 plus one
session-level terminal term (§3.2).

### 3.1 Online action score = conditional expectation of R0

At decision time t with legal history H_t and candidate action a (= evaluating
config c), the score is:

```
score(a) = Ê[R0 | H_t, a] = P̂(T≤D)·q̂(a) − λ_c·Ĉ(a)/C₀
                             − λ_t·Ê[(T−D)₊ | a]/D − λ_f·(1 − P̂(T≤D))
decision rule:  a*_t = argmax_a Ê[R0 | H_t, a]
```

Estimator mapping (all from DESIGN_PREDICTOR_INTERFACE, no oracle anywhere):
- `q̂(a)` — quality estimator (GP over legal observations; prior 0/σ₀ when
  <2 points). It ESTIMATES future q; it never sees gold (the only Q values it
  fits are already-revealed observation scalars — the evaluator computed
  them with gold internally, but gold itself never crosses the boundary).
- `Ĉ(a)` — cost upper bound from the event enumeration × token profiles.
- `P̂(T≤D)` and `Ê[(T−D)₊]` — from the time distribution the predictor
  returns (default E1: normal approximation with mean `w_mean_s`, σ derived
  from `w_p90_s` as σ = (w_p90 − w_mean)/1.2816; then P̂ = Φ((D−w_mean)/σ),
  Ê[(T−D)₊] = σ·[φ(z) + z·(1−Φ(z))], z = (w_mean−D)/σ). Estimator form is
  OPEN-D6; alternatives (log-normal, empirical quantile) tested in phase 3.

### 3.2 Session-level terminal accounting

One session = episode. Session return = mean of realized cell R0 values, plus
`+B` if the session reaches COMPLETE, `−P` if stopped by the G2 wall/StopRun
(deadline-compensated wind-down that finishes within the window counts as
COMPLETE, not as an R0 violation). Charged exactly once; crash = `−P`
(mirrors CampaignQuota crash honesty). B, P frozen constants (OPEN-D3).

## 4. R1 — candidate incremental accounting reward (DEMOTED; diagnostics only)

The v0.1 per-step form, retained verbatim for reference and ablation:

```
r_t = ΔQ*_t − α·Tok_t − β·DeadlineDebt_t − γ·SwitchWaste_t
```

**Answering the reviewer's two questions directly:**

1. *How is ΔQ* estimated without future true quality or gold?* It is NOT an
   estimate of anything future. `ΔQ*_t = max(0, Q_t − max_{s<t} Q_s)` uses
   only the realized Q scalars of ALREADY-revealed observations (legal
   table §2). No gold, no future quality, no prediction enters ΔQ*; the only
   estimated quantities in R1 live in `DeadlineDebt` (predictor) and
   `SwitchWaste` (compensator).
2. *How do per-step and final rewards stay consistent?* They are not claimed
   to telescope. R0 is the objective; R1 is an auxiliary diagnostic signal
   for auditing scheduler behavior round by round. Consistency is enforced
   behaviorally, not algebraically: phase-3 check C1 (VERIFICATION_PLAN)
   requires that on stub replay the R0-greedy decision rule achieves
   session-return ≥ random and ≥ EI-only baselines, and check C2 requires
   the R1 trajectory to be explanatory of the R0 outcome (sign agreement on
   ≥80% of rounds in scripted scenarios). Until C1/C2 pass, R1 appears in NO
   decision path (enforced structurally: the scheduler imports only §3.1).

## 5. Ablation design (R0 vs R1, mirrors the campaign's arm style)

Phase 3 stub replay runs four policy arms on identical seeded scenarios:
A1 `R0-greedy` (§3.1 decision rule) — primary;
A2 `EI/(1+α·cost)` (the existing proposed form, AUDIT §2.2) — baseline;
A3 `random` — floor;
A4 `R1-incremental` (uses r_t-shaped score) — admitted ONLY as an ablation
arm, never as the primary, until C1/C2 evidence exists (reviewer's ruling).

## 6. Numerical/maintenance requirements

- Pure functions, stdlib + numpy only; no torch/botorch in the reward path.
- Every realized R0 (and diagnostic r_t) appends one line to the session's
  `SCHEDULER_STATE.jsonl` with terms, weights, and hashes of the legal-input
  snapshot — append-only, fsync, never rewritten (AUDIT §5 constraint 4).
- Determinism under injected clock + seeded stubs; same inputs ⇒ same values.

## 7. Acceptance criteria (executable specs in VERIFICATION_PLAN)

1. Indicator terms: for scripted (q, C, T, D) tuples, R0 matches a
   hand-computed golden table including boundary T = D exactly (1(T≤D)=1).
2. Monotonicity: ∂R0/∂T ≤ 0 for T > D; ∂R0/∂q ≥ 0; ∂R0/∂C ≤ 0.
3. Conditional expectation: with a scripted predictor (known q̂, Ĉ, w-mean,
   p90), score(a) matches the closed-form E1 computation to 1e-9.
4. Fault-blindness: fault-primed and fault-free replays of the same seed
   produce IDENTICAL scores and realized R0 (faults are invisible by
   construction; assert bitwise).
5. Terminal accounting: exactly one session terminal term per episode; crash
   path yields −P and never +B.
6. `zero_model_calls: true` evidence key on every run.

## 8. Open decisions (numbering kept from v0.1; status updated)

- OPEN-D1 module home (default: separate `reward.py` imported by
  scheduler_state). — unchanged
- OPEN-D2 reward family — **RESOLVED by reviewer 2026-10-10: R0 primary,
  R1 candidate/ablation-only.** Kept numbered for traceability.
- OPEN-D3 weights λ_c, λ_t, λ_f, B, P and their calibration procedure on
  stub replay (v0.1's α/β/γ belong to R1 only).
- OPEN-D4 R1's SwitchWaste charged at decision vs settle time (default:
  realized; predicted only for gating) — now diagnostics-scope only.
- OPEN-D5 (new) R0 unit of "task": per evaluation cell (default) vs per
  task-uid vs per session.
- OPEN-D6 (new) time-distribution form for P̂/Ê[(T−D)₊] (default E1 normal
  approx; alternatives tested in phase 3).
- OPEN-D7 (new) confirm R1 is excluded from all decision paths
  structurally (import graph assertion in VERIFICATION_PLAN L6).
