# WIRING_STATUS.md — Unified Acceptance Report (2026-10-09, v2.7)

Single source of truth for all pipeline wiring evidence. Supersedes all previous
partial reports and the v1 of this file. Items grouped by status.

## PASS: Production Pipeline

**Path**: `ProductionSelector.select()` → `SearchSession.step()` → `JointEvaluator.evaluate()` → `MeteredExecutor.call()` → `Budget` → `observe_evaluator_result()` → next `select()`

**Evidence**: `review/unified_test.py` → `review/UNIFIED_PIPELINE_EVIDENCE.json` (12/12)
- All 6 methods run through SearchSession→JointEvaluator→Budget ✅
- Incremental cost predictor called BEFORE each selection ✅
- Both clean and fault30 states evaluated ✅
- Budget tracked actual token usage ✅
- Methods produce different selection sets ✅

**qNEHVI implementation used in the 6-method pipeline** (v2.3): the OFFICIAL
BoTorch estimator (`botorch_qnehvi_scores`, Track A aligned) scores all
qNEHVI-family methods; `scalarized_bo` uses the self-built GP posterior mean.
The old self-built joint-posterior estimator remains as the Track A alignment
reference and is no longer used for selection.

## PASS: Ablation Isolation

**Evidence**: `review/unified_test.py` (Part B/C) + `review/acquisition_evidence.py`
- State-blind picks identical across clean/fault30 (insensitive) ✅
- Feature dimensions differ (state bit present vs absent) ✅
- use_state/use_cost flags correctly set per method ✅
- Cost divisor removal exactly recovers base scores ✅
- Ranking changes with cost toggle (corr=0.994≠1.0) ✅
- Both ablations share SAME JointPosteriorGP + exact_qnehvi_score ✅

## PASS: Q Scoring Controls

**Evidence**: `review/Q_CONTROLS_AND_SCORES.json` (9/9)
- Q=1 positive control: facts(1.5,2.5), expr(v0+v1), v={"value":4.0}, gold=4.0 → **Stub Q=1.0 via formal scoring path** ✅
- Q=0 negative control (wrong value): v returns 999 → Q=0.0 ✅
- Q=0 negative control (unparseable): v returns {} → Q=0.0 ✅
- Previous Q=0 root cause: gold=4.0 (make_task default, not 200); stub {} → None → Q=0 ✅
- Note: "Q=1.0" here means through the formal JointEvaluator→eval_config→scoring path with Stub dispatch, NOT a real LLM result.

## PASS: Official BoTorch qNEHVI Alignment (Track A, 2026-10-09)

**Evidence**: `review/track_a.py` → `review/TRACK_A_EVIDENCE.json` (7/7)

BoTorch 0.18.1 installed. Alignment under one pinned problem spec — same GP
(SingleTaskGP + train_Yvar, FIXED hyperparameters: ScaleKernel(1.0)×Matérn5/2,
lengthscale 0.4, noise 0.02, zero-mean fit on centered y, no transforms), same
data, same objectives (maximize (Q,C_norm,L_norm), ref point (0,0,0), Q
uncertain via GP, C/L deterministic per config):

- GP posterior: latent mean max diff **1.6e-15**, std max diff **2.8e-14** ✅
- Hypervolume: `sa_pgfs_v1.pareto.hypervolume` vs BoTorch
  `DominatedPartitioning` max rel err **1.6e-16** (6 point sets incl.
  dominated and ref-dominated points) ✅
