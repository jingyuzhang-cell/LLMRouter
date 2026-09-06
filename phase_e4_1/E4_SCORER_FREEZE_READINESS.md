# E4 Scorer Freeze Readiness — Read-Only Audit

**Date:** 2026-09-05
**Status:** READY_PENDING_PRE_FREEZE_CONDITIONS
**Audit scope:** read-only. No scorer code modified, no formal E4 semantic outcomes accessed, no reserved holdout, no router training, no new judge, no human scoring.

## One-line verdict

Cannot freeze yet. Three pre-freeze conditions remain (B1–B3 below); B4–B5 are small and parallel. Qwen-Max is stable; GLM is fixable via atomic scoring using the **existing** parser; Doubao is engineering-unavailable. The plan ("deterministic + Qwen-Max primary + GLM secondary + Doubao unavailable") is viable but requires a protocol amendment because the frozen rules currently mandate a 3-judge median.

## The four questions

### 1. Which existing code can be directly reused?
- **`phase_e4_1/judge_format_normalization.py` → `parse_scores(raw, labels)`** — strict, score-preserving normalizer (repairs literal newlines / escaped apostrophes, strips ```json fences, validates exact label-set coverage, int 0–4, non-empty reasons). 9 tests pass. Reusable **as-is**, including for atomic single-label scoring.
- **`run_c9_multi_judge_feasibility.py`** — judge call infra (`LLMBackend`, `OpenClawConfig.from_yaml`, `extract_message_text`, `prompt_for`, `read_jsonl`) via `openclaw_router`. Reusable; `prompt_for` is multi-candidate and must be split into a single-candidate variant for GLM. The old loose `parse()` here is superseded — do not reintroduce.
- **`phase_e4_0/interfaces.py`** — frozen workflow-validity dataclass fields. Reusable; the mechanical `Q_delivered` rule must be finalized from these fields.

### 2. Which rules are already frozen?
- **Statistical protocol** (`E4_1_STATE_OBSERVABILITY_PROTOCOL.json`, frozen 2026-09-04): `RTG_t = Q_final(N4)` propagated to N1–N3; 5-fold GroupKFold by `leakage_group_id`; HistGradientBoostingRegressor (frozen hyperparams); DR primary + IPS/SNIPS sensitivity; 10000 group bootstrap; GO/STOP co-primary gates + mechanism_safety; **state shuffling = observability mechanism test, not a judge-bias check**. Fully aligned with the plan.
- **Evaluation route** (`E4_1_EVALUATION_AMENDMENT_001.json`, frozen 2026-09-05): deterministic-primary on 17 numeric-reference-eligible tasks; tolerance `max(1e-6, 1e-4*|ref|)` in reference units; percent/ratio needs explicit task-unit contract; judge format repair = strict normalization only; sensitivity = each-judge / excl-Qwen / excl-GLM; **user authorization for deterministic-primary + machine-secondary already on file**. ⚠️ Secondary metric is defined as "median of three 0–4 /4" and the clause forbids two-family-only consensus — this **conflicts** with Qwen-primary and needs Amendment-002.
- **C9 quality protocol + Amendment-003** (frozen): 0–4 rubric, temperature 0, identity blinding, deterministic SHA-256 candidate order; gates parse_success ≥ 0.95, within-one ≥ 0.80, mae ≤ 0.75, duplicate ≥ 0.80, order-perturbation mae ≤ 0.50.

### 3. Deterministic-scoring: how many tasks are truly usable now?
- **17/40 eligible** (outcome-blind, frozen from task/reference only).
- **0/17 frozen-ready.** All 17 are `REQUIRES_SOURCE_UNIT_VALIDATION` (`reference_unit=null`, `answer_scale=null`) in `E4_1_NUMERIC_UNIT_CONTRACT_PENDING.json`. The reference-independent final-answer extractor is not yet built. `candidate_outputs_accessed=false`.
- To reach 17: freeze per-task unit + scale + multiple-valid-representation rules and build the extractor, validated by synthetic tests before any candidate-output access.

### 4. Qwen-Max / GLM / Doubao engineering status + GLM atomic sufficiency
- **Qwen-Max — 15/15, parse 1.0, missing 0.0.** Passes the 0.95 parse gate. Pairwise within-one 0.94 / spearman 0.87 vs GLM. **PRIMARY, stable.**
- **GLM-4-flash — 10/15, parse 0.667.** Fails the 0.95 gate. Failures are `ValueError` (partial label coverage) and `JSONDecodeError` (self-atomized: emits one `{"scores":[…]}` per label in one response). **Root cause is multi-candidate prompting.** Atomic one-answer-per-call removes the root failure mode.
- **Doubao — 13/15, parse 0.867.** Fails the 0.95 gate. Failures are `TimeoutError` at the 90s timeout (observed 90067ms). **ENGINEERING_UNAVAILABLE** — flag and do not block; retain as the Doubao-only sensitivity arm.
- **GLM normalization suffices for atomic scoring: YES in principle.** `parse_scores` already validates single-label responses (`labels=['X']` accepts `{"scores":[{"label":"X",…}]}`). The multi-candidate failure classes vanish under one-candidate-per-call. **Missing:** the atomic call-orchestration loop + a single-candidate `prompt_for` variant; **the parser needs no change.** Verify parse_success ≥ 0.95 on the 5 failed groups after the switch.

## Remaining blockers before freeze
- **B1 (engineering, no API/outcome access)** — freeze per-task unit/scale/multiple-representation contracts for the 17 deterministic tasks (`E4_1_NUMERIC_UNIT_CONTRACT_PENDING.json`).
- **B2 (engineering, no API/outcome access)** — implement the reference-independent final-answer extractor for the deterministic layer (Amendment-001 `deterministic_readiness_gate`); not yet present.
- **B3 (protocol amendment; user authorization already on file)** — reconcile frozen "median of three / no two-family consensus" with the Qwen-primary + GLM-atomic-secondary + Doubao-unavailable plan via `E4_1_EVALUATION_AMENDMENT_002`; retain raw scores + leave-one-judge-out sensitivity.
- **B4 (small, API-bounded to calibration)** — implement GLM atomic-scoring call loop and verify ≥ 0.95 on failed groups; parser unchanged.
- **B5 (small, no API)** — finalize mechanical workflow-validity rule for `Q_delivered = Q_final · I(valid delivery)` from `interfaces.py`.

## Can we freeze per the plan?
**Not yet.** B1, B2, B3 must close first; B4, B5 proceed in parallel. After they close: freeze scorer → label 160 final N4 outcomes (40 × 4) → propagate `RTG_t = Q_final` to N1–N3 → run **RequestOnly vs SimpleStateAware only**.

## Constraints honored
- Read-only; no scorer code modified.
- No formal E4 semantic outcomes accessed (only engineering/protocol/coverage/calibration-diagnostic artifacts).
- No new judge, no human scoring, no reserved-holdout access, no router training.
- State shuffling is correctly scoped as an **observability mechanism test**, not a judge-bias substitute (judge bias is checked via the deterministic subset, Qwen/GLM agreement, and leave-one-judge-out sensitivity).
- Depth analysis uses `RTG_t = Q_final` for the final-return-value question; local N1–N3 semantic labels are added only for local-mechanism ("why does N2 extract better") questions — not added now.
