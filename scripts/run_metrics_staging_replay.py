#!/usr/bin/env python3
"""Synthetic staging shadow replay; never contacts an external model API."""
import asyncio, json, os, tempfile
from pathlib import Path
import httpx
from llmrouter.serve.config import LLMConfig, ServeConfig
from llmrouter.serve.server import BackendCallError, create_app

async def main():
    token_env = "LLMROUTER_REPLAY_METRICS_TOKEN"
    os.environ[token_env] = "synthetic-replay-token"
    with tempfile.TemporaryDirectory(prefix="llmrouter-shadow-") as tmp:
        models = {name: LLMConfig(name, "synthetic", name, "http://not-used.invalid")
                  for name in ("small", "strong", "medium")}
        config = ServeConfig(llms=models, fallback_models=["strong", "medium"],
            show_model_prefix=False, metrics_token_env=token_env,
            metrics_persistence_path=str(Path(tmp) / "resilience.json"),
            circuit_failure_threshold=20)
        app = create_app(config); backend = app.state.llm_backend
        async def synthetic_call(llm, messages, max_tokens, temperature, api_key, timeout_s):
            case = messages[-1]["content"]
            if case == "fallback" and llm.name == "small":
                raise BackendCallError("timeout", "synthetic timeout", 504, True)
            if case == "nonrecoverable" and llm.name == "small":
                raise BackendCallError("authentication", "synthetic auth", 401, False)
            if case == "all_fail":
                raise BackendCallError("temporary_unavailable", "synthetic outage", 503, True)
            return {"model": llm.name, "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    "choices": [{"message": {"content": "synthetic"}}]}
        backend._call_sync = synthetic_call
        cases = ["success"] * 9 + ["fallback", "nonrecoverable", "all_fail"]
        request_log = []
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://staging") as client:
            for index, case in enumerate(cases):
                response = await client.post("/v1/chat/completions",
                    json={"model": "small", "messages": [{"role": "user", "content": case}]})
                request_log.append({"index": index, "case": case, "status": response.status_code})
            unauthorized = await client.get("/metrics/resilience")
            headers = {"Authorization": "Bearer synthetic-replay-token"}
            metrics_response = await client.get("/metrics/resilience", headers=headers)
            prometheus_response = await client.get("/metrics", headers=headers)
        metrics = metrics_response.json()
        assert unauthorized.status_code == 401
        assert metrics_response.status_code == prometheus_response.status_code == 200
        assert metrics["requests"] == len(request_log)
        assert "llmrouter_requests_total 12" in prometheus_response.text
        report = {"mode": "synthetic_staging_shadow_replay", "external_api_calls": 0,
            "endpoint_actually_fetched": True, "unauthorized_status": unauthorized.status_code,
            "logged_requests": len(request_log), "monitored_requests": metrics["requests"],
            "counts_match": metrics["requests"] == len(request_log),
            "quality_alert_enabled": "quality_escalation_rate" in metrics["alerts"],
            "requests": request_log, "metrics": metrics}
        output = Path("run_logs/serve/metrics_staging_shadow_replay.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(json.dumps({"report": str(output), "logged_requests": len(request_log),
            "monitored_requests": metrics["requests"], "unauthorized_status": unauthorized.status_code,
            "active_alerts": metrics["active_alerts"], "external_api_calls": 0}, indent=2))
if __name__ == "__main__": asyncio.run(main())
