# DESIGN_PREDICTOR_INTERFACE — deadline_reward_v1 (rev D)

Status: DRAFT v0.5 (rev D) — applies review rulings of 2026-10-10
(baseline fc201ae + interim 57f2553): OPEN-P3 retired (quality gates
feasibility via Q_min), E2E composition rule fixed, B1/P7 rulings recorded.
Governs phase-2 `outcome_predictor.py`. Zero model calls, phases 1–3.

## 1. Role

At a decision point, for each candidate joint action a, return the three
quantities the two-stage decision needs (DESIGN_REWARD_FUNCTION §3.2):
post-action task-quality belief q̂(a), incremental physical cost ΔC(a), and
completion-time belief (μ, w_p90)(a) — from which E1 supplies
P̂(T≤D_remain) and Ê[(T−D)₊]. Time = PURE service demand; switches owned by
the compensator (no double charge).

## 2. Interface

```python
@dataclass(frozen=True)
class ActionPrediction:
    q_mean: float;  q_std: float
    d_cost_tokens: int                     # ΔC(a): re-exec(R) + first-exec(unexec under π)
    mu_s: float;  w_p90_s: float           # completion-time belief (service only)
    basis: tuple[str, ...]

class OutcomePredictor(Protocol):
    def observe_episode_feedback(self, fb: EpisodeFeedback) -> None: ...
    def predict(self, ctx: DecisionContext, action: ActionView) -> ActionPrediction: ...
```

- `DecisionContext` (rev C): detection event (D1–D6), SchedulerState view
  incl. **reuse_set, unexec_set, node menus**, D_remain, B_remain,
  compensator margins. Constructor whitelist; structurally cannot carry
  gold / fault registry / unexecuted-node outputs (L2/L3).
- `ActionView`: (Z, R, π) fully resolved — model binding per node in
  R ∪ unexec, reuse decisions, enumerated call-event list.

## 3. Quality side — node-level chain under π (rev C)

`JointQualityEstimator`: per-(node, model) correctness priors from PRIORS
(scaled by detection family when the node is the detected-fault node);
within-episode repair feedback updates the failed node's belief (legal,
OPEN-D8). Default combination over the FINAL answer path
(e1,e2 → r → v): **independent-chain product** over nodes whose outputs the
final answer depends on — re-executed nodes under π use their π-model
priors; reused DONE nodes use their observed-state belief (a node that
passed detection has elevated correctness belief vs its raw prior — a
bounded update rule frozen in PRIORS). Correlations (e.g., same-model
co-dependence) = OPEN-P8 (default: independent). q̂ NEVER sees this task's
gold (L2); cross-task pooling default OFF (OPEN-P6 carried).

The 95/85/60-style numbers in the worked example (scheduler doc §2a) are
exactly this q̂ under three different π's — predicted from state, never
future truth.

## 4. Cost side — ΔC(a) with reuse (rev C)

Enumerate call events for R ∪ unexec under π, EXCLUDING reused nodes
(zero new cost — cache semantics mirrored from production,
smoke_runner.py:114):

| Component | Events |
|---|---|
| re-exec of n ∈ R under π(n) | 1 (+ cascade events per production recipe if Z=LOCAL) |
| first-exec of n ∈ unexec under π(n) | 1 |
| reused DONE nodes | 0 |
| FULL (Z) | per chosen FULL semantic (OPEN-B1; E-arm default) |

`ΔC(a) = Σ_events p90_tokens(model(event))` from PRIORS profiles.
Parity P1 (carried, action-event golden tables; search-space sizing
retired).

## 5. Time side — critical-path aggregation + E1 (corrected, carried)

Completion-time belief aggregates SERVICE latencies over the remaining DAG
under π using the **production critical-path rule as precedent**
(fault30_run.py:451-463: max over e-branches + Σ r + Σ v, serial
recovery-in-branch), with CLOSURE structure (multidag_dynamic.py:59):

