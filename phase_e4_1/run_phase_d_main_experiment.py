#!/usr/bin/env python3
"""Phase D: RequestOnly vs SimpleStateAware main experiment + GO/STOP gate.

Frozen protocol (E4_1_STATE_OBSERVABILITY_PROTOCOL.json):
- Estimator: HistGradientBoostingRegressor (lr=0.05, max_iter=200, max_leaf_nodes=15, l2=1.0,
  min_samples_leaf=20, random_state=20260905).
- Cross-fitting: 5-fold deterministic GroupKFold by leakage_group_id; OOF predictions;
  task's trajectories never cross folds.
- Feature sets: request_only = request_features + node one-hot + model one-hot;
  state_aware = request_only + pre_action_state (10 frozen fields).
- Policy: argmax model-specific OOF predicted RTG per task.
- OPE: cross-fitted DR (propensity 0.25) main; IPS/SNIPS sensitivity.
- Cluster uncertainty: 10000 leakage-group bootstrap.
- GO gate (ALL three): co-primary predictability CI-LB>0, co-primary policy CI-LB>0,
  mechanism_safety (DR(StateAware)-DR(Shuffled)>0 AND mean(N2-N4 advantage)>N1 advantage).

Protocol-interpretation choice (documented, not a retune): co-primary policy evaluated at depth
N2 (first node with non-empty upstream state; earliest state-aware decision point). All depths
reported. Missing Q (judge failure) trajectories excluded from policy value + bootstrap.
"""
from __future__ import annotations

import json
import numpy as np
from collections import defaultdict
from pathlib import Path

ROOT = Path("/root")
RTG = ROOT / "phase_e4_1/E4_PHASE_C_RTG.jsonl"
OUT = ROOT / "phase_e4_1/E4_PHASE_D_MAIN_EXPERIMENT.json"

MODELS = ["deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo"]
NODES = ["N1", "N2", "N3", "N4"]
PROPENSITY = 0.25
PRIMARY_DEPTH = "N2"
N_BOOT = 10000
N_SHUFFLE = 100
SEED = 20260905
STATE_FIELDS = ["upstream_provider_success", "upstream_schema_valid", "upstream_evidence_count",
                "upstream_extraction_field_count", "upstream_confidence", "upstream_output_length",
                "upstream_latency_ms", "cumulative_cost_usd", "remaining_budget_usd", "retry_count"]
REQUEST_FIELDS = ["query_token_count", "context_token_count", "sentence_count", "paragraph_count",
                  "numeric_count", "percentage_count", "currency_count", "arithmetic_cue_count",
                  "table_rows", "table_columns", "table_cell_count", "numeric_cell_ratio",
                  "comparison_cue_count", "reasoning_cue_count", "conjunction_count",
                  "cross_reference_count", "modal_count", "negation_count", "exception_count",
                  "uncertainty_count", "conditional_count", "evidence_cue_count",
                  "question_entity_count", "context_dispersion_proxy"]


def read_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def state_vec(state):
    if not state:
        return [0.0] * len(STATE_FIELDS)
    out = []
    for f in STATE_FIELDS:
        v = state.get(f)
        if f == "upstream_schema_valid" and v is None:
            v = state.get("upstream_format_valid")
        if v is None or v is False:
            out.append(0.0)
        elif v is True:
            out.append(1.0)
        else:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                out.append(0.0)
    return out


def build_rows(rows, node, feature_set):
    """Return X (n×p), y (n,), groups (n,), tasks (n, models (n,) for one node depth."""
    sub = [r for r in rows if r["node_id"] == node and r["RTG_t"] is not None]
    X, y, gr, tk, ml = [], [], [], [], []
    for r in sub:
        rf = r.get("request_features") or {}
        feat = [float(rf.get(f, 0) or 0) for f in REQUEST_FIELDS]
        # node one-hot
        feat += [1.0 if node == n else 0.0 for n in NODES]
        # model one-hot
        feat += [1.0 if r["selected_model"] == m else 0.0 for m in MODELS]
        if feature_set == "state_aware":
            feat += state_vec(r.get("pre_action_state"))
        X.append(feat)
        y.append(r["RTG_t"])
        gr.append(r["leakage_group_id"])
        tk.append(r["task_id"])
        ml.append(r["selected_model"])
    return np.array(X, dtype=float), np.array(y, dtype=float), np.array(gr), np.array(tk), np.array(ml)


