"""P0 train-only gap learnability diagnostics.

Runs three checks on the frozen objective-train OOF source:
1. winner stability / noise proxies,
2. task-level versus query-level routing,
3. pairwise ranking, including the large-vs-reasoning edge.

This script never reads validation or test labels.
"""
import argparse
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import RidgeClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from .core import SLOTS, paired_ci
from .data import load_cohort, sha
from .diagnose_rank_signal import load_inputs

ROOT = Path(__file__).resolve().parents[1]
PAIRS = tuple(itertools.combinations(range(len(SLOTS)), 2))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def winner_set(values):
    values = np.asarray(values)
    best = values.max()
    return tuple(int(i) for i in np.flatnonzero(np.abs(values - best) < 1e-12))


def task_best_decisions(y, groups, train_idx, eval_idx):
    groups = np.asarray(groups)
    global_choice = int(y[train_idx].mean(0).argmax())
    decisions = np.full(len(eval_idx), global_choice, dtype=int)
    for group in sorted(set(groups[eval_idx])):
        local = train_idx[groups[train_idx] == group]
        if len(local):
            decisions[groups[eval_idx] == group] = int(y[local].mean(0).argmax())
    return decisions


def oof_task_policy(y, groups, folds):
    decisions = np.zeros(len(y), dtype=int)
    for fold in sorted(set(folds.tolist())):
        tr = np.flatnonzero(folds != fold)
        va = np.flatnonzero(folds == fold)
        decisions[va] = task_best_decisions(y, groups, tr, va)
    return decisions


def repeated_grade_summary(journal_path):
    if not journal_path.exists():
        return {"exists": False}
    by_response = defaultdict(list)
    by_attempt = defaultdict(lambda: defaultdict(dict))
    events = 0
    for line in journal_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") != "grade" or "quality" not in row:
            continue
        events += 1
        key = (row["query_id"], row["slot"], row["response_sha256"])
        by_response[key].append(float(row["quality"]))
        by_attempt[row["query_id"]][int(row.get("attempt", 0))][row["slot"]] = float(row["quality"])
    repeated = {k: v for k, v in by_response.items() if len(v) > 1}
    changed = [v for v in repeated.values() if max(v) - min(v) > 1e-12]
    complete_pairs = []
    for qid, attempts in by_attempt.items():
        complete = {
            attempt: tuple(slots[s] for s in SLOTS)
            for attempt, slots in attempts.items()
            if set(slots) == set(SLOTS)
        }
        for a, b in itertools.combinations(sorted(complete), 2):
            complete_pairs.append(
                {
                    "query_id": qid,
                    "attempt_a": a,
                    "attempt_b": b,
                    "winner_same": winner_set(complete[a]) == winner_set(complete[b]),
                }
            )
    return {
        "exists": True,
        "grade_events": events,
        "repeated_response_keys": len(repeated),
        "changed_repeated_response_keys": len(changed),
        "mean_abs_difference_when_repeated": float(
            np.mean([abs(v[-1] - v[0]) for v in repeated.values()])
        )
        if repeated
        else None,
        "complete_query_attempt_pairs": len(complete_pairs),
        "complete_query_winner_agreement": float(
            np.mean([p["winner_same"] for p in complete_pairs])
        )
        if complete_pairs
        else None,
        "limits": [
            "Repeated grade events are sparse and mostly retry artifacts.",
            "No complete query-level independent repeated generation panel is available in this cache.",
        ],
    }


