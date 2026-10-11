# M3_ERRATA_2 — reused-DONE ctx-drift boundary (review of baseline 4937789)

Operator dual-line review finding: at the M3-errata baseline 4937789,
`evaluate_plan`'s input-identity drift check lived only in the
will-execute branch; a DONE node NOT in R fell to
`changed[n] = parents_changed`, so a ctx change (e.g. ctx_table A→B)
under R=[] could leave the stale e1 output reusable, cascading stale
r/v reuse — contradicting the frozen rule that reuse requires unchanged
input identity.

## Timeline (honest)

- The gap is REAL at 4937789 (the reviewer's baseline).
- It was CLOSED during M4 development (commit de09efe): the non-execute
  branch now compares every candidate-for-reuse DONE node's CURRENT
  input signature (ctx sha + cached parent answers) against its frozen
  `exec_identity`; drift ⇒ `input_identity_changed:<node>` ⇒ staleness
  propagates to descendants ⇒ reject/complete handling. The M4 suite's
  `b1b_r_empty_no_stale_reuse` already pinned the reject direction.
- THIS errata adds the two reviewer-mandated REVERSE tests to the M3
  suite (`test_dag_closure.py`), so the boundary is pinned at the
  milestone where the review found it, independent of the M4 suite:

## New tests (both PASS)

- `f10_ctx_drift_r_empty_rejects_old_cache`: same uid, ctx A→B, R=[]
  → **legal=False**, invalidated ('e1','r','v'),
  `input_identity_changed:e1` in reasons, reuse == () — the stale cache
  is NOT reusable.
- `f11_ctx_drift_r_empty_complete_repairs`: complete mode → legal=True,
  execute == ((e1,True),(r,True),(v,True)) — the affected node AND its
  descendants are explicitly completed as NEW calls — reuse == ('e2',)
  (the unaffected branch), `closure_completed:e1,r,v` recorded.

## Regression

All suites re-run: M1 21/21 · M2 24/24 · **M3 37/37 (35 + the two new
reverse tests)** · M4 25/25 · M5+M6 18/18 · phase-3 19/19 · boundary
14/14 = **158/158**, zero real model calls. No existing assertion was
modified.

**Status: boundary closed and pinned at HEAD. M4 admission awaits the
operator's M3 final acceptance; M4–M6 work remains unauthorized until
then per the dual-line review.**
