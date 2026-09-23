# Corrected Results — 4-node DAG 120-task panel (fixed json_value parser)

All numbers below are re-analyses of the frozen executed data with the fixed
v-parser (see BUG_REPORT.md). Zero new model calls. Not an independent
confirmation. All 120 tasks kept in denominators. Budget accounting: post-hoc
violation statistics vs 1.2 x Static-arm realized tokens (arms ungated, same
口径 for all).

## 1. Main table (corrected)

| Arm | Q | mean tokens | total tokens | adaptation calls | mean latency s |
|---|---:|---:|---:|---:|---:|
| static | 0.3917 | 2759.4 | 331,132 | 426 | 7.79 |
| dynamic (ideal) | 0.4250 | 2664.5 | 319,740 | 426 | 7.33 |
| SM (Static-Matched) | 0.4167 | 2799.1 | 335,888 | 425 | 8.67 |
| RD (Dynamic-Real, local) | 0.4000 | 2323.7 | 278,844 | 309 | 6.69 |
| FG (Full-Graph, new) | 0.3750 | 3346.6 | 401,592 | 592 | 10.36 |

Paired tests (task bootstrap CI, seed 20260918, B=10000; McNemar exact):

| Pair | dQ | CI | Help/Harm | McNemar p |
|---|---:|---:|---:|---:|
| dynamic vs static | +0.0333 | [−0.0250, +0.0917] | 8 / 4 | 0.388 |
| SM vs static | +0.0250 | [−0.0167, +0.0667] | 5 / 2 | 0.453 |
| RD vs SM | −0.0167 | [−0.0750, +0.0417] | 5 / 7 | 0.774 |
| RD vs static | +0.0083 | [−0.0500, +0.0667] | 7 / 6 | 1.000 |
| FG vs RD | −0.0250 | [−0.0583, 0.0000] | 0 / 3 | 0.250 |
| FG vs SM | −0.0417 | [−0.1000, +0.0083] | 3 / 8 | 0.227 |

RD retention (corrected): (Q_RD − Q_static)/(Q_dynamic − Q_static) = 0.249.

## 2. Local vs full-graph re-execution (the FG comparison, corrected)

- FG vs RD: no significant quality difference (FG never helps, harms 3 tasks;
  all 3 within measured session nondeterminism — 38 same-prompt divergences in
  the corrected FG set, concentrated in the 14B GPTQ model).
- Scope savings of RD over FG: 1,023 tokens/task (−31%), 283 adaptation calls
  (−48%), 3.67 s/task (−35%). Unaffected-branch repeats in FG: 217 (1.81/task);
  redundant calls: 277.
- Budget violations (post-hoc): FG 45% at 1.2x, 12% at 1.5x, 1.7% at 2.0x,
  0% at 2.5x; RD 5% at 1.0x, 0% from 1.2x up. FG's problem is efficiency, not
  capability: accuracy is constant across the sweep (arms ungated); FG becomes
  violation-free at 2.5x the reference budget.

## 3. Supplementary E1 — Recovery Effectiveness

N = 78 initially-wrong tasks (42/120 initial v outputs are correct under the
fixed parser). Recovery Rate = recovered-to-correct / initially-wrong.

| Arm | Recovery Rate | RR (detected) | tasks missed | tokens per recovery |
|---|---:|---:|---:|---:|
| static | 0.1026 (8/78) | 0.1026 | 0 | 2812 |
| dynamic | 0.1410 (11/78) | 0.1410 | 0 | 2532 |
| SM | 0.1282 (10/78) | 0.1299 | 0 | 2739 |
| RD | 0.1026 (8/78) | 0.1026 | 0 | 2260 |
| FG | 0.0769 (6/78) | 0.0769 | 0 | 3506 |

Reading: every initially-wrong task did get a detection event (no silent
misses at the task level). RD recovers the same number of tasks as static but
with the lowest cost per recovery (2,260 tokens); FG recovers the FEWEST
(6/78) — its re-executions lose recoveries to session nondeterminism, and each
recovery costs 55% more than RD's. So "RD calls less" = smart scope, not
missed detection at the task level; the detection gap is at the NODE level.

Recovery Coverage (node level, true affected region vs nodes actually
re-executed): static/dynamic/SM 0.939 (miss: 22 evidence nodes, 3 r, 3 v);
RD 0.790 — misses r 35x (executable-but-wrong expressions are not detected),
v 9x, evidence 22x; FG 0.904 (misses only where no round fired).

## 4. Supplementary E2 — Budget Sensitivity (post-hoc sweep)

| Budget | RD violations | FG violations |
|---:|---:|---:|
| 1.0x static | 5.0% | 68.3% |
| 1.2x | 0% | 45.0% |
| 1.5x | 0% | 11.7% |
| 2.0x | 0% | 1.7% |
| 2.5x | 0% | 0% |

Accuracy constant across the sweep by construction (ungated arms). The 1.2x
reference is not biased against FG: FG's violation rate is monotonically
determined by its scope; it needs ~2.1x to clear, which is exactly the
efficiency gap the method addresses.

## 5. Supplementary E3 — Detection Evaluation (initial-pass outputs, fixed parser)

| Failure type | n | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Evidence (e) | 84 | 73 | 0 | 11 | 1.000 | 0.869 | 0.930 |
| Reasoning (r executable-wrong) | 68 | 0 | 0 | 68 | — | 0.000 | — |
| Execution (r unexecutable) | 18 | 18 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| Verification (v) | 90 | 57 | 12 | 21 | 0.826 | 0.731 | 0.776 |
| Structure/topology | N/A on fixed-DAG panel (needs injection run) |

Deterministic evidence-injection check: on the 36 tasks with complete,
well-formed facts, perturbing one fact value x0.8 leaves the r expression
executable in 32/36 (evidence errors are invisible at e and r), breaking 4/36
(they surface at r as execution errors).

Reading: the deployable detector reliably catches execution-level failures
(e parse/empty: F1 0.93; r unexecutable: F1 1.00; v disagreement: F1 0.78) and
is NOT designed for semantic diagnosis — reasoning errors (executable-but-wrong
expressions, 68/68 missed) and value-level evidence errors are invisible to it
until they surface as execution or agreement failures. This is the recall gap
that Recovery Coverage (E1) quantifies at the node level.

## Integrity notes

- Corrected replay re-decides ONLY the v-stage from executed artifacts (e/r
  decisions never touch the buggy parser); retained outputs are real calls.
- The corrected arms are NOT an independent confirmation; a clean re-run on a
  fresh panel would be required for that (rule 4).
- Determinism audit (corrected FG): 580 mapped calls checked, 69 answer
  mismatches, 38 same-prompt divergences (14B GPTQ session nondeterminism).
- Files: corrected_replay/CORRECTED_ARMS.json, CORRECTED_CONSOLIDATED.json,
  BUG_REPORT.md, corrected_replay.py, corrected_consolidate.py.
