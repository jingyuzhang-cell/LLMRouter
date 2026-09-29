> **⚠️ HISTORICAL CHECKPOINT — SUPERSEDED.** This Phase-1 audit relied on the
> legacy f30_dynamic=0.4033, later retired by seed-isolated remeasurement
> (corrected to 0.3433). The claim that P_fault={Single,Dynamic} has been
> **withdrawn**; the frozen result is P_global={Single} in both states.
> See REFERENCE_CUBE.json and commit d7a2896 for the authoritative record.

# collab_scheduler_v1 — Phase 1: real-evidence audit of the state-conditioned Pareto claim (2026-09-27)

Enumerator + evaluator only (no surrogate, no search). Space per the frozen
design: G=(Y,X,Z,M); a cell counts as MEASURED only if a frozen artifact
directly contains its (Q,C,L); composed/estimated values forbidden;
everything else UNEVALUATED. sa_pgfs_v1 calibrated numbers never used.

## Headline: state-conditioned feasible sets and Pareto fronts — all-measured

Formalization: G(s) = state-dependent FEASIBLE strategy set;
P(s) = ND{ F(G|s) : G ∈ G(s) }. States change both the objectives AND the
feasible action set itself.

**Same-panel state change (frozen200, one task population, one strategy set)**
— the strong claim:

| state | measured ND front | reading |
|---|---|---|
| s_clean (200 tasks) | **{Single}** | Single dominates both DAG arms outright (Q 0.55 > 0.415 at ¼ cost) |
| s_fault30 (600 samples) | **{Single, DynamicDAG\|het\|reroute}** | front EXPANDS under fault: Dynamic Q 0.4033 > Single 0.3967 → non-dominated despite 3.1× cost |

P_clean = {Single} ≠ P_fault = {Single, Dynamic}: Dynamic is never
globally better — it becomes non-dominated only when the fault state
appears. This is the core empirical evidence for state-conditioned Pareto
scheduling.

**History-enabled setting (P0-2 96-task follow-up panel) — a SEPARATE case
study, not a horizontal comparison with frozen200** (different task
population, and the feasible set differs: RawReuse ∈ G(s_history) but is
infeasible in fresh states):

- G(s_history) adds reuse-type actions; in that setting **{SER\|reuse}
dominates regeneration and full rerun** — the front collapses to Raw-Reuse.

Together: states alter Q/C/L (clean→fault expands the front WITHIN a fixed
feasible set) and alter G(s) itself (history enables reuse, which then
dominates). Two distinct mechanisms, both measured.

## Evidence gap (what motivates SA-PGFS)

| slice | space | measured | unevaluated |
|---|---|---|---|
| s_clean / s_fault30 | 32 | 3 | 29 |
| s_history | 96 | 4 | 92 |

The combinatorial space is 10–30× larger than the measured evidence in every
slice; exhaustive real evaluation is the expensive step → surrogate-assisted
selection of which G to evaluate next (SA-PGFS) is the principled next phase,
now justified by measurement rather than assumption.

## Notes

- Budget slices: frozen200 Q(B) curves (f30) keep Single on the front at all
  listed budgets (dynamic's Q(B) crosses only beyond the panel's range) —
  budget alone does not flip the f30 front; fault status does.
- X-family exploration: cross_model_matrix supplies 9 real SER (Q-only) cells
  on its own panel (partial evidence; C/L unmeasured there).
- M extensions: 'partial-recompute' (P0-2 B) carried as a measured extra
  beyond the frozen M set; 'reuse-if-supported' = P1b-3 T-gated replay
  (Q 0.2763, C 573) — dominated by raw reuse in this state.

Artifacts: `AUDIT_V1.json`, `audit_v1.py` (enumerator + evidence map + exact
ND per slice).
