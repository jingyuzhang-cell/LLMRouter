"""Judge reliability audit: re-judge a random sample of arenahard slots with the
same frozen judge (qwen-max, judge_prompts/v1.md) and measure agreement.

Reports: exact /10 match rate, within-0.1 and within-0.2 rates, and per-query
ordering preservation (fraction of sampled queries whose 4-slot ranking by
judge_score is identical on re-judge).

Usage (after judged.jsonl exists):  python3 judge_reliability.py --sample 200
Output: JUDGE_RELIABILITY.json
"""
import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from models import clients
from judge import judge_one

R = pathlib.Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--input", default=str(R.parent / "data" / "judged.jsonl"))
    a = ap.parse_args()
    recs = [json.loads(l) for l in pathlib.Path(a.input).read_text().splitlines() if l.strip()]
    slots = []
    for r in recs:
        if r["dataset"] != "arenahard":
            continue
        for s in r["responses"]:
            if s["quality"].get("judge_score") is not None and s.get("answer"):
                slots.append((r["query_id"], s["slot"], r["query"], s["answer"],
                              s["quality"]["judge_score"]))
    rng = random.Random(42)
    rng.shuffle(slots)
    sample = slots[:a.sample]
    print(f"re-judging {len(sample)} of {len(slots)} judged arenahard slots", flush=True)
    client = clients.make_dashscope_client()
    pairs = []
    for i, (qid, slot, q, ans, orig) in enumerate(sample):
        new = None
        for _ in range(2):
            try:
                new = judge_one(client, q, ans)
                if new is not None:
                    break
            except Exception:
                pass
        pairs.append((qid, slot, orig, new))
        if (i + 1) % 50 == 0:
            print(f"[reliability] {i+1}/{len(sample)}", flush=True)
    ok = [(o, n) for _, _, o, n in pairs if n is not None]
    exact = sum(1 for o, n in ok if round(o * 10) == round(n * 10)) / max(len(ok), 1)
    w1 = sum(1 for o, n in ok if abs(o - n) <= 0.1) / max(len(ok), 1)
    w2 = sum(1 for o, n in ok if abs(o - n) <= 0.2) / max(len(ok), 1)
    # ordering preservation per query (queries with >=2 re-judged slots)
    by_q = {}
    for qid, slot, o, n in pairs:
        if n is not None:
            by_q.setdefault(qid, {})[slot] = (o, n)
    ord_ok = ord_tot = 0
    for qid, d in by_q.items():
        if len(d) < 2:
            continue
        slots_ = sorted(d)
        o_rank = {s: i for i, s in enumerate(sorted(slots_, key=lambda s: -d[s][0]))}
        n_rank = {s: i for i, s in enumerate(sorted(slots_, key=lambda s: -d[s][1]))}
        ord_tot += 1
        if all(o_rank[s] == n_rank[s] for s in slots_):
            ord_ok += 1
    report = dict(
        judge="qwen-max", rubric="judge_prompts/v1.md", n_sample=len(pairs),
        n_rescored=len(ok),
        exact_match_on_10=round(exact, 4), within_0_1=round(w1, 4), within_0_2=round(w2, 4),
        ordering_preserved=f"{ord_ok}/{ord_tot}",
        ordering_rate=round(ord_ok / max(ord_tot, 1), 4),
        mean_abs_diff=round(sum(abs(o - n) for o, n in ok) / max(len(ok), 1), 4),
        note="labels below 0.8 within-0.1 or 0.9 ordering-rate flag unreliable supervision")
    (R.parent / "JUDGE_RELIABILITY.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
