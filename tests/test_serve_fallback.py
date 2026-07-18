import asyncio
import pytest
from fastapi import HTTPException
from llmrouter.serve.config import LLMConfig, ServeConfig
from llmrouter.serve.server import BackendCallError, LLMBackend, classify_backend_error

def make_backend(fallbacks=("strong", "medium"), **overrides):
    config = ServeConfig(llms={name: LLMConfig(name, "test", name, "https://example.test") for name in ("primary", "strong", "medium")}, fallback_models=list(fallbacks), request_timeout_s=0.05, total_timeout_s=0.2, circuit_failure_threshold=2, circuit_cooldown_s=30.0)
    for key, value in overrides.items(): setattr(config, key, value)
    return LLMBackend(config)

def response(model): return {"model": model, "choices": [{"message": {"content": "ok"}}]}

def install_script(backend, outcomes, calls):
    async def fake_call(llm, messages, max_tokens, temperature, api_key, timeout_s):
        calls.append(llm.name)
        outcome = outcomes[llm.name]
        if isinstance(outcome, list): outcome = outcome.pop(0)
        if isinstance(outcome, Exception): raise outcome
        if callable(outcome): return await outcome(llm, timeout_s)
        return response(llm.name)
    backend._call_sync = fake_call

def run(backend): return asyncio.run(backend.call_with_fallback("primary", [{"role": "user", "content": "x"}]))

def test_primary_success():
    backend, calls = make_backend(), []; install_script(backend, {"primary": "ok"}, calls)
    result = run(backend)
    assert calls == ["primary"] and result["_llmrouter"]["selected_model"] == "primary"

def test_primary_failure_strong_success():
    backend, calls = make_backend(), []; install_script(backend, {"primary": BackendCallError("timeout", "late", 504, True), "strong": "ok"}, calls)
    result = run(backend)
    assert calls == ["primary", "strong"] and result["_llmrouter"]["selected_model"] == "strong"

def test_strong_failure_medium_success():
    backend, calls = make_backend(), []; failure = BackendCallError("temporary_unavailable", "down", 503, True)
    install_script(backend, {"primary": failure, "strong": failure, "medium": "ok"}, calls)
    result = run(backend)
    assert calls == ["primary", "strong", "medium"] and result["_llmrouter"]["selected_model"] == "medium"

def test_all_fail_and_never_duplicate_models():
    backend, calls = make_backend(("primary", "strong", "strong", "medium")), []; failure = BackendCallError("model_unavailable", "down", 404, True)
    install_script(backend, {name: failure for name in ("primary", "strong", "medium")}, calls)
    with pytest.raises(HTTPException) as caught: run(backend)
    assert calls == ["primary", "strong", "medium"] and caught.value.detail["error_category"] == "model_unavailable"

def test_total_timeout_budget_stops_chain():
    backend, calls = make_backend(request_timeout_s=0.2, total_timeout_s=0.02), []
    async def slow(llm, timeout_s):
        await asyncio.sleep(0.05); return response(llm.name)
    install_script(backend, {name: slow for name in ("primary", "strong", "medium")}, calls)
    with pytest.raises(HTTPException) as caught: run(backend)
    assert caught.value.detail["error_category"] == "timeout" and calls == ["primary"]

@pytest.mark.parametrize("category,status", [("authentication", 401), ("invalid_request", 400)])
def test_nonrecoverable_error_fails_immediately(category, status):
    backend, calls = make_backend(), []; install_script(backend, {"primary": BackendCallError(category, "bad", status, False)}, calls)
    with pytest.raises(HTTPException) as caught: run(backend)
    assert calls == ["primary"] and caught.value.detail["error_category"] == category

def test_circuit_breaker_opens_skips_and_half_open_recovers():
    backend, calls = make_backend(), []; failure = BackendCallError("temporary_unavailable", "down", 503, True)
    install_script(backend, {"primary": [failure, failure], "strong": "ok"}, calls)
    run(backend); run(backend)
    assert backend.circuit_snapshot()["primary"]["state"] == "open"
    run(backend); assert calls.count("primary") == 2
    backend._circuits["primary"]["open_until"] = 0.0
    install_script(backend, {"primary": "ok"}, calls)
    result = run(backend)
    assert result["_llmrouter"]["selected_model"] == "primary" and backend.circuit_snapshot()["primary"]["state"] == "closed"

@pytest.mark.parametrize("status,category,recoverable", [(504,"timeout",True),(429,"rate_limit",True),(401,"authentication",False),(422,"invalid_request",False),(404,"model_unavailable",True),(503,"temporary_unavailable",True)])
def test_error_classification(status, category, recoverable):
    error = classify_backend_error(status, Exception("failure"))
    assert (error.category, error.recoverable) == (category, recoverable)


