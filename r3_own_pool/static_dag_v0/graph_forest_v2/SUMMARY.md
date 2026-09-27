# Graph Forest v2 — Zero-Call Diagnostic Package (2026-09-26)

Post-processing of frozen artifacts only. **Zero model calls, zero GPU.**

- `graph_forest_v2_diagnostic.py` → `DIAGNOSTIC.json|md`: exact expected follow-up
  values derived from gold programs; v1 regen values classified.
- `graph_forest_v2_reuse_arm.py` → `REUSE_ARM.json|md`: stored round-1 expressions
  re-executed on modified facts (Arm B) vs v1's regenerate arm (Arm A).

## Verified inputs (all numbers in the external advice check out)

| claim | artifact | value |
|---|---|---|
| v1 call reduction | `graph_forest_v1/RESULTS.json` | 0.50 (80→40 calls) |
| v1 token reduction | same | 0.9141 |
| v1 executes / responds | same | 19/20, 19/19 |
| v1 verifier_accept | same | **0** |
| Frozen200 Single/Dynamic | `frozen200/FROZEN200_CORRECTED_SUMMARY.json` | 0.3967 / 0.4033 |
| Frozen200 recovery rate | unchanged per FZ-1 fix | 48.4% (15/31) |
| Selective oracle | same | 101/200 |

## Finding 1 — verifier_accept = 0/19 decomposes into 16 correct rejects + 3 false rejects

Expected follow-up value = gold program mapped onto gold facts (mapping arbitrated
by exact reproduction of the gold answer; 20/20 mapped, 0 failures), then
facts[0] × 1.1 substituted, evaluated in exact Fraction arithmetic.

- **V1_DRIFT = 16**: regen value wrong, median |rel_err| = 66.7%.
  Drift taxonomy: ×100 percent over-application (~5), +10% double-application
  (exactly ×1.1, ≥1), no propagation (new == old exactly, 2), structural formula
  change (spurious /3, rewritten formula).
- **V1_CORRECT = 3**: value exact; the verifier rejected them anyway → the LLM
  verifier has **no discriminative power** (rejects everything; its 84% accuracy
  is pure base rate). It was given only a number, no expression/derivation.
- Exact quality retention of v1's regen arm: **3/19 ≈ 15.8%**.

## Finding 2 — reuse beats regeneration: 12/20 at 0 calls vs 3/20 at 2 calls/task

Root cause of v1's quality collapse: the follow-up **re-called the model to
regenerate the expression** (`graph_forest_v1.py` line ~98) instead of
re-executing the expression already stored in round 1. Round-1 responses for all
3 models are frozen in `fresh_static_confirmation/{model}_RESPONSES.jsonl`, and
both rounds present facts in the node's `gold_facts` order
(`sorted(set(operand_values(program)))`) → v-indices are consistent, so stored
expressions can be re-executed legitimately.

| arm | calls/task | correct | notes |
|---|---|---|---|
| A regen (v1, run) | 2 | 3/20 | 1 exec failure (IndexError) |
| B reuse (this pkg) | **0** | **12/20** | 0 exec failures; B also succeeds on A's failed task |

**Correctness inheritance is exact: round1_correct == reuse_correct on 20/20
tasks.** Reuse propagates modifications deterministically and never introduces
new errors; its quality ceiling is the round-1 expression's own correctness
(12/20 = 60% on this panel).

## Finding 3 — the residual 8 failures are write-time errors, not reuse errors

Every arm-B-wrong task stores an already-wrong round-1 expression:
`((v1-v0)/v0)*100` (percent scaling, ×2 tasks), `(v0+v1)*100/2`, `v1` (partial
formula), `v1 - v0` (missing division), `v1/v0`, spurious `/3`. Fix direction:
**verify at write time** (expression sanity / selective cross-check when the
node enters the forest), not regenerate at follow-up time.

## v2 design implications

1. Follow-up policy becomes **Reuse-first**: input diff → descendant closure →
   re-execute stored deterministic artifacts; regeneration only for structural
   changes (new facts, question-type change), gated by expected net value.
2. Verifier redesign: judge the (expression, modified facts) pair, or replace
   with exact re-execution consistency at evaluation time; report verifier ROC
   separately from generation quality.
3. `responds_to_modification` was noisy (float-ε counted as True); v2 uses the
   exact expected value as ground truth for both metrics.
4. Next GPU experiment (small): three-arm paired follow-up study
   (reuse / regen / fresh full chain) × write-time-verification on/off,
   frozen 200-task panel, report Q/C/L.

## Second-paper positioning update

RQ1 (does the forest have reuse value?) moves from "cost proven, quality
unproven" to a precise mechanism: **reuse is correctness-preserving and
call-free; quality is bounded by write-time node correctness** — which is
exactly the selective-intervention story of Frozen200, now at the node level.
