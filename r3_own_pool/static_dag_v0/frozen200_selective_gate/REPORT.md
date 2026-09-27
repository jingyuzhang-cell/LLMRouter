# P0-1: Selective Gate Learnability — NEGATIVE result with mechanism (2026-09-26)

**Zero-LLM-call analysis.** No LLM workflow/generation calls of any kind; the
router-risk feature arm uses ONLY the frozen GTE encoder checkpoint
(sentence embedding, deterministic) — no new generation calls. Protocol:
GroupKFold(5) by task, threshold chosen on train folds only, exact per-seed
held-out outcomes. No gold/answer/derivation/`injected`/outcome features.

## Result: the +11.8pp selective-oracle headroom is NOT learnable from
## pre-execution features — and the decomposition says it CANNOT be.

| gate | Q | regret vs oracle |
|---|---|---|
| Always Single | 0.3967 | 0.118 |
| Always Dynamic | 0.4033 | 0.112 |
| Random (50%) | 0.400 | 0.115 |
| Learned (best of 11 model×feature combos) | 0.4033 | 0.112 |
| **Oracle selective** | **0.5150** | 0 |
| Clairvoyant fault-aware (intervene iff fault present) | 0.4917 | 0.023 |

11 combinations (logistic / HistGB / calibrated-HistGB × {lexical,
router-risk, lexical+router}): held-out AUROC 0.39–0.54 (chance). The learned
gates degenerate to "always/never intervene" — their apparent help-capture
(0.44–0.96) is an artifact of intervention rate, with harm avoidance
collapsing to 0.05–0.38. Full tables: `RESULTS.json`, `RESULTS_ROUTER.json`.

## Why (mechanism, `DECOMPOSITION.json`)

- **Clean panel (no faults): Dynamic is NET harmful** — help 8, harm 35
  (Q 0.55 → 0.415). Intervening on healthy tasks breaks ~4× more than it fixes.
- **Fault panel (600 samples, 180 injected)**: help = 71 total, of which
  **57 sit on injected tasks** (fault placement is random per seed →
  unpredictable by ANY pre-execution feature); harm = 67, **all on
  non-injected tasks**. On injected tasks Single is 0/180 and Dynamic
  recovers 57/180 (31.7%).
- **Ceilings**: perfect runtime fault detection → 0.4917 (grabs 0.095 of the
  0.118 gap); the residual 0.023 requires predicting task-intrinsic help
  (14 samples against 67 intrinsic-harm — base rate says don't try).

## Consequence for the second paper

1. **The task-conditioned a-priori gate is dead on this benchmark** — not
   because the models are weak, but because the opportunity is concentrated
   in random fault placement. Any P(help|x) learnable-gate framing hits this
   wall; this negative result should be REPORTED in the paper as the
   motivation for state-conditioned (runtime) intervention.
2. **The learnable signal must be runtime state**: deployable failure signals
   during/after node execution → trust estimation. This matches the existing
   Dynamic detector's 48.4% fault recall (it sees runtime signals; a priori
   features see nothing) and redirects method effort to M1 (trust model) and
   M2 (V(a|s) gating on runtime state), exactly the "diagnosability /
   state observability" bottleneck.
3. **Deployment-relevant bound**: the practical target is the gap between
   Dynamic-with-current-detector (0.4033) and clairvoyant-fault-aware
   (0.4917) — i.e., detector precision/recall on RUNTIME signals, with the
   V(a|s) threshold τ set by the harm/help asymmetry (67:14 on healthy
   tasks → high τ).
4. P0-2 (200-task 3×2 + C′) remains valid and unblocked — it addresses the
   follow-up/reuse axis, orthogonal to this gate axis.

## Artifacts

- `frozen200_selective_gate.py` → `RESULTS.json` (lexical arm)
- `frozen200_selective_gate_router.py` → `RESULTS_ROUTER.json` + `QUESTION_EMBEDDINGS.npz` (router-risk arm, encoder-only)
- `frozen200_selective_gate_decompose.py` → `DECOMPOSITION.json` (clean-vs-fault attribution + ceilings)