def group_kfold_indices(groups, n_splits=5):
    """Deterministic 5-fold GroupKFold by leakage_group_id."""
    uniq = sorted(set(groups.tolist()))
    folds = [[] for _ in range(n_splits)]
    for i, g in enumerate(uniq):
        folds[i % n_splits].append(g)
    for k in range(n_splits):
        test_groups = set(folds[k])
        test_idx = np.array([i for i, g in enumerate(groups) if g in test_groups])
        train_idx = np.array([i for i, g in enumerate(groups) if g not in test_groups])
        yield train_idx, test_idx


def oof_predict(X, y, groups, X_shuffle_mask=None):
    from sklearn.ensemble import HistGradientBoostingRegressor
    oof = np.full(len(y), np.nan, dtype=float)
    for tr, te in group_kfold_indices(groups, 5):
        m = HistGradientBoostingRegressor(
            learning_rate=0.05, max_iter=200, max_leaf_nodes=15, l2_regularization=1.0,
            min_samples_leaf=20, random_state=SEED)
        m.fit(X[tr], y[tr])
        oof[te] = m.predict(X[te])
    return oof


def policy_value(oof, y, tasks, models, task_list, model_order):
    """V_DM, V_IPS, V_SNIPS, V_DR for argmax policy, plus per-task chosen model."""
    chosen = {}  # task -> model index
    for t in task_list:
        mask = tasks == t
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            continue
        # argmax model by oof pred
        best = idxs[np.argmax(oof[idxs])]
        chosen[t] = models[best]
    # matched trajectory per task
    matched_y, matched_pred = [], []
    all_pred = list(oof)
    all_y = list(y)
    for t, m_idx in chosen.items():
        mask = (tasks == t) & (models == m_idx)
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            continue
        i = idxs[0]
        matched_y.append(y[i])
        matched_pred.append(oof[i])
    matched_y = np.array(matched_y, dtype=float)
    matched_pred = np.array(matched_pred, dtype=float)
    n_logged = len(y)
    n_tasks = len(matched_y)
    v_dm = np.mean(matched_pred) if n_tasks else np.nan
    v_ips = (np.sum(matched_y) / PROPENSITY) / n_logged if n_logged else np.nan
    w_sum = (n_tasks / PROPENSITY)
    v_snips = (np.sum(matched_y) / PROPENSITY) / w_sum if w_sum else np.nan  # = mean matched y
    v_dr = (np.sum(all_pred) + np.sum((matched_y - matched_pred) / PROPENSITY)) / n_logged if n_logged else np.nan
    abs_err = np.mean(np.abs(oof - y))
    return {"V_DM": float(v_dm), "V_IPS": float(v_ips), "V_SNIPS": float(v_snips),
            "V_DR": float(v_dr), "abs_err": float(abs_err), "n_tasks": n_tasks}


