"""
LLMRouter OpenAI-Compatible Server
==================================
Provides an OpenAI-compatible API that integrates directly with OpenClaw and other frontends.

Usage:
    llmrouter serve --config serve_config.yaml

Or via code:
    from llmrouter.serve import create_app, run_server
    app = create_app(config_path="serve_config.yaml")
    run_server(app, port=8000)
"""

import asyncio
import os
import secrets
import json
import sys
import re
import threading
import time
import uuid
from typing import AsyncGenerator, Optional, Dict, Any, List

# FastAPI
try:
    from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import PlainTextResponse, StreamingResponse
    from pydantic import BaseModel, Field
    import httpx
    import uvicorn
except ImportError:
    print("Please install: pip install fastapi uvicorn httpx pydantic")
    sys.exit(1)

from .config import ServeConfig, LLMConfig
from .monitoring import OpenTelemetryExporter, ResilienceMonitor
from llmrouter.solver import IncrementalDAGSolver, NodeSpec, SQLiteNodeStore


# ============================================================
# Request/Response Models
# ============================================================

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "auto"
    messages: List[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False


class SolverNodeRequest(BaseModel):
    id: str
    semantic_key: str
    executor: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    implementation_version: str = "1"
    model_version: str = ""
    prompt_version: str = ""
    ttl_seconds: Optional[float] = None
    cacheable: bool = True


class SolverRoundRequest(BaseModel):
    session_id: str
    question: str
    nodes: List[SolverNodeRequest]


# ============================================================
# Router Integration
# ============================================================

class RouterAdapter:
    """LLMRouter adapter"""

    def __init__(self, router_name: str, config_path: Optional[str] = None):
        self.router_name = router_name
        self.config_path = config_path
        self.router = None
        self._load_router()

    def _load_router(self):
        """Load router"""
        try:
            # Add LLMRouter root directory to path
            llmrouter_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if llmrouter_root not in sys.path:
                sys.path.insert(0, llmrouter_root)

            if self.router_name == "randomrouter":
                from custom_routers.randomrouter.router import RandomRouter
                self.router = RandomRouter(self.config_path)

            elif self.router_name == "thresholdrouter":
                from custom_routers.thresholdrouter.router import ThresholdRouter
                self.router = ThresholdRouter(self.config_path)

            else:
                # Dynamic loading
                import importlib
                module = importlib.import_module(f"custom_routers.{self.router_name}.router")
                for attr in dir(module):
                    if "router" in attr.lower() and not attr.startswith("_"):
                        RouterClass = getattr(module, attr)
                        if hasattr(RouterClass, "route_single"):
                            self.router = RouterClass(self.config_path)
                            break

            print(f"[OK] Router loaded: {self.router_name}")

        except Exception as e:
            print(f"[WARN] Failed to load router '{self.router_name}': {e}")
            print("   Falling back to random selection")
            self.router = None

    def route(self, query: str, available_models: List[str]) -> str:
        """Select model"""
        if self.router is None:
            import random
            return random.choice(available_models)

        try:
            result = self.router.route_single({"query": query})
            model_name = result.get("model_name") or result.get("predicted_llm")

            # Check if model is available
            if model_name in available_models:
                return model_name

            # Fuzzy match
            for m in available_models:
                if model_name and (model_name.lower() in m.lower() or m.lower() in model_name.lower()):
                    return m

            # Fallback
            return available_models[0]

        except Exception as e:
            print(f"[Router] Error: {e}")
            return available_models[0]


# ============================================================
# LLM Backend
# ============================================================

class BackendCallError(Exception):
    """Normalized backend failure used by fallback and circuit-breaker logic."""

    def __init__(self, category: str, detail: str, status_code: int = 503, recoverable: bool = True):
        super().__init__(detail)
        self.category = category
        self.detail = detail
        self.status_code = status_code
        self.recoverable = recoverable


def classify_backend_error(status_code: Optional[int] = None, exc: Optional[Exception] = None) -> BackendCallError:
    detail = str(exc) if exc is not None else f"backend HTTP {status_code}"
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)) or status_code in (408, 504):
        return BackendCallError("timeout", detail, status_code or 504, True)
    if status_code == 429:
        return BackendCallError("rate_limit", detail, 429, True)
    if status_code in (401, 403):
        return BackendCallError("authentication", detail, status_code, False)
    if status_code in (400, 409, 415, 422):
        return BackendCallError("invalid_request", detail, status_code, False)
    if status_code == 404:
        return BackendCallError("model_unavailable", detail, 404, True)
    if status_code is not None and status_code >= 500:
        return BackendCallError("temporary_unavailable", detail, status_code, True)
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return BackendCallError("temporary_unavailable", detail, 503, True)
    return BackendCallError("invalid_request", detail, status_code or 400, False)


