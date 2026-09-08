"""Full-run opportunity analysis (pre-registered before 5000x4 completes).

Input:  --input data/judged_full.jsonl (assembled + metrics + judge, full quota)
Output: full_matrix.csv + FULL_OPPORTUNITY.md

Pre-registered analyses (user spec, 2026-09-08):
  A1 Oracle gap by task        -> routing headroom depends on query type
  A2 Pareto coverage           -> share of queries where each model is non-dominated
                                  in (quality up, cost down, latency down)
  A3 Routing difficulty        -> per-query top1-top2 quality margin distribution;
                                  large tie/small-margin share => uncertainty-aware
                                  router is needed
No training; descriptive only.
"""
import argparse
import json
import pathlib

import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parent
SLOTS = ["small", "medium", "large", "reasoning"]
NAME = {"small": "Qwen2.5-3B", "medium": "Qwen2.5-7B", "large": "Qwen2.5-14B",
        "reasoning": "DS-R1-Distill-14B"}


def load(path):
    recs = [json.loads(l) for l in (path).read_text().splitlines() if l.strip()]
    by = [{s["slot"]: s for s in r["responses"]} for r in recs]
    rows = []
    for i, r in enumerate(recs):
        row = dict(query_id=r["query_id"], dataset=r["dataset"], task_type=r["task_type"])
        for s in SLOTS:
            row[f"q_{NAME[s]}"] = by[i][s]["quality"].get("final")
            row[f"c_{NAME[s]}"] = by[i][s]["cost"].get("usd")
            row[f"t_{NAME[s]}"] = by[i][s]["latency"].get("total_ms")
        rows.append(row)
    return pd.DataFrame(rows)


