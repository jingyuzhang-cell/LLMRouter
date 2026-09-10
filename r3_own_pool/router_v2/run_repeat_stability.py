"""Collect and aggregate repeat-stability labels for a blind panel.

Writes to an isolated output directory and never mutates data/raw or the frozen
training matrix. Objective scoring is applied immediately for math, knowledge,
and code tasks using the existing project scorers.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import time
from collections import defaultdict

from urllib import request, error

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECT = ROOT / "collect"
SLOTS = {
    "large": {
        "model": "Qwen/Qwen2.5-14B-Instruct",
        "path": "/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8",
        "served": "Qwen/Qwen2.5-14B-Instruct",
        "local": True,
    },
    "reasoning": {
        "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        "served": "deepseek-r1-distill-qwen-14b",
        "local": False,
    },
}
MAX_TOKENS = {"math": 4096, "code": 2048, "knowledge": 2048, "general": 4096}
PORT = 8127


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    if not pathlib.Path(path).exists():
        return []
    return [json.loads(line) for line in pathlib.Path(path).read_text().split('\n') if line.strip()]


def write_protocol(out, args):
    protocol = {
        "label_protocol_version": 2,
        "scorer_sha256": sha(__file__),
        "cohort_sha256": sha(ROOT / "data/cohort_full_v2/queries.jsonl"),
        "role": "repeat_stability_collection_large_vs_reasoning",
        "panel": str(pathlib.Path(args.panel).resolve()),
        "panel_sha256": sha(args.panel),
        "slot": args.slot,
        "repeats": args.repeats,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens_by_task_type": MAX_TOKENS,
        "stable_threshold": args.stable_threshold,
        "pair_aggregation": "all repeat cross-product comparisons per query",
        "output_isolated_from_primary_raw": True,
        "limits": [
            "Panel is train-only development data.",
            "Nonzero temperature repeat labels estimate stochastic robustness, not the original temperature-0 deployment distribution.",
            "No validation or test labels are loaded.",
        ],
    }
    path = out / "PROTOCOL.json"
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("label_protocol_version") != 2:
            raise RuntimeError("Legacy repeat scores are invalid; use a new output directory")
        comparable = {k: old[k] for k in protocol if k in old and k != "slot"}
        expected = {k: protocol[k] for k in comparable}
        if comparable != expected:
            raise RuntimeError("Existing protocol does not match requested repeat run")
        if args.slot not in old.get("slots_started", []):
            old.setdefault("slots_started", []).append(args.slot)
            path.write_text(json.dumps(old, indent=2) + "\n")
        return old
    protocol["slots_started"] = [args.slot]
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(protocol, indent=2) + "\n")
    return protocol


def done_keys(path):
    return {(r["query_id"], r["slot"], int(r["repeat_index"])) for r in read_jsonl(path)}


def bind_panel(panel, cohort_dir):
    from .data import load_cohort
    cohort, split = load_cohort(cohort_dir)
    if len({r['query_id'] for r in panel}) != len(panel):
        raise ValueError('Duplicate repeat panel ID')
    rows=[]
    for row in panel:
        qid=row['query_id']
        if qid not in set(split['train']) or row['query'] != cohort[qid]['query']:
            raise ValueError('Repeat panel must match original train query')
        if any(row[k] != cohort[qid][k] for k in ('dataset','task_type')):
            raise ValueError('Repeat panel metadata mismatch')
        rows.append({**row, 'ground_truth':cohort[qid]['ground_truth']})
    return rows


def score_answer(row, answer, status):
    if row.get('ground_truth') is None:
        raise ValueError('Missing ground truth: never silently score a blind panel')
    if status == 'failed':
        return {'quality':None, 'evaluation_status':'infrastructure_failure_missing'}
    # A truncated but delivered answer is evaluated as delivered.
    if row['dataset'] in ('mbpp','humaneval'):
        from .score_code import score
    else:
        from .score_available import score
    result=score(row, {'answer':answer, 'status':status})
    if result is None: raise ValueError('Unsupported repeat dataset')
    return result


def generate(client, model, row, temperature, top_p, max_retries):
    last_err = None
    opener = request.build_opener(request.ProxyHandler({})) if client.get("local") else request
    for attempt in range(max_retries):
        try:
            t0 = time.perf_counter()
            payload = json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": row["query"]}],
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": MAX_TOKENS[row["task_type"]],
                    "stream": False,
                }
            ).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if client.get("api_key"):
                headers["Authorization"] = f"Bearer {client['api_key']}"
            req = request.Request(client["base_url"] + "/chat/completions", data=payload, headers=headers, method="POST")
            with opener.open(req, timeout=client.get("timeout", 240)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            total = time.perf_counter() - t0
            choice = data["choices"][0]
            message = choice.get("message", {})
            answer = (message.get("content") or "").strip() or None
            thinking = message.get("reasoning_content")
            finish_reason = choice.get("finish_reason")
            usage = data.get("usage") or {}
            out_tok = usage.get("completion_tokens")
            in_tok = usage.get("prompt_tokens")
            estimated = out_tok is None or in_tok is None
            if out_tok is None:
                out_tok = len((answer or "") + (thinking or "")) // 3
            return {
                "answer": answer,
                "thinking": thinking,
                "finish_reason": finish_reason,
                "status": "ok" if finish_reason == "stop" and answer else ("truncated" if finish_reason == "length" else "failed"),
                "cost": {"tokens_input": in_tok, "tokens_output": out_tok, "tokens_estimated": estimated},
                "latency": {
                    "total_ms": round(total * 1000, 1),
                    "ttft_ms": None,
                    "decode_ms": None,
                    "tokens_per_second": round(out_tok / total, 1) if total > 0 else None,
                },
            }
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    return {
        "answer": None,
        "thinking": None,
        "finish_reason": None,
        "status": "failed",
        "error": str(last_err),
        "cost": {"tokens_input": None, "tokens_output": None, "tokens_estimated": True},
        "latency": {"total_ms": None, "ttft_ms": None, "decode_ms": None, "tokens_per_second": None},
    }


def wait_healthy(process, timeout=1800):
    start = time.time()
    url = f"http://127.0.0.1:{PORT}/health"
    while time.time() - start < timeout:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited with {process.returncode}")
        check = subprocess.run(["curl", "-fsS", "-m", "5", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode == 0:
            return
        time.sleep(5)
    raise RuntimeError("vLLM did not become healthy")


def local_client(slot, out):
    cfg = SLOTS[slot]
    log_dir = out / "logs"
    log_dir.mkdir(exist_ok=True)
    cmd = [
        "/root/autodl-tmp/r3_venv/bin/vllm",
        "serve",
        cfg["path"],
        "--served-model-name",
        cfg["served"],
        "--port",
        str(PORT),
        "--max-model-len",
        "16384",
        "--gpu-memory-utilization",
        "0.92",
        "--dtype",
        "auto",
        "--generation-config",
        "vllm",
    ]
    env = {**os.environ, "VLLM_LOGGING_LEVEL": "WARNING"}
    log = open(log_dir / f"vllm_{slot}.log", "a")
    proc = subprocess.Popen(cmd, cwd=str(COLLECT), env=env, stdout=log, stderr=subprocess.STDOUT)
    wait_healthy(proc)
    return {"base_url": f"http://127.0.0.1:{PORT}/v1", "api_key": "local", "timeout": 240, "local": True}, proc, log


def api_client():
    from dotenv import dotenv_values
    for key, value in dotenv_values("/root/.env").items():
        if value is not None:
            os.environ.setdefault(key, value)
    if not os.environ.get("QWEN_API_KEY"):
        raise RuntimeError("QWEN_API_KEY unavailable")
    return {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": os.environ["QWEN_API_KEY"], "timeout": 600}


def collect(args):
    out = pathlib.Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    write_protocol(out, args)
    panel = bind_panel(read_jsonl(args.panel), ROOT/'data/cohort_full_v2')
    if any(r['dataset'] in ('mbpp','humaneval') for r in panel):
        from .code_sandbox import verify_runtime
        runtime_hash=verify_runtime()
        probe=json.loads((ROOT/'router_v2/CODE_SANDBOX_PROBE_V3.json').read_text())
        if probe.get('status') != 'PASS' or probe.get('runtime_manifest_sha256') != runtime_hash:
            raise RuntimeError('Audited code scoring runtime required')
    cohort_signature = sha(ROOT / "data/cohort_full_v2/queries.jsonl")
    raw_path = out / f"{args.slot}.jsonl"
    complete = done_keys(raw_path)
    targets = [(row, repeat) for row in panel for repeat in range(args.repeats) if (row["query_id"], args.slot, repeat) not in complete]
    print(json.dumps({"slot": args.slot, "to_collect": len(targets), "raw": str(raw_path)}, indent=2), flush=True)
    if not targets:
        return
    lock_name = "local_gpu" if SLOTS[args.slot]["local"] else "reasoning_api"
    lock_path = out / f"{lock_name}.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.write(str(os.getpid()))
        lock.flush()
        client = None
        proc = None
        log = None
        try:
            if SLOTS[args.slot]["local"]:
                client, proc, log = local_client(args.slot, out)
            else:
                client = api_client()
            model = SLOTS[args.slot]["served"]
            count = 0
            with raw_path.open("a") as f:
                for row, repeat in targets:
                    slot_out = generate(client, model, row, args.temperature, args.top_p, args.max_retries)
                    score = score_answer(row, slot_out.get("answer"), slot_out.get("status"))
                    record = {
                        "cohort_sha256": cohort_signature,
                        "label_protocol_version": 2,
                        "panel_sha256": sha(args.panel),
                        "scorer_sha256": sha(__file__),
                        "query_id": row["query_id"],
                        "panel_index": row["panel_index"],
                        "dataset": row["dataset"],
                        "task_type": row["task_type"],
                        "slot": args.slot,
                        "model": SLOTS[args.slot]["model"],
                        "served_model": model,
                        "repeat_index": repeat,
                        "temperature": args.temperature,
                        "top_p": args.top_p,
                        "ts": time.time(),
                        **slot_out,
                        **score,
                    }
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()
                    fcntl.flock(f, fcntl.LOCK_UN)
                    count += 1
                    if count % 10 == 0:
                        print(f"[{args.slot}] {count}/{len(targets)}", flush=True)
        finally:
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if log is not None:
                log.close()


def aggregate(args):
    out = pathlib.Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    panel = {r["query_id"]: r for r in read_jsonl(args.panel)}
    rows = read_jsonl(out / "large.jsonl") + read_jsonl(out / "reasoning.jsonl")
    grouped = defaultdict(lambda: defaultdict(dict))
    invalid_repeats = 0
    expected_panel_sha = sha(args.panel)
    expected_scorer_sha = sha(__file__)
    expected_cohort_sha = sha(ROOT / "data/cohort_full_v2/queries.jsonl")
    for row in rows:
        if row["query_id"] in panel and row["slot"] in ("large", "reasoning"):
            if (row.get('label_protocol_version') != 2
                    or row.get('panel_sha256') != expected_panel_sha
                    or row.get('scorer_sha256') != expected_scorer_sha
                    or row.get('cohort_sha256') != expected_cohort_sha
                    or row.get('temperature') != args.temperature or row.get('top_p') != args.top_p
                    or row.get('status') == 'failed' or row.get('quality') is None
                    or not isinstance(row.get('quality'), (int,float))
                    or not math.isfinite(row['quality']) or not 0 <= row['quality'] <= 1
                    or row.get('evaluation_status') not in ('scored','answer_parse_failed')):
                invalid_repeats += 1
                continue
            idx=int(row['repeat_index'])
            if idx not in range(args.repeats): raise ValueError('Invalid repeat index')
            if idx in grouped[row['query_id']][row['slot']]: raise ValueError('Duplicate repeat index')
            grouped[row['query_id']][row['slot']][idx]=row
    labels = []
    incomplete = []
    for qid in sorted(panel):
        large = [r for _,r in sorted(grouped[qid]["large"].items())]
        reasoning = [r for _,r in sorted(grouped[qid]["reasoning"].items())]
        if len(large) < args.repeats or len(reasoning) < args.repeats:
            incomplete.append({"query_id": qid, "large": len(large), "reasoning": len(reasoning)})
            continue
        wins_r = wins_l = ties = 0
        comparisons = 0
        for a in large[: args.repeats]:
            for b in reasoning[: args.repeats]:
                comparisons += 1
                if b["quality"] > a["quality"]:
                    wins_r += 1
                elif a["quality"] > b["quality"]:
                    wins_l += 1
                else:
                    ties += 1
        r_rate = wins_r / comparisons
        l_rate = wins_l / comparisons
        t_rate = ties / comparisons
        if r_rate >= args.stable_threshold:
            label = "reasoning>large"
        elif l_rate >= args.stable_threshold:
            label = "large>reasoning"
        else:
            label = "unstable_or_tie"
        labels.append({
            "query_id": qid,
            "panel_index": panel[qid]["panel_index"],
            "dataset": panel[qid]["dataset"],
            "task_type": panel[qid]["task_type"],
            "strata": panel[qid]["strata"],
            "comparisons": comparisons,
            "independent_generations_per_slot": args.repeats,
            "cross_products_are_independent": False,
            "reasoning_win_rate": r_rate,
            "large_win_rate": l_rate,
            "tie_rate": t_rate,
            "stable_label": label,
            "large_quality_mean": sum(r["quality"] for r in large[: args.repeats]) / args.repeats,
            "reasoning_quality_mean": sum(r["quality"] for r in reasoning[: args.repeats]) / args.repeats,
            "large_ok_rate": sum(r["status"] == "ok" for r in large[: args.repeats]) / args.repeats,
            "reasoning_ok_rate": sum(r["status"] == "ok" for r in reasoning[: args.repeats]) / args.repeats,
        })
    with (out / "STABLE_LABELS.jsonl").open("w") as f:
        for row in labels:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    stable_pairs = []
    for row in labels:
        if row["stable_label"] == "reasoning>large":
            stable_pairs.append({**row, "winner": "reasoning", "loser": "large"})
        elif row["stable_label"] == "large>reasoning":
            stable_pairs.append({**row, "winner": "large", "loser": "reasoning"})
    with (out / "stable_pairs.jsonl").open("w") as f:
        for row in stable_pairs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    from collections import Counter
    summary = {
        "role": "repeat_stability_labels_large_vs_reasoning",
        "n_panel": len(panel),
        "invalid_repeats_excluded": invalid_repeats,
        "stability_interpretation": "Empirical threshold from 5 generations per slot; 25 dependent comparisons are not 25 independent observations",
        "n_complete": len(labels),
        "n_incomplete": len(incomplete),
        "stable_threshold": args.stable_threshold,
        "label_counts": dict(Counter(r["stable_label"] for r in labels)),
        "stable_pair_count": len(stable_pairs),
        "stable_pair_ratio": len(stable_pairs) / len(labels) if labels else None,
        "discard_count": sum(1 for r in labels if r["stable_label"] == "unstable_or_tie"),
        "discard_ratio": sum(1 for r in labels if r["stable_label"] == "unstable_or_tie") / len(labels) if labels else None,
        "mean_reasoning_win_rate": sum(r["reasoning_win_rate"] for r in labels) / len(labels) if labels else None,
        "mean_large_win_rate": sum(r["large_win_rate"] for r in labels) / len(labels) if labels else None,
        "mean_tie_rate": sum(r["tie_rate"] for r in labels) / len(labels) if labels else None,
        "incomplete": incomplete[:20],
        "files": {
            "STABLE_LABELS.jsonl": sha(out / "STABLE_LABELS.jsonl"),
            "stable_pairs.jsonl": sha(out / "stable_pairs.jsonl"),
        },
    }
    (out / "LABEL_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--slot", choices=["large", "reasoning"], default="large")
    parser.add_argument("--mode", choices=["collect", "aggregate"], default="collect")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--stable-threshold", type=float, default=0.8)
    args = parser.parse_args()
    if args.mode == "collect":
        collect(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    main()
