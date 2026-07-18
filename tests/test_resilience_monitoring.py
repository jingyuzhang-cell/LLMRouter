import asyncio
import httpx
from llmrouter.serve.config import LLMConfig, ServeConfig
from llmrouter.serve.monitoring import ResilienceMonitor
from llmrouter.serve.server import create_app

def record(monitor, *, success=True, events=(), latency_s=0.1, quality=False, duplicates=0):
    monitor.record(success=success, primary="small", final="small" if success else None,
                   events=list(events), latency_s=latency_s, quality_escalated=quality,
                   duplicates_prevented=duplicates)

def test_persistence_survives_restart(tmp_path):
    state = tmp_path / "resilience.json"
    first = ResilienceMonitor(persistence_path=state)
    record(first, events=[{"category": "timeout"}], duplicates=2)
    second = ResilienceMonitor(persistence_path=state)
    snap = second.snapshot({})
    assert snap["requests"] == 1
    assert snap["error_categories"]["timeout"] == 1
    assert snap["duplicate_calls_prevented"] == 2

def test_alert_thresholds_and_quality_gate():
    monitor = ResilienceMonitor(quality_cascade_enabled=False)
    monitor.p95_baseline_ms = 50
    record(monitor, success=False, events=[{"category": "authentication"}],
           latency_s=0.1, quality=True, duplicates=1)
    snap = monitor.snapshot({"small": {"state": "open"}})
    assert set(snap["active_alerts"]) >= {"all_chain_failure_rate", "p95_latency_regression",
        "circuit_open_rate", "nonrecoverable_error", "duplicate_calls_increase"}
    assert "quality_escalation_rate" not in snap["alerts"]
    enabled = ResilienceMonitor(quality_cascade_enabled=True,
        alert_thresholds={"quality_escalation_rate": 0.1})
    record(enabled, quality=True)
    assert enabled.snapshot({})["alerts"]["quality_escalation_rate"]

def test_prometheus_contains_required_series():
    monitor = ResilienceMonitor(); record(monitor)
    output = monitor.prometheus({"small": {"state": "closed"}})
    assert "llmrouter_requests_total 1" in output
    assert "llmrouter_latency_p95_baseline_ms" in output
    assert 'llmrouter_circuit_open{model="small"} 0' in output
    assert 'llmrouter_alert_active{alert="all_chain_failure_rate"}' in output

def test_metrics_endpoints_fail_closed_and_require_bearer(monkeypatch):
    token_env = "TEST_LLMROUTER_METRICS_TOKEN"
    config = ServeConfig(llms={"small": LLMConfig("small", "test", "small", "https://example.test")},
                         metrics_token_env=token_env)
    app = create_app(config)
    async def checks():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://staging") as client:
            assert (await client.get("/metrics/resilience")).status_code == 503
            monkeypatch.setenv(token_env, "synthetic-secret")
            assert (await client.get("/metrics/resilience")).status_code == 401
            headers = {"Authorization": "Bearer synthetic-secret"}
            payload = (await client.get("/metrics/resilience", headers=headers)).json()
            prometheus = await client.get("/metrics", headers=headers)
            assert payload["requests"] == 0
            assert payload["quality_cascade_enabled"] is False
            assert prometheus.status_code == 200
            assert "llmrouter_requests_total" in prometheus.text
    asyncio.run(checks())
