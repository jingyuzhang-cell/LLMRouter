"""Free decomposition of the within-task oracle gap on binary objective labels.

Null: within each dataset, each slot's per-query correctness is exchangeable Bernoulli
with the slot's observed dataset-level rate (independent across slots). This destroys
all query-level structure while preserving dataset-level rates.
If the observed within-task gap matches the null, the gap is exactly what uncorrelated
outcomes produce (ex-post max-of-noise), i.e., not predictable ex ante.
No API, train-only, deterministic given seed.
"""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SLOTS = ["small", "medium", "large", "reasoning"]
OUT = ROOT / "router_v2/gap_null_20260910"
rng = np.random.default_rng(42)

rows = [json.loads(l) for l in open(ROOT / "data/train_matrix_snapshot_20260909c/TRAIN_MATRIX.jsonl") if l.strip()]
data = []
for r in rows:
    if r["dataset"] == "arenahard":
        continue  # judge-graded continuous; permutation null defined on binary outcomes
    q = {s["slot"]: s for s in r["responses"]}
    if all(s in q and q[s].get("quality", {}).get("final") is not None for s in SLOTS):
        y = np.array([q[s]["quality"]["final"] for s in SLOTS])
        if set(np.unique(y)) <= {0.0, 1.0}:
            data.append((r["query_id"], r["dataset"], y))

ds_arr = np.array([d[1] for d in data])
Y = np.stack([d[2] for d in data])
datasets = sorted(set(ds_arr.tolist()))

def gaps(M):
    oracle = M.max(1).mean()
    dsel = {}
    for ds in datasets:
        m = ds_arr == ds
        dsel[ds] = int(np.argmax(M[m].mean(0)))
    dbest = np.mean([Y_i[dsel[ds_arr[i]]] for i, Y_i in enumerate(M)])
    return oracle, dbest, oracle - dbest

obs_o, obs_d, obs_gap = gaps(Y)
rates = {ds: Y[ds_arr == ds].mean(0) for ds in datasets}

n_perm = 2000
null_gaps = np.empty(n_perm)
for k in range(n_perm):
    P = np.empty_like(Y)
    for ds in datasets:
        m = ds_arr == ds
        nds = int(m.sum())
        p = rates[ds]
        for j in range(len(SLOTS)):  # independent Bernoulli at observed rates
            P[m, j] = rng.random(nds) < p[j]
    null_gaps[k] = gaps(P)[2]

pct = float((null_gaps >= obs_gap).mean() * 100)
per_ds = {}
for ds in datasets:
    m = ds_arr == ds
    per_ds[ds] = dict(n=int(m.sum()),
                      rates={SLOTS[j]: round(float(rates[ds][j]), 4) for j in range(4)},
                      observed_within_gap=round(float(Y[m].max(1).mean() - Y[m, int(np.argmax(rates[ds]))].mean()), 4))

OUT.mkdir(parents=True, exist_ok=True)
result = dict(
    role="exploratory_train_only_gap_null", n=len(data), n_perm=n_perm, seed=42,
    observed=dict(oracle=round(float(obs_o), 4), dataset_best=round(float(obs_d), 4),
                  within_task_gap=round(float(obs_gap), 4)),
    null=dict(mean=round(float(null_gaps.mean()), 4), sd=round(float(null_gaps.std()), 4),
              p95=round(float(np.quantile(null_gaps, 0.95)), 4),
              pct_null_ge_observed=pct),
    per_dataset=per_ds,
    interpretation=("observed within-task gap >= null 95th pct => excess query-level disagreement "
                    "structure exists (potentially learnable); close to null mean => gap is "
                    "max-of-noise, not predictable ex ante"),
    limits=["independent-Bernoulli null also destroys shared difficulty; all-wrong/all-right queries "
            "contribute ~0 to this gap by construction",
            "arenahard excluded (judge-graded continuous labels); binary objective only"])
(OUT / "RESULTS.json").write_text(json.dumps(result, indent=1))
print(json.dumps(result, indent=1)[:1500])