def component_sensitivity_summary(path):
    if not path.exists():
        return {"exists": False}
    audit = json.loads(path.read_text())
    counts = audit.get("counts", {})
    complete = counts.get("complete_four_slot_queries", 0)
    comparable = counts.get("comparable_labels", 0)
    pairs = counts.get("comparable_same_query_pairs", 0)
    return {
        "exists": True,
        "audit_sha256": sha(path),
        "comparable_labels": comparable,
        "label_change_rate": counts.get("changed_labels", 0) / comparable if comparable else None,
        "mean_absolute_label_difference": audit.get("mean_absolute_label_difference"),
        "complete_four_slot_queries": complete,
        "best_slot_set_change_rate": counts.get("best_slot_set_changes", 0) / complete
        if complete
        else None,
        "strict_order_reversal_rate": counts.get("strict_order_reversals", 0) / pairs
        if pairs
        else None,
        "tie_status_change_rate": counts.get("tie_status_changes", 0) / pairs if pairs else None,
        "limits": [
            "Component-sum is a sensitivity alternative, not ground truth.",
            "This is an open-ended judge proxy and does not certify objective-task repeat stability.",
        ],
    }


def objective_winner_summary(y, fixed_choice):
    sets = [winner_set(row) for row in y]
    sizes = np.array([len(s) for s in sets])
    pair_ties = 0
    pair_strict = 0
    for row in y:
        for i, j in PAIRS:
            if abs(row[i] - row[j]) < 1e-12:
                pair_ties += 1
            else:
                pair_strict += 1
    fixed = y[np.arange(len(y)), fixed_choice]
    oracle = y.max(1)
    return {
        "n": int(len(y)),
        "unique_winner_rate": float((sizes == 1).mean()),
        "multi_winner_rate": float((sizes > 1).mean()),
        "all_slots_tied_best_rate": float((sizes == len(SLOTS)).mean()),
        "mean_best_set_size": float(sizes.mean()),
        "pairwise_strict_fraction": float(pair_strict / (pair_strict + pair_ties)),
        "oracle_quality": float(oracle.mean()),
        "oracle_gap_vs_best_single": float((oracle - fixed).mean()),
        "interpretation": "Binary objective labels create many winner ties; argmax winner classification is often an arbitrary target.",
    }


def fit_pairwise_scores(x_train, y_train, x_eval, alpha):
    scores = np.zeros((len(x_eval), len(SLOTS)), dtype=float)
    pair_probs = {}
    for i, j in PAIRS:
        diff = y_train[:, i] - y_train[:, j]
        keep = np.abs(diff) > 1e-12
        labels = (diff[keep] > 0).astype(int)
        key = f"{SLOTS[i]}>{SLOTS[j]}"
        if len(labels) == 0 or len(np.unique(labels)) == 1:
            p = np.full(len(x_eval), float(labels[0]) if len(labels) else 0.5)
        else:
            model = RidgeClassifier(alpha=alpha)
            model.fit(x_train[keep], labels)
            p = sigmoid(model.decision_function(x_eval))
        scores[:, i] += p
        scores[:, j] += 1.0 - p
        pair_probs[key] = p
    return scores, pair_probs


def pairwise_task_scores(y, groups, train_idx, eval_idx):
    groups = np.asarray(groups)
    scores = np.zeros((len(eval_idx), len(SLOTS)), dtype=float)
    pair_probs = {}
    for i, j in PAIRS:
        p = np.full(len(eval_idx), 0.5, dtype=float)
        global_diff = y[train_idx, i].mean() - y[train_idx, j].mean()
        p[:] = 1.0 if global_diff > 1e-12 else (0.0 if global_diff < -1e-12 else 0.5)
        for group in sorted(set(groups[eval_idx])):
            local = train_idx[groups[train_idx] == group]
            if len(local):
                diff = y[local, i].mean() - y[local, j].mean()
                p[groups[eval_idx] == group] = (
                    1.0 if diff > 1e-12 else (0.0 if diff < -1e-12 else 0.5)
                )
        scores[:, i] += p
        scores[:, j] += 1.0 - p
        pair_probs[f"{SLOTS[i]}>{SLOTS[j]}"] = p
    return scores, pair_probs


def guarded_pairwise_choice(scores, fallback, tau):
    winner = scores.argmax(1)
    advantage = scores[np.arange(len(scores)), winner] - scores[np.arange(len(scores)), fallback]
    return np.where(advantage > tau, winner, fallback)