- qNEHVI MC estimator (6144 samples/side): Spearman **0.997**, **100%** of
  38 candidates within 3σ MC bounds; argmax is a statistical tie (top pair
  score-identical to 5dp, each estimator ranks the other's argmax #2) ✅
- Score distribution non-degenerate ✅

**Official implementation for our problem class**: `track_a.botorch_qnehvi_scores()`
— BoTorch qNEHVI with a single-output Q model and an `MCMultiOutputObjective`
(`QConstantCL`) that attaches deterministic per-config C/L and restores the
y-mean offset. This handles the "only Q is uncertain" objective structure
BoTorch has no canned constructor for.

**Registered semantic deltas of the old self-built in-loop estimator**
(`exact_qnehvi_test.py`; kept as alignment reference only):
(a) sampled with +0.02 observation-noise diagonal vs BoTorch latent sampling;
(b) clipped samples to [0,1]; (c) implicit constant prior mean at empirical
y-mean (equivalent to ConstantMean(ȳ) — not a bug).

**Label issue RESOLVED**: the production closed loop now scores all qNEHVI-family
methods (`official_qnehvi_same_state`, both `proposed_*`, `wo_*`) through the
official BoTorch estimator — Track B rerun after the swap: 20/20 PASS, 32
distinct / 43 nonzero scores of 44 candidates (`TRACK_B_EVIDENCE.json`).

## PASS: Independent Task Panel + Power + Budget Fit (Track C, 2026-10-09)

**Evidence**: `review/track_c.py` → `review/TASK_PANEL_V1.json` +
`review/TRACK_C_EVIDENCE.json` (14/14). Fills the protocol's
`task_panel: UNASSIGNED` gap; SEARCH_BUDGET_V1.json left untouched (hash-bound),
superseded by manifest reference.

- **Provenance**: same lineage and eligibility as the 4-node DAG panels
  (TAT-QA train, `answer_from=table-text` so BOTH extractors are load-bearing,
  arithmetic, evaluable derivation, ≥2 distinct literals, tokenizer guard
  prompt+512≤8192 applied before split). Exposure scan = UUID superset over the
  whole workspace excluding raw `data/` sources — strictly stronger than the
  historical static_dag_v0-only scan; frozen200/smoke/fault30 tasks all
  excluded. 97 fresh tasks remain of 538 eligible ✅
- **Split** (hash-frozen `sha256("jointsearch_v1:"+uid)` ascending):
  SEARCH8 (in-session panel, identical for all 6 methods × 3 seeds) + TEST16
  (never evaluated during search; one-shot confirmatory evaluation of final
  selections) + 73 reserve. Disjoint, deterministic, zero prior exposure ✅
- **Power** (paired-binary from frozen200 corrected per-task arms, variance
  prior only): historical discordance D=0.08 (clean static-vs-dynamic) to
  0.155 (clean-vs-fault). MDE(SEARCH8)≈0.34 — per-config Q estimates cannot
  resolve small differences, acceptable because search SELECTS, it does not
  test; MDE(TEST16)≈0.24 on paired marginal delta; n=42 needed for MDE 0.15
  (registered as an honest limitation; sub-0.24 effects need pooled seeds) ✅
- **Budget fit**: 18 sessions = 6 methods × 3 seeds exactly; per-session
  scenario 330 requests ≤ 400 cap, 123.6k tokens ≤ 3.28M cap, 2201s ≤ 7200s ✅
- **Confirmation allocation** (TEST16 final evaluations, OUTSIDE the 18
  sessions): recomputed at the FULL call ceiling (v2.5) — 6×2×16×12 = 2304 max
  logical calls; HARD upper bound 2304 requests / 18,874,368 tokens (reservation
  basis, failed calls retain full reservation); realistic estimate ≈ 863k tokens
  (mean 374.5 tok/req). The earlier 0.58M figure was an optimistic mean-basis
  estimate and is superseded. Declared for approval: the HARD bound.
- Manifest status `FROZEN_FOR_APPROVAL_EXECUTION_NOT_AUTHORIZED`.
- Budget-fit caveat (registered): caps are operational ceilings, NOT completion
  guarantees; the 330-request scenario reference under the 400 cap does not
  ensure completion with new configs and FULL; incomplete runs reported as
  measured (stopping rules in SEARCH_BUDGET_V1).

## PASS: Cross-State Production Closed Loop + Full-Identity Cache Prediction (Track B v2, 2026-10-09)

**Evidence**: `review/track_b.py` (v2, same file — no parallel suite) →
`review/TRACK_B_EVIDENCE.json` (**15/15 ALL PASS**). Supersedes the v1
single-state closed loop (20/20) after review identified two admission gaps.

**Gap 1 fixed — cache deduction by full identity, not node+model**:
`CacheIdentityPredictor` verifies the complete per-(state, task) identity chain:
e=(node, model); r=(m_e1, m_e2, m_r); v=(m_e1, m_e2, m_r, m_v) with Z-context in
fault30 (e-node faults are rerouted at extraction stage, so v's realized input
is recovery-path dependent). Unknown successors are never predicted as hits.
Verified against the executor's own TRAJECTORY.jsonl hit records:
- **precision = 1.0 for all six methods** — every predicted hit is an actual
  hit; the incremental estimate never underestimates new search tokens ✅
- e/r recall = 1.0 (exact); v recall 0.40–0.57 conservative by design —
  recovery-driven cache population (v escalation, FULL replay chains) is
  output-dependent and outside the searcher's information boundary; unpredicted
  hits are charged as new ✅
- recovery charged conditionally: E[new tokens] = overhead × P_fire(state),
  frozen params; measured recovery-call counts reported per method ✅
- the reviewed counter-example is now a pinned test: same e-models + different
  r-model ⇒ e hit, r charged NEW ✅

**Gap 2 fixed — clean+fault30 in the SAME loop**: every selection is evaluated
on both states with a real fault panel (r-corruption + empty-e2-facts).
- both states observed per selection (10 obs / 5 selections × 6 methods) ✅
- fault30 Q is Z-dependent inside the loop (NONE=0, LOCAL/FULL recover) ✅
- per-state acquisition scores non-degenerate from pure evaluator data ✅
- state ablation diverges WITHIN this loop (aware vs blind pick sequences) ✅
- state-blind search is label-invariant (swapping state labels changes nothing) ✅
- calibration Spearman(est, actual C) = 0.798 over 20 (config,state) units ✅

**Gap 3 — C/L information boundary**: evaluated units use ACTUAL evaluator C/L;
candidates use frozen ex-ante predictions; identical boundary for all six
methods; ablations toggle only declared bits (state features / cost divisor).

**Stub semantics for this wiring admission** (zero real calls): output-coupled
chain (v recomputes from r's expression over parsed facts — r corruption
propagates to Q), model-tagged outputs (facts evidence and expression spacing
vary by model) so cache identity structure matches real deployments. Registered
limit: clean-state stub Q is uniformly 1.0; real-model heterogeneity expected
to strengthen, not change, the wiring.

## PASS: Cost Predictor Counter-example Fix (Track B v1, 2026-10-09 — superseded by v2 above)

v1 separated deployment vs incremental cost and calibrated against smoke
counter-examples (HET-LOCAL +245%, QUAL-LOCAL est-1430-vs-0, HET-NONE −49%).
v2 replaces the incremental estimator with the full-identity predictor.

## PASS (DIAGNOSTIC): Per-Round Candidate Score Distribution

**Evidence**: `review/Q_CONTROLS_AND_SCORES.json`
- 40 candidates, 30 distinct @10dp, 31 nonzero, 1 tied@max (2.5%)
- Range [0, 0.0022], std 0.0006, non-degenerate, all finite
- **Scope**: mixed observations (superseded for closed-loop claims by Track B
  above; retained as acquisition-function diagnostics)

## PASS: FULL Reachability

**Evidence**: `review/exact_qnehvi_test.py` (8/8) + `review/wiring_test.py` (13/13)
- FULL present in 48-config space (16 FULL configs) ✅
- Random search selects FULL with sufficient budget ✅
- Acquisition selects FULL when FULL Pareto-dominates ✅
- Cost-aware EHVI correctly avoids FULL when cost high (documented behavior) ✅

## PASS: Prior Unit Tests (not superseded)

- `test_evaluator.py`: 8/8 (48 configs execute, FULL=8 calls, cache, fault cost, detector) ✅
- `test_runtime.py`: 10/10 (campaign quotas, GPU lock, crash recovery, fail-closed) ✅
- `review/wiring_test.py`: 13/13 (features, C/L estimates, 6 methods through stub) ✅

## BLOCKING: FULL + New Fault Billing Real Validation

Stub-verified (8 logical calls, swapped models, both charged). Requires
small-scale real LLM validation before formal experiment.

## NOT STARTED: Formal Experiment Protocol Freeze

Data splits, sample size, budget, stopping rules — awaiting blocking items.

## Summary

| Item | Status | Evidence |
|---|---|---|
| Cross-state closed loop + full-identity cache prediction (Track B v2) | ✅ PASS (15/15) | TRACK_B_EVIDENCE.json |
| Cache prediction vs executor ground truth | ✅ precision 1.0 all methods | TRACK_B_EVIDENCE.json |
| Production pipeline 6 methods (official BoTorch qNEHVI wired) | ✅ PASS | UNIFIED_PIPELINE_EVIDENCE.json + TRACK_B_EVIDENCE.json |
| Ablation isolation (in-loop, cross-state) | ✅ PASS | TRACK_B_EVIDENCE.json |
| Q scoring controls (Stub via formal path) | ✅ PASS | Q_CONTROLS_AND_SCORES.json |
| FULL reachability | ✅ PASS | EXACT_QNEHVI_TESTS.json |
| Evaluator (48 configs) | ✅ PASS | test_evaluator.py 8/8 |
| Runtime (quota, GPU, crash) | ✅ PASS | test_runtime.py 10/10 |
| Official BoTorch qNEHVI alignment (Track A) | ✅ PASS (7/7) | TRACK_A_EVIDENCE.json |
| FULL real validation (envelope A) | ✅ COMPLETE (min scope exceeded, 4/4 S4=0-req) | FULLVAL_STAGE1_REPORT.json |
| Task panel / power / budget (Track C) | ✅ PASS (14/14) | TASK_PANEL_V1.json |
| TEST16 envelope (hard bound 2304 req / 18.87M tok) | ✅ recomputed | ADMISSION_PACKAGE_V1.json |
| Formal experiment freeze | ⏳ MANIFESTS FROZEN, staged approval | ADMISSION_PACKAGE_V1.md |

## Next Steps

**Single admission package**: `ADMISSION_PACKAGE_V1.md` / `.json` (2026-10-09).
Staged approval only — Stage 1: finish FULL validation (envelope A, already
authorized; 3 of 4 calibration tasks remain, S4 cache-reuse already verified at
0 new requests). Stage 2: formal search (envelope B = 18 sessions + TEST16
sub-envelope at the hard bound) decided ONLY from stage-1 measurements.

**Track A — DONE**. **Track B v2 — DONE** (cross-state + full-identity cache,
this file). **Track C — DONE** (TEST16 bound recomputed at call ceiling).


## RUN ADMISSION AUDIT 1 (2026-10-09, post-pause) — v2.6

Formal campaign dispatch PAUSED after review flagged scoring-admission gaps.
Audit (RUN_ADMISSION_AUDIT_1.md, zero-call):

- **Old-gold defect CONFIRMED in the running wiring**: scoring used
  eval-derivation golds. Contamination: SEARCH8 1/8, TEST16 7/16,
  calibration 1/4 (percent-scale x100 class; t1 annotation 517.5 vs 5.175 —
  correcting my earlier wrong attribution to prompt/gold mismatch).
- Re-scored under final contract (GOLD_CONTRACT_V1): session-1's 8 evaluations
  show NO numeric flip but are registered DIAGNOSTIC (selection-bias risk was
  real). FULLVAL t1 flips 0→1 on all four scenarios — stage-1 quality now
  2/4 clean-correct; recovery-preserves-correctness confirmed on t1 AND t4.
- Budget: per-session 400 x 18 = 7,200 = frozen campaign cap exactly — NO
  expansion. Consumed before pause: 299 req / 48,707 tok (journal corrected).
- FORMAL_LAUNCH_V2 frozen (corrected golds, diagnostics registered,
  prior consumption carried). **Dispatch remains PAUSED pending review
  decision. TEST16 not released.**
- Session-1 "state-conditioned signal" claim downgraded to: state differences
  were observed; no search-efficiency or method-superiority claim.


## DIAGNOSTIC CAMPAIGN REGISTRATION (v2.7, review directive)

The running formal campaign is registered **DIAGNOSTIC — automation complete !=
formal admission** until the scoring protocol aligns with the executed version.
No new campaign stages; TEST16 not released; algorithm-advantage discussion
blocked until ALL of:

- **A. Scoring consistency**: per-session hashes of the executed scoring path
  (evaluator.py + fault30_run.py) and the gold manifest the session ran with
  (TASK_PANEL snapshot = GOLD_CONTRACT_V1 answers); re-score under scoring
  contract v2.1 (contract_v2_gold + score_v21 = close OR round-2dp);
  sessions with Q flips are NOT mergeable across contracts.
  FLAGGED: `task_contract_v2/SEARCH8_V21_MANIFEST.json` covers a DISJOINT
  8-uid set (0/8 overlap with the executed TASK_PANEL_V1 panel; includes
  excluded P1-B uid 0dc550d6) — never merge across panels.
- **B. Quota settlement**: every claim ledger-proven from the session DISPATCH
  journal (reserve/response+usage); random_20261009's 0-request claim proven by
  absent ledger, not inferred; incomplete/failed cells billed and retained;
  retry consumption additive, totals never reset (cross-directory ceiling
  6,901 = 7,200 frozen - 299 v1 diagnostic).
- **C. Comparison basis**: search physical (requests / tokens / wall /
  model-switch wall) reported separately from deployment Q/C/L per state;
  budget-exhausted INCOMPLETE cells retained in all tables.

Implementation: `reconcile_formal_campaign.py` (zero-call) runs all three
checks; `FORMAL_CAMPAIGN_RECONCILIATION.json` is the wrap-up artifact. The
post-campaign chain runs reconciliation + descriptive digest automatically
when all drivers (main + collision retries) finish. Partial snapshot: 3 cells,
193 ledger-proven requests, 0 v2.1 flips so far, panel overlap 0 flagged.
