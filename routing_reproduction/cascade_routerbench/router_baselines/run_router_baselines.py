"""Phase 1: official router baselines (Random / KNN / MLP) on the frozen R1 protocol.

Reuses, unmodified:
  - routerbench/routers/{knn_router,mlp_router}.py (official classes, official defaults)
  - cascade-routing/src/selection/utils.py::auc_all (the R1 AUC definition)
  - runs/*/SMOKE_METADATA.json train/test indices (R1 frozen 5/95 split, seed 42)
  - data/routerbench_0shot.pkl (verified official artifact)

New code: RandomRouter (uniform over pool; the official repo ships no random router)
and this evaluation harness. No upstream files are edited.
"""
import hashlib
import json
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent  # cascade_routerbench/
OUT = pathlib.Path(__file__).resolve().parent          # router_baselines/
(OUT / "data").mkdir(exist_ok=True)
os.chdir(OUT)

sys.path.insert(0, str(ROOT / "routerbench"))
sys.path.insert(0, str(ROOT / "cascade-routing" / "src"))

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # official evaluate_routers.py default

import numpy as np
import pandas as pd

from embedding.cache import EmbeddingCache
from routers.knn_router import KNNRouter
from routers.mlp_router import MLPRouter
from selection.utils import auc_all
from utils import WILLINGNESS_TO_PAY  # routerbench/utils.py, official WTP grid


class RandomRouter:
    """Uniform random router over the pool. The official repo has none; this is the
    standard Random Router baseline. Seeded per setting for reproducibility."""

    def __init__(self, models_to_route, seed=0):
        self.models_to_route = list(models_to_route)
        self.rng = np.random.RandomState(seed)

    def batch_route_prompts(self, prompts, **kwargs):
        return self.rng.choice(self.models_to_route, size=len(prompts))


def evaluate_routing(test_df, routed, pool):
    """Per-sample quality and cost for a routing decision array."""
    routed = np.asarray(routed)
    assert set(routed) <= set(pool), f"router produced unknown model: {set(routed) - set(pool)}"
    quality = test_df[[m for m in pool]].to_numpy(dtype=float)[
        np.arange(len(test_df)), [list(pool).index(m) for m in routed]
    ]
    cost = test_df[[f"{m}|total_cost" for m in pool]].to_numpy(dtype=float)[
        np.arange(len(test_df)), [list(pool).index(m) for m in routed]
    ]
    return quality, cost