def select_pairwise_config(x, y, groups, train_idx, seed, alphas, thresholds):
    inner = [
        (train_idx[a], train_idx[b])
        for a, b in StratifiedKFold(3, shuffle=True, random_state=seed).split(train_idx, groups[train_idx])
    ]
    candidates = []
    for alpha in alphas:
        for tau in thresholds:
            values = []
            changed = []
            for it, iv in inner:
                scores, _ = fit_pairwise_scores(x[it], y[it], x[iv], alpha)
                base = task_best_decisions(y, groups, it, iv)
                choice = guarded_pairwise_choice(scores, base, tau)
                values.extend(y[iv, choice].tolist())
                changed.extend((choice != base).tolist())
            candidates.append(
                {
                    "alpha": alpha,
                    "threshold": tau,
                    "quality": float(np.mean(values)),
                    "route_change_rate": float(np.mean(changed)),
                }
            )
    return max(candidates, key=lambda r: (r["quality"], r["threshold"], r["alpha"])), candidates


def pair_metrics(y, pair_probs):
    result = {}
    for i, j in PAIRS:
        key = f"{SLOTS[i]}>{SLOTS[j]}"
        diff = y[:, i] - y[:, j]
        strict = np.abs(diff) > 1e-12
        labels = (diff[strict] > 0).astype(int)
        probs = pair_probs[key][strict]
        row = {
            "strict_n": int(strict.sum()),
            "tie_n": int((~strict).sum()),
            "positive_rate": float(labels.mean()) if len(labels) else None,
            "accuracy": float(((probs >= 0.5).astype(int) == labels).mean())
            if len(labels)
            else None,
        }
        if len(labels) and len(np.unique(labels)) == 2:
            row["auc"] = float(roc_auc_score(labels, probs))
        else:
            row["auc"] = None
        result[key] = row
    return result



def decision_comparison(y, left, right):
    left = np.asarray(left, dtype=int)
    right = np.asarray(right, dtype=int)
    changed = left != right
    diff = y[np.arange(len(y)), left] - y[np.arange(len(y)), right]
    row = {
        "agreement": float((~changed).mean()),
        "changed_n": int(changed.sum()),
        "gain": float(diff.mean()),
        "ci95": paired_ci(diff),
    }
    if changed.any():
        local = diff[changed]
        row.update(
            {
                "win_rate_on_changed": float((local > 0).mean()),
                "loss_rate_on_changed": float((local < 0).mean()),
                "tie_rate_on_changed": float((np.abs(local) < 1e-12).mean()),
            }
        )
    else:
        row.update(
            {
                "win_rate_on_changed": None,
                "loss_rate_on_changed": None,
                "tie_rate_on_changed": None,
            }
        )
    return row

def policy_report(y, datasets, decisions, fixed, oracle):
    actual = y[np.arange(len(y)), decisions]
    fixed_values = y[np.arange(len(y)), fixed]
    gain = actual - fixed_values
    gap = float((oracle - fixed_values).mean())
    return {
        "quality": float(actual.mean()),
        "gain_vs_best_single": float(gain.mean()),
        "gain_vs_best_single_ci95": paired_ci(gain),
        "gap_recovery": float(gain.mean() / gap) if gap > 1e-12 else None,
        "routing_fraction": (np.bincount(decisions, minlength=len(SLOTS)) / len(decisions)).tolist(),
        "by_dataset": {
            ds: float(actual[datasets == ds].mean()) for ds in sorted(set(datasets.tolist()))
        },
    }


