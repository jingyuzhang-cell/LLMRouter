"""Freeze: difficulty terciles + split (seed42 0.8/0.2 stratified by dataset) +
utility_scores (24 frozen lam/mu combos, per-query min-max normalized) + sha256.

Input:  data/judged.jsonl
Output: data/frozen/pilot_v1.jsonl (or full_v1.jsonl), data/frozen/split.json,
        data/frozen/MANIFEST.json
"""
import argparse
import hashlib
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

R = pathlib.Path(__file__).resolve().parents[1]
DATA = R / "data"
LAMS = (0, 0.1, 0.5, 1, 2, 5)
MUS = (0, 0.1, 0.5, 1)


def freeze(version):
    if version != "pilot_v1":
        raise ValueError("Legacy freeze is pilot-only: full v2 must preserve cohort_full_v2/split.json and pass explicit scoring/cost gates; do not regenerate an 80/20 split.")
    recs = [json.loads(l) for l in (DATA / "judged.jsonl").read_text().split("\n") if l.strip()]

    # 1) utility: per-query min-max normalize cost/latency across the 4 slots
    for rec in recs:
        costs = [s["cost"].get("usd") or 0.0 for s in rec["responses"]]
        lats = [s["latency"].get("total_ms") or 1.0 for s in rec["responses"]]
        cmax, tmax = max(costs) or 1.0, max(lats) or 1.0
        for s in rec["responses"]:
            q = s["quality"]["final"]
            cn = (s["cost"].get("usd") or 0.0) / cmax if cmax else 0.0
            tn = (s["latency"].get("total_ms") or 0.0) / tmax if tmax else 0.0
            u = {}
            for lam in LAMS:
                for mu in MUS:
                    key = f"lam{lam:g}_mu{mu:g}"
                    u[key] = None if q is None else round(q - lam * cn - mu * tn, 6)
            s["utility_scores"] = u

    # 2) difficulty: tercile of pool-mean final per task_type
    import statistics
    by_task = {}
    for rec in recs:
        vals = [s["quality"]["final"] for s in rec["responses"] if s["quality"]["final"] is not None]
        if vals:
            by_task.setdefault(rec["task_type"], []).append(sum(vals) / len(vals))
    cuts = {t: sorted(v)[len(v) // 3: len(v) * 2 // 3 + 1] for t, v in by_task.items()}
    for rec in recs:
        vals = [s["quality"]["final"] for s in rec["responses"] if s["quality"]["final"] is not None]
        m = sum(vals) / len(vals) if vals else None
        if m is None:
            rec["difficulty"] = "medium"
        else:
            lo, hi = cuts[rec["task_type"]][0], cuts[rec["task_type"]][-1]
            rec["difficulty"] = "easy" if m <= lo else ("hard" if m >= hi else "medium")

    # 3) split: stratified by dataset, prompt-level 0.8/0.2 seed 42
    rng = random.Random(42)
    train, test = [], []
    by_ds = {}
    for rec in recs:
        by_ds.setdefault(rec["dataset"], []).append(rec["query_id"])
    for ds, ids in sorted(by_ds.items()):
        ids = sorted(ids)
        rng.shuffle(ids)
        k = round(len(ids) * 0.8)
        train += ids[:k]
        test += ids[k:]

    out_dir = DATA / "frozen"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{version}.jsonl"
    with open(p, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "split.json").write_text(json.dumps({"train": sorted(train), "test": sorted(test)}, indent=0))
    (out_dir / "MANIFEST.json").write_text(json.dumps(dict(
        version=version, n_records=len(recs),
        split=dict(train=len(train), test=len(test)),
        dataset_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        judge_prompt="judge_prompts/v1.md",
        price_table="price_table.json",
        utility_grid=dict(lam=list(LAMS), mu=list(MUS), normalize="per-query pool max"),
    ), indent=2))
    print(f"frozen {len(recs)} records -> {p} (train {len(train)} / test {len(test)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="pilot_v1")
    freeze(ap.parse_args().version)