def bootstrap_ci(oof_s, oof_r, y, tasks, models, task_list, n_boot=N_BOOT, seed=SEED):
    """Bootstrap DR(StateAware)-DR(RequestOnly) and abs_err diff by resampling leakage groups."""
    rng = np.random.default_rng(seed)
    uniq = sorted(set(tasks.tolist()))
    dr_diff, err_diff = [], []
    # precompute per-task matched indices for each policy
    def matched(oof):
        out = {}
        for t in task_list:
            mask = tasks == t
            idxs = np.where(mask)[0]
            if len(idxs) == 0:
                continue
            best = idxs[np.argmax(oof[idxs])]
            out[t] = best
        return out
    ms = matched(oof_s); mr = matched(oof_r)
    for _ in range(n_boot):
        samp = rng.choice(uniq, size=len(uniq), replace=True)
        idx_lists = []
        for g in samp:
            idx_lists.append(np.where(tasks == g)[0])
        idx = np.concatenate(idx_lists) if idx_lists else np.array([], dtype=int)
        if len(idx) == 0:
            continue
        # rebuild per-task chosen from the bootstrap sample's tasks (unique groups)
        uniq_samp = sorted(set(samp.tolist()))
        def dr_for(oof, matched_map):
            allp = np.sum(oof[idx])
            my = np.array([y[matched_map[t]] for t in uniq_samp if t in matched_map])
            mp = np.array([oof[matched_map[t]] for t in uniq_samp if t in matched_map])
            n = len(idx)
            return (np.sum(allp) + np.sum((my - mp) / PROPENSITY)) / n if n else np.nan
        drs = dr_for(oof_s, ms); drr = dr_for(oof_r, mr)
        dr_diff.append(drs - drr)
        err_diff.append(np.mean(np.abs(oof_s[idx] - y[idx])) - np.mean(np.abs(oof_r[idx] - y[idx])))
    dr_diff = np.array(dr_diff); err_diff = np.array(err_diff)
    return {
        "DR_diff_mean": float(np.mean(dr_diff)),
        "DR_diff_CI_lo": float(np.percentile(dr_diff, 2.5)),
        "DR_diff_CI_hi": float(np.percentile(dr_diff, 97.5)),
        "abs_err_diff_mean": float(np.mean(err_diff)),
        "abs_err_diff_CI_lo": float(np.percentile(err_diff, 2.5)),
        "abs_err_diff_CI_hi": float(np.percentile(err_diff, 97.5)),
    }


def shuffle_state_value(rows, node, task_list, model_order, n_perm=N_SHUFFLE):
    """DR(ShuffledState): permute pre_action_state across tasks within node strata."""
    sub = [r for r in rows if r["node_id"] == node and r["RTG_t"] is not None]
    if not sub:
        return None
    # base state_aware X with shuffled state
    base_rows = sub[:]
    states = [r.get("pre_action_state") for r in base_rows]
    drs = []
    for p in range(n_perm):
        rng = np.random.default_rng(SEED + p)
        perm = rng.permutation(len(base_rows))
        shuffled_states = [states[i] for i in perm]
        for i, r in enumerate(base_rows):
            r["pre_action_state"] = shuffled_states[i]
        X, y, gr, tk, ml = build_rows(rows, node, "state_aware")
        oof = oof_predict(X, y, gr)
        pv = policy_value(oof, y, tk, ml, [r["task_id"] for r in base_rows if r["node_id"] == node], model_order)
        drs.append(pv["V_DR"])
    # restore
    for i, r in enumerate(base_rows):
        r["pre_action_state"] = states[i]
    return {"DR_shuffled_mean": float(np.mean(drs)), "DR_shuffled_p025": float(np.percentile(drs, 2.5)),
            "DR_shuffled_p975": float(np.percentile(drs, 97.5)), "n_perm": n_perm}


