# B1/B2/B3 fix status (ruling on 781fd25) — all three closed; zero real calls

## B1 — reward settlement unified with the declared C (FIXED)

Every settlement row now carries TWO rewards, each computed
CONSISTENTLY (recomputed by `realized_rtask`, never a patched field):
- **`R_conditional`** (PRIMARY): C = the arm's own incremental tokens,
  T = the arm's own episode time from the identical shared post-fault
  state. This is the recovery-CONDITIONAL net benefit — what the
  shared-snapshot design actually measures.
- **`R_full_task_cost_view`** (SECONDARY): C = per-task base + 
  incremental; same T (labeled: shared base wall time is not fairly
  attributable per arm) — an attribution view, explicitly NOT marked
  as a verified independent end-to-end deployment metric.
T12 verifies BOTH rewards against independent hand computation
(`realized_rtask` re-derived in the test) for every DAG row.

## B2 — per-task base attribution (FIXED)

`_per_task_base_tokens()` reads the base engine's own ledger and
records PER-TASK physical base tokens. The batch÷6 division is GONE.
T12 asserts: per-task keys == task set, all > 0, and
Σ(per-task) == base total. The primary endpoint is declared
recovery-conditional; the full-task cost view is reported separately
with its limitation stated in every row's `metric_semantics`.

## B3 — real safety gates (FIXED, entry-owned)

Inside `execute()`:
1. **P3 freeze hash VERIFIED** before any spend — T12 proves a wrong
   hash is refused with NO DISPATCH file created.
2. **GPU-exclusive flock** taken when `gpu_lock_path` is provided;
   released in finally.
3. **Entry-owned failure protection**: any exception →
   `manager.stop_current()` (model server stopped — T12 counts the
   stops), `write_results(INCOMPLETE)` WITH reason and traceback —
   written by the ENTRY, not by test code (T12 previously wrote it
   manually; the new T12 only READS the artifact), ledgers preserved,
   exception re-raised. No auto-restart exists anywhere.
4. Same-dir re-execution refused; INCOMPLETE twin permanently blocks
   COMPLETE.
5. The proposed caps (60 req / 25K tok / 1,800 s) are recorded in the
   payload as `caps_proposed` with the explicit note that they are a
   PROPOSAL pending operator approval.

## Verification

T1–T12 all PASS (13/13); full M-suite (15 suites) + admission check
green at this commit. Zero real model calls, zero GPU; P3 freeze
untouched (sha b04ffb29…); reward weights unchanged.

**Remaining before the pilot: the operator's GO/NO-GO only (and, at
GO, the budget approval for 3 tasks × 6 arms).**
