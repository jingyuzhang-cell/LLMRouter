# DESIGN_PREDICTOR_INTERFACE — deadline_reward_v1 (rev C)

Status: DRAFT v0.4 (rev C) — prediction target extended to the JOINT action
a = (Z, R, π) (recovery strategy, re-execution set, model assignment for
affected + unexecuted nodes). Governs phase-2 `outcome_predictor.py`.
Zero model calls, phases 1–3.

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

Feasibility decision itself is the compensator's (`w_p90 ≤ margin`); the
predictor stays clock-free. The filter uses P̂ (distribution), never the
mean alone — the operator's P90 trap is pinned by test V2.

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

## 8. Open decisions

Carried: P1 (q̂ target = terminal v2.1 semantics), P2 (cache-aware cost
refinement out of scope), P3 (quality never gates feasibility), P4 (profile
granularity per-model default), P6 (cross-task pooling default OFF),
P7 (PRIORS values at phase-2 freeze).
New: **OPEN-P8** node-correctness correlation model (default: independent
chain; alternatives: copula/simulation-based — phase-3 ablation);
**OPEN-P9** observed-state belief update rule for reused DONE nodes
(default: frozen bounded table in PRIORS).
