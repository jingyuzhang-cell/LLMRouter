# DESIGN_PREDICTOR_INTERFACE — Phase 1 deliverable 4/4 (deadline_reward_v1)

Status: DRAFT v0.2 (revision A) for phase-1 review. Governs phase-2 file
`outcome_predictor.py`. Zero model calls in all phases through 3.
Executable leakage-firewall test specs live in `VERIFICATION_PLAN.md`
(L1–L6); the §7 list below is the same content in contract form.

## 1. Role

One interface serving three consumers:
- the dynamic scheduler's feasibility gate (`W_predicted(c)`, DESIGN_DYNAMIC_SCHEDULER §2),
- the deadline compensator's demand estimates (§3 there),
- the reward's predicted-work term (DESIGN_REWARD_FUNCTION §3).

It UNIFIES two existing, currently disconnected capabilities (AUDIT §2.5):
the call-event cost enumerator (predictor_v3) and the quality surrogate
(QSurrogate/EI). It must compose with them, not duplicate or import-and-mutate
them (phase 2 re-implements the small enumeration table locally so that no
`collab_scheduler_v1` file is touched; behavior parity is asserted against
predictor_v3's published event table in tests — see §6).

## 2. Interface (contract to freeze at review)

```python
@dataclass(frozen=True)
class Prediction:
    q_mean: float;  q_std: float            # deployment Q belief
    c_upper_tokens: int                     # search-side physical token upper bound
    w_mean_s: float;  w_p90_s: float        # serial service demand est. for THIS round
    feasible: bool;  margin_s: float        # vs the compensator's D̂
    basis: tuple[str, ...]                  # provenance tags of estimators used

class OutcomePredictor(Protocol):
    def observe(self, observation: dict) -> None: ...      # legal schema only
    def predict(self, config: ConfigView, ctx: DeadlineContext) -> Prediction: ...
```

- `ConfigView`: id + X (node→model) + Z. Nothing else from the candidate.
- `DeadlineContext`: current model, D̂ (from compensator), elapsed, remaining
  rounds. Assembled by the driver from legal sources only.
- `observe()` accepts ONLY the observation schema keys
  (`config_id, state, objectives{Q,C,L}, search_spend{...}`); any other key
  (faults, gold, task fields) ⇒ ValueError. This is the leakage firewall at
  the interface level, testable without the scheduler.

## 3. Cost side (deterministic core)

Event enumeration per config (parity with predictor_v3 / AUDIT §2.5):
`NONE → e1,e2,r,v (4); LOCAL → +e_fb×2,r_fbd,r_esc,v_fbd,v_esc (10);
FULL → +4 replay nodes (8)`. Multiply by per-model token/latency profiles:
`Profile(model) = (p50_tokens, p90_tokens, p50_lat_s, p90_lat_s)` from a
frozen `PRIORS.json` (provenance rule of DESIGN_DYNAMIC_SCHEDULER §4 applies:
constants now, campaign-fitted priors only after the phase-4 gate).
`c_upper_tokens = Σ_events p90_tokens(model(e))`;
`w_p90_s = Σ_events p90_lat_s(model(e))` (serial sum — consistent with the
campaign's L semantics, AUDIT §2.1). No cache exploitation in the default:
cross-config cache hits are a known lower-bound refinement, deferred
(OPEN-P2) because search sessions are explicitly no-historical-cache
(runtime.py docstring).

## 4. Quality side

Default `GPQualityEstimator`: wrap `sa_pgfs_v1.surrogate.QSurrogate` with the
5-dim `_feat` encoding [e1,e2,r,v,Z] (audited encoding, selectors.py:27-34);
features computed locally. `observe()` refits on ≥2 points, else returns the
uninformative prior `q_mean=0, q_std=σ₀` (frozen constant). No task-uid
features, no state features (state-blindness preserved, matching the
`proposed_without_state` ablation boundary, AUDIT §2.2).

## 5. Deadline side (bridge to compensator)

`feasible/margin_s` are computed by the caller-injected `D̂` vs `w_p90_s`:
the predictor stays clock-free and purely computational; all timing authority
lives in `deadline_compensator` + the injected clock. This keeps the
predictor unit-testable with plain numbers.

### 5.1 On-time estimator E1 (feeds Ê[R0 | H, a], DESIGN_REWARD_FUNCTION §3.1)

The interface additionally exposes, from `(w_mean_s, w_p90_s)`:

```
sigma = (w_p90_s − w_mean_s) / 1.2816                # normal approx (z_0.9)
P_on_time(D)   = Φ((D − w_mean_s)/sigma)             # P̂(T ≤ D)
E_late(D)      = sigma·[φ(z) + z·(1 − Φ(z))],  z = (w_mean_s − D)/sigma   # Ê[(T−D)₊]
```

Degenerate cases pinned by tests: `sigma ≤ 0` ⇒ P_on_time = 1{w_mean ≤ D},
E_late = (w_mean − D)₊. Distribution form is OPEN-D6 (reward doc);
log-normal / empirical-quantile variants are phase-3 ablations behind the
same two methods, so R0 code never changes when the estimator swaps.

## 6. Implementations shipped in phase 2

| Class | Purpose | Determinism |
|---|---|---|
| `PriorOnlyPredictor` | profiles + priors, no learning | fully |
| `GPQualityEstimator` | priors + QSurrogate quality | seeded fit |
| `StubOutcomePredictor` | scripted predictions incl. adversarial (NaN, inf, zero-std, flip-flop) for F5/F3 tests | scripted |
| `CalibratedPredictor` | STUB SKELETON ONLY: future fitting on admitted frozen campaign artifacts; raises NotImplementedError until the phase-4 authorization exists | — |

## 7. Parity and acceptance tests (phase-3 review)

1. Event-table parity: for all 96 configs, enumeration counts equal the
   predictor_v3 table (4/10/8 by Z) — assert from a frozen golden file
   generated once during phase 2 with zero model calls.
2. Schema firewall: `observe()` rejects every illegal key (enumerated list in
   test), including nested injection (`objectives.__gold__` style).
3. Determinism: same observation stream ⇒ identical Prediction sequence
   (bitwise on floats via seeded GP fit).
4. Degenerate inputs: <2 observations, single-model configs, all-coder v,
   Z=FULL with fault-replay sizing — no NaN/inf leaks past `Prediction`
   construction (adversarial values must be caught, not propagated).
5. Profile monotonicity: scaling any p90 latency profile by k scales
   `w_p90_s` by k; feasibility flips sign correctly around `D̂ = w_p90_s`.
6. Zero model calls (`zero_model_calls: true`), no network imports, no
   filesystem writes outside the run directory.

## 8. Open decisions (finalize at phase-1 review)

- OPEN-P1 whether `q_mean` may use the v2.1-rescored Q only (default: yes —
  it is what observations carry; no re-scoring in the predictor).
- OPEN-P2 cache-aware cost refinement (default: out of scope for phase 2).
- OPEN-P3 quality prior σ₀ and whether an uninformative prior participates
  in gating (default: gating uses cost/w side only; quality never gates
  feasibility).
- OPEN-P4 profile granularity: per-model vs per-(model,node) priors
  (default: per-model; per-node after phase-4 calibration review).
- OPEN-P5 whether `Prediction` should carry interval (p10/p90) instead of
  mean/std for Q (default: mean/std now — matches QSurrogate output; revisit
  if R3 frontier reward is chosen).
