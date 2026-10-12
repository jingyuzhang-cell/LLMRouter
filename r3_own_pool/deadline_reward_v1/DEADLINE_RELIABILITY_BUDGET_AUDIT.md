# DEADLINE_RELIABILITY_BUDGET_AUDIT — request / token / wall reconciliation

Zero real model calls. Arithmetic inputs (all measured, cited):
per-call latency medians from run_20261012_092146 (e|r|v physical
samples: 0.17–7.1 s, medians 0.24–2.09 s); tokens per call p95 from
PRIORS_REAL_V1 (max single-call 1879, mix ≈ 350 average); switch costs
measured 2026-10-11 (start 58.7–70.8 s, stop ≈ 1.4 s).

## Reuse vs REQUIRED new physical requests (task 2.1–2.2)

REUSABLE at zero new requests:
- D3 fault manifestation: cache hit + post-metering corruption (0 base
  calls; only policy-chosen retries charge);
- fixed-path D-tier replays (actuals do not depend on D);
- family binding, coverage statistics, joint verdicts, report writing;
- any within-run identity repeat that is NOT a declared sampling repeat.

REQUIRED new physical requests (nothing else can produce them):
- all base cascades (fit / screen / validate: distinct task identities);
- fit K-repeats (declared no_cache latency sampling);
- fault retries chosen by the policy on the faulted validate subset;
- contention-pair executions (cache hits do not occupy the serial
  executor — real queueing needs real calls).

## Stage arithmetic (upper bounds; 15% reserve included)

| stage | physical requests | tokens (p95 mix) | wall |
|---|---|---|---|
| S-FIT 24 tasks × 4 nodes × K=3 | 288 + reserve → **332** | ~101K → **116K** | switches: stage-major grouping ≤10/pass × 3 passes ≈ 2,100 s; calls ~640 s; startup 70 s → **≈2,900 s** |
| S-SCREEN 12 × 4 | 48 + reserve → **56** | ~17K → **20K** | 1 pass ≈ 700 + 110 s → **≈850 s** |
| S-VALIDATE 90 × 4 + 27 fault tasks × ≤2 retries | 360+40 + reserve → **460** | ~126K → **145K** | stage-major ≈ 12 switches + retries (+2 model groups) ≈ 1,000 s; calls ~880 s → **≈2,100 s** |
| S-CONTENTION 8 pairs × 2 tasks × 4 | 64 + reserve → **74** | ~22K → **26K** | interleaved serial: ~5 switches/pair ≈ 2,800 + calls 140 s → **≈3,100 s** |
| **TOTAL** | **922** | **307K** | **≈8,950 s + slack → 10,000 s** |

Stage-wise caps (independent stops; a stage hitting its cap is
INCOMPLETE and closes the gate): FIT 340/120K/3,300 s · SCREEN 60/22K/
1,100 s · VALIDATE 460/150K/2,600 s · CONTENTION 80/28K/3,600 s.

## Sufficiency verdict against 1200 / 600K / 14400 (task 2.4)

- Requests: 922 ≤ 1,200 (headroom 23%).
- Tokens: 307K ≤ 600K (headroom 49%).
- Wall: ≈10,000 s ≤ 14,400 s (headroom 31%). Wall is the binding
  constraint and is driven by model switches — mitigated by stage-major
  batching (~10–14 switches per pass instead of per-task). If observed
  switch costs exceed the measured 59–71 s (e.g., GPU contention), the
  stage caps trip INCOMPLETE before the global cap.
**Verdict: SUFFICIENT as a single authorization** — no cap increase is
requested. If the operator prefers smaller authorizations, the natural
split is {S-FIT + S-SCREEN} (≈3,900 s) then {S-VALIDATE +
S-CONTENTION} (≈5,200 s), with the second gate requiring the first
stage's frozen quantiles — no budget or validation semantics change.

## INCOMPLETE packaging rules (task 2.5)

Per stage: append-only ledger + stage STATUS (COMPLETE/INCOMPLETE +
reason + requests/tokens/wall). Partial → `*_INCOMPLETE.json` only;
downstream stages refuse to start; the official
`RELIABILITY_RESULTS.json` (per-cell CP verdicts, joint verdict,
D-tier regions) is written ONLY when every stage completed — and is
never overwritten. CONDITIONAL cells stay CONDITIONAL with their
extension arithmetic (spare pool 24 tasks; any larger extension needs a
new panel freeze + new authorization).
