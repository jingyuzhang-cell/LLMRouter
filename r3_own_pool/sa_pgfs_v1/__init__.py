"""SA-PGFS: Surrogate-Assisted Pareto Graph Forest Scheduling.

Second-paper method core. The optimization problem:

    max_G ( Q(G), -C(G), -L(G) )   over   G = (Y, X, Z, M)

Y DAG topology, X node-model assignment, Z recovery policy, M reuse policy.
C and L are deterministic given (Y, X) profiles; Q is the expensive black box
(real LLM executions) → surrogate-assisted search (stage A, offline forest
construction) + state-conditioned Pareto scheduling (stage B, online).

Modules: pareto (dominance/HV/knee/selection), graph_spec (G + features +
graph distance), space (frozen-artifact-calibrated candidate space),
surrogate (GP over phi(G) -> Q), acquisition (EHVI, cost-aware EHVI),
archive (Pareto archive + diversity archive), sim_search (zero-call search
simulation producing HV-vs-real-evaluation curves).
"""
