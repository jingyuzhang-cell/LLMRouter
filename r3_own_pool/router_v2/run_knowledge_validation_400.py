"""Collect Coder on the frozen knowledge panel, rescore four models, and diagnose."""
import fcntl
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import run_repeat_stability as engine
from .data import load_cohort, read_rows, sha
from .rescore_glm_pilot import extract_option


ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/knowledge_validation_400"
OUT = ROOT / "data/knowledge_validation_400"
RESULTS = ROOT / "router_v2/knowledge_validation_400_results"
MODEL_DIR = Path("/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct")
CODER_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct"
CODER_REVISION = "c03e6d358207e414f1eca0bb1891e29f1db0e242"
SLOTS = ("medium", "large", "coder", "reasoning")


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def state(phase, **extra):
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "STATUS.json", {"phase": phase, "ts": time.time(), **extra})


def score_option(source, raw):
    if raw.get("status") == "failed" or not raw.get("answer"):
        return {"quality": None, "evaluation_status": "generation_failure", "parse_succeeded": False}
    option = extract_option(raw["answer"])
    return {
        "quality": float(option == str(source["ground_truth"]).strip().upper()[-1]) if option else 0.0,
        "evaluation_status": "scored" if option else "answer_parse_failed",
        "parse_succeeded": option is not None,
        "extracted_option": option,
    }


def load_historical(panel, cohort):
    sys.path.insert(0, str(ROOT / "collect"))
    import storage
    raw_paths = {slot: ROOT / f"data/raw/{slot}.jsonl" for slot in ("medium", "large", "reasoning")}
    canonical = {slot: storage.canonical_rows(path) for slot, path in raw_paths.items()}
    result = {}
    for row in panel:
        qid = row["query_id"]
        result[qid] = {}
        for slot in canonical:
            if qid not in canonical[slot]:
                raise ValueError(f"Missing historical response: {slot}/{qid}")
            raw = canonical[slot][qid]
            scored = score_option(cohort[qid], raw)
            if scored["quality"] is None:
                raise ValueError(f"Historical generation failure: {slot}/{qid}")
            result[qid][slot] = {**raw, **scored, "slot": slot}
    hashes = {slot: sha(path) for slot, path in raw_paths.items()}
    return result, hashes