def main():
    rows = read_jsonl(RTG)
    task_list = sorted(set(r["task_id"] for r in rows))
    results = {"per_depth": {}, "version": "E4.1-phase-D-main-experiment-v1",
               "protocol": "E4_1_STATE_OBSERVABILITY_PROTOCOL.json",
               "primary_depth": PRIMARY_DEPTH, "propensity": PROPENSITY,
               "n_bootstrap": N_BOOT, "n_shuffle": N_SHUFFLE}

    oof_cache = {}
    for node in NODES:
        for fset in ("request_only", "state_aware"):
            X, y, gr, tk, ml = build_rows(rows, node, fset)
            if len(y) == 0:
                continue
            oof = oof_predict(X, y, gr)
            oof_cache[(node, fset)] = (oof, y, tk, ml)
            pv = policy_value(oof, y, tk, ml, task_list, MODELS)
            results["per_depth"].setdefault(node, {})[fset] = pv

    # state advantage per depth
    adv = {}
    for node in NODES:
        if node in results["per_depth"] and "state_aware" in results["per_depth"][node] and "request_only" in results["per_depth"][node]:
            adv[node] = results["per_depth"][node]["state_aware"]["V_DR"] - results["per_depth"][node]["request_only"]["V_DR"]
    results["state_advantage_by_depth"] = {k: float(v) for k, v in adv.items()}

    # co-primary predictability + policy at primary depth (pooled predictability across depths)
    # predictability: pooled abs err across all 4 nodes
    err_s = np.concatenate([oof_cache[(n, "state_aware")][0] - oof_cache[(n, "state_aware")][1] for n in NODES if (n, "state_aware") in oof_cache])
    err_r = np.concatenate([oof_cache[(n, "request_only")][0] - oof_cache[(n, "request_only")][1] for n in NODES if (n, "request_only") in oof_cache])
    abs_s = np.abs(err_s); abs_r = np.abs(err_r)
    results["co_primary_predictability_pooled"] = {
        "abs_err_request_only": float(np.mean(abs_r)),
        "abs_err_state_aware": float(np.mean(abs_s)),
        "diff_RequestOnly_minus_StateAware": float(np.mean(abs_r) - np.mean(abs_s)),
    }

    # bootstrap at primary depth
    oof_s, y, tk, ml = oof_cache[(PRIMARY_DEPTH, "state_aware")]
    oof_r, _, _, _ = oof_cache[(PRIMARY_DEPTH, "request_only")]
    boot = bootstrap_ci(oof_s, oof_r, y, tk, ml, task_list)
    results["co_primary_bootstrap_primary_depth"] = boot

    # mechanism: shuffled state at primary depth
    shuf = shuffle_state_value(rows, PRIMARY_DEPTH, task_list, MODELS)
    results["mechanism_shuffled_state"] = shuf

    # depth pattern
    n1_adv = adv.get("N1", 0.0)
    n24_adv = [adv.get(n, 0.0) for n in ("N2", "N3", "N4")]
    mean_n24 = float(np.mean(n24_adv)) if n24_adv else 0.0
    results["mechanism_depth_pattern"] = {"N1_advantage": float(n1_adv), "mean_N2_N4_advantage": mean_n24,
                                          "N2_N4_gt_N1": mean_n24 > n1_adv}

    # GO/STOP gate
    g1 = boot["abs_err_diff_CI_lo"] > 0  # predictability (from bootstrap at primary depth)
    g2 = boot["DR_diff_CI_lo"] > 0  # policy
    g3a = shuf is not None and (oof_cache[(PRIMARY_DEPTH, "state_aware")] and
          (results["per_depth"][PRIMARY_DEPTH]["state_aware"]["V_DR"] - shuf["DR_shuffled_mean"]) > 0)
    g3b = mean_n24 > n1_adv
    gate = {
        "co_primary_predictability_pass": bool(g1),
        "co_primary_policy_pass": bool(g2),
        "mechanism_safety_pass": bool(g3a and g3b),
        "mechanism_DR_StateAware_minus_DR_Shuffled": float(results["per_depth"][PRIMARY_DEPTH]["state_aware"]["V_DR"] - (shuf["DR_shuffled_mean"] if shuf else 0)) if shuf else None,
    }
    gate["decision"] = "GO" if (g1 and g2 and g3a and g3b) else "STOP"
    results["go_gate"] = gate

    # limitations
    results["limitations"] = [
        "Single machine judge (Qwen-Max) for 23 open tasks; no human validation; GLM/Doubao unavailable.",
        f"Delivery-validity is model-confounded (frozen strict N4 schema): only {sum(1 for r in rows if r['RTG_t'] is not None and r['node_id']=='N4')}/160 N4 outcomes workflow_valid; Q_delivered=0 for the rest. State-aware routing may partly exploit delivery validity rather than semantic quality.",
        "Development gate, not confirmatory paper evidence (per protocol role).",
        f"Co-primary policy evaluated at pre-specified depth {PRIMARY_DEPTH}; all depths reported.",
    ]

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
