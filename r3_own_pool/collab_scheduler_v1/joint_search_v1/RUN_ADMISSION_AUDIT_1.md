# RUN ADMISSION AUDIT 1 (2026-10-09) — zero-call, post-pause

Campaign dispatch PAUSED before this audit (driver terminated; model server
stopped; GPU 0 MiB; ledgers and raw answers retained untouched).

## Corrections to my prior report (accepted)

1. **t1 gold**: the original annotation is 517.5 with scale=percent (raw-data
   reconciliation, user-confirmed); 5.175 came from `eval(derivation)`. This is
   the OLD-GOLD CONVERSION defect in the task-lineage builders
   (`answer=float(eval(d))`), NOT a model-prompt/gold mismatch. My earlier
   attribution was wrong.
2. **Q varying by state** in session 1 only demonstrates that state
   differences were OBSERVED. It is not evidence that state features improve
   search efficiency, nor that Proposed beats baselines. No six-method
   performance aggregation is presented.

## Item 1 — actual scoring wiring of the running campaign

- Scoring path (bound by admission hashes, verified in code):
  `fault30_run.py:422-425` — `gold = t['answer']`;
  `ok = close(v_value, gold)`; `close(a,b)=|a-b|<=max(1e-4,1e-4*|b|)`.
- Gold actually used: `answer` field of FORMAL_LAUNCH_V1 tasks =
  **eval-derivation values** (lineage builder semantics). NOT the raw
  annotations.
- Per-UID comparison vs raw TAT-QA annotations (data sha256 recorded in
  GOLD_CONTRACT_V1.json):
  - SEARCH8: **1/8 contaminated** (a3568c44: used -0.8477, annotated -84.77,
    scale=percent)
  - TEST16: **7/16 contaminated** (six percent-scale x100 + one rounding case)
  - calibration-4: 1/4 (5c5cb310: 5.175 vs 517.5)

## Item 2 — old gold confirmed: dispatch paused

Driver SIGTERM'd (loop continued into next session by design — then SIGKILL'd),
orphaned vllm terminated, GPU lock released. All artifacts retained:
WORKFLOW/TRAJECTORY/EVALUATIONS/DISPATCH + budget journal.

## Item 3 — re-scoring under the final contract

Final contract = GOLD_CONTRACT_V1 (annotation-authoritative golds; tolerance
and scoring path unchanged). Re-scored from stored final v answers
(RESCORE_FINAL_CONTRACT_1.json):

- Session 1 (8 evaluations, 4 configs x 2 states): **Q_old == Q_final on every
  unit — no numeric flip** (the contaminated task was answered incorrectly by
  every config under either gold). The trajectory is nonetheless registered
  DIAGNOSTIC: search-time Q for a3568c44 was scored against the wrong gold, so
  selection-bias risk existed even though it did not materialize numerically.
- FULLVAL stage-1: **t1 flips 0 -> 1 on ALL FOUR scenarios** (v=517.5 equals
  the annotated gold, including the faulted S2/S3 recovery cells). Under the
  final contract the stage-1 quality picture is: clean-correct on t1 AND t4
  (2/4); "recovery preserves/restores correctness" now confirmed under the
  final contract on both t4 (unchanged) and t1 (flipped). t2/t3 remain genuine
  model errors.

## Item 4 — request-cap accounting

Frozen SEARCH_BUDGET_V1: per-session 400 x 18 sessions = 7,200 =
campaign_caps.new_request_attempts EXACTLY (tokens: 3,276,800 x 18 =
58,982,400 = campaign cap exactly). **No authorization expansion occurred.**
Actual consumption before pause: session 1 = 299 requests / 48,707 tokens
(delivered responses; journal carries a settle_correction entry because the
first settle read only DISPATCH line counts).

## Disposition

- GOLD_CONTRACT_V1.json frozen (24 uids, annotation-authoritative, 8
  contaminated instances listed).
- FORMAL_LAUNCH_V2.json built: same frozen protocol/panels/faults/model
  bindings; tasks carry corrected golds; v1 session registered diagnostic with
  its consumption charged; campaign root formal_campaign_v2 will open with a
  settled prior-consumption entry (299 req / 48,707 tok) so remaining headroom
  is 6,901 requests / 58,934,293 tokens.
- Dispatch remains PAUSED. Resume of the remaining 18 method/seed cells under
  V2 awaits the review decision; no TEST16 release, no expansion.