class LLMBackend:
    """LLM backend with recoverable fallback and per-model circuit breakers."""

    def __init__(self, config: ServeConfig):
        self.config = config
        self._circuits: Dict[str, Dict[str, Any]] = {}
        self._circuit_lock = threading.Lock()
        self.monitor = ResilienceMonitor(
            persistence_path=config.metrics_persistence_path,
            alert_thresholds=config.alert_thresholds,
            quality_cascade_enabled=config.quality_cascade_enabled,
        )
        self.otel_exporter = OpenTelemetryExporter()

    def _circuit_acquire(self, model: str, now: float) -> bool:
        with self._circuit_lock:
            state = self._circuits.setdefault(model, {"state": "closed", "failures": 0, "open_until": 0.0, "probe": False})
            if state["state"] == "open":
                if now < state["open_until"]:
                    return False
                state.update({"state": "half_open", "probe": True})
                return True
            if state["state"] == "half_open":
                if state["probe"]:
                    return False
                state["probe"] = True
            return True

    def _circuit_success(self, model: str) -> None:
        with self._circuit_lock:
            self._circuits[model] = {"state": "closed", "failures": 0, "open_until": 0.0, "probe": False}

    def _circuit_failure(self, model: str, now: float) -> None:
        with self._circuit_lock:
            state = self._circuits.setdefault(model, {"state": "closed", "failures": 0, "open_until": 0.0, "probe": False})
            state["failures"] += 1
            if state["state"] == "half_open" or state["failures"] >= self.config.circuit_failure_threshold:
                state.update({"state": "open", "open_until": now + self.config.circuit_cooldown_s, "probe": False})

    def circuit_snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._circuit_lock:
            return {name: dict(value) for name, value in self._circuits.items()}

    async def call(self, llm_name: str, messages: List[Dict], max_tokens: int = 4096,
                   temperature: Optional[float] = None, stream: bool = False):
        if llm_name not in self.config.llms:
            raise HTTPException(status_code=404, detail=f"LLM '{llm_name}' not found")
        if stream:
            return self._stream_chunks(llm_name, messages, max_tokens, temperature)
        return await self.call_with_fallback(llm_name, messages, max_tokens, temperature)

    async def _stream_chunks(self, primary: str, messages: List[Dict], max_tokens: int,
                             temperature: Optional[float]) -> AsyncGenerator:
        async for _, chunk in self.call_stream_with_fallback(
            primary, messages, max_tokens, temperature
        ):
            yield chunk

    async def call_stream_with_fallback(self, primary: str, messages: List[Dict],
                                        max_tokens: int = 4096,
                                        temperature: Optional[float] = None,
                                        fallback_models: Optional[List[str]] = None,
                                        total_timeout_s: Optional[float] = None):
        """Fallback only before the first SSE chunk is committed to the client."""
        raw_chain = [primary] + list(fallback_models if fallback_models is not None else self.config.fallback_models)
        chain = list(dict.fromkeys(raw_chain))
        duplicates_prevented = len(raw_chain) - len(chain)
        chain = [name for name in chain if name in self.config.llms]
        started = time.monotonic()
        events = []
        deadline = started + float(
            total_timeout_s if total_timeout_s is not None else self.config.total_timeout_s
        )
        last_error = None
        for model_name in chain:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                last_error = BackendCallError("timeout", "total timeout budget exhausted", 504, True)
                break
            if not self._circuit_acquire(model_name, now):
                events.append({"model": model_name, "outcome": "circuit_open"})
                continue
            llm = self.config.llms[model_name]
            api_key = llm.api_key or self.config.get_api_key(llm.provider)
            attempt_timeout = min(float(self.config.request_timeout_s), remaining)
            stream = self._call_streaming(llm, messages, max_tokens, temperature, api_key)
            last_error = None
            try:
                first_chunk = await asyncio.wait_for(anext(stream), timeout=attempt_timeout)
            except StopAsyncIteration:
                last_error = BackendCallError(
                    "model_unavailable", "stream ended before first chunk", 503, True
                )
            except BackendCallError as error:
                last_error = error
            except (asyncio.TimeoutError, httpx.TimeoutException) as error:
                last_error = classify_backend_error(exc=error)
            except Exception as error:
                last_error = classify_backend_error(exc=error)
            else:
                self._circuit_success(model_name)
                events.append({"model": model_name, "outcome": "success"})
                llm_config = self.config.llms[model_name]
                usage = {}
                def capture_usage(chunk):
                    if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
                        return
                    try:
                        payload = json.loads(chunk[6:])
                        if payload.get("usage"):
                            usage.update(payload["usage"])
                    except (ValueError, TypeError):
                        pass
                capture_usage(first_chunk)
                yield model_name, first_chunk
                try:
                    async for chunk in stream:
                        capture_usage(chunk)
                        yield model_name, chunk
                except Exception:
                    # Once a chunk is visible, switching models would corrupt the response.
                    self._circuit_failure(model_name, time.monotonic())
                    events.append({"model": model_name, "outcome": "failure", "category": "stream_abort", "recoverable": False})
                    self.monitor.record(success=False, primary=primary, final=model_name, events=events, latency_s=time.monotonic()-started, usage=usage, input_price=llm_config.input_price, output_price=llm_config.output_price, duplicates_prevented=duplicates_prevented)
                    self.monitor.record_stream_abort()
                    raise
                self.monitor.record(success=True, primary=primary, final=model_name, events=events, latency_s=time.monotonic()-started, usage=usage, input_price=llm_config.input_price, output_price=llm_config.output_price, duplicates_prevented=duplicates_prevented)
                return
            finally:
                if last_error is not None:
                    await stream.aclose()
            events.append({"model": model_name, "outcome": "failure", "category": last_error.category, "recoverable": last_error.recoverable})
            if not last_error.recoverable:
                self.monitor.record(success=False, primary=primary, final=None, events=events, latency_s=time.monotonic()-started, duplicates_prevented=duplicates_prevented)
                raise HTTPException(
                    status_code=last_error.status_code,
                    detail={"error_category": last_error.category, "message": last_error.detail},
                )
            self._circuit_failure(model_name, time.monotonic())
        error = last_error or BackendCallError(
            "model_unavailable", "no available model in fallback chain", 503, True
        )
        self.monitor.record(success=False, primary=primary, final=None, events=events, latency_s=time.monotonic()-started, duplicates_prevented=duplicates_prevented)
        raise HTTPException(
            status_code=error.status_code,
            detail={"error_category": error.category, "message": error.detail},
        )

    async def call_with_fallback(self, primary: str, messages: List[Dict], max_tokens: int = 4096,
                                 temperature: Optional[float] = None,
                                 fallback_models: Optional[List[str]] = None,
                                 total_timeout_s: Optional[float] = None) -> Dict:
        raw_chain = [primary] + list(fallback_models if fallback_models is not None else self.config.fallback_models)
        chain = list(dict.fromkeys(raw_chain))
        duplicates_prevented = len(raw_chain) - len(chain)
        chain = [name for name in chain if name in self.config.llms]
        started = time.monotonic()
        deadline = started + float(total_timeout_s if total_timeout_s is not None else self.config.total_timeout_s)
        events = []
        last_error = None
        for model_name in chain:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                last_error = BackendCallError("timeout", "total timeout budget exhausted", 504, True)
                events.append({"model": model_name, "outcome": "budget_exhausted", "category": "timeout"})
                break
            if not self._circuit_acquire(model_name, now):
                events.append({"model": model_name, "outcome": "circuit_open"})
                continue
            llm = self.config.llms[model_name]
            api_key = llm.api_key or self.config.get_api_key(llm.provider)
            attempt_timeout = min(float(self.config.request_timeout_s), remaining)
            try:
                result = await asyncio.wait_for(
                    self._call_sync(llm, messages, max_tokens, temperature, api_key, attempt_timeout),
                    timeout=attempt_timeout,
                )
                self._circuit_success(model_name)
                events.append({"model": model_name, "outcome": "success"})
                usage = result.get("usage", {})
                self.monitor.record(success=True, primary=primary, final=model_name, events=events, latency_s=time.monotonic()-started, usage=usage, input_price=llm.input_price, output_price=llm.output_price, duplicates_prevented=duplicates_prevented)
                result["_llmrouter"] = {
                    "primary_model": primary,
                    "selected_model": model_name,
                    "fallback_count": sum(event["outcome"] == "failure" for event in events),
                    "elapsed_s": time.monotonic() - started,
                    "events": events,
                }
                return result
            except BackendCallError as error:
                last_error = error
            except (asyncio.TimeoutError, httpx.TimeoutException) as error:
                last_error = classify_backend_error(exc=error)
            except Exception as error:
                last_error = classify_backend_error(exc=error)
            events.append({"model": model_name, "outcome": "failure", "category": last_error.category, "recoverable": last_error.recoverable})
            if not last_error.recoverable:
                self.monitor.record(success=False, primary=primary, final=None, events=events, latency_s=time.monotonic()-started, duplicates_prevented=duplicates_prevented)
                raise HTTPException(status_code=last_error.status_code, detail={"error_category": last_error.category, "message": last_error.detail, "events": events})
            self._circuit_failure(model_name, time.monotonic())
        status = last_error.status_code if last_error is not None else 503
        category = last_error.category if last_error is not None else "model_unavailable"
        message = last_error.detail if last_error is not None else "no available model in fallback chain"
        self.monitor.record(success=False, primary=primary, final=None, events=events, latency_s=time.monotonic()-started, duplicates_prevented=duplicates_prevented)
        raise HTTPException(status_code=status, detail={"error_category": category, "message": message, "events": events})

    async def _call_sync(self, llm: LLMConfig, messages: List[Dict], max_tokens: int,
                         temperature: Optional[float], api_key: str,
                         timeout_s: Optional[float] = None) -> Dict:
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                body = {"model": llm.model_id, "messages": messages, "max_tokens": min(max_tokens, llm.max_tokens)}
                if temperature is not None:
                    body["temperature"] = temperature
                resp = await client.post(f"{llm.base_url}/chat/completions", headers=headers, json=body, timeout=timeout_s or self.config.request_timeout_s)
                if resp.status_code != 200:
                    raise classify_backend_error(resp.status_code, Exception(resp.text[:500]))
                return resp.json()
        except BackendCallError:
            raise
        except Exception as error:
            raise classify_backend_error(exc=error) from error

    async def _call_streaming(self, llm: LLMConfig, messages: List[Dict], max_tokens: int,
                              temperature: Optional[float], api_key: str) -> AsyncGenerator:
        async with httpx.AsyncClient() as client:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            body = {"model": llm.model_id, "messages": messages, "max_tokens": min(max_tokens, llm.max_tokens), "stream": True}
            if temperature is not None:
                body["temperature"] = temperature
            async with client.stream("POST", f"{llm.base_url}/chat/completions", headers=headers, json=body, timeout=self.config.request_timeout_s) as resp:
                if resp.status_code != 200:
                    error = await resp.aread()
                    raise classify_backend_error(
                        resp.status_code, Exception(error.decode()[:200])
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"


# ============================================================
# FastAPI App
# ============================================================

def create_app(
    config: ServeConfig = None,
    config_path: str = None,
    *,
    solver_executors: Optional[Dict[str, Any]] = None,
    solver_store_path: Optional[str] = None,
) -> FastAPI:
    """Create FastAPI application"""

    if config is None and config_path:
        config = ServeConfig.from_yaml(config_path)
    elif config is None:
        config = ServeConfig()

    app = FastAPI(
        title="LLMRouter Serve",
        description="OpenAI-compatible API with intelligent routing",
        version="1.0.0"
    )

    # Initialize components
    router_adapter = RouterAdapter(
        router_name=config.router_name,
        config_path=config.router_config_path
    )
    llm_backend = LLMBackend(config)
    app.state.llm_backend = llm_backend
    app.state.router_adapter = router_adapter
    solver_store = SQLiteNodeStore(solver_store_path or ":memory:")
    dag_solver = IncrementalDAGSolver(solver_executors or {}, solver_store)
    solver_lock = threading.Lock()
    app.state.dag_solver = dag_solver

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "router": config.router_name,
            "llms": list(config.llms.keys()),
            "circuits": llm_backend.circuit_snapshot(),
        }

    def require_metrics_access(request: Request) -> None:
        if not config.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        expected = os.environ.get(config.metrics_token_env)
        if not expected:
            raise HTTPException(status_code=503, detail="Metrics access token is not configured")
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {expected}"):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/metrics/resilience")
    async def resilience_metrics(request: Request):
        require_metrics_access(request)
        snapshot = llm_backend.monitor.snapshot(llm_backend.circuit_snapshot())
        snapshot["exporters"] = {
            "prometheus": True,
            "opentelemetry": llm_backend.otel_exporter.enabled,
        }
        llm_backend.otel_exporter.export(snapshot)
        return snapshot

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics(request: Request):
        require_metrics_access(request)
        return PlainTextResponse(
            llm_backend.monitor.prometheus(llm_backend.circuit_snapshot()),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/v1/models")
    async def list_models():
        return {
            "data": [
                {"id": name, "object": "model"}
                for name in config.llms.keys()
            ]
        }

    @app.post("/v1/solver/round")
    def solve_round(request: SolverRoundRequest):
        """Execute one DAG turn against the session's complete history."""
        if not solver_executors:
            raise HTTPException(
                status_code=503,
                detail="No solver executors were registered with create_app",
            )
        try:
            specs = [
                NodeSpec(
                    id=node.id,
                    semantic_key=node.semantic_key,
                    executor=node.executor,
                    inputs=node.inputs,
                    depends_on=tuple(node.depends_on),
                    implementation_version=node.implementation_version,
                    model_version=node.model_version,
                    prompt_version=node.prompt_version,
                    ttl_seconds=node.ttl_seconds,
                    cacheable=node.cacheable,
                )
                for node in request.nodes
            ]
            with solver_lock:
                result = dag_solver.run(request.session_id, request.question, specs)
            return {
                "session_id": result.session_id,
                "round_number": result.round_number,
                "question": result.question,
                "reused_count": result.reused_count,
                "nodes": [
                    {
                        "id": node.node_id,
                        "semantic_key": node.semantic_key,
                        "status": node.status,
                        "output": node.output,
                        "fingerprint": node.fingerprint,
                        "reused_from_round": node.reused_from_round,
                    }
                    for node in result.nodes
                ],
                "outputs": result.outputs,
            }
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/solver/sessions/{session_id}/history")
    def solver_history(session_id: str):
        with solver_lock:
            history = solver_store.history(session_id)
        return {"session_id": session_id, "history": history}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatRequest):
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        # Extract user query
        user_query = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_query = m["content"][:500]
                break

        # Select model
        available_models = list(config.llms.keys())
        if request.model == "auto" or request.model not in available_models:
            selected_model = router_adapter.route(user_query, available_models)
            print(f"[Router] Query: '{user_query[:50]}...' -> {selected_model}")
        else:
            selected_model = request.model

        # Call LLM
        if request.stream:
            async def generate():
                first_chunk = True
                async for actual_model, chunk in llm_backend.call_stream_with_fallback(
                    selected_model, messages, request.max_tokens, request.temperature
                ):
                    # Add model prefix
                    if first_chunk and config.show_model_prefix and "content" in chunk:
                        try:
                            data = json.loads(chunk[6:])
                            if data.get("choices") and data["choices"][0].get("delta", {}).get("content"):
                                data["choices"][0]["delta"]["content"] = f"[{actual_model}] " + data["choices"][0]["delta"]["content"]
                                chunk = f"data: {json.dumps(data)}\n\n"
                        except:
                            pass
                        first_chunk = False
                    yield chunk

            return StreamingResponse(generate(), media_type="text/event-stream")

        else:
            result = await llm_backend.call(
                selected_model, messages, request.max_tokens,
                request.temperature, stream=False
            )

            actual_model = result.get("_llmrouter", {}).get("selected_model", selected_model)

            # Add model prefix
            if config.show_model_prefix and result.get("choices"):
                content = result["choices"][0].get("message", {}).get("content", "")
                if content:
                    result["choices"][0]["message"]["content"] = f"[{actual_model}] {content}"

            result["model"] = actual_model
            return result

    @app.websocket("/v1/chat/ws")
    async def chat_websocket(websocket: WebSocket):
        """WebSocket endpoint for real-time streaming"""
        await websocket.accept()
        try:
            # Receive request
            data = await websocket.receive_json()
            request = ChatRequest(**data)
            messages = [{"role": m.role, "content": m.content} for m in request.messages]

            # Extract user query
            user_query = ""
            for m in reversed(messages):
                if m["role"] == "user":
                    user_query = m["content"][:500]
                    break

            # Select model
            available_models = list(config.llms.keys())
            if request.model == "auto" or request.model not in available_models:
                selected_model = router_adapter.route(user_query, available_models)
                print(f"[WS Router] Query: '{user_query[:50]}...' -> {selected_model}")
            else:
                selected_model = request.model

            # Call LLM backend in streaming mode
            first_chunk = True
            async for actual_model, chunk in llm_backend.call_stream_with_fallback(
                selected_model, messages, request.max_tokens, request.temperature
            ):
                # Add model prefix
                if first_chunk and config.show_model_prefix and "content" in chunk:
                    try:
                        data_chunk = json.loads(chunk[6:])
                        if data_chunk.get("choices") and data_chunk["choices"][0].get("delta", {}).get("content"):
                            data_chunk["choices"][0]["delta"]["content"] = f"[{actual_model}] " + data_chunk["choices"][0]["delta"]["content"]
                            chunk = f"data: {json.dumps(data_chunk)}\n\n"
                    except:
                        pass
                    first_chunk = False
                
                if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                    try:
                        # Send as JSON if it's a valid data chunk
                        json_str = chunk[6:]
                        await websocket.send_json(json.loads(json_str))
                    except:
                        await websocket.send_text(chunk)
                else:
                    await websocket.send_text(chunk)

        except WebSocketDisconnect:
            print("[WS] Client disconnected")
        except Exception as e:
            print(f"[WS Error] {type(e).__name__}: {e}")
            try:
                await websocket.send_json({"error": str(e)})
            except:
                pass
        finally:
            try:
                await websocket.close()
            except:
                pass

    return app


def run_server(app: FastAPI = None, config_path: str = None, host: str = "0.0.0.0", port: int = 8000):
    """Run server"""
    if app is None:
        app = create_app(config_path=config_path)

    print(f"""
============================================================
  LLMRouter Serve
============================================================
  Server: http://{host}:{port}
  API:    http://{host}:{port}/v1/chat/completions
  Health: http://{host}:{port}/health
============================================================
""")

    uvicorn.run(app, host=host, port=port)


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLMRouter Serve")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to bind")
    args = parser.parse_args()

    run_server(config_path=args.config, host=args.host, port=args.port)
