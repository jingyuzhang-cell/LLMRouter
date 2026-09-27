# SA-PGFS — Surrogate-Assisted Pareto Graph Forest Scheduling (prototype)

**Calibrated zero-call simulation for algorithm development.
Results are NOT empirical workflow-performance claims.**

This package validates that the SA-PGFS algorithm components work correctly —
Pareto dominance / exact 3D hypervolume / knee-point and budget selection
(`pareto.py`), graph individuals G=(Y,X,Z,M) with fixed-length features and
graph distance (`graph_spec.py`), a candidate space calibrated against frozen
artifacts (`space.py`), a GP surrogate for the only expensive objective Q
(`surrogate.py`), MC-EHVI and cost-aware EHVI acquisition (`acquisition.py`),
and the MEoH-style dual (Pareto + diversity) archive (`archive.py`).

The 559-config space composes ground truth from frozen measurements
(frozen200 anchors, cross-model matrix, node SCORED_MATRIX) with documented
assumptions (interaction correction, correlation discounts, quality-neutral
verification, Q ceiling). Its frontier shape REPRODUCES the paper's measured
panel structure (static dominated by single; recovery as the effective
dimension) but contains topologies never actually executed. Do not cite
numbers out of `results_*/` as workflow performance.

When the second paper's search phase runs, candidate graphs get REAL
evaluations (LLM executions on the frozen panel) and this space becomes the
initial design + fallback; the surrogate/acquisition/archive modules carry
over unchanged.

## Modules

- `pareto.py` — dominance, 2D/3D exact hypervolume, knee point, budget/preference selection
- `graph_spec.py` — Graph individual (Y topology, X assignment, Z recovery, M reuse), φ(G), D(G,G')
- `space.py` — frozen-artifact-calibrated candidate space + composed ground truth
- `surrogate.py` — GP over φ(G) → Q (C and L are deterministic, no surrogate needed)
- `acquisition.py` — MC-EHVI and EHVI/C_eval (per-unit-cost hypervolume gain)
- `archive.py` — Pareto archive + dominance-dissimilarity diversity archive
- `sim_search.py` — zero-call search simulation (HV vs #evaluations / vs spent cost)

## Run

    cd /root/r3_own_pool && python3 -m sa_pgfs_v1.sim_search
