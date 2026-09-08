"""Pilot opportunity analysis (user Step 2, no training).

Input:  data/judged.jsonl (assembled + auto metrics + arenahard judge)
Output: pilot_matrix.csv          query-level quality/cost/latency x 4 slots
        PILOT_OPPORTUNITY.md      ① oracle gap ② complementarity ③ cost-quality

All quality values are protocol-v1.1 `final` labels (auto metric for GT tasks,
judge for arenahard). Ties are never dropped; tie semantics are explicit below.
"""
import json
import pathlib
from collections import defaultdict

import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parent
SLOTS = ["small", "medium", "large", "reasoning"]
NAME = {"small": "Qwen2.5-3B", "medium": "Qwen2.5-7B", "large": "Qwen2.5-14B",
        "reasoning": "DS-R1-Distill-14B"}

recs = [json.loads(l) for l in (R / "data/judged.jsonl").read_text().splitlines() if l.strip()]
by = [{s["slot"]: s for s in r["responses"]} for r in recs]

def val(i, slot, section, key):
    try:
        return by[i][slot][section].get(key)
    except Exception:
        return None

rows = []
for i, r in enumerate(recs):
    row = dict(query_id=r["query_id"], dataset=r["dataset"], task_type=r["task_type"])
    for s in SLOTS:
        row[f"q_{NAME[s]}"] = val(i, s, "quality", "final")
        row[f"c_{NAME[s]}"] = val(i, s, "cost", "usd")
        row[f"t_{NAME[s]}"] = val(i, s, "latency", "total_ms")
    rows.append(row)
df = pd.DataFrame(rows)
df.to_csv(R / "pilot_matrix.csv", index=False)

# keep only queries with complete 4-slot labels for the analysis (report the rest)
complete = df[[f"q_{NAME[s]}" for s in SLOTS]].notna().all(1)
print(f"complete-label queries: {complete.sum()}/{len(df)} "
      f"(dropped {len(df)-complete.sum()} for analysis only, kept in csv)")

Q = df.loc[complete, [f"q_{NAME[s]}" for s in SLOTS]].to_numpy()
C = df.loc[complete, [f"c_{NAME[s]}" for s in SLOTS]].to_numpy()
T = df.loc[complete, [f"t_{NAME[s]}" for s in SLOTS]].to_numpy()
tasks = df.loc[complete, "task_type"].to_numpy()
datasets = df.loc[complete, "dataset"].to_numpy()

lines = ["# Pilot 500x4 Routing Opportunity Analysis", "",
         f"Queries analyzed: {len(Q)} (complete labels; arenahard judge = qwen-max v1 rubric)", ""]

# ---- ① oracle gap ----------------------------------------------------------
lines += ["## 1. Oracle gap (routing headroom)", "",
          "| scope | Best Single (model) | Oracle | gap |", "|---|---|---|---|"]
def gap_block(mask, label):
    if mask.sum() == 0:
        return None
    q = Q[mask]
    means = q.mean(0)
    b = int(means.argmax())
    orc = float(q.max(1).mean())
    lines.append(f"| {label} | {means[b]:.4f} ({NAME[SLOTS[b]]}) | {orc:.4f} | **{orc-means[b]:+.4f}** |")
    return dict(label=label, best_single=float(means[b]), best_model=NAME[SLOTS[b]],
                oracle=orc, gap=orc - means[b], n=int(mask.sum()))
gaps = []
gaps.append(gap_block(np.ones(len(Q), bool), "overall"))
for tt in ("math", "code", "knowledge", "general"):
    g = gap_block(tasks == tt, tt)
    if g:
        gaps.append(g)
lines += ["", "Best Single = max_m E[Q_m]; Oracle = E[max_m Q_m]. Positive gap = routing headroom exists.", ""]

# ---- ② complementarity -------------------------------------------------------
best = Q.argmax(1)
best_val = Q.max(1)
uniq = (Q == best_val[:, None]).sum(1) == 1  # unique best (no tie at the top)
lines += ["## 2. Model complementarity", "",
          "| model | unique-best share | tied-best share | mean quality |", "|---|---|---|---|"]