def main():
    data = pd.read_pickle(ROOT / "data" / "routerbench_0shot.pkl")
    data_sha = hashlib.sha256((ROOT / "data" / "routerbench_0shot.pkl").read_bytes()).hexdigest()
    model_cols = list(data.columns[3:14])  # the 11 model quality columns, same extraction as R1
    # dtype adaptation, semantics unchanged: object('0.0'..'1.0'/None) -> float
    data[model_cols] = data[model_cols].astype(float)

    cache = EmbeddingCache(local_mode=True, local_cache_path=str(OUT / "data" / f"embedding_cache_{EMBEDDING_MODEL}.pkl"))

    settings = []
    for meta_path in sorted((ROOT / "runs").glob("*/SMOKE_METADATA.json")):
        meta = json.loads(meta_path.read_text())
        settings.append((meta_path.parent.name, meta))
    settings.sort(key=lambda s: (s[1]["dataset"], len(s[1]["models"])))

    rows = []
    curve_rows = []
    started = time.time()
    for name, meta in settings:
        dataset, pool = meta["dataset"], list(meta["models"])
        train_df = data.loc[meta["train_indices"]]
        test_df = data.loc[meta["test_indices"]]
        assert meta["sample_count"] == len(train_df) + len(test_df)
        test_prompts = test_df["prompt"].tolist()

        baseline_qualities = [float(test_df[m].mean()) for m in pool]
        baseline_costs = [float(test_df[f"{m}|total_cost"].mean()) for m in pool]

        # reference single points, same definitions as R1
        best = train_df[pool].mean().idxmax()
        rows.append(dict(setting=name, dataset=dataset, model_count=len(pool), method="Best Single (train selected)",
                         auc=None, quality=float(test_df[best].mean()), mean_cost=float(test_df[f"{best}|total_cost"].mean())))
        rows.append(dict(setting=name, dataset=dataset, model_count=len(pool), method="Oracle (per-query hindsight)",
                         auc=None, quality=float(test_df[pool].max(axis=1).mean()), mean_cost=None))

        routers = {
            "Random": RandomRouter(pool, seed=0),
            "KNN (official)": KNNRouter(embedding_model=EMBEDDING_MODEL, cache=cache,
                                        train_file=train_df, n_neighbors=min(50, len(train_df)),
                                        distance_metric="cosine", models_to_route=pool),
            "MLP (official)": MLPRouter(embedding_model=EMBEDDING_MODEL, cache=cache,
                                        train_file=train_df, hidden_layer_sizes=(100, 100, 100),
                                        activation_function="relu", learning_rate_method="constant",
                                        learning_rate=0.001, models_to_route=pool),
        }

        for method, router in routers.items():
            t0 = time.time()
            if method == "Random":
                routed = router.batch_route_prompts(test_prompts)
                quality, cost = evaluate_routing(test_df, routed, pool)
                rows.append(dict(setting=name, dataset=dataset, model_count=len(pool), method=method,
                                 auc=None, quality=float(quality.mean()), mean_cost=float(cost.mean())))
                print(f"{name} {method}: quality={quality.mean():.4f} cost={cost.mean():.6f} ({time.time()-t0:.0f}s)", flush=True)
                continue
            qualities, costs = [], []
            for w in WILLINGNESS_TO_PAY:
                routed = router.batch_route_prompts(test_prompts, willingness_to_pay=w)
                quality, cost = evaluate_routing(test_df, routed, pool)
                qualities.append(float(quality.mean()))
                costs.append(float(cost.mean()))
                curve_rows.append(dict(setting=name, dataset=dataset, model_count=len(pool),
                                       method=method, wtp=w, quality=float(quality.mean()),
                                       mean_cost=float(cost.mean())))
            auc = auc_all(qualities, costs, baseline_qualities, baseline_costs)["auc"]
            k = int(np.argmax(qualities))
            rows.append(dict(setting=name, dataset=dataset, model_count=len(pool), method=method,
                             auc=auc, quality=qualities[k], mean_cost=costs[k]))
            print(f"{name} {method}: auc={auc:.4f} maxq={qualities[k]:.4f} ({time.time()-t0:.0f}s)", flush=True)

    # R1 reference AUCs (LogReg-based 'Routing' policy), read-only
    for name, meta in settings:
        r1 = json.loads((ROOT / "runs" / name / "REPRO_RESULTS.json").read_text())
        routing_auc = next(r["auc"] for r in r1["results"] if r["policy"] == "Routing")
        rows.append(dict(setting=name, dataset=meta["dataset"], model_count=len(meta["models"]),
                         method="Routing LogReg (R1 frozen)", auc=routing_auc, quality=None, mean_cost=None))

    results = pd.DataFrame(rows).sort_values(["dataset", "model_count", "method"])
    results.to_csv(OUT / "ROUTER_BASELINE_RESULTS.csv", index=False)
    pd.DataFrame(curve_rows).to_csv(OUT / "ROUTER_BASELINE_CURVES.csv", index=False)

    audit = dict(
        status="PASS",
        started=time.strftime("%Y-%m-%dT%H:%M:%S"),
        elapsed_seconds=round(time.time() - started, 1),
        embedding_model=EMBEDDING_MODEL,
        embedding_backend="local sentence_transformers (CPU), official EmbeddingCache local_mode",
        data=dict(path=str(ROOT / "data" / "routerbench_0shot.pkl"), sha256=data_sha),
        split="R1 frozen 5/95 seed 42, indices read verbatim from runs/*/SMOKE_METADATA.json",
        routers=dict(
            random="uniform over pool, np.random.RandomState(0) per setting",
            knn="official KNNRouter, cosine; n_neighbors=50 (official default), capped to n_train where the frozen 5/95 split has <50 train samples (modern sklearn raises where older sklearn auto-capped)",
            mlp="official MLPRouter, hidden (100,100,100), relu, lr 0.001, max_iter 200, random_state 1234",
        ),
        wtp_grid="official routerbench/utils.py WILLINGNESS_TO_PAY (32 points)",
        adaptation="model quality columns (graded scores) cast object->float before use; no other data changes",
        auc="upstream auc_all (cascade-routing/src/selection/utils.py), baseline = per-model test means",
        settings={name: dict(dataset=meta["dataset"], pool=meta["models"], n_train=meta["train_count"],
                             n_test=meta["test_count"]) for name, meta in settings},
    )
    (OUT / "ROUTER_BASELINE_RUN.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    print(results.to_string(index=False))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
