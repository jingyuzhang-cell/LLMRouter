"""Unified 5-source loader for R3 collection.

Emits {query_id, dataset, task_type, query, ground_truth} dicts. Prompts for the four
bench sources are the EXACT served prompts from the frozen official run (data/bench),
so results stay comparable with R2A. gsm8k prompts are built with a frozen template.

Pilot quotas: first 100 per source by index (deterministic; pilot is a subset of the
full 5000 run - no waste).
"""
import glob
import json
import pathlib

import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
BENCH = pathlib.Path("/root/routing_reproduction/llmrouterbench_r2/data/bench")
EVAL = pathlib.Path("/root/routing_reproduction/llmrouterbench_r2/LLMRouterBench")
BENCH_MODEL_DIR = "DeepHermes-3-Llama-3-8B-Preview"

GSM8K_PROMPT = (
    "Solve the following math problem step by step. "
    "The last line of your response should only contain your final answer "
    "inside a \\boxed{{}} command.\n\n{question}"
)

FULL_QUOTA = {"gsm8k": 2113, "mbpp": 974, "humaneval": 164, "mmlupro": 1000, "arenahard": 750}
PILOT_QUOTA = {k: 100 for k in FULL_QUOTA}


def bench_records(dataset, subdir):
    p = sorted(glob.glob(str(BENCH / dataset / subdir / BENCH_MODEL_DIR / "*.json")))
    assert p, f"no bench file for {dataset}"
    return json.load(open(p[0]))["records"]


def load_mbpp_tests():
    # official MBPP test.json is JSONL; sha256 == LFS stub oid f3fcebc8... (provenance verified)
    data = [json.loads(l) for l in (EVAL / "data" / "MBPP" / "test.json").read_text().splitlines() if l.strip()]
    return {x["text"]: x for x in data}


def load_humaneval():
    data = [json.loads(l) for l in (EVAL / "data" / "HumanEval" / "HumanEval.jsonl").read_text().splitlines() if l.strip()]
    return {x["prompt"]: x for x in data}


def load_sources(quota):
    out = []
    # gsm8k (HF parquet, frozen template)
    te = pd.read_parquet(R / "data/sources/gsm8k/main/test-00000-of-00001.parquet")
    tr = pd.read_parquet(R / "data/sources/gsm8k/main/train-00000-of-00001.parquet")
    n_test = min(quota["gsm8k"], len(te))
    rows = [("test", i, te.iloc[i]) for i in range(n_test)]
    if quota["gsm8k"] > n_test:
        rows += [("train", i, tr.iloc[i]) for i in range(quota["gsm8k"] - n_test)]
    for split, i, r in rows:
        gt = r["answer"].rsplit("####", 1)[-1].strip()
        out.append(dict(query_id=f"gsm8k_{split}_{i+1:04d}", dataset="gsm8k", task_type="math",
                        query=GSM8K_PROMPT.format(question=r["question"]), ground_truth=gt))
    # mbpp (bench prompt + test_list from official eval data)
    mbpp_tests = load_mbpp_tests()
    for rec in bench_records("mbpp", "test")[:quota["mbpp"]]:
        t = mbpp_tests.get(rec["origin_query"])
        assert t, f"mbpp test not found for index {rec['index']}"
        out.append(dict(query_id=f"mbpp_{rec['index']:04d}", dataset="mbpp", task_type="code",
                        query=rec["prompt"], ground_truth=json.dumps(t["test_list"])))
    # humaneval (bench prompt + canonical tests)
    he = load_humaneval()
    for rec in bench_records("humaneval", "test")[:quota["humaneval"]]:
        h = he.get(rec["origin_query"])
        assert h, f"humaneval entry not found for index {rec['index']}"
        out.append(dict(query_id=f"humaneval_{rec['index']:04d}", dataset="humaneval", task_type="code",
                        query=rec["prompt"],
                        ground_truth=json.dumps({"test": h["test"], "entry_point": h["entry_point"]})))
    # mmlupro (bench prompt + option letter)
    for rec in bench_records("mmlupro", "test_1000")[:quota["mmlupro"]]:
        out.append(dict(query_id=f"mmlupro_{rec['index']:04d}", dataset="mmlupro", task_type="knowledge",
                        query=rec["prompt"], ground_truth=str(rec["ground_truth"]).strip()))
    # arenahard (bench prompt, no GT)
    for rec in bench_records("arenahard", ".")[:quota["arenahard"]]:
        out.append(dict(query_id=f"arenahard_{rec['index']:04d}", dataset="arenahard", task_type="general",
                        query=rec["prompt"], ground_truth=None))
    # exact-text dedup keep-first
    seen, ded = set(), []
    for r in out:
        if r["query"] not in seen:
            seen.add(r["query"])
            ded.append(r)
    return ded


if __name__ == "__main__":
    import sys
    q = PILOT_QUOTA if "--pilot" in sys.argv else FULL_QUOTA
    rows = load_sources(q)
    counts = {}
    for r in rows:
        counts[r["dataset"]] = counts.get(r["dataset"], 0) + 1
    print("quota:", q, "-> loaded:", counts, "total", len(rows))
