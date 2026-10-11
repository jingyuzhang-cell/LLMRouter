# FORMAL_SETTLEMENT_AUDIT_RO — read-only settlement audit of the Formal campaign

Scope: operator-authorized READ-ONLY evidence verification (2026-10-11).
Zero model calls, no GPU, no modification of any frozen artifact; the
only writes are this report, the script, and the evidence JSON inside
`settlement_audit_ro/`. Baseline audited: commits through ffa9bfc;
campaign ledgers under `joint_search_v1/formal_campaign_v2*` (base +
retry1..retry7).

## Verdict

**18/18 checks PASS. The announced settlement figures reproduce EXACTLY
from the raw ledgers.** One finding (F1) documented below — a retry-
criterion asymmetry that is infra-only in substance but broader than the
in-process driver's literal tuple; it does not affect any settled
number, cap, or completeness result.

## What was verified (all from raw artifacts, no announcements trusted)

**A. Journal integrity.** All 8 roots' CAMPAIGN.jsonl bind the SAME
frozen protocol sha + campaign caps. 28 reservations, 28 settlements;
no duplicate settlement, no settle-without-reserve, no unknown events,
no reserved-but-unsettled (crash) sessions.

**B. Three-way reconciliation, every session.** DISPATCH reservation
count == DISPATCH response count == STATUS new_requests; Σ settled
usage tokens == STATUS charged_tokens; CAMPAIGN settle charge ==
STATUS record (requests and tokens); no negative walls. Includes the
zero-spend hard-crash sessions (no DISPATCH.jsonl — failed before the
Budget existed; STATUS legitimately records 0).

**C. Cap compliance.** Every per-session charge within the frozen
per-session caps (400 requests / 3,276,800 tokens). Campaign totals
WITH the frozen prior v1 consumption carried in the launch config
(299 requests / 48,707 tokens): **5,170 requests ≤ 7,200 and
1,792,521 tokens ≤ 58,982,400**. The v2 headroom rule
(v2 requests ≤ 7,200 − 299) holds: 4,871 ≤ 6,901.

**D. Retry legitimacy (two levels, honestly separated).**
- SEMANTIC: every retried original is infrastructure-class — GPU busy /
  Model server exited / BlockingIOError (flock contention) /
  FileExistsError / wall-deadline termination / hard crash with no
  STATUS on disk — and every retry settled COMPLETE (18/18 unique
  method×seed sessions COMPLETE). Across ALL 30+ INCOMPLETE journal
  entries there is NOT ONE search-logic failure: no search failure was
  ever retried or left unresolved.
- FINDING F1 (documented, not massaged): the in-process driver's literal
  `INFRA_FAILURE` tuple ('termination' / 'File exists' / 'interrupted'
  / 'deadline') does NOT cover 'GPU busy', 'Model server exited',
  'BlockingIOError', or the no-STATUS hard crashes. Those retries were
  orchestrated by the RESUME_DRIVER processes (RESUME_DRIVER*.log),
  which applied a broader but still infra-only criterion. Substantively
  compliant with the announced policy ("search-logic failures are NOT
  retried"); literally broader than the frozen tuple. No numbers move.

**E. Announced figures — all reproduce exactly:**

| Announced | Ledger-verified |
|---|---|
| 18/18 COMPLETE (6 methods × 3 seeds, unique) | ✓ exactly the 18 expected sids |
| envelope 4,871 requests | ✓ 4,871 |
| envelope ≈1.74M tokens | ✓ 1,743,814 |
| COMPLETE-only 4,542 requests | ✓ 4,542 (1,620,410 tokens) |
| proposed ties wo_state at 663 | ✓ proposed_state_incremental 663 = proposed_without_state 663 |
| prior v1 consumption 299 carried | ✓ launch config + headroom arithmetic |

**F. Unresolved incompletes.** None: every INCOMPLETE original has a
COMPLETE retry under some root; the two NO_STATUS hard crashes
(random_20261009 @ 0 requests, random_20261010 @ 168 requests) are
itemized in the evidence with their journal charges.

## Reproduction

```
cd /root/r3_own_pool
python3 -m collab_scheduler_v1.joint_search_v1.settlement_audit_ro
# → 18/18 checks PASS; evidence: settlement_audit_ro/SETTLEMENT_AUDIT_RO.json
```

The script reads only CAMPAIGN.jsonl / STATUS.jsonl / DISPATCH.jsonl /
SEARCH_BUDGET_V1.json / FORMAL_LAUNCH_V2.json; it imports nothing from
the execution stack and starts no models.

## Boundaries of this audit

- Ledger/settlement arithmetic, caps, retry classification, and the
  announced totals are verified. Scientific ANALYSIS claims (paired
  per-seed comparisons, deployment findings, v2.1 re-score zero-flips)
  were verified by the Formal workstream's own final-evidence commits
  (62c2dd9/05293dc/c23a780) and are cited, not recomputed, here.
- This audit does not authorize phase-4 model calls; it is one of the
  three phase-4 admission gates (Formal settlement audit ✓ pending
  operator acceptance · net-benefit gates · independent calibration
  plan).
