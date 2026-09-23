> SUPERSEDED BY corrected_replay/CORRECTED_REPORT.md (2026-09-23): the numbers in this file
> reflect the EXECUTED run with the buggy json_value fence parser. Every v-node output wrapped
> in ```json fences was parsed as None, so all arms over-fired their v-stage recovery and the
> static arm was under-scored. See corrected_replay/BUG_REPORT.md. This file is kept as the
> executed-artifact record.

# FG Full-Graph Re-execution Control — Results Summary

Panel: frozen 4-node DAG, 120 TAT-QA arithmetic table-text tasks (`multidag_dynamic_120`).
Question: how much computation does dependency-aware LOCAL recovery save versus
feedback-triggered FULL-GRAPH re-execution, and is there any quality difference?

## Main comparison (all 120 tasks, paired)

| Metric | Static (base) | SM Static-Matched | RD Dynamic-Real local | FG Full-Graph (new) |
|---|---:|---:|---:|---:|
| Accuracy | 0.1667 | 0.3500 | 0.3500 | 0.3333 |
| Mean tokens/task | 2848.7 | 2895.7 | 2459.5 | 4039.9 |
| Total tokens | 341,848 | 347,480 | 295,139 | 484,791 |
| Adaptation calls | 466 | 465 | 365 | 832 |
| Mean latency/task (s) | 7.88 | 8.90 | 7.15 | 12.70 |
| Budget violations (post-hoc) | — | 0/120 | 0/120 | 96/120 (80.0%) |
| Max budget ratio (vs 1.2x static) | — | 1.19 | 1.18 | 2.17 |

FG vs RD (primary): dQ = −0.0167 (−1.7pp), bootstrap CI [−0.0583, +0.0250],
McNemar exact b=2, c=4, p=0.6875 (Help 2 / Harm 4). Not significant.
FG vs SM: dQ = −0.0167, CI [−0.0750, +0.0417], McNemar p=0.7905.
RD vs SM: dQ = 0.0000, CI [−0.0583, +0.0583], McNemar p=1.0.

## What local scope saves (RD vs FG, identical rules otherwise)

- 467 fewer adaptation calls (−56% of FG's adaptation calls).
- 1,580 tokens per task (−39% of mean tokens; total 189,652 tokens saved on the panel).
- 5.55 s per task in observed sequential-call latency (−44%).
- Budget: 0 vs 96 violations against the same 1.2x-static rule (FG's full re-execution
  exceeds the reference budget on 80% of tasks; max ratio 2.17x).

## Scope audit (FG)

- Rounds executed: e 73, r 15, v 120 (832 real calls = 4 per round).
  RD had 16 r-rounds; the 1-round difference is traced to a same-prompt divergence
  of the 14B model (see determinism audit).
- Unaffected-branch repeat executions: 337 (2.81/task; all 120 tasks had >=1 repeat).
  These are clean-branch re-executions that local recovery avoids entirely.
- Redundant calls (executed beyond trigger + needed descendants): 457.

## Determinism audit (important caveat)

- 820 of 832 FG adaptation calls map 1:1 to an RD/base call with identical prompt+model
  (12 calls are extra intermediate v calls with no RD counterpart, by design of full-graph
  rounds). 101 of the 820 mapped pairs produced different answers.
- Of these 101: 54 are SAME-prompt divergences (identical prompt, identical model —
  pure vLLM session nondeterminism): 47 on large (14B GPTQ-Int8), 7 on medium.
  47 more are cascades (upstream divergence changed facts/expression). 1 pair has a
  model mismatch (the task whose r-round did not fire).
- Independent probe (fresh sessions, 20 prompts each): large 2/20 diverged (10%),
  medium 0/20, coder 0/20. Pre-existing cross-arm same-prompt pairs in the frozen data
  (coder/medium only): 0/158 diverged. The 14B GPTQ model is the nondeterministic one;
  it had never been re-run with identical prompts before this experiment.
- 6 tasks flip ok between RD and FG (4 FG-harm, 2 FG-help) — entirely within this
  measured nondeterminism. The −1.7pp is NOT attributable to the scope difference
  (with deterministic models, re-running a clean node with the same prompt reproduces
  its output; FG and RD would be identical). It is inference noise, reported as-is.

## Answer

Local dependency-aware recovery saves ~39% tokens, ~56% of adaptation calls and ~44%
latency versus full-graph re-execution, and keeps 0/120 tasks over the reference budget
where full-graph re-execution violates it on 80% of tasks — with no statistically
detectable quality difference (dQ −1.7pp, CI [−5.8, +2.5] pp, McNemar p=0.69; the
observed gap is fully covered by measured 14B-model session nondeterminism).

## Integrity notes

- All 120 tasks in the denominator; no threshold tuning; one-shot.
- Budget accounting: post-hoc violation statistics against 1.2 x Static-arm realized
  tokens (no hard limit at execution, identical口径 for RD and FG).
- Supplementary experiment designed after known results; not an independent confirmation.
- Execution was real (832 new model calls; only the shared initial pass reused cache).
- Run history: three sessions (crashes fixed at stage-R model-override fallback and a
  `t.answer` field typo; both fixes are semantic-free and the pre-run replay test
  re-passed: RD replay 120/120, FG key mapping 824/0 problems).

Artifacts:
- Protocol: `FULLGRAPH_PROTOCOL.md` (frozen before execution)
- Policy: `multidag_fullgraph_120/POLICY.json`
- Runner: `multidag_fullgraph.py`; analysis: `multidag_fullgraph_analyze.py`
- Test: `test_multidag_fullgraph.py`; probe: `determinism_probe.py`
- Results: `multidag_fullgraph_120/FULLGRAPH_ANALYSIS.json` (+ RAW_TAIL/REQUESTS/RESPONSES)