for j, s in enumerate(SLOTS):
    uniq_share = float(((best == j) & uniq).mean())
    tied_share = float(((Q[:, j] == best_val) & ~uniq).mean())
    lines.append(f"| {NAME[s]} | {uniq_share:.1%} | {tied_share:.1%} | {Q[:, j].mean():.4f} |")
lines += ["", f"Unique-best queries: {uniq.mean():.1%} (ties at the top: {(~uniq).mean():.1%} — "
          "on ties any choice is accuracy-equivalent; the win there is cost/latency).", ""]
lines += ["Per dataset unique-best winner distribution:", "", "| dataset | " + " | ".join(NAME[s] for s in SLOTS) + " |",
          "|---|" + "---|" * 4]
for ds in sorted(set(datasets)):
    m = datasets == ds
    w = [(f"{((best[m] == j) & uniq[m]).mean():.0%}") for j in range(4)]
    lines.append(f"| {ds} | " + " | ".join(w) + " |")
lines.append("")

# ---- ③ cost-quality tradeoff --------------------------------------------------
lines += ["## 3. Cost-quality tradeoff", "",
          "| model | mean quality | mean cost ($) | mean latency (ms) |", "|---|---|---|---|"]
for j, s in enumerate(SLOTS):
    lines.append(f"| {NAME[s]} | {Q[:, j].mean():.4f} | {C[:, j].mean():.7f} | {T[:, j].mean():.0f} |")
# quality-parity cost comparison: pairs within 2pp quality
lines += ["", "Quality-parity pairs (|Δquality| ≤ 2pp) — cost advantage:", ""]
for a in range(4):
    for b_ in range(4):
        if a >= b_:
            continue
        dq = Q[:, a].mean() - Q[:, b_].mean()
        if abs(dq) <= 0.02:
            cr = C[:, a].mean() / max(C[:, b_].mean(), 1e-12)
            lines.append(f"- {NAME[SLOTS[a]]} vs {NAME[SLOTS[b_]]}: Δq={dq:+.4f}, "
                         f"cost ratio {cr:.2f}x ({'cheaper' if cr < 1 else 'costlier'})")
# per-task cost at ~equal quality (who is cheapest among models within 2pp of the task-best)
lines += ["", "Per task: cheapest model within 2pp of the best-quality model:", ""]
for tt in ("math", "code", "knowledge", "general"):
    m = tasks == tt
    if not m.any():
        continue
    means = Q[m].mean(0)
    bestq = means.max()
    near = [j for j in range(4) if bestq - means[j] <= 0.02]
    cheap = min(near, key=lambda j: C[m][:, j].mean())
    lines.append(f"- {tt}: best {NAME[SLOTS[int(means.argmax())]]} ({bestq:.3f}); "
                 f"cheapest within 2pp = {NAME[SLOTS[cheap]]} "
                 f"(q={means[cheap]:.3f}, ${C[m][:, cheap].mean():.7f}/query)")
lines += ["", "NOTE: cost/latency are Phase-1 mixed-deployment values (indicative only; "
          "paper metric comes from Phase-2 all-local vLLM per protocol v1.1).", ""]

# status summary
st = defaultdict(int)
for i, r in enumerate(recs):
    for s in r["responses"]:
        st[(s["slot"], s.get("status"))] += 1
lines += ["## Collection status", "", "| slot | ok | truncated | failed | parse_failed |", "|---|---|---|---|---|"]
for s in SLOTS:
    lines.append(f"| {NAME[s]} | {st[(s,'ok')]} | {st[(s,'truncated')]} | {st[(s,'failed')]} | {st[(s,'parse_failed')]} |")

(R / "PILOT_OPPORTUNITY.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
print("\nwritten: pilot_matrix.csv, PILOT_OPPORTUNITY.md")
