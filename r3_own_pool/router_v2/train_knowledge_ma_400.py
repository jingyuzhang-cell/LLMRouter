"""Four-model MMLU-Pro MA after the pre-registered routability gate passes."""
import json
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import Ridge
from torch import nn

from .data import sha
from .mmlu_learnability import group_ci


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "router_v2/knowledge_validation_400_results"
PANEL_DIR = ROOT / "router_v2/knowledge_validation_400"
OUT = ROOT / "router_v2/experiment_knowledge_ma_400"
EMBEDDINGS = ROOT / "data/embeddings_full_v2_recovery1/EMBEDDINGS.npz"
SLOTS = ["medium", "large", "coder", "reasoning"]
SEEDS = [42, 43, 44]


class UtilityMA(nn.Module):
    """Shared f(e_q, e_m) predicting one scalar realized utility per pair."""

    def __init__(self, query_dim, model_dim=8):
        super().__init__()
        self.model_embedding = nn.Embedding(len(SLOTS), model_dim)
        self.head = nn.Sequential(
            nn.Linear(query_dim + model_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def forward(self, query):
        expanded_query = query[:, None, :].expand(-1, len(SLOTS), -1)
        models = self.model_embedding.weight[None, :, :].expand(len(query), -1, -1)
        return self.head(torch.cat([expanded_query, models], dim=-1)).squeeze(-1)


def fit_ma(x_train, y_train, x_eval, seed):
    torch.manual_seed(seed)
    model = UtilityMA(x_train.shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
    tx = torch.tensor(x_train, dtype=torch.float32)
    ty = torch.tensor(y_train, dtype=torch.float32)
    te = torch.tensor(x_eval, dtype=torch.float32)
    rng = np.random.default_rng(seed)
    model.train()
    for _ in range(50):
        for batch in np.array_split(rng.permutation(len(tx)), int(np.ceil(len(tx) / 32))):
            loss = (model(tx[batch]) - ty[batch]).square().mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    model.eval()
    with torch.no_grad():
        prediction = model(te).numpy()
    return prediction, model.state_dict()


def summarize(y, choices, groups):
    rows = np.arange(len(y))
    baseline = y[rows, choices["DatasetBest"]]
    oracle = y.max(1)
    gap = float((oracle - baseline).mean())
    methods = {}
    for name, choice in choices.items():
        routed = y[rows, choice]
        gain = routed - baseline
        ci = group_ci(gain, groups)
        methods[name] = {
            "accuracy": float(routed.mean()),
            "gain_vs_datasetbest": float(gain.mean()),
            "gain_ci95": ci,
            "gap_recovery": float(gain.mean() / gap),
            "gap_recovery_ci95": [float(v / gap) for v in ci],
            "rescued": int((gain > 0).sum()),
            "harmed": int((gain < 0).sum()),
            "selection_counts": dict(zip(SLOTS, np.bincount(choice, minlength=len(SLOTS)).tolist())),
        }
    seed_scores = np.array([
        y[rows, choices[f"MA_seed{seed}"]] for seed in SEEDS
    ])
    averaged = seed_scores.mean(0)
    gain = averaged - baseline
    ci = group_ci(gain, groups)
    methods["MA_seed_mean"] = {
        "accuracy": float(averaged.mean()),
        "gain_vs_datasetbest": float(gain.mean()),
        "gain_ci95": ci,
        "gap_recovery": float(gain.mean() / gap),
        "gap_recovery_ci95": [float(v / gap) for v in ci],
        "note": "Mean realized accuracy across the three fixed seed routers; queries/seeds are not pooled as independent samples.",
    }
    return {
        "n": len(y),
        "oracle_accuracy": float(oracle.mean()),
        "datasetbest_accuracy": float(baseline.mean()),
        "oracle_gap": gap,
        "methods": methods,
    }


def main():
    torch.set_num_threads(4)
    if OUT.exists():
        raise FileExistsError(OUT)
    diagnostic = json.loads((SOURCE / "RESULTS.json").read_text())
    if diagnostic["gate"] != {
        "oracle_gap_gt_8pct": True,
        "winner_entropy_gt_0_7": True,
        "pass": True,
        "next_action": "READY_FOR_MA_DESIGN",
    }:
        raise ValueError("Pre-registered routability gate did not pass exactly")
    for path, expected in diagnostic["sources"].items():
        if path in ("panel", "panel_protocol", "coder", "collector_and_analysis"):
            continue
    source_hashes = {
        "diagnostic_results": sha(SOURCE / "RESULTS.json"),
        "diagnostic_npz": sha(SOURCE / "DIAGNOSTIC.npz"),
        "panel": sha(PANEL_DIR / "PANEL.jsonl"),
        "panel_protocol": sha(PANEL_DIR / "PROTOCOL.json"),
        "query_embeddings": sha(EMBEDDINGS),
        "trainer": sha(Path(__file__)),
    }
    if source_hashes["panel"] != diagnostic["sources"]["panel"]:
        raise ValueError("Panel provenance mismatch")
    with np.load(SOURCE / "DIAGNOSTIC.npz", allow_pickle=False) as saved:
        ids = saved["ids"]
        folds = saved["folds"].astype(int)
        y = saved["quality"].astype("float32")
    panel = {row["query_id"]: row for row in map(json.loads, (PANEL_DIR / "PANEL.jsonl").read_text().splitlines())}
    groups = np.array([panel[q]["prompt_group"] for q in ids])
    with np.load(EMBEDDINGS, allow_pickle=False) as saved:
        index = {qid: i for i, qid in enumerate(saved["ids"].tolist())}
        x = saved["vectors"][[index[q] for q in ids]].astype("float32")
    if y.shape != (400, 4) or x.shape[0] != 400 or not np.isin(y, [0, 1]).all() or not np.isfinite(x).all():
        raise ValueError("Invalid MA input")
    names = ["BestSingle", "DatasetBest", "QueryOnlyRidge"] + [f"MA_seed{s}" for s in SEEDS]
    choices = {name: np.empty(400, dtype=int) for name in names}
    predicted = {"QueryOnlyRidge": np.empty_like(y)}
    predicted.update({f"MA_seed{s}": np.empty_like(y) for s in SEEDS})
    trace = []
    OUT.mkdir(parents=True)
    for fold in sorted(set(folds)):
        train = np.flatnonzero(folds != fold)
        valid = np.flatnonzero(folds == fold)
        if set(groups[train]) & set(groups[valid]):
            raise ValueError("Prompt-group leakage")
        best = int(y[train].mean(0).argmax())
        choices["BestSingle"][valid] = best
        # This panel has one dataset, so DatasetBest is intentionally identical.
        choices["DatasetBest"][valid] = best
        ridge_prediction = Ridge(alpha=1.0).fit(x[train], y[train]).predict(x[valid])
        predicted["QueryOnlyRidge"][valid] = ridge_prediction
        choices["QueryOnlyRidge"][valid] = ridge_prediction.argmax(1)
        for seed in SEEDS:
            name = f"MA_seed{seed}"
            ma_prediction, state = fit_ma(x[train], y[train], x[valid], seed)
            predicted[name][valid] = ma_prediction
            choices[name][valid] = ma_prediction.argmax(1)
            torch.save(state, OUT / f"model_fold{fold}_seed{seed}.pt")
        trace.append({
            "fold": int(fold),
            "train_ids": ids[train].tolist(),
            "validation_ids": ids[valid].tolist(),
            "best_single_model": SLOTS[best],
        })
        print(f"finished fold {fold}", flush=True)
    if not np.array_equal(choices["BestSingle"], choices["DatasetBest"]):
        raise AssertionError("Single-dataset baselines must be identical")
    report = summarize(y, choices, groups)
    protocol = {
        "role": "train-only four-model MMLU-Pro MA after frozen diagnostic gate",
        "target": "single-generation binary realized utility U(q,m); no repeat-mean or variance claim",
        "inputs": "e_q=frozen normalized GTE 3584; e_m=learned embedding table 4x8",
        "architecture": "concat(e_q,e_m) -> Linear64 -> ReLU -> Linear1 -> sigmoid, shared across models",
        "loss": "MSE over all four model utilities; ties retained",
        "epochs": 50,
        "batch_size": 32,
        "learning_rate": 0.001,
        "weight_decay": 0.01,
        "seeds": SEEDS,
        "ridge": "multi-output Ridge alpha=1 on query embedding only",
        "folds": "inherited three group-isolated folds; no outer-fold tuning or early stopping",
        "baselines": ["BestSingle", "DatasetBest", "QueryOnlyRidge", "MA"],
        "note": "BestSingle and DatasetBest are identical because every query is MMLU-Pro.",
        "goal": "20%-30% gap recovery is an evaluation target, not a pass condition or guaranteed result.",
        "source_sha256": source_hashes,
        "limits": [
            "Development-only original-train panel, selected after a 120-query directional diagnosis.",
            "The same 400 outcomes triggered the gate and evaluate MA; this is not independent confirmation.",
            "Single responses do not estimate expected-utility variance or repeat stability.",
            "Historical and Coder responses were served at different times/stacks; no latency or cost comparison.",
        ],
    }
    (OUT / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    (OUT / "RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / "FOLDS.json").write_text(json.dumps(trace, indent=2) + "\n")
    np.savez_compressed(OUT / "PREDICTIONS.npz", ids=ids, folds=folds, quality=y,
                        **{f"choice_{k}": v for k, v in choices.items()},
                        **{f"prediction_{k}": v for k, v in predicted.items()})
    lines = [
        "# MMLU-Pro 400题四模型MA", "",
        f"Oracle={report['oracle_accuracy']:.2%}；DatasetBest={report['datasetbest_accuracy']:.2%}；Gap={report['oracle_gap']:.2%}。", "",
        "| 方法 | Accuracy | 相对DatasetBest | Gap Recovery | 95%区间 |",
        "|---|---:|---:|---:|---|",
    ]
    for name, result in report["methods"].items():
        lines.append(f"| {name} | {result['accuracy']:.2%} | {result['gain_vs_datasetbest']*100:+.2f} pp | "
                     f"{result['gap_recovery']:.2%} | {result['gap_recovery_ci95']} |")
    lines.extend([
        "", "BestSingle与DatasetBest在单一MMLU-Pro数据集上定义相同，并均只用训练折选择。",
        "20%-30% Gap Recovery是合理目标区间，不是预注册成功门槛。全部固定seed均报告，不选择最好seed。",
        "这是原train开发实验；同一400题先触发门禁再评估MA，因此需要新的独立面板才能形成论文主结论。",
    ])
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