def run(args):
    source = Path(args.source).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError(out)
    frozen, x, datasets = load_inputs(source)
    y = frozen["quality"]
    folds = frozen["folds"]
    ids = frozen["ids"].tolist()
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    cohort_path = next(Path(p).parent for p in protocol["input_sha256"] if Path(p).name == "queries.jsonl")
    cohort, split = load_cohort(cohort_path)
    if not set(ids) <= set(split["train"]):
        raise ValueError("P0 diagnostics must stay on original train IDs")
    task_types = np.array([cohort[qid]["task_type"] for qid in ids])

    out.mkdir(parents=True, exist_ok=False)
    exp_protocol = {
        "role": "exploratory_train_only_p0_gap_learnability",
        "source": str(source),
        "source_files": {name: sha(source / name) for name in ("PROTOCOL.json", "RESULTS.json", "OOF.npz")},
        "implementation_sha256": sha(__file__),
        "seeds": args.seeds,
        "pairwise_alphas": args.alphas,
        "pairwise_thresholds": args.thresholds,
        "large_vs_reasoning_key": "large>reasoning",
        "limits": [
            "Original train objective subset only; no validation/test labels loaded.",
            "Task-only policies use benchmark task metadata and are diagnostic baselines.",
            "Judge stability uses available repeated grades and component sensitivity proxies, not a full independent repeat panel.",
            "Pairwise routing is selected by inner train folds and reported for all declared seeds.",
            "Binary labels make winner identity tie-heavy; winner-set and pairwise metrics are more informative than single argmax accuracy.",
        ],
    }
    (out / "PROTOCOL.json").write_text(json.dumps(exp_protocol, indent=2) + "\n")

    fixed = frozen["BestSingle"].astype(int)
    oracle = y.max(1)
    task_type_choice = oof_task_policy(y, task_types, folds)
    dataset_choice = frozen["DatasetBest"].astype(int)
    query_choice = frozen["Ridge"].astype(int)

    choices = {
        "task_type_best": task_type_choice,
        "dataset_best": dataset_choice,
        "query_ridge": query_choice,
    }
    pair_probs_by_seed = {}
    selections = []
    for seed in args.seeds:
        pair_choice = np.zeros(len(y), dtype=int)
        pair_task_choice = np.zeros(len(y), dtype=int)
        all_probs = {f"{SLOTS[i]}>{SLOTS[j]}": np.zeros(len(y), dtype=float) for i, j in PAIRS}
        all_task_probs = {f"{SLOTS[i]}>{SLOTS[j]}": np.zeros(len(y), dtype=float) for i, j in PAIRS}
        for fold in sorted(set(folds.tolist())):
            start = time.monotonic()
            tr = np.flatnonzero(folds != fold)
            va = np.flatnonzero(folds == fold)
            chosen, candidates = select_pairwise_config(
                x, y, datasets, tr, seed, args.alphas, args.thresholds
            )
            scores, probs = fit_pairwise_scores(x[tr], y[tr], x[va], chosen["alpha"])
            base = task_best_decisions(y, datasets, tr, va)
            pair_choice[va] = guarded_pairwise_choice(scores, base, chosen["threshold"])
            task_scores, task_probs = pairwise_task_scores(y, datasets, tr, va)
            pair_task_choice[va] = task_scores.argmax(1)
            for key, values in probs.items():
                all_probs[key][va] = values
                all_task_probs[key][va] = task_probs[key]
            selections.append(
                {
                    "seed": seed,
                    "fold": int(fold),
                    "chosen": chosen,
                    "candidates": candidates,
                    "seconds": round(time.monotonic() - start, 3),
                }
            )
            print(
                f"seed={seed} fold={fold} pairwise selected alpha={chosen['alpha']} "
                f"tau={chosen['threshold']} q={chosen['quality']:.6f}",
                flush=True,
            )
        choices[f"pairwise_query_seed{seed}"] = pair_choice
        choices[f"pairwise_task_seed{seed}"] = pair_task_choice
        pair_probs_by_seed[f"query_seed{seed}"] = all_probs
        pair_probs_by_seed[f"task_seed{seed}"] = all_task_probs

    if sha(__file__) != exp_protocol["implementation_sha256"]:
        raise ValueError("Implementation changed during run")
    np.savez_compressed(
        out / "OOF_CHOICES.npz",
        ids=frozen["ids"],
        **choices,
        **{
            f"{source_key}_{pair_key}": values
            for source_key, pairs in pair_probs_by_seed.items()
            for pair_key, values in pairs.items()
        },
    )
    (out / "SELECTION.json").write_text(json.dumps(selections, indent=2) + "\n")

    policy_reports = {
        key: policy_report(y, datasets, decision.astype(int), fixed, oracle)
        for key, decision in choices.items()
    }
    for key, report in policy_reports.items():
        actual = y[np.arange(len(y)), choices[key].astype(int)]
        dataset_actual = y[np.arange(len(y)), dataset_choice]
        report["gain_vs_dataset_best"] = float((actual - dataset_actual).mean())
        report["gain_vs_dataset_best_ci95"] = paired_ci(actual - dataset_actual)

    pair_reports = {}
    for source_key, probs in pair_probs_by_seed.items():
        metrics = pair_metrics(y, probs)
        pair_reports[source_key] = {
            "all_pairs": metrics,
            "large_vs_reasoning": metrics["large>reasoning"],
        }

    winner_stability = {
        "objective_binary_subset": objective_winner_summary(y, fixed),
        "repeated_judge_grades": repeated_grade_summary(
            ROOT / "data/judged_train_primary_v2/ATTEMPTS.jsonl"
        ),
        "judge_component_sensitivity_proxy": component_sensitivity_summary(
            ROOT / "data/judge_sensitivity_priority_20260909/AUDIT.json"
        ),
    }
    comparisons = {
        "query_ridge_minus_dataset_best": {
            "gain": policy_reports["query_ridge"]["gain_vs_dataset_best"],
            "ci95": policy_reports["query_ridge"]["gain_vs_dataset_best_ci95"],
        },
    }
    for seed in args.seeds:
        key = f"pairwise_query_seed{seed}"
        comparisons[f"{key}_minus_dataset_best"] = {
            "gain": policy_reports[key]["gain_vs_dataset_best"],
            "ci95": policy_reports[key]["gain_vs_dataset_best_ci95"],
            "route_change_rate": float((choices[key] != dataset_choice).mean()),
        }
        diff = y[np.arange(len(y)), choices[key]] - y[np.arange(len(y)), query_choice]
        comparisons[f"{key}_minus_query_ridge"] = {
            "gain": float(diff.mean()),
            "ci95": paired_ci(diff),
        }

    result = {
        "role": exp_protocol["role"],
        "n": int(len(y)),
        "winner_stability": winner_stability,
        "task_vs_query": {
            "policies": {
                k: policy_reports[k]
                for k in ("task_type_best", "dataset_best", "query_ridge")
            },
            "decision_agreements": {
                "query_ridge_vs_dataset_best": decision_comparison(y, query_choice, dataset_choice),
                "query_ridge_vs_task_type_best": decision_comparison(y, query_choice, task_type_choice),
                "task_type_best_vs_dataset_best": decision_comparison(y, task_type_choice, dataset_choice),
            },
            "interpretation": "Dataset-level task signal matches query Ridge on this frozen OOF source; task_type is coarser because two code datasets are pooled.",
        },
        "pairwise": {
            "policies": {
                k: v for k, v in policy_reports.items() if k.startswith("pairwise_")
            },
            "pair_metrics": pair_reports,
        },
        "comparisons": comparisons,
        "fixed_model_means": dict(zip(SLOTS, y.mean(0).tolist())),
        "empirical_oracle": float(oracle.mean()),
        "validation_labels_loaded": False,
        "test_labels_loaded": False,
        "files": {
            name: sha(out / name)
            for name in ("PROTOCOL.json", "SELECTION.json", "OOF_CHOICES.npz")
        },
    }
    (out / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(out, result, args.seeds)
    print(json.dumps(result["comparisons"], indent=2), flush=True)


def pct(x):
    return "NA" if x is None else f"{100 * x:.2f}%"


def write_report(out, result, seeds):
    lines = [
        "# P0 Gap Learnability Diagnostics",
        "",
        "Scope: frozen original-train objective subset only. Validation and test labels were not loaded.",
        "",
        "## P0-1 Winner Stability",
        "",
    ]
    obj = result["winner_stability"]["objective_binary_subset"]
    rep = result["winner_stability"]["repeated_judge_grades"]
    sens = result["winner_stability"]["judge_component_sensitivity_proxy"]
    lines += [
        f"- Objective subset n={obj['n']}: unique winner {pct(obj['unique_winner_rate'])}, "
        f"multi-winner {pct(obj['multi_winner_rate'])}, mean winner-set size {obj['mean_best_set_size']:.3f}.",
        f"- Objective pair labels are strict for {pct(obj['pairwise_strict_fraction'])} of model pairs; the rest are ties.",
        f"- Available repeated judge grades: {rep.get('repeated_response_keys', 0)} repeated response keys, "
        f"{rep.get('changed_repeated_response_keys', 0)} changed labels, "
        f"{rep.get('complete_query_attempt_pairs', 0)} complete query-level attempt pairs.",
        f"- Judge component proxy: label change {pct(sens.get('label_change_rate'))}, "
        f"best-slot set changed {pct(sens.get('best_slot_set_change_rate'))} on "
        f"{sens.get('complete_four_slot_queries')} complete open-ended queries.",
        "",
        "## P0-2 Task-Level vs Query-Level",
        "",
        "| policy | quality | gap recovery | gain vs dataset-best |",
        "|---|---:|---:|---:|",
    ]
    for key, row in result["task_vs_query"]["policies"].items():
        lines.append(
            f"| {key} | {100*row['quality']:.3f}% | {100*row['gap_recovery']:.2f}% | "
            f"{100*row['gain_vs_dataset_best']:+.3f} pp |"
        )
    agree = result["task_vs_query"]["decision_agreements"]["query_ridge_vs_dataset_best"]
    lines += [
        "",
        f"Query Ridge agrees with dataset-best on {100*agree['agreement']:.2f}% of queries; "
        f"on {agree['changed_n']} changed decisions, wins and losses each account for "
        f"{100*agree['win_rate_on_changed']:.2f}% when labels differ, so net gain is {100*agree['gain']:+.3f} pp.",
        "",
        "## P0-3 Pairwise Ranking",
        "",
        "| policy | quality | gap recovery | gain vs dataset-best | changed from dataset-best |",
        "|---|---:|---:|---:|---:|",
    ]
    for seed in seeds:
        key = f"pairwise_query_seed{seed}"
        row = result["pairwise"]["policies"][key]
        comp = result["comparisons"][f"{key}_minus_dataset_best"]
        lines.append(
            f"| {key} | {100*row['quality']:.3f}% | {100*row['gap_recovery']:.2f}% | "
            f"{100*row['gain_vs_dataset_best']:+.3f} pp | {100*comp['route_change_rate']:.2f}% |"
        )
    lines += [
        "",
        "Large-vs-reasoning pair, query model:",
        "",
        "| seed | strict n | ties | positive rate | accuracy | AUC |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for seed in seeds:
        row = result["pairwise"]["pair_metrics"][f"query_seed{seed}"]["large_vs_reasoning"]
        lines.append(
            f"| {seed} | {row['strict_n']} | {row['tie_n']} | {pct(row['positive_rate'])} | "
            f"{pct(row['accuracy'])} | {'NA' if row['auc'] is None else f'{row['auc']:.3f}'} |"
        )
    lines += [
        "",
        "Interpretation: if pairwise query routing does not beat dataset-best, the current train evidence still says most recoverable signal is coarse task/domain signal. If large-vs-reasoning pair AUC is meaningfully above 0.5, MA should focus on that edge with additional independent repeats or stronger compatibility features.",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--alphas", type=float, nargs="+", default=[0.1, 1.0, 10.0, 100.0])
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.0, 0.05, 0.1])
    run(parser.parse_args())


if __name__ == "__main__":
    main()