def pareto_mask(q, c, t):
    """Model i non-dominated iff no j with qj>=qi, cj<=ci, tj<=ti and one strict."""
    n = len(q)
    keep = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            ge = (q[j] >= q[i]) and (c[j] <= c[i]) and (t[j] <= t[i])
            strict = (q[j] > q[i]) or (c[j] < c[i]) or (t[j] < t[i])
            if ge and strict:
                dominated = True
                break
        keep.append(not dominated)
    return np.array(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(R / "data/judged_full.jsonl"))
    ap.add_argument("--tag", default="full")
    a = ap.parse_args()
    df = load(pathlib.Path(a.input))
    df.to_csv(R / f"{a.tag}_matrix.csv", index=False)
    qcols = [f"q_{NAME[s]}" for s in SLOTS]
    complete = df[qcols].notna().all(1)
    print(f"complete-label queries: {complete.sum()}/{len(df)}")
    d = df.loc[complete]
    Q = d[qcols].to_numpy()
    C = d[[f"c_{NAME[s]}" for s in SLOTS]].to_numpy()
    T = d[[f"t_{NAME[s]}" for s in SLOTS]].to_numpy()
    T = np.where(np.isfinite(T), T, np.nan)  # latency may be None on api hiccups
    lat_ok = np.isfinite(T).all(1)
    tasks = d["task_type"].to_numpy()
    datasets = d["dataset"].to_numpy()

    L = [f"# {a.tag} 5000x4 Routing Opportunity Analysis (pre-registered A1-A3)", "",
         f"Queries analyzed: {len(d)} (complete labels)", ""]

    # A1 oracle gap by task
    L += ["## A1. Oracle gap by task", "", "| scope | Best Single (model) | Oracle | gap |", "|---|---|---|---|"]
    for label, mask in [("overall", np.ones(len(Q), bool))] + \
            [(tt, tasks == tt) for tt in ("math", "code", "knowledge", "general")]:
        if mask.sum() == 0:
            continue
        q = Q[mask]
        means = q.mean(0)
        b = int(means.argmax())
        orc = float(q.max(1).mean())
        L.append(f"| {label} | {means[b]:.4f} ({NAME[SLOTS[b]]}) | {orc:.4f} | **{orc-means[b]:+.4f}** |")
    L.append("")

    # A2 pareto coverage
    L += ["## A2. Pareto coverage (share of queries where model is non-dominated)", "",
          "Objectives: quality up, cost down, latency down (Phase-1 latency, indicative).", "",
          "| model | Pareto-member share | mean quality | mean cost ($) |", "|---|---|---|---|"]
    shares = np.zeros(4)
    m = lat_ok
    psets = []
    for i in np.where(m)[0]:
        pm = pareto_mask(Q[i], C[i], T[i])
        shares += pm
        psets.append(int(pm.sum()))
    for j, s in enumerate(SLOTS):
        L.append(f"| {NAME[s]} | {shares[j]/m.sum():.1%} | {Q[:, j].mean():.4f} | {C[:, j].mean():.7f} |")
    L += ["", f"Mean Pareto-set size: {np.mean(psets):.2f} of 4; "
          f"queries where ALL 4 models are Pareto-member: "
          f"{np.mean(np.array(psets)==4):.1%} (ties make everyone non-dominated).", ""]

    # A3 routing difficulty (quality margin)
    L += ["## A3. Routing difficulty (top1-top2 quality margin)", ""]
    srt = np.sort(Q, axis=1)
    margin = srt[:, -1] - srt[:, -2]
    L.append(f"- margin == 0 (tie at top): {np.mean(margin == 0):.1%}")
    L.append(f"- margin < 0.05: {np.mean(margin < 0.05):.1%}")
    L.append(f"- margin >= 0.10: {np.mean(margin >= 0.10):.1%}")
    qs = np.quantile(margin, [0.25, 0.5, 0.75])
    L.append(f"- margin quartiles: {qs[0]:.3f} / {qs[1]:.3f} / {qs[2]:.3f}")
    L.append("")
    L.append("If most margins are small/zero: hard labels are noise -> utility/regression + "
             "uncertainty-aware routing is the right formulation (confirms pilot finding).")
    L.append("")

    # A4 cost-saving opportunity at fixed quality (user spec 2.3)
    L += ["## A4. Cost-saving opportunity at fixed quality", ""]
    means = Q.mean(0)
    b_idx = int(means.argmax())
    T = means[b_idx] - 0.005  # quality floor: within 0.5pp of Best Single
    # per-query cheapest model that meets the floor (cost-optimal oracle at floor T);
    # queries where no model meets T fall back to the max-quality model's cost
    def cost_at_floor(qrow, crow, floor):
        ok = np.where(qrow >= floor)[0]
        if len(ok):
            return crow[ok].min()
        return crow[qrow.argmax()]
    or_cost = np.mean([cost_at_floor(Q[i], C[i], T) for i in range(len(Q))])
    L += [f"- quality floor T = {T:.4f} (Best Single − 0.5pp, best = {NAME[SLOTS[b_idx]]})",
          f"- always-best-single cost: ${C[:, b_idx].mean():.7f}/query",
          f"- per-query cheapest-model-meeting-T (cost-oracle): ${or_cost:.7f}/query "
          f"-> potential saving {1 - or_cost / C[:, b_idx].mean():.1%}",
          f"- fraction of queries where some cheaper model meets T: "
          f"{np.mean([np.any((Q[i] >= T) & (C[i] < C[i, b_idx])) for i in range(len(Q))]):.1%}",
          "", "This bounds what a router can save at matched quality (before any learning).", ""]

    # A5 difficulty-conditioned best model (user spec 2.4: router is not random)
    L += ["## A5. Best-model distribution by query difficulty", "",
          "Difficulty = pool-mean quality tercile (easy: all models fine; hard: few survive).", "",
          "| bucket | n | " + " | ".join(f"best={NAME[s]}" for s in SLOTS) + " | oracle gap |",
          "|---|---|" + "---|" * 5]
    pool_mean = Q.mean(1)
    qs = np.quantile(pool_mean, [1 / 3, 2 / 3])
    for label, msk in (("easy", pool_mean >= qs[1]), ("medium", (pool_mean >= qs[0]) & (pool_mean < qs[1])),
                       ("hard", pool_mean < qs[0])):
        if msk.sum() == 0:
            continue
        sub = Q[msk]
        w = [(f"{((sub[:, j] == sub.max(1)[:, None]).any(1)).mean():.0%}") for j in range(4)]
        gap = float(sub.max(1).mean() - sub.mean(0).max())
        L.append(f"| {label} | {msk.sum()} | " + " | ".join(w) + f" | {gap:+.4f} |")
    L += ["", "If hard queries favor R1/14B while easy queries tie widely, routing signal is "
          "difficulty-structured (not random): cheap models suffice on easy mass, expensive "
          "models matter on the hard tail.", ""]
    # status
    from collections import Counter
    st = Counter()
    for line in pathlib.Path(a.input).read_text().splitlines():
        if not line.strip():
            continue
        for s in json.loads(line)["responses"]:
            st[(s["slot"], s.get("status"))] += 1
    L += ["## Collection status", "", "| slot | ok | truncated | failed | parse_failed |", "|---|---|---|---|---|"]
    for s in SLOTS:
        L.append(f"| {NAME[s]} | {st[(s,'ok')]} | {st[(s,'truncated')]} | {st[(s,'failed')]} | {st[(s,'parse_failed')]} |")

    out = R / f"{a.tag.upper() if a.tag=='full' else a.tag.capitalize()}_OPPORTUNITY.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwritten: {a.tag}_matrix.csv, {out.name}")


if __name__ == "__main__":
    main()
