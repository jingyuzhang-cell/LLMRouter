# CALIBRATION_AUDIT_REPORT — zero-call audit of PRIORS_REAL_V1 (commit 252fc80)

Operator review found q_success issues. This is the zero-call audit
BEFORE any supplementary measurement. Frozen artifact SHAs recorded;
no data modified.

## 1. Artifact freeze (never overwrite)

| Artifact | SHA-256 |
|---|---|
| PRIORS_REAL_V1.json | `f5e5092c731c55ce5ac205acf4fd06e972e2b9965e87853372af577ba8794246` |
| CALIBRATION_LEDGER.jsonl | `bb202e2e866684fb5f041ccf3a7cc3ee0322917753eb02a2bb2bbe74a002200f` |

## 2. Corrections to my previous report

**My earlier claim "q_success all zero" was WRONG.** The reviewer
correctly identified that 15/40 cells have non-zero q_success:
- r nodes: 6/8 cells non-zero (q=1.00 for large/medium clean and
  cross-condition — the r prompt asks for a JSON expression and the
  models DO produce parseable `{"expression": "..."}` in many cases)
- v|large: q=0.3667 (the v prompt asks for `{"value": ...}` and
  large produces parseable JSON ~37% of the time)
- e|medium: q=0.10 (medium occasionally produces `{"facts": [...]}`)
- e|coder, e|large, v|coder, and all fault-condition cells: q=0.00

**BUT the reviewer is also correct that these values MEASURE THE WRONG
THING**: they measure raw-output format-parseability
(`json.loads(answer)` → structured-check), NOT the quality the reward
mechanism needs. A format-correct but numerically wrong expression
would be counted as success; a format-incorrect but semantically
correct answer would be counted as failure. Additionally, the
fault-injection conditions used direct answer-overwriting, confounding
model capability with injected corruption.

## 3. What IS valid (confirmed)

- **Latency P50/P90/P95 per (node, model, condition)**: valid real
  measurements (30 samples per cell, all 1,200 call events have
  lat_s, tokens, status).
- **Token P50/P90/P95 per cell**: valid (all calls have token counts).
- **Switch costs (start_s, stop_s per model)**: valid single
  measurements (one start/stop per model; see §5 for the repetition
  gap).
- **Ledger integrity**: 1,200 call events, all with answer_head
  preserved, lat_s, tokens, status. No missing events.
- **Panel isolation**: 30 calibration uids, 0 overlap with evaluation
  panel (8 uids checked). Verified.

## 4. Gaps identified

| Gap | Severity | Impact |
|---|---|---|
| q_success measures format-parseability, not task correctness | **MAJOR** | Cannot use for quality constraints or the reward mechanism's Q_min filter |
| No distribution-family tests (Shapiro-Wilk / D'Agostino) | MAJOR | B4 remains unlanded; E1 estimator family unselected |
| No contention probe | MAJOR | T1 remains unlanded; cross-task waiting unmeasured |
| Switch costs: 1 measurement per model, no repeats | MINOR | Uncertainty unknown; start_s P50/P90 unavailable |
| Answer head truncated to 60 chars in ledger | MINOR | Full answers not preserved; limits post-hoc quality re-analysis |

## 5. Quality metric redefinition (for the supplementary plan)

Three distinct quality metrics must be separated:

| Metric | Definition | Measured through | Used by |
|---|---|---|---|
| **Node format rate** | P(json-parseable output \| node, model) | Single-call calibration (already measured, but mislabeled) | Diagnostic only; NOT for reward |
| **Node conditional success** | P(node produces semantically correct output \| node, model, input) | Single-call + semantic check (evaluate expression, check facts match gold) | PRIORS quality profile |
| **DAG task correctness** | P(final answer matches gold \| full 4-node pipeline, model assignment) | Full pipeline with the frozen scorer (score_v21) | The reward's q and Q_min filter |

The supplementary measurement must produce metrics 2 and 3. Metric 1
should be reported as a diagnostic alongside.

## 6. Supplementary measurement plan (for review before execution)

### 6.1 DAG task correctness (the critical gap)

Run the **real 4-node pipeline** (e1→e2→r→v) with the frozen
evaluation scorer. For each (model-assignment, condition) combination:

- **Configurations**: use the 5-arm model assignments from V2.3
  (SS/DS/SD/DD/NONE × the specific planned models) — this directly
  previews the experimental conditions.
- **Tasks**: 20 tasks per configuration (minimum) from the calibration
  panel (disjoint from evaluation).
- **Per-task recording**: the full pipeline runs e1→e2→r→v with real
  model calls; the final answer is scored against gold using the
  frozen v2.1 scoring contract.
- **Output**: P(task correct | model-assignment) — the actual q the
  reward mechanism uses.
- **Estimated calls**: 5 configurations × 20 tasks × 4 nodes = 400
  calls. With faults/recovery, ~500-600 total.

### 6.2 Node conditional success (quality profile)

For each (node, model, condition) cell, re-check the EXISTING 1,200
responses semantically:
- e nodes: check extracted facts against task gold facts (match
  values, not just format)
- r nodes: evaluate the expression against the facts and check
  correctness
- v nodes: compare the value against gold answer
- Requires: full answer text (not truncated to 60 chars) — need to
  either re-run or find a way to recover from the stub server cache.

### 6.3 Distribution-family tests + contention probe

- Apply Shapiro-Wilk + D'Agostino K² to the EXISTING latency data
  (zero additional calls; purely computational).
- Contention probe: 20 × 2-task shared-executor trials on the stub
  with the real PRIORS profiles (zero additional real calls; stub
  uses the real latency distributions).

### 6.4 Switch cost repeats

5 start/stop cycles per model → start_s P50/P90. ~15 additional
model-load cycles (no inference calls; just load/unload).

### 6.5 Budget estimate

| Component | Requests | Tokens (est.) | Wall (est.) |
|---|---|---|---|
| 6.1 DAG correctness | ~600 | ~400K | ~30 min |
| 6.2 Node re-scoring | 0 (re-analysis) | 0 | 0 |
| 6.3 Tests + probe | 0 | 0 | ~5 min |
| 6.4 Switch repeats | 0 | 0 | ~15 min |
| **Total** | ~600 | ~400K | ~50 min |

## 7. What remains gated

- Experiment GO: HOLD until quality metrics 2 & 3 are measured,
  distribution tests pass, and contention probe runs.
- No reward weight or Q_min adjustment based on the quality-gap
  discovery (the frozen protocol's Q_min=0.80 stays; if real quality
  is below 0.80, that is an experimental result, not a reason to
  lower the bar).
- No five-arm experiment until the operator approves.