def make_stream(outcomes, calls):
    async def fake_stream(llm, messages, max_tokens, temperature, api_key):
        calls.append(llm.name)
        outcome = outcomes[llm.name]
        if isinstance(outcome, Exception):
            raise outcome
        for chunk in outcome:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk
    return fake_stream


def collect_stream(backend):
    async def collect():
        return [item async for item in backend.call_stream_with_fallback(
            "primary", [{"role": "user", "content": "x"}]
        )]
    return asyncio.run(collect())


def test_stream_falls_back_before_first_chunk():
    backend, calls = make_backend(), []
    backend._call_streaming = make_stream({
        "primary": BackendCallError("timeout", "late", 504, True),
        "strong": ["data: first\n\n", "data: [DONE]\n\n"],
    }, calls)
    chunks = collect_stream(backend)
    assert calls == ["primary", "strong"]
    assert chunks[0] == ("strong", "data: first\n\n")


def test_stream_never_switches_after_first_chunk():
    backend, calls = make_backend(), []
    backend._call_streaming = make_stream({
        "primary": ["data: first\n\n", RuntimeError("connection lost")],
    }, calls)
    with pytest.raises(RuntimeError):
        collect_stream(backend)
    assert calls == ["primary"]


def test_resilience_monitor_records_fallback_tokens_cost_and_latency():
    backend, calls = make_backend(("strong", "strong", "medium")), []
    backend.config.llms["strong"].input_price = 2.0
    backend.config.llms["strong"].output_price = 4.0
    async def fake(llm, messages, max_tokens, temperature, api_key, timeout_s):
        calls.append(llm.name)
        if llm.name == "primary":
            raise BackendCallError("timeout", "late", 504, True)
        return {"model": llm.name, "usage": {"prompt_tokens": 100, "completion_tokens": 10}, "choices": [{"message": {"content": "ok"}}]}
    backend._call_sync = fake
    run(backend)
    snap = backend.monitor.snapshot(backend.circuit_snapshot())
    assert snap["requests"] == 1 and snap["successes"] == 1
    assert snap["service_fallback_rate"] == 1.0
    assert snap["quality_escalation_rate"] == 0.0
    assert snap["error_categories"]["timeout"] == 1
    assert snap["tokens"] == {"prompt": 100, "completion": 10}
    assert snap["estimated_token_cost"] == pytest.approx((100*2+10*4)/1_000_000)
    assert snap["duplicate_calls_prevented"] == 1
    assert snap["latency_ms"]["samples"] == 1
    assert "primary" in snap["circuits"]


def test_resilience_monitor_records_all_chain_failure():
    backend, calls = make_backend(), []
    failure = BackendCallError("model_unavailable", "down", 404, True)
    install_script(backend, {name: failure for name in ("primary", "strong", "medium")}, calls)
    with pytest.raises(HTTPException):
        run(backend)
    snap = backend.monitor.snapshot(backend.circuit_snapshot())
    assert snap["requests"] == 1
    assert snap["all_chain_failure_rate"] == 1.0
    assert snap["error_categories"]["model_unavailable"] == 3


def test_resilience_metrics_route_is_read_only():
    from llmrouter.serve.server import create_app
    app = create_app(make_backend().config)
    routes = {route.path: route for route in app.routes}
    assert "/metrics/resilience" in routes
    assert "GET" in routes["/metrics/resilience"].methods
    assert "POST" not in routes["/metrics/resilience"].methods


def test_stream_monitor_captures_usage_and_cost():
    backend, calls = make_backend(), []
    backend.config.llms["primary"].input_price = 2.0
    backend.config.llms["primary"].output_price = 4.0
    backend._call_streaming = make_stream({
        "primary": [
            'data: {"choices":[{"delta":{"content":"x"}}]}\n\n',
            'data: {"choices":[],"usage":{"prompt_tokens":50,"completion_tokens":5}}\n\n',
            "data: [DONE]\n\n",
        ],
    }, calls)
    collect_stream(backend)
    snap = backend.monitor.snapshot(backend.circuit_snapshot())
    assert snap["requests"] == 1 and snap["successes"] == 1
    assert snap["tokens"] == {"prompt": 50, "completion": 5}
    assert snap["estimated_token_cost"] == pytest.approx((50*2+5*4)/1_000_000)


def test_stream_abort_is_failure_not_success():
    backend, calls = make_backend(), []
    backend._call_streaming = make_stream({
        "primary": ["data: first\n\n", RuntimeError("lost")],
    }, calls)
    with pytest.raises(RuntimeError):
        collect_stream(backend)
    snap = backend.monitor.snapshot(backend.circuit_snapshot())
    assert snap["requests"] == 1 and snap["successes"] == 0
    assert snap["all_chain_failure_rate"] == 1.0
    assert snap["stream_aborts"] == 1
    assert snap["error_categories"]["stream_abort"] == 1