```
mu_s    = Σ p50_lat over critical path of (remaining DAG under a)
w_p90_s = path-conservative p90 aggregation (default: sum of per-node p90
          on the critical path; per-node p90 per (node, model) from PRIORS)
σ = (w_p90 − μ)/1.2816 ;  P̂(T≤D) = Φ((D−μ)/σ) ;
Ê[(T−D)₊] = σ[φ(z) + zΦ(z)],  z = (μ−D)/σ          # corrected rev A error
```

**E2E composition (rev D, review ruling 3):** the quantity the on-time
constraint compares is the REMAINING-TO-COMPLETION E2E time of the WHOLE
DAG — unexecuted nodes + recovery cascades + necessary model switches, from
the decision instant. Ownership stays split (predictor = service,
compensator = switches) but the POLICY composes them before E1, exactly
once:

```
μ_E2E(a) = μ_service(a) + switch_overhead(a)      # compensator-injected
σ from service p90 (switch estimates deterministic priors; switch-variance
    modeling = OPEN-P8 companion)
P̂(T_a ≤ D_remain) and Ê[(T−D)₊] computed via E1 on (μ_E2E, σ)
```

B6 audits that switch overhead enters exactly one term. The predictor
itself stays clock-free and returns service-only values; it never estimates
only the fault node's repair — its event set always covers R ∪ unexec under
π (§4).

**Feasibility (rev D, review ruling 2 / replaces retired OPEN-P3):** an
action is feasible iff ALL THREE hold — `q̂(a) ≥ Q_min` (whole-DAG final
quality prediction, §3 — NOT an isolated model accuracy), `P̂ ≤` rule above
`≥ 1−ε`, and `ΔC(a) ≤ B_remain`. Quality gating is part of the filter by
design; the retired rev B/C default ("quality never gates feasibility") is
VOID. `w_p90 ≤ margin` remains the compensator's hard safety view. The
filter uses the distribution, never the mean alone — pinned by test V2.

## 6. Implementations shipped in phase 2

| Class | Purpose |
|---|---|
| `PriorOnlyPredictor` | PRIORS + estimators, no learning |
| `JointQualityEstimator` | §3 (priors + observed-state updates) |
| `StubOutcomePredictor` | scripted predictions incl. adversarial (NaN, inf, zero-σ, flip-flop, mean-pass/P90-fail) for F5/V2/B6 tests |
| `CalibratedPredictor` | SKELETON ONLY; raises NotImplementedError until phase-4 authorization (provenance-gated) |

## 7. Acceptance criteria (carried from rev B §7; rev C deltas)

Carried: P1 parity, L2/L3 firewall, determinism, degenerate inputs,
monotonicity, E1 goldens, zero-call. Added:
1. Reuse zero-cost: ΔC excludes reused nodes exactly (V5 companion).
2. π-sensitivity: changing π(n) for any n ∈ R ∪ unexec changes q̂/ΔC/μ in
   the documented direction (monotone in profile ordering; golden grid).
3. Chain semantics: q̂ strictly increases when a FAILED node's π-model
   upgrades (PRIORS ordering), all else fixed.

## 8. Open decisions & rulings (rev D)

**RULED by operator review 2026-10-10 (no longer open):**
- ~~OPEN-P3~~ **RETIRED** — quality DOES gate feasibility via Q_min on the
  whole-DAG q̂ (§5 feasibility block).
- **B1 (predictor side)**: static FULL baseline = net-benefit E-arm matched
  semantics; DYNAMIC FULL may carry its own π, and every applied FULL is
  recorded with (scope, model-delta) separated so scope and model effects
  stay attributable.
- **P7**: PRIORS.json may contain SYNTHETIC stub priors WITH provenance
  notes; they must never be labeled real-model calibration, and confirmation
  tests must not write/tune PRIORS (read-only; V7 enforces).

Still open: P1 (q̂ target semantics — default terminal v2.1), P2
(cache-aware cost refinement — out of phase-2 scope), P4 (profile
granularity per-model default), P6 (cross-task pooling — default OFF), P7
VALUES (stub prior numbers at phase-2 freeze), **P8** node-correctness
correlation model (default independent chain), **P9** observed-state belief
update rule for reused DONE nodes (default frozen bounded table), **P10**
(new) switch-variance treatment in σ (default: deterministic switch
estimates, σ service-only).
