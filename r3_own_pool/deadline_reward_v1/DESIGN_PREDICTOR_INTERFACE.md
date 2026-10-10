# DESIGN_PREDICTOR_INTERFACE — deadline_reward_v1 (rev B)

Status: DRAFT v0.3 (rev B) — predictor target changed from search
configurations to RECOVERY ACTIONS at execution-layer decision points.
Governs phase-2 file `outcome_predictor.py`. Zero model calls, phases 1–3.

## 1. Role

At a decision point (detection event e, task state s, candidate action a),
the predictor returns the three quantities Ê[R0|H,a] needs
(DESIGN_REWARD_FUNCTION §3.2): post-recovery quality belief, incremental
physical cost, and completion-time belief — plus on-time probability via
estimator E1. Time estimates are PURE service demand; switch overhead is
owned by the compensator (scheduler doc §6, no double charge).

## 2. Interface (contract to freeze at review)

```python
@dataclass(frozen=True)
class ActionPrediction:
    q_mean: float;  q_std: float          # post-recovery task-quality belief
    d_cost_tokens: int                     # incremental physical tokens (bound)
    mu_s: float;  w_p90_s: float           # completion-time belief (service only)
    basis: tuple[str, ...]                  # provenance tags of estimators used

class OutcomePredictor(Protocol):
    def observe_episode_feedback(self, fb: EpisodeFeedback) -> None: ...
    def predict(self, ctx: DecisionContext, action: ActionView) -> ActionPrediction: ...
```

- `DecisionContext`: detection event enum (D1–D6), SchedulerState view
  (node statuses, models, recovery counts — scheduler doc §3), deadline
  margin from the compensator, within-episode observed feedback. Structurally
  CANNOT carry gold/fault registry/unexecuted outputs (constructor whitelist;
  firewall tests L2/L3).
- `ActionView`: the action id + its resolved model substitution + enumerated
  call-event list (from the action interface, scheduler doc §4). No future
  outputs.
- `observe_episode_feedback`: legal within-episode signals only (repair
  succeeded/failed per predicates, changed-outputs). OPEN-D8 controls
  whether q̂ uses them (default yes; ablation arm feedback-off).

## 3. Quality side (q̂)

`RecoveryQualityEstimator`: per (detection family, action, model-delta)
success-rate belief, initialized from frozen PRIORS (stub-world constants;
real-data fitting is phase-4 provenance-gated), updated within-episode from
observed repair outcomes (legal feedback), with a beta-style prior so early
episodes are prior-dominated. Never receives this task's gold (§2 firewall;
test L2). Cross-task pooling within a session is allowed (other tasks'
OUTCOMES — ok/cost — become observable only at THEIR termination; gold-free
aggregate statistics only — OPEN-P6 whether pooling uses other tasks'
terminal ok at all; default: no, priors + within-episode only, strictest).

## 4. Cost side (ΔC) — deterministic core

Action event enumeration (reuses the audited tables verbatim; AUDIT II §3,
II §9 — predictor_v3.enumerate_call_events is the precedent; re-implemented
locally, zero production imports):

| Action | Events |
|---|---|
| NONE | 0 |
| LOCAL @D1 (e empty) | e_fb(1 per empty node) + r_fbd·1{facts changed} + v_fbd·1{r changed} (bounds: include both branches, count max) |
| LOCAL @D3 (r unparseable) | r_esc + v_fbd·1{r changed} |
| LOCAL @D4 (r changed) | v_fbd |
| LOCAL @D5 (v fail) | v_esc |
| FULL | 4 planned nodes + (E-arm semantics: alternative-model events on trigger nodes; all-swap semantics: 4 swapped nodes) — bound includes the production cascade caps |

`d_cost_tokens = Σ_events p90_tokens(model(event))` from PRIORS profiles.
Parity test P1 (rev B): enumeration counts per (action, trigger family)
match a frozen golden table derived from the audited production tables —
NOT the search-space size (48/96 issue retired; AUDIT corrections §1).

## 5. Time side (μ, w_p90) + E1 (corrected)

`mu_s = t_now_service_remaining + Σ_events p50_lat(model(event))`;
`w_p90_s` analogously with p90 latencies. Service only — no switch time, no
gaps. On-time quantities (owner: reward doc §3.3):

```
σ  = (w_p90_s − μ_s)/1.2816                # degenerate σ≤0 → point mass
P̂(T≤D)    = Φ((D−μ_s)/σ)
Ê[(T−D)₊] = σ·[φ(z) + z·Φ(z)],  z = (μ_s−D)/σ        # CORRECTED (rev A was wrong off z=0)
```

Feasibility itself is the compensator's call (`w_p90 ≤ margin`), the
predictor stays clock-free and purely computational.

## 6. Implementations shipped in phase 2

| Class | Purpose |
|---|---|
| `PriorOnlyPredictor` | PRIORS + estimators, no learning |
| `RecoveryQualityEstimator` | §3 (priors + within-episode updates) |
| `StubOutcomePredictor` | scripted predictions incl. adversarial (NaN, inf, zero-σ, flip-flop) for F5/B6 tests |
| `CalibratedPredictor` | SKELETON ONLY; raises NotImplementedError until phase-4 authorization (provenance-gated fit on admitted frozen artifacts) |

## 7. Acceptance criteria (contracts; executable specs in VERIFICATION_PLAN)

1. P1 action-event parity vs golden table (per trigger family).
2. L2/L3 schema firewall: DecisionContext/ActionView/feedback reject all
   illegal keys (enumerated LEAK_PROBES.json), incl. nested smuggles.
3. Determinism: same inputs ⇒ bitwise identical ActionPrediction.
4. Degenerate inputs (σ→0, zero-event actions, replay-exhausted) → finite,
   well-defined outputs; NaN/inf never escapes (adversarial stub tests).
5. Profile monotonicity: p90 latency ×k ⇒ w_p90 ×k; boundary flip at
   margin = w_p90.
6. E1 goldens on the CORRECTED closed form (P3), incl. D=μ, D=μ+σ, D≪μ.
7. `zero_model_calls: true`; no network; no filesystem writes outside run dir.

## 8. Open decisions

- OPEN-P1 (revised): q̂ target = task-level terminal quality (v2.1 contract
  semantics); no re-scoring inside the predictor. [unchanged default]
- OPEN-P2 (carried): cache-aware cost refinement — OUT of phase-2 scope
  (stub engine has deterministic cache semantics; refine later).
- OPEN-P3 (revised): quality never gates feasibility (feasibility = cost/time
  only); q̂ enters only through the score. [default unchanged]
- OPEN-P4 (carried): profile granularity per-model (default) vs
  per-(model,node).
- OPEN-P6 (new): cross-task pooling of terminal outcomes into q̂ priors
  (default: OFF — strictest leakage posture).
- OPEN-P7 (new): prior VALUES for (family, action, model-delta) success
  rates and token/latency profiles — stub-world constants set at phase-2
  freeze, listed in PRIORS.json with provenance notes.
