"""Deterministic offline shadow replay for the serving fallback path."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from llmrouter.serve.config import LLMConfig, ServeConfig
from llmrouter.serve.server import BackendCallError, LLMBackend
from fastapi import HTTPException


async def replay(requests: int):
    config = ServeConfig(
        llms={name: LLMConfig(name, "shadow", name, "https://shadow.invalid") for name in ("primary", "strong", "medium")},
        fallback_models=["strong", "medium"],
        request_timeout_s=0.1,
        total_timeout_s=0.3,
        circuit_failure_threshold=requests + 1,
    )
    backend = LLMBackend(config)
    records = []
    current = {"id": 0}

    async def shadow_call(llm, messages, max_tokens, temperature, api_key, timeout_s):
        request_id = current["id"]
        delays = {"primary": 0.001, "strong": 0.002, "medium": 0.003}
        await asyncio.sleep(delays[llm.name])
        if llm.name == "primary":
            if request_id and request_id % 67 == 0:
                raise BackendCallError("authentication", "injected auth failure", 401, False)
            if request_id % 10 == 0:
                raise BackendCallError("timeout", "injected timeout", 504, True)
        if llm.name == "strong" and request_id % 40 == 0:
            raise BackendCallError("temporary_unavailable", "injected unavailable", 503, True)
        return {"model": llm.name, "choices": [{"message": {"content": "shadow"}}]}

    backend._call_sync = shadow_call
    for request_id in range(requests):
        current["id"] = request_id
        started = time.monotonic()
        try:
            result = await backend.call_with_fallback("primary", [{"role": "user", "content": f"shadow-{request_id}"}])
            meta = result["_llmrouter"]
            records.append({"request_id": request_id, "status": "success", "selected_model": meta["selected_model"], "fallback_count": meta["fallback_count"], "latency_ms": (time.monotonic() - started) * 1000, "events": meta["events"]})
        except HTTPException as error:
            records.append({"request_id": request_id, "status": "failure", "error_category": error.detail["error_category"], "fallback_count": sum(e.get("outcome") == "failure" for e in error.detail["events"]) - 1, "latency_ms": (time.monotonic() - started) * 1000, "events": error.detail["events"]})

    latencies = sorted(r["latency_ms"] for r in records)
    percentile = lambda p: latencies[min(len(latencies) - 1, round((len(latencies) - 1) * p))]
    selected = {name: sum(r.get("selected_model") == name for r in records) for name in ("primary", "strong", "medium")}
    failures = [r for r in records if r["status"] == "failure"]
    fallback_requests = sum(r["status"] == "success" and r["selected_model"] != "primary" for r in records)
    return {
        "mode": "offline_shadow_no_external_calls",
        "requests": requests,
        "successes": requests - len(failures),
        "failures": len(failures),
        "selected_models": selected,
        "actual_fallback_requests": fallback_requests,
        "second_level_fallbacks": selected["medium"],
        "nonrecoverable_failures": {category: sum(r.get("error_category") == category for r in failures) for category in ("authentication", "invalid_request")},
        "nonrecoverable_with_fallback": sum(bool(r["events"][1:]) for r in failures),
        "latency_ms": {"mean": statistics.mean(latencies), "p50": percentile(0.5), "p95": percentile(0.95), "p99": percentile(0.99)},
        "duplicate_model_calls": sum(len([e["model"] for e in r["events"]]) != len(set(e["model"] for e in r["events"])) for r in records),
        "circuit_snapshot": backend.circuit_snapshot(),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("run_logs/serve/fallback_shadow_replay.json"))
    args = parser.parse_args()
    report = asyncio.run(replay(args.requests))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    summary = {key: value for key, value in report.items() if key != "records"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
