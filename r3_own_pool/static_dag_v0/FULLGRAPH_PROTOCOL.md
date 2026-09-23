# Full-Graph Re-execution Control Arm — Frozen Protocol

Panel: `multidag_dynamic_120` (frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks).
Role: supplementary experiment (designed after the base + ablation results were seen).
Question: how much computation does dependency-aware local recovery save versus
feedback-triggered full-graph re-execution, and is there any quality difference?

## Comparison strategies (all on the same frozen panel, same initial DAG)

| Arm | Existing / new | Semantics |
|---|---|---|
| SM (Static-Matched) | existing (`multidag_ablation_120/sm`) | static semantics + dynamic escalation targets; kept as the existing control for recovery-model/action effects |
| RD (Dynamic-Real, local) | existing (`multidag_ablation_120/rd`) | deployable detection, dynamic rules, re-execute ONLY failed node + descendant closure — the method |
| FG (Full-Graph) | NEW (`multidag_fullgraph_120/fg`) | identical to RD in every rule except scope: every feedback-triggered recovery re-executes the ENTIRE graph (e1, e2, r, v) |

## What FG shares with RD (frozen, must match RD exactly)

1. Initial DAG execution: e1/e2 = large, r = medium, v = coder; initial-pass calls are
   the same cached calls (`e1:{uid}`, `e2:{uid}`, `r:{uid}`, `v:{uid}`) from the base panel.
2. Model assignment rule: same three models (Qwen2.5-14B-GPTQ-Int8 / Qwen2.5-7B /
   Qwen2.5-Coder-7B), same planned assignment, same recovery targets:
   e fail -> coder for the first failure in frozen task order, medium for later ones
   (cross-task failure memory); r fail -> large; v fail -> large.
3. Feedback (detection) rules — DEPLOYABLE ONLY, never gold:
   e fail = facts unparseable or empty;
   r fail = expression unparseable or unexecutable;
   v fail = v value unparseable OR v value disagrees with r value.
   Gold answers are used ONLY for scoring (ok), never to trigger recovery.
4. Recovery target: one recovery attempt per failed node (same event structure as RD:
   e stage, r stage, v stage — single detection pass per stage, frozen task order).
5. Budget: NO hard limit at execution time (identical to RD, which is ungated).
   The budget rule is the same per-task reference for BOTH arms:
   B_task = 1.2 x Static-arm realized tokens (base panel).
   Budget violations are POST-HOC statistics for both arms (rule: 执行时无硬限制,
   事后按同一口径统计违规率; 不混用两种口径).
6. Generation: temperature 0, top_p 1, max_tokens 512, local vLLM servers,
   sequential calls, same prompts (eprompt / sprompt / VPROMPT).

## What differs (the ONLY difference): execution scope

- RD: a feedback event re-executes the failed node with its recovery model plus the
  descendant closure with planned models (e fail -> r refresh -> v refresh; r fail ->
  v refresh; v fail -> v only).
- FG: a feedback event triggers ONE full re-execution of all four nodes for that task.
  The triggering (failed) node uses its recovery model; every other node keeps its
  CURRENT model (planned model unless that node itself failed earlier — recoveries
  persist across rounds; re-executing a clean node with its planned model and the same
  prompt is deterministic at temperature 0, so it is pure cost).
  Round structure: e round (all e failures of the task handled in one re-execution),
  r round (r failure), v round (v failure). A task can have 0-3 rounds.
- All FG adaptation calls are REAL executions with new arm-prefixed keys
  (`{node}:fg:{uid}:{round}`); no cost is extrapolated from node counts.
  Only the shared initial pass is cache-reused (it is the same initial DAG by design).

## Recorded metrics (per task, all 120 tasks kept in denominators)

- Accuracy (ok), paired FG vs RD delta-Q with task bootstrap CI (seed 20260918,
  B=10000, same as base panel) and McNemar exact test; Help/Harm counts.
- Total tokens per arm (sum over all keys, initial + adaptation), mean per task.
- Call counts per arm (adaptation calls; initial pass shared).
- Observed latency per arm (sum of per-call latency_s, sequential execution).
- Unaffected-branch repeat executions: for every FG round, count re-executions of
  branch nodes (e1/e2) that were NOT the trigger of that round. Also total redundant
  calls (executed nodes beyond trigger + needed descendants).
- Budget violation rate: tasks with used > 1.2 x static realized (+1e-9), post-hoc,
  same computation for RD and FG.

## Integrity rules

- All tasks stay in the denominator; infra-failed, timeout or over-budget tasks are
  not dropped. Infra failure of a call raises and the run is resumed from cache
  (deterministic at temperature 0).
- This is a supplementary experiment designed after known results; it is NOT an
  independent confirmation of the method (no claim of confirmatory status).
- No threshold tuning after results are seen; one-shot.

Code: `multidag_fullgraph.py` (freeze + run), `multidag_fullgraph_analyze.py`
(analysis, zero model calls). Pre-run replay test: `test_multidag_fullgraph.py`
(replays the RD arm from cached responses and asserts exact agreement with
`multidag_ablation_120/RAW_TAIL.json` — validates the shared stage/detection logic
before any new model call is made).
