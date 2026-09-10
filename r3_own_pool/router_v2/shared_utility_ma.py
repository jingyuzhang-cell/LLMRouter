"""P1 skeleton: shared utility predictor U(q,m). NOT for training until P0 passes.

Design (user-pinned 2026-09-10): U_hat(q,m) = f(e_q, e_m) with a shared query
encoder and one model embedding per pool entry. Routing score for a pair is the
antisymmetric difference DeltaU = U_hat(q,reasoning) - U_hat(q,large); swapping
model order flips only the sign. Extending the pool adds one embedding row and
leaves the form of all existing predictions unchanged.

Status: wiring + synthetic smoke only. Real training fails closed unless the P0
learnability gate passes (mmlu_learnability RESULTS signal_gate_pass=true) and
all 400 paired distributions are complete. Multi-objective Score(q,m) =
U_hat - lambda_c*Cost - lambda_l*Latency is carried as fields only; weights stay
unset until MA learns (see router_v2/multiobjective_design.md).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .data import sha

ROOT = Path(__file__).resolve().parents[1]
SLOT_ORDER = ("large", "reasoning")
SLOT_INDEX = {s: i for i, s in enumerate(SLOT_ORDER)}


def build_records(labels_path, source_dir):
    """Flatten EXPECTED_UTILITY_LABELS.jsonl into per-(query, model) records.

    One row per query and slot: quality from the repeat posterior mean, cost as
    mean kTokens, latency as mean seconds. Format: query_id, query_embedding,
    model, quality, cost, latency — never a winner label.
    """
    from .diagnose_rank_signal import load_inputs

    frozen, x, _ = load_inputs(Path(source_dir))
    emb_by_id = {qid: x[i].astype(np.float32) for i, qid in enumerate(frozen["ids"])}
    labels = [json.loads(l) for l in Path(labels_path).read_text().split("\n") if l.strip()]
    records = []
    for row in labels:
        qid = row["query_id"]
        for slot in SLOT_ORDER:
            d = row["distributions"][slot]
            records.append(dict(
                query_id=qid, model=slot,
                query_embedding=emb_by_id[qid],
                quality=float(d["posterior_mean"]),
                empirical_quality=float(d["empirical_mean"]),
                n_repeats=int(d["n"]),
                cost_ktok=float(d["mean_total_ktokens"]),
                latency_s=float(d["mean_latency_seconds"]),
            ))
    return records


def pair_matrix(records):
    """Rows = queries; returns embeddings, U targets, DeltaU target, meta."""
    by_query = {}
    for r in records:
        by_query.setdefault(r["query_id"], {})[r["model"]] = r
    qids = sorted(by_query)
    emb = np.stack([by_query[q]["large"]["query_embedding"] for q in qids])
    u = np.array([[by_query[q][s]["quality"] for s in SLOT_ORDER] for q in qids], dtype=np.float32)
    meta = [{q: {s: {k: by_query[q][s][k] for k in ("cost_ktok", "latency_s", "n_repeats")}} for s in SLOT_ORDER} for q in qids]
    return qids, emb, u, meta


class SharedUtility(nn.Module):
    """f(e_q, e_m): shared trunk on [query features, model embedding] -> scalar U."""

    def __init__(self, query_dim, num_models=2, model_dim=16, hidden=64, seed=42):
        super().__init__()
        torch.manual_seed(seed)
        self.model_embedding = nn.Embedding(num_models, model_dim)
        self.head = nn.Sequential(
            nn.Linear(query_dim + model_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, 1),
        )

    def forward(self, q, model_idx):
        m = self.model_embedding(model_idx)
        return self.head(torch.cat([q, m], dim=1)).squeeze(-1)

    def delta(self, q):
        """U(q,reasoning) - U(q,large); antisymmetric under slot swap."""
        n = q.shape[0]
        return self.forward(q, torch.ones(n, dtype=torch.long)) - \
               self.forward(q, torch.zeros(n, dtype=torch.long))


def losses(model, q, u_target, weight_pair=1.0):
    """Two objectives only: MSE regression on U and pairwise sign on DeltaU."""
    idx = torch.arange(q.shape[0]).repeat_interleave(2)
    slot = torch.arange(2).repeat(q.shape[0])
    qf = q[idx]
    u_pred = model(qf, slot)
    reg = F.mse_loss(u_pred, u_target.reshape(-1))
    d_pred = model.delta(q)
    d_target = u_target[:, 1] - u_target[:, 0]
    nonzero = d_target != 0
    if nonzero.any():
        pair = F.binary_cross_entropy_with_logits(d_pred[nonzero], (d_target[nonzero] > 0).float())
    else:
        pair = d_pred.new_tensor(0.)
    return reg + weight_pair * pair, dict(reg=float(reg.detach()), pair=float(pair.detach()))


def train_oof(emb, u, fold_of_query, seed=42, epochs=60, lr=1e-3):
    """Fold-isolated OOF: each query scored by a model never trained on its fold."""
    from sklearn.metrics import roc_auc_score

    emb_t = torch.tensor(emb)
    u_t = torch.tensor(u)
    delta_target = u[:, 1] - u[:, 0]
    oof_delta = np.zeros(len(u), dtype=np.float32)
    for fold in sorted(set(fold_of_query)):
        tr = np.flatnonzero(fold_of_query != fold)
        va = np.flatnonzero(fold_of_query == fold)
        model = SharedUtility(emb.shape[1], seed=seed)
        opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
        for _ in range(epochs):
            opt.zero_grad()
            loss, _ = losses(model, emb_t[tr], u_t[tr])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            oof_delta[va] = model.delta(emb_t[va]).numpy()
    nonzero = delta_target != 0
    two_class = len(np.unique(delta_target[nonzero] > 0)) == 2
    return dict(
        oof_delta=oof_delta.tolist(),
        auc_pair=float(roc_auc_score((delta_target[nonzero] > 0), oof_delta[nonzero])) if nonzero.any() and two_class else None,
        auc_n=int(nonzero.sum()),
    )


def gate(learnability_results):
    """Fail closed unless the P0 learnability gate explicitly passed."""
    p = Path(learnability_results)
    if not p.exists():
        raise RuntimeError("P0 learnability results missing; run mmlu_learnability first")
    d = json.loads(p.read_text())
    if not d.get("signal_gate_pass"):
        raise RuntimeError("P0 gate NOT passed (signal_gate_pass != true); MA training not authorized")
    return d


def smoke():
    """Synthetic wiring check: shared head recovers a planted utility surface."""
    rng = np.random.default_rng(0)
    n, dim = 400, 16
    q = rng.normal(size=(n, dim)).astype(np.float32)
    true_w = rng.normal(size=dim).astype(np.float32)
    u = np.stack([(q @ true_w) * 0.1 + 0.5, (q @ true_w) * 0.1 + 0.5 + q[:, 0] * 0.4], 1)
    u = np.clip(u, 0, 1).astype(np.float32)
    folds = rng.integers(0, 3, n)
    q_t, u_t = torch.tensor(q), torch.tensor(u)
    model = SharedUtility(dim, seed=7)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-2, weight_decay=1e-3)
    first = None
    for _ in range(80):
        opt.zero_grad()
        loss, _ = losses(model, q_t, u_t)
        if first is None:
            first = float(loss.detach())
        loss.backward()
        opt.step()
    with torch.no_grad():
        final = float(losses(model, q_t, u_t)[0])
    oof = train_oof(q, u, folds, epochs=80)
    d_pred = np.asarray(oof["oof_delta"])
    d_true = u[:, 1] - u[:, 0]
    confident = np.abs(d_true) > 0.05
    acc = float(((d_pred[confident] > 0) == (d_true[confident] > 0)).mean())
    assert final < first, f"smoke: loss did not decrease ({first} -> {final})"
    assert acc > 0.8, f"smoke: OOF pair accuracy too low ({acc:.2f})"
    return dict(first_loss=first, final_loss=final, oof_pair_accuracy=acc, oof_auc=oof["auc_pair"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["smoke", "train"], default="smoke")
    ap.add_argument("--labels", default=str(ROOT / "data/mmlu_utility_repeats_400/EXPECTED_UTILITY_LABELS.jsonl"))
    ap.add_argument("--source", default=str(ROOT / "router_v2/objective_verified_20260910"))
    ap.add_argument("--fold-selection", default=str(ROOT / "router_v2/mmlu_utility_panel_400/FOLD_SELECTION.json"))
    ap.add_argument("--learnability-results", default=str(ROOT / "router_v2/mmlu_learnability_400/RESULTS.json"))
    ap.add_argument("--output")
    a = ap.parse_args()
    if a.mode == "smoke":
        print(json.dumps(smoke(), indent=2))
        return
    gate(a.learnability_results)
    records = build_records(a.labels, a.source)
    qids, emb, u, meta = pair_matrix(records)
    foldsel = json.loads(Path(a.fold_selection).read_text())
    fold_of = np.zeros(len(qids), dtype=int)
    for fold, per_q in foldsel.items():
        for qid in per_q:
            fold_of[qids.index(qid)] = int(fold)
    result = train_oof(emb, u, fold_of)
    result.update(records=len(records), queries=len(qids),
                  labels_sha256=sha(Path(a.labels)), implementation_sha256=sha(Path(__file__)),
                  role="shared_utility_Uqm_oof_development", winner_labels_used=False)
    out = Path(a.output) if a.output else ROOT / "router_v2/shared_utility_ma_20260910"
    out.mkdir(parents=True, exist_ok=True)
    (out / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "oof_delta"}, indent=2))


if __name__ == "__main__":
    main()
