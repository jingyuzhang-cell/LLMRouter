"""Regenerate sim_search (stage A) with the FIXED hypervolume/EHVI.

The original results_sim_v1 was produced before the 2026-09-27 fixes to
pareto.hypervolume (2D/3D returned a single extreme point's box) and
acquisition.ehvi (axis bug) — its HV traces and strategy ratios are invalid
pending this regeneration. Zero model calls (composed space).

Run: python3 -m sa_pgfs_v1.sim_search_regression   (backgroundable)
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sa_pgfs_v1 import sim_search  # noqa: E402

sim_search.OUT = ROOT / 'sa_pgfs_v1/results_sim_v1_regenerated'

if __name__ == '__main__':
    t0 = time.time()
    sim_search.run()
    print(f'regenerated wall {time.time() - t0:.1f}s -> {sim_search.OUT}')