def collect_coder(panel, cohort):
    path = OUT / "coder.jsonl"
    attempts = OUT / "ATTEMPTS.jsonl"
    completed = {r["query_id"]: r for r in read_rows(path)} if path.exists() else {}
    spent = {r["query_id"] for r in read_rows(attempts)} if attempts.exists() else set()
    if len(completed) == len(panel):
        return completed
    with (ROOT / "collect/logs/local_gpu.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (OUT / "VLLM.log").open("a") as log:
            proc = subprocess.Popen([
                "/root/autodl-tmp/r3_venv/bin/vllm", "serve", str(MODEL_DIR),
                "--served-model-name", CODER_REPO, "--port", "8127",
                "--max-model-len", "8192", "--max-num-seqs", "2",
                "--gpu-memory-utilization", ".92", "--generation-config", "vllm",
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                state("LOADING", records=len(completed), target=400)
                engine.wait_healthy(proc)
                client = {"base_url": "http://127.0.0.1:8127/v1", "api_key": "local", "local": True, "timeout": 600}
                with path.open("a") as output, attempts.open("a") as budget:
                    for row in panel:
                        qid = row["query_id"]
                        if qid in completed:
                            continue
                        if qid in spent:
                            raise RuntimeError(f"Interrupted request requires audit: {qid}")
                        budget.write(json.dumps({"query_id": qid, "max_requests": 2, "ts": time.time()}) + "\n")
                        budget.flush()
                        raw = engine.generate(client, CODER_REPO, row, 0.0, 1.0, 2)
                        scored = score_option(cohort[qid], raw)
                        record = {**raw, **scored, "query_id": qid, "slot": "coder", "model": CODER_REPO,
                                  "revision": CODER_REVISION, "temperature": 0.0, "top_p": 1.0,
                                  "panel_sha256": sha(PANEL_DIR / "PANEL.jsonl"), "ts": time.time()}
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                        output.flush()
                        if scored["quality"] is None:
                            raise RuntimeError(f"Coder generation failed: {qid}")
                        completed[qid] = record
                        state("COLLECTING", records=len(completed), target=400,
                              parse_failures=sum(not r["parse_succeeded"] for r in completed.values()))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    return completed


def diagnostic(q, baseline, slot_names):
    n, k = q.shape
    oracle = q.max(1)
    unique_mask = q.sum(1) == 1
    unique_counts = q[unique_mask].sum(0)
    entropy = None
    if unique_counts.sum():
        p = unique_counts[unique_counts > 0] / unique_counts.sum()
        entropy = float(-(p * np.log2(p)).sum() / np.log2(k))
    correlations = {}
    defined = []
    for i, j in itertools.combinations(range(k), 2):
        value = None
        if np.std(q[:, i]) and np.std(q[:, j]):
            value = float(np.corrcoef(q[:, i], q[:, j])[0, 1])
            defined.append(value)
        correlations[f"{slot_names[i]} / {slot_names[j]}"] = value
    return {
        "n": n,
        "accuracy": dict(zip(slot_names, q.mean(0).tolist())),
        "oracle_accuracy": float(oracle.mean()),
        "datasetbest_oof_accuracy": float(baseline.mean()),
        "oracle_gap": float((oracle - baseline).mean()),
        "oracle_gap_count": int((oracle - baseline).sum()),
        "winner_entropy_unique_normalized": entropy,
        "unique_winner_ratio": float(unique_mask.mean()),
        "unique_winner_count": int(unique_mask.sum()),
        "unique_wins": dict(zip(slot_names, unique_counts.astype(int).tolist())),
        "mean_model_correlation": float(np.mean(defined)),
        "pair_correlations": correlations,
        "all_correct": int((q.sum(1) == k).sum()),
        "all_wrong": int((q.sum(1) == 0).sum()),
    }


def analyze(panel, historical, coder):
    if RESULTS.exists():
        raise FileExistsError(RESULTS)
    ids = np.array([r["query_id"] for r in panel])
    folds = np.array([r["fold"] for r in panel])
    groups = np.array([r["prompt_group"] for r in panel])
    q = np.array([[historical[x]["medium"]["quality"], historical[x]["large"]["quality"],
                   coder[x]["quality"], historical[x]["reasoning"]["quality"]] for x in ids])
    baseline = np.empty(len(ids))
    choices = np.empty(len(ids), dtype=int)
    for fold in sorted(set(folds)):
        train = folds != fold
        valid = ~train
        if set(groups[train]) & set(groups[valid]):
            raise ValueError("Prompt-group fold leakage")
        choice = int(q[train].mean(0).argmax())
        choices[valid] = choice
        baseline[valid] = q[valid, choice]
    result = diagnostic(q, baseline, list(SLOTS))
    gate = {
        "oracle_gap_gt_8pct": result["oracle_gap"] > 0.08,
        "winner_entropy_gt_0_7": result["winner_entropy_unique_normalized"] is not None
        and result["winner_entropy_unique_normalized"] > 0.7,
    }
    gate["pass"] = all(gate.values())
    gate["next_action"] = "READY_FOR_MA_DESIGN" if gate["pass"] else "RESELECT_BENCHMARK_OR_MODEL_DIFFERENTIATION"
    RESULTS.mkdir(parents=True)
    np.savez_compressed(RESULTS / "DIAGNOSTIC.npz", ids=ids, folds=folds, quality=q,
                        datasetbest_choices=choices, datasetbest_quality=baseline)
    sources = {
        "panel": sha(PANEL_DIR / "PANEL.jsonl"),
        "panel_protocol": sha(PANEL_DIR / "PROTOCOL.json"),
        "coder": sha(OUT / "coder.jsonl"),
        "collector_and_analysis": sha(Path(__file__)),
    }
    output = {"diagnostic": result, "gate": gate, "sources": sources,
              "definitions": {
                  "oracle_gap": "Oracle accuracy minus held-fold BestSingle/DatasetBest for this one-dataset panel",
                  "winner_entropy": "normalized Shannon entropy across strict unique-winner model counts",
                  "unique_winner_ratio": "fraction with exactly one correct model",
                  "model_correlation": "mean defined pairwise Pearson/phi correlation of binary correctness",
              },
              "limits": ["Original-train development diagnostic; not independent confirmation.",
                         "Single samples estimate realized correctness, not expected utility variance.",
                         "MA is not trained by this pipeline."]}
    atomic_json(RESULTS / "RESULTS.json", output)
    entropy = result["winner_entropy_unique_normalized"]
    report = [
        "# MMLU-Pro 400题四模型路由可行性诊断", "",
        "| Oracle Gap | Winner entropy | Unique winner ratio | Model correlation |", "|---:|---:|---:|---:|",
        f"| {result['oracle_gap']:.2%} ({result['oracle_gap_count']}题) | {entropy:.3f} | {result['unique_winner_ratio']:.2%} | {result['mean_model_correlation']:.3f} |",
        "", "独有赢家：" + json.dumps(result["unique_wins"], ensure_ascii=False),
        "", "各模型准确率：" + json.dumps(result["accuracy"], ensure_ascii=False),
        "", f"门禁：{'PASS' if gate['pass'] else 'FAIL'}；下一步：{gate['next_action']}。",
        "", "这是原train开发诊断且每题单次，不作为独立论文验证。MA未训练。",
    ]
    (RESULTS / "REPORT.md").write_text("\n".join(report) + "\n")
    state("DIAGNOSTIC_COMPLETE", records=400, gate=gate, report=str(RESULTS / "REPORT.md"))


def main():
    protocol = json.loads((PANEL_DIR / "PROTOCOL.json").read_text())
    if sha(PANEL_DIR / "PANEL.jsonl") != protocol["panel_sha256"]:
        raise ValueError("Panel changed")
    if json.loads((MODEL_DIR / "DOWNLOAD_COMPLETE.json").read_text()) != {"repo": CODER_REPO, "revision": CODER_REVISION}:
        raise ValueError("Coder checkpoint mismatch")
    panel = read_rows(PANEL_DIR / "PANEL.jsonl")
    cohort, split = load_cohort(ROOT / "data/cohort_full_v2")
    if len(panel) != 400 or any(r["query_id"] not in split["train"] for r in panel):
        raise ValueError("Invalid panel membership")
    state("RESCORING_HISTORICAL", records=0, target=400)
    historical, hashes = load_historical(panel, cohort)
    atomic_json(OUT / "HISTORICAL_RAW_HASHES.json", hashes)
    coder = collect_coder(panel, cohort)
    state("ANALYZING", records=len(coder), target=400)
    analyze(panel, historical, coder)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        state("BLOCKED_ERROR", error=f"{type(exc).__name__}: {exc}")
        raise
