"""arenahard-only LLM judge (qwen-max, judge_prompts/v1.md). Fills quality.judge_score
and final for arenahard slots in assembled.jsonl (in place rewrite to judged.jsonl).
"""
import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from models import clients
from datasets.sources import load_sources, PILOT_QUOTA, FULL_QUOTA

R = pathlib.Path(__file__).resolve().parent
PROMPT = (R / "judge_prompts" / "v1.md").read_text()
SYS = "You are a strict, consistent grader. Output JSON only."
USER = PROMPT.split("## User", 1)[1].split("## Parsing", 1)[0].strip()
JSON_RE = re.compile(r"\{[^{}]*\}")


def judge_one(client, question, answer):
    txt = USER.replace("{question}", question[:8000]).replace("{answer}", (answer or "")[:8000])
    r = client.chat.completions.create(
        model="qwen-max", temperature=0.0,
        messages=[{"role": "system", "content": SYS}, {"role": "user", "content": txt}],
        response_format={"type": "json_object"}, max_tokens=200)
    m = JSON_RE.findall(r.choices[0].message.content or "")
    if not m:
        return None
    d = json.loads(m[-1])
    return max(0.0, min(1.0, float(d["score"]) / 10.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    a = ap.parse_args()
    quota = PILOT_QUOTA if a.pilot else FULL_QUOTA
    src = R.parent / "data" / "assembled.jsonl"
    recs = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    client = clients.make_dashscope_client()
    n, done = 0, 0
    for rec in recs:
        if rec["dataset"] != "arenahard":
            continue
        for s in rec["responses"]:
            if s["quality"].get("judge_score") is not None or s.get("answer") is None:
                continue
            n += 1
            for attempt in range(2):
                try:
                    sc = judge_one(client, rec["query"], s["answer"])
                    if sc is not None:
                        s["quality"]["judge_score"] = sc
                        s["quality"]["judge"] = "qwen-max"
                        s["quality"]["final"] = sc
                        break
                except Exception as e:
                    time.sleep(2 * (attempt + 1))
            done += 1
            if done % 25 == 0:
                print(f"[judge] {done}/{n}", flush=True)
    out = R.parent / "data" / "judged.jsonl"
    with open(out, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"judged -> {out} ({n} arenahard slots processed)")


if __name__ == "__main__":
    main()
