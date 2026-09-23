> UPDATE 2026-09-23: implementation moved to corrected_consolidate.py and now runs on the
> CORRECTED arms (fixed json_value parser; see corrected_replay/BUG_REPORT.md). Definitions
> below are unchanged; all E1/E2/E3 numbers in corrected_replay/CORRECTED_REPORT.md follow them.

# Supplementary Analysis Protocol: Recovery Effectiveness / Budget Sensitivity / Detection F1

Panel: frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks (multidag_dynamic_120).
Arms (all frozen data, zero new model calls):
  static (base), dynamic-ideal (base), SM (Static-Matched), RD (Dynamic-Real local),
  FG (Full-Graph re-execution, new).
Role: supplementary analyses designed after known results to test MECHANISM claims
(reviewer Major-Revision points). Not confirmatory. Gold answers are used ONLY as
evaluation labels, never to trigger anything.

Tolerance throughout: v value "correct" iff close to gold, same rule as the panel
(|a-b| <= max(1e-4, 1e-4*|b|)).

## E1. Recovery Effectiveness (priority 1) — "is RD's low call count smartness or missed errors?"

Definitions (fixed before computation):
- Initial state: the shared initial pass (e1/e2 large, r medium, v coder) is the
  same for every arm. Initial-correct task = initial v value close to gold.
- N = number of tasks initially WRONG (identical across arms).
- Recovery success M(arm) = initially-wrong tasks whose FINAL arm output is correct.
- Recovery Rate RR(arm) = M(arm) / N.
- RR_detected(arm) = M(arm) / N_det(arm), where N_det(arm) = initially-wrong tasks
  on which the arm fired >=1 feedback event (its detection actually engaged).
- Missed-detection tasks(arm) = initially-wrong tasks with 0 events in that arm.
- Tokens per recovered task = mean arm tokens over the M(arm) tasks.
- Recovery Coverage (node level): per-task TRUE affected region R = {truly-wrong
  nodes} U descendants (e -> {r,v}, r -> {v}, v -> {}). Node truth labels:
    e node wrong  = facts unparseable or empty (execution-level);
    evidence wrong (pair level) = both e nodes well-formed AND gold derivation
      literals (excluding 0/1/100) not all present among combined fact values;
      labels the region {e1,e2,r,v};
    r node wrong  = expression unparseable/unexecutable, OR executes on its own
      facts to a value not close to gold (reasoning error);
    v node wrong  = v value not close to gold.
  Executed set E(arm) = node prefixes of the arm's adaptation keys.
  Coverage(arm, task) = |E(arm) n R| / |R| for tasks with R non-empty.
  Report mean coverage, and counts of truly-wrong nodes missed by the arm's
  executed set (the 漏检 count), broken down by node type.
- All 120 tasks kept; no threshold tuning.

## E2. Budget Sensitivity (priority 2) — "is the 1.2x reference biased against FG?"

- Arms were executed UNGATED (no hard limit; identical for RD and FG). The sweep is
  therefore pure post-hoc accounting of the same frozen executions — accuracy is
  constant across multipliers by construction; only violation counts change.
- Multipliers m in {1.0, 1.2, 1.5, 2.0, 2.5} x Static-arm realized tokens per task.
- violation(arm, m) = # {tasks: used(arm) > m * static_used(task)}.
- Report per arm: violation rate and max ratio used/static (the break-even
  multiplier at which the arm becomes violation-free).

## E3. Detection Evaluation (priority 3) — "does the detector catch real errors or
## only obvious failures?"

Instances = the frozen panel's INITIAL-pass node outputs (the first detection
opportunity), 120 tasks each for e1, e2, r, v; plus the task-level evidence check.
Detector (deployable, unchanged): e fires iff facts unparseable/empty; r fires iff
expression unparseable/unexecutable; v fires iff v value unparseable OR v != r value.

Rows (per failure type, instance = task unless noted):
  Evidence: task-level GT = both e well-formed AND operand-recall gap
    (wrong value, normal form). Prediction = e detector fires (never on
    well-formed facts by construction -> recall 0 by design; precision vacuous).
    Deterministic injection sub-check: on tasks whose combined facts are complete
    and well-formed, perturb ONE fact value x0.8 and execute the task's actual r
    expression on the perturbed facts: report how often the expression still
    executes (error invisible downstream at r) vs breaks (surfaces at r).
  Reasoning: GT = r executable AND value on its own facts != gold.
    Prediction = r detector fires -> by construction never on executable
    expressions (recall 0 by design).
  Execution: GT = r unparseable/unexecutable. Prediction = r detector fires.
    TP expected; precision checked against GT (fires only when truly wrong).
  Verification: GT = v != gold. Prediction = v detector fires (unparseable or
    v != r). TP = fires AND wrong; FP = fires AND correct (v corrected a wrong r,
    the agreement check's known false positive); FN = no fire AND wrong
    (v agrees with a wrong r).
  Structure/topology errors: NOT observable on a fixed-DAG panel (no reordered
  executions). Reported as N/A; requires an injection run (deferred).
Metrics per row: TP/FP/FN with Precision/Recall/F1 (precision reported only where
the detector can fire). Overall rows too. No new model calls anywhere in E3.

## Integrity

- Gold answers used only as evaluation labels (post-hoc), never as triggers.
- All 120 tasks in denominators. Supplementary-not-confirmatory status.
- One-shot: definitions above are fixed before computation; results are reported
  as-is including empty recall rows.
