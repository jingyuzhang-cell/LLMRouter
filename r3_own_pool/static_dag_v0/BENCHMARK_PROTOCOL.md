# Adaptive Failure Benchmark — Frozen Protocol

Panel: frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks (multidag_dynamic_120).
Role: supplementary experiment (designed after known results). NOT independent confirmation.
Parser: the FIXED json_value (see corrected_replay/BUG_REPORT.md). Gold used ONLY for scoring.

## Methods (the three baselines)

1. Router (Best Single Model): one direct QA call per task, model = large
   (Qwen2.5-14B-GPTQ-Int8). No DAG, no node collaboration, no recovery.
   Direct-QA prompt returns ONLY JSON {"answer": <number>}; scoring = fence-strip
   + json parse + close to gold (same tolerance as the panel).
   Router-2 (query classifier) is degenerate on this panel: every task is
   arithmetic/table-text, so the category rule maps all tasks to large =
   Router-1. Router-3 (cost-aware) is out of scope, noted as future work.
2. Static DAG: the frozen panel's shared initial pass — e1/e2 (large) -> r
   (medium) -> v (coder), fixed structure, fixed models, NO feedback, no
   recovery. Same DAG structure, model pool and prompts as Dynamic. Clean Q is
   the fixed-parser initial-pass score (0.35 on this panel). Reference row:
   Static-with-local-fallback (the frozen static arm, corrected 0.3917).
3. Dynamic DAG (the method): RD arm of the frozen ablation with the corrected
   v-stage (corrected 0.4000), deployable detection only:
   e fail = facts empty/unparseable; r fail = expression unexecutable;
   v fail = v unparseable or v != r value. Recovery targets: e first failure ->
   coder then medium (cross-task memory); r -> large; v -> large. One recovery
   attempt per node. Reference row: dynamic-ideal (corrected 0.4250, gold-driven
   r/v triggers, reported for transparency only).

## Scenarios

S1 Clean: each method executed once on the panel as-is.
S2 Failure Injection: task-level fault injection at rates 10%, 20%, 30% of
   tasks (floor(120*p) tasks), one faulted node per task, uniform over
   {e1, e2, r, v}, seed 20260923 (one seed per rate; rates share the same
   seed so the 10% set is a subset of the 20% set etc.).
S3 Budget: post-hoc budget statistics vs 1.2 x Static-arm realized tokens per
   task (same口径 as the frozen panel; no hard limit at execution).

## Failure model (fixed before execution)

CAPABILITY FAULT: the faulted (task, node, planned model) triple is permanently
failing — every call of that model for that node-task in this scenario returns
a failing output, regardless of prompt. Failing outputs are sampled from REAL
failure outputs of the frozen panel by node kind (e: parse-failing facts
answers; r: truly unexecutable expressions; v: prose/non-JSON verifier answers).
Recovery policies (the only difference between methods):
  Router: retry the same call with the same model -> fault persists -> answer
    wrong; cost = the task's clean call tokens x2 (failed + retry).
  Static: re-execute the WHOLE flow with the fixed models -> the faulted node
    reproduces its failing output; downstream nodes run for real on the corrupt
    upstream (new prompts, real calls); no model switching, no feedback.
  Dynamic: deployable detection fires on the injected failure -> local recovery
    with the RD rules (failed node + descendants only; recovery models are
    DIFFERENT models, hence not faulted; real calls, cache-reused by
    (model, prompt) when identical to an executed call).
Cost accounting for transient faults (secondary reading): Router retry +1 call,
Static +4 calls, Dynamic +1..3 calls per fault — reported separately; all three
recover to clean accuracy under transient faults by construction (temp 0).

## Execution & integrity

- All calls are REAL except (model, prompt)-identical reuses of executed calls
  (temperature 0; the measured 14B session nondeterminism ~10-15% is reported
  alongside, not hidden). Fault overrides bypass the cache by definition.
- All 120 tasks stay in every denominator; injected tasks that were already
  wrong in clean remain in denominators.
- Metrics per scenario: accuracy (fixed parser), mean/total tokens, adaptation
  calls, observed latency, recovery rate (faulted tasks recovered to correct),
  budget violations, and a Q-vs-C Pareto table per scenario.
- One-shot: seed, rates, node distribution, failure pools and prompts are fixed
  before execution; no threshold tuning after results are seen.
- Budget口径: post-hoc violation statistics only (rule 2).

Code: benchmark_run.py (freeze + S1 Router clean + S2 per rate),
benchmark_analyze.py (zero-call consolidation).
