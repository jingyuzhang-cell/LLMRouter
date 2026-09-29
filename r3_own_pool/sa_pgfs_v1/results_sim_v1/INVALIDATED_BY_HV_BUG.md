INVALIDATED BY HV IMPLEMENTATION BUG (2026-09-27)

Every HV-based number in this directory was produced with the broken
sa_pgfs_v1/pareto.hypervolume (2D/3D branches each returned a single extreme
point's box and violated monotonicity under point addition) and the broken
acquisition.ehvi (sample/candidate axis swap). Do not cite any value from
results_sim_v1 — including values that a regeneration may happen to
reproduce closely.

Replacement: ../results_sim_v1_regenerated/ (same protocol, fixed
implementations; see sa_pgfs_v1/sim_search_regression.py and the regression
tests test_pareto_regression.py / test_acquisition_regression.py).
