"""Archived P1 statistic: task-clustered bootstrap CI for recovery effects.

Reproduces DELTA_Z_BOOTSTRAP.json exactly (rng seed 20261008, 10000 resamples,
tasks resampled with replacement, 3 fault seeds averaged within task).
Run: python3 -m collab_scheduler_v1.fault30_prep.delta_z_bootstrap
"""
import json
from pathlib import Path
import numpy as np

ROOT = Path('/root/r3_own_pool')
res = json.loads((ROOT / 'collab_scheduler_v1/fault30_prep/FAULT30_RESULTS.json').read_text())
seeds = sorted(res['seeds'])
rng = np.random.default_rng(20261008)
out = {}
for fam in ('BALANCED', 'HETEROGENEOUS', 'QUALITY'):
    none_c = f'DYNAMICDAG__{fam}__NONE__FRESH'
    rr_c = f'DYNAMICDAG__{fam}__LOCAL_REROUTE__FRESH'
    uids = list(res['seeds'][seeds[0]][none_c])
    vals = {}
    for m, f in (('Q', 'ok'), ('C', 'used'), ('L', 'lat')):
        a = np.array([np.mean([res['seeds'][s][rr_c][u][f] - res['seeds'][s][none_c][u][f]
                               for s in seeds]) for u in uids])
        bs = np.array([np.mean(a[rng.integers(len(a), size=len(a))]) for _ in range(10000)])
        vals[m] = dict(mean=float(a.mean()),
                       ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                       p_two_sided=float(2 * min((bs <= 0).mean(), (bs >= 0).mean())))
    out[fam] = vals
doc = dict(method='task-cluster bootstrap (tasks resampled with replacement; '
                  '3 fault seeds averaged within task — preserves dependence)',
           n_tasks=200, n_boot=10000, seed=20261008,
           command='python3 -m collab_scheduler_v1.fault30_prep.delta_z_bootstrap',
           delta_Z_reroute_minus_none=out, zero_model_calls=True)
(ROOT / 'collab_scheduler_v1/fault30_prep/DELTA_Z_BOOTSTRAP.json').write_text(json.dumps(doc, indent=1))
print(json.dumps({k: (v['Q']['mean'], v['Q']['ci95'], round(v['Q']['p_two_sided'], 4))
                  for k, v in out.items()}, indent=1))
