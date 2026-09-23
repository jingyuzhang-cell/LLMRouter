# Dynamic + Adaptive Verification & Hard-Subset — Frozen Protocol

Panel: frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks (multidag_dynamic_120).
Role: supplementary experiments. NOT independent confirmation. One-shot; no threshold
tuning after results. Gold used only for scoring (the RD v-stage close-to-gold skip is
kept identical to RD for arm comparability).

## Experiment A (priority 1): Dynamic + Verifier ablation

Motivation (from the corrected detection evaluation): the deployable detector catches
execution-level failures (e-row F1 0.93, r-execution F1 1.0, v-agreement F1 0.78) but
has recall 0 on REASONING errors (r executable-but-wrong, 68/68 missed) — Dynamic never
gets a chance to recover them.

DV arm = RD (deployable Dynamic-Real, corrected v-stage) plus ONE additional deployable
signal at the r stage:
  - second opinion: execute r a second time with coder (same sprompt, same current
    facts, same generation params) — a pool model, not a new one;
  - reasoning-failure signal = BOTH executions parse and execute AND their computed
    values disagree (close() tolerance) — conservative, precision-oriented;
  - on signal (or on the existing unexecutable signal) -> r escalates to large (the
    SAME recovery target RD already uses), then v refresh (coder), then the standard
    RD v stage. One recovery attempt per node, unchanged.

Fairness rules (fixed):
  - Static is untouched; RD is untouched; DV adds the verifier mechanism and PAYS its
    cost: every second-opinion call, escalation and refresh is counted in tokens/calls.
  - Same model pool, same prompts, same generation params, same recovery targets.
    No prompt engineering, no extra token budget, no larger models anywhere.
  - The verifier is additional deployable machinery (no gold); the ablation table
    quantifies what it buys at its measured cost.

Ablation table (clean scenario): Static (initial pass) / Dynamic (RD, corrected) /
Dynamic+Verifier (DV). Also reported: signal statistics — how often the disagreement
signal fires, its precision against the r node's actual wrongness (value on its own
facts != gold, labeled post-hoc), and how many recoveries it enables.

## Experiment B (priority 2): Hard-subset evaluation (zero model calls)

Difficulty split, frozen BEFORE looking at any outcome (pre-execution feature from the
frozen POLICY derivations):
  - Easy: gold derivation has 1 arithmetic operator (74 tasks).
  - Hard: gold derivation has >= 2 operators (46 tasks; up to 6).
  Secondary split (reported for reference): >= 3 distinct numeric literals (20 tasks).
Report per-subset accuracy for Router / Static / Dynamic (+ DV once available) in the
clean scenario and in the fault scenarios (20%, 30%) for Router / Static / Dynamic.
Hypothesis under test: the Dynamic advantage concentrates on Hard tasks; on Easy tasks
the decomposition overhead dominates (consistent with the clean Router result).

Code: verifier_run.py (freeze + DV execution), verifier_subset_analyze.py (zero-call
consolidation of both experiments).
