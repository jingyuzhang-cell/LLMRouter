# VERIFICATION_GUIDE — operator review map for the supplementary measurement

Branch: `main` @ jingyuzhang-cell/LLMRouter. All evidence paths below are
in-repo, committed. Zero real calls were used to produce any file cited
here except the quarantined partial run (§5).

## 1. Physical budget caps for real calls

- The runner's ONLY dispatch path is `RealServer.draw()`
  (`supplementary_runner.py`), which calls `budget.reserve()` before every
  request and `budget.settle()` after, with usage validation.
- The Budget is the PRODUCTION class
  (`collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py`,
  `class Budget`): append-only `DISPATCH.jsonl`, per-request token
  reservation (2048 ≥ max observed single-call total 1879), charged-token
  accounting, wall-clock check.
- Caps in `supplementary_runner.py` `CAPS`: 1200 requests / 800,000
  tokens / 7200 s wall. Zero-call drill proving each cap trips, the
  invalid-usage guard retains the full reservation, and the declared
  worst-case plan (1100 calls / 620K tokens at per-node p95) fits:
  `evidence/ADMISSION_CHECK.json` → `gate4_budget_drill` (artifacts in
  `evidence/adm4_drill/*/DISPATCH.jsonl`).
- Model dispatch failures are returned (not raised) by `call_model`;
  `draw()` retries once on EITHER signal, settles only the delivered
  response (commit `79d136c`).

## 2. Over-limit stop mechanisms

Four independent stops, all visible in the run ledger:
1. `Budget.reserve` raises on request/token cap (`StopRun`);
2. `Budget.check` raises on wall cap — plus a SIGALRM hard deadline set
   in `execute()` as a backstop outside the Budget's own clock;
3. `draw()` refuses to settle responses with invalid/missing usage (the
   reservation stays charged — never silently released);
4. `Budget.__init__` refuses any existing `DISPATCH.jsonl` — no silent
   resume of a partially spent budget.
All exceptions funnel to `execute()`'s finally: model server stopped, GPU
lock released, `STATUS.json` written with attempts/tokens/wall/cells.

## 3. Shared-cache comparability (operator boundary 3)

- The run uses ONE engine + ONE identity cache (`(model, input_sha)`;
  `input_sha` = task uid + node + static-context sha + consumed upstream
  answers — `dag_closure.input_signature`). This is the M3 deployment
  reuse semantics, NOT an accident.
- Per-cell separation is now RECORDED, not just promised: every cell
  record carries `metering = {new_requests, cache_hits, injected_faults,
  physical_tokens, logical_calls}` with the invariant
  `logical == new_requests + cache_hits` (asserted in the smoke).
  Quality (P_correct) is cache-invariant — cached answers are the same
  real responses. COST comparisons are cache-scenario results and must be
  reported as such; cache-hit savings are separable per cell.
- Cell order affects later cells only through RECOVERED tasks: a retry's
  answer (no-cache, never cache-written) updates the task's downstream
  input identities, so later cells see new r/v inputs for those tasks.
  The structural expectation, zero-call derived — cell | expected new
  requests (base, before recovery variance):
    - clean|SS: ~80 (40 e + 20 r + 20 v; first cell populates the cache)
    - clean|DS/SD/DD/NONE: ~0 base (all hits); recovery adds per-decision
    - fault30_D3|SS: ~6 (r|medium retries, no-cache) + ~6-20 v (changed
      r inputs); faulted R1s are cache HITS corrupted after metering
    - fault30_D3|DS: ~0-6 (degrades) + v for non-degraded
    - fault30_D3|SD/DD: ~6 r|large + v for recovered tasks
    - fault30_D3|NONE: ~6-20 v (faulted tasks' v inputs differ)
  Total structural estimate 150-250 physical requests ≪ 1200 cap. After
  a real run, per-cell `metering` is checkable against this table; large
  deviations indicate identity drift and must be investigated, not
  interpreted.

## 4. Do the frozen hashes actually constrain run parameters?

Executed checks at `execute()` start (`supplementary_runner.py`):
1. `--approved-freeze-sha256` must equal sha256(SUPPLEMENTARY_PANEL_FREEZE
   .json) — the operator-approved panel/fault/seed file;
2. beliefs are RECOMPUTED from the trajectories and their hash compared
   to the approved preflight's — any drift aborts;
3. mirror-vs-production detection divergence must be zero — aborts;
4. the run dir copies the freeze + protocol verbatim; every decision row
   is appended to the engine ledger with the arm's full scored table.
Decision parameters (q_min 0.80, eps 0.10, λs, c0) are frozen in
`PARAMS`; `arm_entry.py` (hash-bound in the preflight) is the sole
selection layer; the priors used are written to the run dir
(`BELIEFS.json`). What the hashes do NOT bind: the runner script itself
(git-commit-bound instead — run against commit 9b29672's descendants).

## 5. Pre-GO engineering findings (all zero-call verified)

1. Two detection-mirror parity bugs (fences; split-on-'+' expressions) —
   fixed in `detection.py`, 0 divergences on every evaluated real record.
2. **Strict facts validation** (this round): the lenient mirror accepted
   string-valued facts, marking e-nodes DONE while the production prompt
   builder feeds r EMPTY facts — 48/122 e-answers in the aborted partial
   run; formal-trajectory strict e2 rates are 0.25–0.375 (e1 = 1.0).
   `parse_facts` now mirrors production validation exactly. Consequence:
   the arms' recovery now engages on natural e2 failures (as production's
   ER stage was designed to), and decision beliefs use the strict rates
   (e2|large q̂=0.25). Under min-composition this makes most e-recovery
   candidates infeasible for the policy arms — a recorded phenomenon per
   the operator's boundary 1, not an algorithm verdict.
3. **Double-v execution bug** (caught by the new metering smoke 42/42):
   the batched plan application ran PENDING v nodes inside the plan AND
   the V stage ran them again. Fixed to the `apply_decision` rule: first
   executions run exactly once, in their planned stage, under the chosen
   π.
4. Quarantined partial run `run_20261011_223149` (see its
   OPERATOR_HOLD_NOTE.md): 80/1200 requests, 26,462/800K tokens, 2/10
   cells, diagnostic-only.

## Operator boundaries (recorded verbatim in SUPPLEMENTARY_RUNNER.md)

q̂ parse-rate is a proxy (r|medium=0.783 says the METRIC is below 0.80);
D=3600 makes deadlines non-binding (no time-pressure claims); shared
cache = shared-cache deployment scenario (cost separation per §3).
