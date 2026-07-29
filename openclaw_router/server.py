"""
OpenClaw Router Server
======================
OpenAI-compatible API server with intelligent LLM routing.

Usage:
    llmrouter serve --config configs/openclaw_example.yaml

Or directly:
    python server.py --config config.yaml
"""

import asyncio
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, deque
from pathlib import Path
from typing import AsyncGenerator, Optional, Dict, Any, List

import yaml

# Check dependencies
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    import httpx
    import uvicorn
except ImportError:
    print("Please install: pip install fastapi uvicorn httpx pydantic")
    sys.exit(1)

# Handle both relative and direct imports
try:
    from .config import OpenClawConfig, LLMConfig, MODELS_WITHOUT_SYSTEM_ROLE, MODEL_CONTEXT_LIMITS
    from .routers import OpenClawRouter, _safe_log, record_contextual_bandit_feedback
    from .media import process_multimodal_content, MediaConfig
    from .routerbench import build_routerbench, render_routerbench_markdown
    from .experience import RoutingExperienceStore, automatic_verification, utility_score as experience_utility_score
    from .scoring import utility as canonical_utility, normalized_cost as canonical_normalized_cost
    from .checkpoint import load_successful, append_record, write_progress
    from .judge_utils import extract_message_text, parse_judge_payload, load_calibration, calibrate_score
    from .experiment_protocol import (ANSWER_FORMAT_VERSION, DATA_VERSION, MAX_INPUT_CHARS, OBJECTIVE_FEASIBILITY_THRESHOLD,
        PROMPT_TEMPLATE_VERSION, build_prompt as build_experiment_prompt, objective_feasible,
        objective_score as protocol_objective_score, select_context_pilot, signature as protocol_signature,
        signature_payload as protocol_signature_payload)
except ImportError:
    from config import OpenClawConfig, LLMConfig, MODELS_WITHOUT_SYSTEM_ROLE, MODEL_CONTEXT_LIMITS
    from routers import OpenClawRouter, _safe_log, record_contextual_bandit_feedback
    from media import process_multimodal_content, MediaConfig
    from routerbench import build_routerbench, render_routerbench_markdown
    from experience import RoutingExperienceStore, automatic_verification, utility_score as experience_utility_score
    from scoring import utility as canonical_utility, normalized_cost as canonical_normalized_cost
    from checkpoint import load_successful, append_record, write_progress
    from judge_utils import extract_message_text, parse_judge_payload, load_calibration, calibrate_score
    from experiment_protocol import (ANSWER_FORMAT_VERSION, DATA_VERSION, MAX_INPUT_CHARS, OBJECTIVE_FEASIBILITY_THRESHOLD,
        PROMPT_TEMPLATE_VERSION, build_prompt as build_experiment_prompt, objective_feasible,
        objective_score as protocol_objective_score, select_context_pilot, signature as protocol_signature,
        signature_payload as protocol_signature_payload)

try:
    from llmscheduler import BatchConstraints, SchedulerType, solve_batch_assignment
except ImportError:
    BatchConstraints = None
    SchedulerType = None
    solve_batch_assignment = None


# ============================================================
# Request/Response Models
# ============================================================

class Message(BaseModel):
    role: str
    content: Optional[Any] = None  # Can be string or list (multimodal)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    model: str = "auto"
    messages: List[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    user: Optional[str] = None  # Optional user id (used for memory scoping if enabled)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    stream_options: Optional[Dict[str, Any]] = None
    solve_mode: Optional[str] = "single"
    dispatch_mode: Optional[str] = "conservative"
    verify_response: bool = False


class RouterUpdateRequest(BaseModel):
    strategy: str
    algorithm: Optional[str] = None


class ModelConfigRequest(BaseModel):
    id: str
    provider: str
    model_id: str
    base_url: str
    chat_path: str = "/chat/completions"
    auth_mode: str = "bearer"
    api_key: Optional[str] = None
    description: str = ""
    context_limit: int = 32768
    max_tokens: int = 1024
    input_price: float = 0.0
    output_price: float = 0.0
    auto_routable: bool = True
    local: Optional[bool] = None


class ExperimentRunRequest(BaseModel):
    mode: str = "simulated"
    sample_limit: int = 50
    repeats: int = 3
    judge_enabled: bool = True


class ModelTestRequest(BaseModel):
    prompt: str = "你好，请用一句话回复模型连接正常。"


class FeedbackRequest(BaseModel):
    query: str
    model: str
    rating: str = "up"
    latency_ms: float = 0.0
    fallback_count: int = 0
    reason: Optional[str] = None
    strategy: Optional[str] = None
    request_id: Optional[str] = None
    corrected_answer: Optional[str] = None
    preferred_model: Optional[str] = None
    feedback_text: Optional[str] = None


class ABCompareRequest(BaseModel):
    messages: List[Message]
    models: Optional[List[str]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 768
    user: Optional[str] = None


# ============================================================
# Message Processing
# ============================================================

def normalize_content(content: Any) -> str:
    """Convert multimodal content to plain string"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif "text" in part:
                    text_parts.append(part.get("text", ""))
            elif isinstance(part, str):
                text_parts.append(part)
        return "\n".join(text_parts)
    return str(content) if content else ""


def normalize_messages(messages: List[Dict], model_id: str = "") -> List[Dict]:
    """Normalize message format for compatibility"""
    normalized = []
    system_content = ""

    for msg in messages:
        role = msg.get("role", "user")
        content = normalize_content(msg.get("content", ""))
        normalized_msg = {"role": role, "content": content}

        if msg.get("tool_calls") is not None:
            normalized_msg["tool_calls"] = msg["tool_calls"]
        if msg.get("tool_call_id") is not None:
            normalized_msg["tool_call_id"] = msg["tool_call_id"]
        if msg.get("function_call") is not None:
            normalized_msg["function_call"] = msg["function_call"]

        if role == "system":
            system_content = content
        else:
            normalized.append(normalized_msg)

    # Handle models without system role support
    if system_content and model_id in MODELS_WITHOUT_SYSTEM_ROLE:
        if normalized and normalized[0]["role"] == "user":
            normalized[0]["content"] = f"[System Instructions]\n{system_content}\n\n[User Message]\n{normalized[0]['content']}"
        else:
            normalized.insert(0, {"role": "user", "content": f"[System Instructions]\n{system_content}"})
    elif system_content:
        normalized.insert(0, {"role": "system", "content": system_content})

    return normalized


def estimate_tokens(text: str) -> int:
    """Estimate token count (approx 4 chars = 1 token)"""
    return len(text) // 4


def adjust_max_tokens(messages: List[Dict], model_id: str, requested_max: int) -> int:
    """Adjust max_tokens based on context limit"""
    context_limit = MODEL_CONTEXT_LIMITS.get(model_id, 32768)

    input_text = " ".join(m.get("content", "") for m in messages)
    input_tokens = estimate_tokens(input_text)

    available = context_limit - input_tokens - 100
    if available < 100:
        available = 100

    result = min(requested_max, available)

    # NVIDIA API limits max_tokens to 1024
    if model_id in MODELS_WITHOUT_SYSTEM_ROLE:
        result = min(result, 1024)

    return result


def clean_response(result: Dict) -> Dict:
    """Clean response for OpenAI compatibility"""
    usage = _clean_usage(result.get("usage"))

    cleaned = {
        "id": result.get("id", ""),
        "object": result.get("object", "chat.completion"),
        "model": result.get("model", ""),
        "choices": [],
        "usage": usage
    }

    for choice in result.get("choices", []):
        cleaned_choice = {
            "index": choice.get("index", 0),
            "finish_reason": choice.get("finish_reason", "stop")
        }
        if "message" in choice:
            msg = choice["message"]
            cleaned_choice["message"] = {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content")
            }
            if msg.get("tool_calls") is not None:
                cleaned_choice["message"]["tool_calls"] = msg["tool_calls"]
            if msg.get("function_call") is not None:
                cleaned_choice["message"]["function_call"] = msg["function_call"]
            for reasoning_key in ("reasoning_content", "reasoning", "analysis"):
                if msg.get(reasoning_key) is not None:
                    cleaned_choice["message"][reasoning_key] = msg[reasoning_key]
        cleaned["choices"].append(cleaned_choice)

    return cleaned


def _message_has_tool_calls(message: Optional[Dict[str, Any]]) -> bool:
    return bool(message and (message.get("tool_calls") or message.get("function_call")))


def _delta_has_tool_calls(delta: Optional[Dict[str, Any]]) -> bool:
    return bool(delta and (delta.get("tool_calls") or delta.get("function_call")))


def _clean_usage_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_item = _clean_usage_value(item)
            if cleaned_item is not None:
                cleaned[key] = cleaned_item
        return cleaned
    if isinstance(value, list):
        cleaned = []
        for item in value:
            cleaned_item = _clean_usage_value(item)
            if cleaned_item is not None:
                cleaned.append(cleaned_item)
        return cleaned
    if value is None:
        return None
    return value


def _clean_usage(usage_raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not usage_raw:
        return {}
    if not isinstance(usage_raw, dict):
        return {}
    cleaned_usage = _clean_usage_value(usage_raw)
    return cleaned_usage if isinstance(cleaned_usage, dict) else {}


def _merge_stream_options(stream_options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(stream_options or {})
    merged.setdefault("include_usage", True)
    return merged


def clean_streaming_chunk(chunk: Dict) -> Optional[Dict]:
    """Clean streaming chunk for OpenAI compatibility"""
    choices = chunk.get("choices", [])
    usage = _clean_usage(chunk.get("usage"))
    if not choices and not usage:
        return None

    cleaned = {
        "id": chunk.get("id", ""),
        "object": chunk.get("object", "chat.completion.chunk"),
        "choices": []
    }
    if "model" in chunk:
        cleaned["model"] = chunk["model"]
    if usage:
        cleaned["usage"] = usage

    for choice in choices:
        finish_reason = choice.get("finish_reason")
        cleaned_choice = {
            "index": choice.get("index", 0),
            "finish_reason": finish_reason
        }

        if "delta" in choice:
            delta = choice["delta"]
            if finish_reason == "stop":
                cleaned_choice["delta"] = {}
            else:
                cleaned_delta = {}
                if "role" in delta:
                    cleaned_delta["role"] = delta["role"]
                if "content" in delta:
                    cleaned_delta["content"] = delta["content"]
                if "tool_calls" in delta:
                    cleaned_delta["tool_calls"] = delta["tool_calls"]
                if "function_call" in delta:
                    cleaned_delta["function_call"] = delta["function_call"]
                cleaned_choice["delta"] = cleaned_delta
        else:
            cleaned_choice["delta"] = {}

        cleaned["choices"].append(cleaned_choice)

    return cleaned


LOCAL_PROVIDER_HINTS = {
    "sglang",
    "vllm",
    "llama.cpp",
    "llama_cpp",
    "lmstudio",
    "lm_studio",
    "huggingface_cli",
}


def _is_local_base_url(base_url: str) -> bool:
    if not base_url:
        return False
    lower = base_url.lower()
    return (
        "localhost" in lower
        or "127.0.0.1" in lower
        or lower.startswith("http://0.0.0.0")
    )


def _resolve_auth_mode(provider: str, base_url: str, auth_mode: str = "auto", local: Optional[bool] = None) -> str:
    mode = (auth_mode or "auto").strip().lower()
    if mode in ("none", "bearer"):
        return mode

    provider_norm = (provider or "").strip().lower()
    is_local = bool(local) if local is not None else _is_local_base_url(base_url)
    if provider_norm in LOCAL_PROVIDER_HINTS or is_local:
        return "none"
    return "bearer"


def _build_chat_url(base_url: str, chat_path: str) -> str:
    path = (chat_path or "/chat/completions").strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"{(base_url or '').rstrip('/')}{path}"


# ============================================================
# LLM Backend
# ============================================================

class LLMBackend:
    """LLM API caller"""

    def __init__(self, config: OpenClawConfig):
        self.config = config

    @staticmethod
    def _timeout_for(llm: LLMConfig) -> float:
        provider = (llm.provider or "").lower()
        model_id = (llm.model_id or "").lower()
        if provider == "doubao" or "doubao" in model_id:
            return 35.0
        if provider == "zhipu" or "glm" in model_id:
            return 45.0
        return 90.0

    async def call(self, llm_name: str, messages: List[Dict], max_tokens: int = 4096,
                   temperature: Optional[float] = None, stream: bool = False,
                   tools: Optional[List[Dict[str, Any]]] = None,
                   tool_choice: Optional[Any] = None,
                   stream_options: Optional[Dict[str, Any]] = None):
        """Call LLM API"""
        if llm_name not in self.config.llms:
            raise HTTPException(status_code=404, detail=f"LLM '{llm_name}' not found")

        llm_config = self.config.llms[llm_name]
        api_key = self.config.get_api_key(llm_config.provider, llm_config)

        if stream:
            return self._call_streaming(
                llm_config,
                messages,
                max_tokens,
                temperature,
                api_key,
                tools,
                tool_choice,
                stream_options,
            )
        else:
            return await self._call_sync(llm_config, messages, max_tokens, temperature, api_key, tools, tool_choice)

    async def _call_sync(self, llm: LLMConfig, messages: List[Dict], max_tokens: int,
                         temperature: Optional[float], api_key: Optional[str],
                         tools: Optional[List[Dict[str, Any]]] = None,
                         tool_choice: Optional[Any] = None) -> Dict:
        """Synchronous API call"""
        normalized = normalize_messages(messages, llm.model_id)
        requested_max = min(int(max_tokens or llm.max_tokens), int(llm.max_tokens or max_tokens or 1024))
        adjusted_max = adjust_max_tokens(normalized, llm.model_id, requested_max)
        auth_mode = _resolve_auth_mode(llm.provider, llm.base_url, llm.auth_mode, llm.local)
        chat_url = _build_chat_url(llm.base_url, llm.chat_path)


        async with httpx.AsyncClient() as client:
            headers = {"Content-Type": "application/json"}
            if auth_mode == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            body = {
                "model": llm.model_id,
                "messages": normalized,
                "max_tokens": adjusted_max,
            }
            if temperature is not None:
                body["temperature"] = temperature
            if tools is not None:
                body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice

            resp = await client.post(
                chat_url,
                headers=headers,
                json=body,
                timeout=self._timeout_for(llm)
            )

            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])

            result = resp.json()
            return clean_response(result)

    async def _call_streaming(self, llm: LLMConfig, messages: List[Dict], max_tokens: int,
                          temperature: Optional[float], api_key: Optional[str],
                          tools: Optional[List[Dict[str, Any]]] = None,
                          tool_choice: Optional[Any] = None,
                          stream_options: Optional[Dict[str, Any]] = None) -> AsyncGenerator:
        """Streaming API call"""
        normalized = normalize_messages(messages, llm.model_id)
        requested_max = min(int(max_tokens or llm.max_tokens), int(llm.max_tokens or max_tokens or 1024))
        adjusted_max = adjust_max_tokens(normalized, llm.model_id, requested_max)
        auth_mode = _resolve_auth_mode(llm.provider, llm.base_url, llm.auth_mode, llm.local)
        chat_url = _build_chat_url(llm.base_url, llm.chat_path)

        async with httpx.AsyncClient() as client:
            headers = {"Content-Type": "application/json"}
            if auth_mode == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            body = {
                "model": llm.model_id,
                "messages": normalized,
                "max_tokens": adjusted_max,
                "stream": True,
                "stream_options": _merge_stream_options(stream_options),
            }
            if temperature is not None:
                body["temperature"] = temperature
            if tools is not None:
                body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice

            async with client.stream(
                "POST",
                chat_url,
                headers=headers,
                json=body,
                timeout=self._timeout_for(llm)
            ) as resp:
                if resp.status_code != 200:
                    error = await resp.aread()
                    print(f"[Backend Streaming] Error {resp.status_code}: {error.decode()[:200]}")
                    yield f'data: {json.dumps({"error": error.decode()[:200]})}\n\n'
                    return

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"


# ============================================================
# FastAPI App Factory
# ============================================================

def create_app(config: OpenClawConfig = None, config_path: str = None) -> FastAPI:
    """Create FastAPI application"""
    if config is None and config_path:
        config = OpenClawConfig.from_yaml(config_path)
    elif config is None:
        config = OpenClawConfig()

    app = FastAPI(
        title="OpenClaw Router",
        description="OpenAI-compatible API with intelligent LLM routing",
        version="1.0.0"
    )
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    # Initialize components
    router = OpenClawRouter(config)
    backend = LLMBackend(config)
    experience_store = RoutingExperienceStore(Path.cwd() / "run_logs" / "routing_experience.jsonl")
    judge_calibration = load_calibration(Path.cwd() / "configs" / "judge_calibration.json")
    request_logs = deque(maxlen=200)
    model_failures: Dict[str, Dict[str, Any]] = {}
    metrics = {
        "requests": 0,
        "successes": 0,
        "failures": 0,
        "fallbacks": 0,
        "total_latency_ms": 0.0,
        "model_usage": Counter(),
    }
    experiment_state: Dict[str, Any] = {
        "last_run": None,
        "runs": 0,
    }

    experiment_cache_path = Path.cwd() / "run_logs" / "llmrouter_experiment_last.json"
    legacy_real_experiment_path = Path.cwd() / "run_logs" / "llmrouter_real_experiment_last.json"

    def persist_experiment_run(payload: Dict[str, Any], *, legacy_real: bool = False) -> None:
        experiment_cache_path.parent.mkdir(parents=True, exist_ok=True)
        experiment_cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if legacy_real:
            legacy_real_experiment_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def load_experiment_cache() -> None:
        for path in (experiment_cache_path, legacy_real_experiment_path):
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload.get("strategies"):
                    experiment_state["last_run"] = payload
                    experiment_state["runs"] = 1
                    if path != experiment_cache_path:
                        persist_experiment_run(payload)
                    return
            except Exception as error:
                _safe_log(f"[Experiment] Failed to load cached result {path}: {error}")

    load_experiment_cache()
    service_strategy_catalog = [
        {
            "id": "llmrouter",
            "name": "算法路由",
            "description": "调用算法层路由器，根据问题动态选择模型。",
            "available": True,
        },
        {
            "id": "constrained_multi_objective",
            "name": "约束多目标路由",
            "description": "先按任务场景约束过滤候选模型，再用 Pareto 前沿和综合效用选择模型。",
            "available": True,
            "note": "无需训练；适合展示质量、成本、延迟和可靠性的权衡过程。",
        },
        {
            "id": "contextual_bandit",
            "name": "在线反馈路由",
            "description": "根据任务上下文、模型先验能力、历史成功率和调用反馈动态调整模型选择。",
            "available": True,
            "note": "适合作为论文中的在线学习策略：真实调用后会更新 reward、success rate 和探索项。",
        },
        {
            "id": "cascading_bandit_pareto",
            "name": "级联 Bandit Pareto 路由",
            "description": "先用低成本 Pareto 候选模型起步，根据置信度、不确定性和失败情况升级到更强模型。",
            "available": True,
            "note": "适合作为论文主方法：把级联调用、在线反馈和多目标 Pareto 选择合并到一个自适应路由器。",
        },
        {
            "id": "latency_sla_pareto",
            "name": "Latency-SLA Pareto 路由",
            "description": "先满足延迟、成本、质量和可靠性 SLA 约束，再在 Pareto 前沿中选择最优模型。",
            "available": True,
            "note": "适合作为理论贡献：把服务等级约束和多目标 Pareto 决策结合起来。",
        },
        {
            "id": "finance_risk_adaptive",
            "name": "金融风险自适应路由",
            "description": "面向金融、审计和合规任务，使用硬约束、非线性效用和 Pareto 前沿选择模型。",
            "available": True,
            "note": "适合作为论文主方法：避免简单线性加权，按风险等级动态调整质量、可靠性、成本和延迟惩罚。",
        },
        {
            "id": "rules",
            "name": "规则路由",
            "description": "根据关键词规则和默认规则选择模型。",
            "available": True,
        },
        {
            "id": "random",
            "name": "随机路由",
            "description": "按随机或配置权重抽取模型。",
            "available": True,
        },
        {
            "id": "round_robin",
            "name": "轮询路由",
            "description": "按照模型列表顺序轮流分配请求。",
            "available": True,
        },
        {
            "id": "llm",
            "name": "LLM 裁判路由",
            "description": "调用一个路由裁判模型阅读问题后作出选择。",
            "available": True,
            "note": "无需训练；当前使用 DeepSeek Chat 作为路由裁判模型。",
        },
    ]
    algorithm_catalog = [
        {
            "id": "graphrouter",
            "name": "GraphRouter",
            "description": "图神经网络，根据问题与模型关系进行匹配。",
            "config": "configs/model_config_test/multi_provider_graphrouter.yaml",
        },
        {
            "id": "smallest_llm",
            "name": "SmallestLLM",
            "description": "始终选择参数规模最小的模型，适合作为低成本基线。",
            "config": "configs/model_config_test/multi_provider_smallest_llm.yaml",
        },
        {
            "id": "largest_llm",
            "name": "LargestLLM",
            "description": "始终选择参数规模最大的模型，适合作为质量基线。",
            "config": "configs/model_config_test/largest_llm.yaml",
        },
        {
            "id": "knnrouter",
            "name": "KNNRouter",
            "description": "根据相似历史问题的近邻结果选择模型。",
            "config": "configs/model_config_test/knnrouter.yaml",
        },
        {
            "id": "svmrouter",
            "name": "SVMRouter",
            "description": "使用支持向量机对问题进行模型分类。",
            "config": "configs/model_config_test/svmrouter.yaml",
        },
        {
            "id": "mlprouter",
            "name": "MLPRouter",
            "description": "使用多层感知机预测最合适的模型。",
            "config": "configs/model_config_test/mlprouter.yaml",
        },
        {
            "id": "mfrouter",
            "name": "MFRouter",
            "description": "使用矩阵分解学习问题与模型的匹配关系。",
            "config": "configs/model_config_test/mfrouter.yaml",
        },
        {
            "id": "elorouter",
            "name": "EloRouter",
            "description": "根据历史对战结果和 Elo 排名选择模型。",
            "config": "configs/model_config_test/elorouter.yaml",
        },
        {
            "id": "dcrouter",
            "name": "RouterDC",
            "description": "使用双重对比学习匹配问题和模型。",
            "config": "configs/model_config_test/dcrouter.yaml",
        },
        {
            "id": "hybrid_llm",
            "name": "HybridLLM",
            "description": "在小模型与大模型之间进行成本和能力权衡。",
            "config": "configs/model_config_test/hybrid_llm.yaml",
        },
        {
            "id": "automixrouter",
            "name": "AutoMix",
            "description": "先尝试小模型，再根据置信度升级到大模型。",
            "config": "configs/model_config_test/automix.yaml",
        },
        {
            "id": "causallm_router",
            "name": "CausalLMRouter",
            "description": "让经过训练的因果语言模型直接生成目标模型名。",
            "config": "configs/model_config_test/causallm_router.yaml",
        },
        {
            "id": "gmtrouter",
            "name": "GMTRouter",
            "description": "面向用户、会话和多轮关系的图路由器。",
            "config": "configs/model_config_test/gmtrouter.yaml",
        },
        {
            "id": "personalizedrouter",
            "name": "PersonalizedRouter",
            "description": "结合用户偏好进行个性化模型选择。",
            "config": "configs/model_config_test/personalizedrouter.yaml",
        },
        {
            "id": "knnmultiroundrouter",
            "name": "KNNMultiRoundRouter",
            "description": "拆分复杂任务，并使用 KNN 为子问题路由。",
            "config": "configs/model_config_test/knnmultiroundrouter.yaml",
        },
        {
            "id": "llmmultiroundrouter",
            "name": "LLMMultiRoundRouter",
            "description": "使用大模型拆解任务、分步路由和汇总结果。",
            "config": "configs/model_config_test/llmmultiroundrouter.yaml",
        },
        {
            "id": "router_r1",
            "name": "RouterR1",
            "description": "智能体式多步推理路由，需要额外模型和运行环境。",
            "config": "configs/model_config_test/router_r1.yaml",
        },
        {
            "id": "randomrouter",
            "name": "RandomRouter 插件",
            "description": "项目插件示例，随机选择候选模型。",
            "config": "custom_routers/randomrouter/config.yaml",
        },
        {
            "id": "thresholdrouter",
            "name": "ThresholdRouter 插件",
            "description": "按问题难度阈值选择小模型或大模型。",
            "config": None,
        },
    ]
    native_algorithm_ids = {"graphrouter"}
    router_configs = {
        item["id"]: item["config"]
        for item in algorithm_catalog
        if item.get("config")
    }
    try:
        from llmrouter.cli.router_inference import ROUTER_REGISTRY as _ROUTER_REGISTRY

        registered_algorithm_ids = set(_ROUTER_REGISTRY.keys())
    except Exception:
        registered_algorithm_ids = set()

    def algorithm_config_exists(algorithm_id: str) -> bool:
        config_path = router_configs.get(algorithm_id)
        return bool(config_path and (Path.cwd() / config_path).is_file())

    routerdc_for_benchmark = "dcrouter" in registered_algorithm_ids and algorithm_config_exists("dcrouter")
    mfrouter_for_benchmark = "mfrouter" in registered_algorithm_ids and algorithm_config_exists("mfrouter")
    contrastive_representative_id = (
        "dcrouter"
        if routerdc_for_benchmark
        else "mfrouter"
        if mfrouter_for_benchmark
        else "dcrouter"
    )
    contrastive_representative_name = "RouterDC" if contrastive_representative_id == "dcrouter" else "MFRouter"

    def algorithm_availability(item: Dict[str, Any]) -> Dict[str, Any]:
        config_path = item.get("config")
        config_exists = bool(config_path and (Path.cwd() / config_path).is_file())
        registered = False
        error = None
        try:
            from llmrouter.cli.router_inference import ROUTER_REGISTRY

            registered = item["id"] in ROUTER_REGISTRY
        except Exception as exc:
            error = str(exc)

        native = item["id"] in native_algorithm_ids and registered and config_exists
        available = True
        note = None
        if native:
            note = "当前使用项目原生算法和已训练权重。"
        elif item["id"] in {"router_r1", "causallm_router"}:
            note = "当前使用兼容模式；原生模式通常需要额外模型、GPU 或运行依赖。"
        elif item["id"] in {"knnmultiroundrouter", "llmmultiroundrouter"}:
            note = "当前使用兼容模式；原生多轮模式会执行任务拆解并产生更高延迟。"
        elif not registered or not config_exists:
            note = "当前使用兼容模式；缺少原生注册、配置、数据或训练权重。"
        else:
            note = "当前使用兼容模式；待准备匹配当前四个模型的训练数据后可切换原生模式。"

        return {
            **item,
            "available": available,
            "execution_mode": "native" if native else "compatibility",
            "note": note,
            "registry_error": error,
        }

    def model_health_payload(model_name: str) -> Dict[str, Any]:
        failure = model_failures.get(model_name)
        if not failure:
            return {"status": "healthy", "failures": 0, "last_error": None}
        cooldown_until = float(failure.get("cooldown_until", 0))
        cooling_down = cooldown_until > time.time()
        return {
            "status": "cooldown" if cooling_down else "retry",
            "failures": int(failure.get("count", 0)),
            "last_error": failure.get("error"),
            "cooldown_until": cooldown_until if cooling_down else None,
        }

    def healthy_models() -> List[str]:
        result = []
        now = time.time()
        for name, llm in config.llms.items():
            if not getattr(llm, "auto_routable", True):
                continue
            failure = model_failures.get(name)
            if not failure or float(failure.get("cooldown_until", 0)) <= now:
                result.append(name)
        return result or [
            name for name, llm in config.llms.items()
            if getattr(llm, "auto_routable", True)
        ] or list(config.llms.keys())

    def mark_model_failure(model_name: str, error: Exception) -> str:
        detail = getattr(error, "detail", str(error))
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        if not detail:
            detail = f"{type(error).__name__}: 模型调用超时或连接被中断"
        failure = model_failures.setdefault(model_name, {"count": 0})
        failure["count"] = int(failure.get("count", 0)) + 1
        failure["error"] = detail[:500]
        failure["last_failed_at"] = time.time()
        failure["cooldown_until"] = time.time() + 600
        return detail

    def fallback_order(
        selected_model: str,
        candidate_scores: Dict[str, float],
        models: List[str],
    ) -> List[str]:
        remaining = [model for model in models if model != selected_model]
        return sorted(
            remaining,
            key=lambda model: float(candidate_scores.get(model, 0.0)),
            reverse=True,
        )

    def response_text(result: Dict[str, Any]) -> str:
        choices = result.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content") or ""

    def merge_usage(*items: Dict[str, Any]) -> Dict[str, int]:
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for item in items:
            for key in usage:
                usage[key] += int((item.get("usage") or {}).get(key) or 0)
        return usage

    def is_complex_query(query: str) -> bool:
        query_lower = query.lower()
        complex_words = (
            "分析", "比较", "方案", "报告", "规划", "审计", "风险", "原因",
            "改进", "评估", "流程", "多步骤", "复杂", "为什么", "如何",
            "compare", "analyze", "plan", "report", "risk",
        )
        return len(query) > 70 or any(word in query_lower for word in complex_words)

    def task_kind(query: str) -> str:
        query_lower = query.lower()
        if any(word in query_lower for word in ("代码", "python", "java", "函数", "算法", "debug", "sql")):
            return "code"
        if any(word in query_lower for word in ("审计", "合规", "风险", "控制", "制度")):
            return "audit"
        if any(word in query_lower for word in ("演讲", "文案", "通知", "创作", "作文")):
            return "writing"
        if any(word in query_lower for word in ("比较", "为什么", "推理", "证明", "计算")):
            return "reasoning"
        return "general"

    def static_plan(query: str) -> List[Dict[str, str]]:
        return [
            {
                "name": "理解与拆解",
                "goal": "先识别用户问题的任务类型、关键约束、风险点和需要回答的核心内容。",
                "query": f"请只做问题分析，不要直接给最终答案。用户问题：{query}",
            },
            {
                "name": "主体求解",
                "goal": "根据上一步分析生成主体答案，要求内容准确、结构清晰。",
                "query": f"请基于用户问题生成主体答案。用户问题：{query}",
            },
            {
                "name": "检查与润色",
                "goal": "检查答案是否遗漏重点、是否需要补充风险或边界说明，并给出可直接展示的表达。",
                "query": f"请检查并润色这个问题的回答，确保适合给用户展示。用户问题：{query}",
            },
        ]

    def dynamic_plan(query: str) -> List[Dict[str, str]]:
        kind = task_kind(query)
        if kind == "audit":
            return [
                {"name": "风险识别", "goal": "识别场景中的主要风险点。", "query": f"围绕审计合规场景识别核心风险：{query}"},
                {"name": "原因分析", "goal": "解释风险产生的原因和影响路径。", "query": f"分析这些风险产生的原因和可能影响：{query}"},
                {"name": "控制措施", "goal": "提出可执行的控制、验证和追踪措施。", "query": f"提出降低风险的控制措施和落地方案：{query}"},
                {"name": "汇报化整理", "goal": "整理成适合汇报或文档使用的结构。", "query": f"把分析结果整理成清晰的汇报结构：{query}"},
            ]
        if kind == "code":
            return [
                {"name": "需求拆解", "goal": "确认输入、输出、边界条件和复杂度要求。", "query": f"分析这道代码任务的需求和边界条件：{query}"},
                {"name": "代码生成", "goal": "编写可运行代码并加必要说明。", "query": f"请编写可运行代码：{query}"},
                {"name": "复杂度与验证", "goal": "解释时间/空间复杂度，并给出测试样例。", "query": f"解释代码复杂度并给出测试用例：{query}"},
            ]
        if kind == "writing":
            return [
                {"name": "意图定位", "goal": "确定受众、语气和内容重点。", "query": f"分析这段写作任务的受众、语气和重点：{query}"},
                {"name": "内容生成", "goal": "生成完整正文。", "query": f"根据要求生成正文：{query}"},
                {"name": "表达润色", "goal": "优化语言流畅度和展示效果。", "query": f"润色并优化这段内容，使其自然清晰：{query}"},
            ]
        return [
            {"name": "问题拆解", "goal": "拆出要回答的关键点。", "query": f"拆解这个复杂问题的关键点：{query}"},
            {"name": "分点求解", "goal": "分别回答关键点。", "query": f"分点回答这个问题：{query}"},
            {"name": "综合归纳", "goal": "把多个部分合并成最终答案。", "query": f"综合整理最终答案：{query}"},
        ]

    def annotate_dependencies(plan: List[Dict[str, Any]], kind: str, dispatch_mode: str) -> List[Dict[str, Any]]:
        annotated = [{**step, "depends_on": []} for step in plan]
        if dispatch_mode == "fast":
            return annotated
        if dispatch_mode == "conservative":
            for index in range(1, len(annotated)):
                annotated[index]["depends_on"] = [index - 1]
            return annotated
        if kind == "audit" and len(annotated) >= 4:
            annotated[0]["depends_on"] = []
            annotated[1]["depends_on"] = []
            annotated[2]["depends_on"] = [0, 1]
            annotated[3]["depends_on"] = [2]
            return annotated
        for index in range(1, len(annotated)):
            annotated[index]["depends_on"] = [index - 1]
        return annotated

    def dispatch_profile(dispatch_mode: str) -> Dict[str, Any]:
        profiles = {
            "conservative": {
                "label": "串行",
                "concurrency": 1,
                "step_timeout": 75,
                "step_tokens": 900,
                "candidate_limit": None,
                "description": "全部步骤串行执行，优先保证上下文连续和结果稳定。",
            },
            "balanced": {
                "label": "DAG图",
                "concurrency": 2,
                "step_timeout": 45,
                "step_tokens": 700,
                "candidate_limit": None,
                "description": "按子任务依赖关系分批并行，兼顾速度、成本和质量。",
            },
            "fast": {
                "label": "并行",
                "concurrency": 3,
                "step_timeout": 18,
                "step_tokens": 320,
                "candidate_limit": 2,
                "description": "尽量并行执行，优先选择低延迟模型，并限制输出长度和等待时间。",
            },
        }
        return profiles.get(dispatch_mode, profiles["conservative"])

    def budget_aware_candidates(models: List[str], dispatch_mode: str) -> List[str]:
        if dispatch_mode != "fast":
            return models
        def score_model(name: str) -> float:
            profile = model_profile(name)
            cost = float(profile.get("cost", 0.5))
            latency = float(profile.get("latency", 0.5))
            reliability = float(profile.get("reliability", 0.7))
            quality = float(profile.get("quality", 0.7))
            return quality * 0.05 + (1.0 - cost) * 0.25 + (1.0 - latency) * 0.55 + reliability * 0.15

        speed_pool = [
            name for name in models
            if float(model_profile(name).get("latency", 0.5)) < 0.75
            and float(model_profile(name).get("cost", 0.5)) < 0.75
        ]
        preferred = sorted(speed_pool or models, key=score_model, reverse=True)
        limit = int(dispatch_profile(dispatch_mode).get("candidate_limit") or len(preferred))
        return preferred[:limit] or models

    def dependency_ready_steps(plan: List[Dict[str, Any]], completed: set[int], started: set[int]) -> List[int]:
        ready = []
        for index, step in enumerate(plan):
            if index in completed or index in started:
                continue
            deps = step.get("depends_on", [])
            if all(dep in completed for dep in deps):
                ready.append(index)
        return ready

    async def call_step_with_fallback(
        step_query: str,
        step_messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: Optional[float],
        user: Optional[str],
        route_candidates: List[str],
        local_replan: bool = False,
        step_timeout: Optional[float] = None,
        dispatch_mode: str = "conservative",
    ) -> Dict[str, Any]:
        routing = await router.select_model_details(
            step_query,
            user=user,
            available_models=route_candidates,
        )
        selected = routing["selected_model"]
        candidates = [selected] + fallback_order(
            selected,
            routing.get("candidate_scores", {}),
            route_candidates,
        )
        attempted = []
        fallbacks = []
        last_error = None
        for candidate in candidates:
            attempted.append(candidate)
            try:
                call_task = backend.call(
                    candidate,
                    step_messages,
                    max_tokens,
                    temperature,
                    stream=False,
                )
                result = await asyncio.wait_for(call_task, timeout=step_timeout) if step_timeout else await call_task
                return {
                    "ok": True,
                    "model": candidate,
                    "initial_model": selected,
                    "attempted_models": attempted,
                    "fallbacks": fallbacks,
                    "routing": routing,
                    "result": result,
                    "content": response_text(result),
                    "local_replan": local_replan and candidate != selected,
                    "timed_out": False,
                    "dispatch_mode": dispatch_mode,
                }
            except Exception as error:
                last_error = error
                if isinstance(error, asyncio.TimeoutError):
                    error_detail = f"步骤超过 {step_timeout} 秒未返回，触发超时降级。"
                else:
                    error_detail = mark_model_failure(candidate, error)
                fallbacks.append({"model": candidate, "error": error_detail})
                _safe_log(f"[MultiStep Fallback] {candidate} failed: {error_detail}")
        return {
            "ok": False,
            "model": selected,
            "initial_model": selected,
            "attempted_models": attempted,
            "fallbacks": fallbacks,
            "routing": routing,
            "result": None,
            "content": "",
            "error": str(getattr(last_error, "detail", last_error)),
            "local_replan": local_replan,
            "timed_out": isinstance(last_error, asyncio.TimeoutError),
            "dispatch_mode": dispatch_mode,
        }

    async def solve_complex_request(
        solve_mode: str,
        original_query: str,
        base_messages: List[Dict[str, Any]],
        request: ChatRequest,
        route_candidates: List[str],
    ) -> Dict[str, Any]:
        kind = task_kind(original_query)
        dispatch_mode = (request.dispatch_mode or "conservative").strip().lower()
        if dispatch_mode not in {"conservative", "balanced", "fast"}:
            dispatch_mode = "conservative"
        if solve_mode == "static_multi":
            dispatch_mode = "conservative"
        profile = dispatch_profile(dispatch_mode)
        mode_label = "静态多轮路由" if solve_mode == "static_multi" else f"动态子任务调度 · {profile['label']}"
        plan = static_plan(original_query) if solve_mode == "static_multi" else dynamic_plan(original_query)
        if solve_mode == "dynamic_subtasks":
            plan = annotate_dependencies(plan, kind, dispatch_mode)
        else:
            plan = annotate_dependencies(plan, kind, "conservative")
        active_candidates = budget_aware_candidates(route_candidates, dispatch_mode)
        steps = []
        usage_items = []
        completed_outputs: Dict[int, Dict[str, Any]] = {}
        step_token_limit = min(int(request.max_tokens or 1024), int(profile["step_tokens"]))

        async def execute_step(index: int, step: Dict[str, Any], prior_items: List[Dict[str, Any]], parallel_group: int) -> Dict[str, Any]:
            concise_instruction = "极速模式下请控制在 200 字以内，只给关键结论。" if dispatch_mode == "fast" else ""
            prior_text = "\n\n".join(
                f"已完成步骤：{item['name']}\n模型：{item['model']}\n结果：{item['content'][:1200]}"
                for item in prior_items
            )
            prompt = (
                f"你正在执行复杂问题求解流程：{mode_label}。\n"
                f"原始问题：{original_query}\n"
                f"当前步骤：{step['name']}\n"
                f"步骤目标：{step['goal']}\n"
                f"调度策略：{profile['description']}\n"
                f"{'已得到的中间结果：' + prior_text if prior_text else ''}\n"
                f"请只完成当前步骤，不要编造没有依据的信息。{concise_instruction}"
            )
            step_messages = [{"role": "system", "content": "你是一个严谨的多模型协同求解助手。"}]
            step_messages.append({"role": "user", "content": prompt})

            try:
                step_result = await call_step_with_fallback(
                    step["query"],
                    step_messages,
                    step_token_limit,
                    request.temperature,
                    request.user,
                    active_candidates,
                    local_replan=solve_mode == "dynamic_subtasks",
                    step_timeout=float(profile["step_timeout"]),
                    dispatch_mode=dispatch_mode,
                )
            except Exception as error:
                step_result = {
                    "ok": False,
                    "model": None,
                    "initial_model": None,
                    "attempted_models": [],
                    "fallbacks": [],
                    "routing": {},
                    "result": None,
                    "content": "",
                    "error": str(getattr(error, "detail", error)),
                    "local_replan": False,
                    "timed_out": isinstance(error, asyncio.TimeoutError),
                    "dispatch_mode": dispatch_mode,
                }

            if step_result.get("result"):
                usage_items.append(step_result["result"])
            step_payload = {
                "index": index + 1,
                "name": step["name"],
                "goal": step["goal"],
                "depends_on": [dep + 1 for dep in step.get("depends_on", [])],
                "parallel_group": parallel_group,
                "dispatch_mode": dispatch_mode,
                "dispatch_mode_label": profile["label"],
                "selected_model": step_result.get("model"),
                "initial_model": step_result.get("initial_model"),
                "attempted_models": step_result.get("attempted_models", []),
                "fallbacks": step_result.get("fallbacks", []),
                "candidate_scores": step_result.get("routing", {}).get("candidate_scores", {}),
                "status": "success" if step_result.get("ok") else ("timeout" if step_result.get("timed_out") else "failed"),
                "local_replan": bool(step_result.get("local_replan")),
                "excerpt": (step_result.get("content") or step_result.get("error") or "")[:600],
            }
            output = None
            if step_result.get("ok"):
                output = {
                    "name": step["name"],
                    "model": step_result.get("model"),
                    "content": step_result.get("content", ""),
                }
            return {"index": index, "payload": step_payload, "output": output}

        if solve_mode == "static_multi":
            for index, step in enumerate(plan):
                prior_items = [completed_outputs[i] for i in sorted(completed_outputs)]
                result = await execute_step(index, step, prior_items, index + 1)
                steps.append(result["payload"])
                if result["output"]:
                    completed_outputs[index] = result["output"]
        else:
            completed: set[int] = set()
            started: set[int] = set()
            parallel_group = 0
            while len(completed) < len(plan):
                ready = dependency_ready_steps(plan, completed, started)
                if not ready:
                    blocked = [
                        index for index in range(len(plan))
                        if index not in completed and index not in started
                    ]
                    for index in blocked:
                        step = plan[index]
                        steps.append({
                            "index": index + 1,
                            "name": step["name"],
                            "goal": step["goal"],
                            "depends_on": [dep + 1 for dep in step.get("depends_on", [])],
                            "parallel_group": parallel_group + 1,
                            "dispatch_mode": dispatch_mode,
                            "dispatch_mode_label": profile["label"],
                            "selected_model": None,
                            "initial_model": None,
                            "attempted_models": [],
                            "fallbacks": [],
                            "candidate_scores": {},
                            "status": "blocked",
                            "local_replan": False,
                            "excerpt": "前置步骤未完成，当前子任务被阻塞。",
                        })
                        completed.add(index)
                    break
                batch = ready[: int(profile["concurrency"])]
                started.update(batch)
                parallel_group += 1
                prior_items = [completed_outputs[i] for i in sorted(completed_outputs)]
                batch_results = await asyncio.gather(
                    *(execute_step(index, plan[index], prior_items, parallel_group) for index in batch),
                    return_exceptions=True,
                )
                for index, item in zip(batch, batch_results):
                    if isinstance(item, Exception):
                        step = plan[index]
                        steps.append({
                            "index": index + 1,
                            "name": step["name"],
                            "goal": step["goal"],
                            "depends_on": [dep + 1 for dep in step.get("depends_on", [])],
                            "parallel_group": parallel_group,
                            "dispatch_mode": dispatch_mode,
                            "dispatch_mode_label": profile["label"],
                            "selected_model": None,
                            "initial_model": None,
                            "attempted_models": [],
                            "fallbacks": [],
                            "candidate_scores": {},
                            "status": "failed",
                            "local_replan": False,
                            "excerpt": str(getattr(item, "detail", item))[:600],
                        })
                    else:
                        steps.append(item["payload"])
                        if item["output"]:
                            completed_outputs[index] = item["output"]
                    completed.add(index)

        partial_outputs = [completed_outputs[i] for i in sorted(completed_outputs)]
        aggregate_prompt = (
            f"请把下面多个步骤的结果聚合成一个完整、自然、可直接给用户看的最终答案。"
            f"{'控制在 600 字以内，优先给结论和要点。' if dispatch_mode == 'fast' else ''}\n"
            f"原始问题：{original_query}\n\n"
            + "\n\n".join(
                f"步骤：{item['name']}\n执行模型：{item['model']}\n中间结果：{item['content']}"
                for item in partial_outputs
            )
            if partial_outputs
            else f"子任务未得到有效结果，请直接围绕原始问题给出谨慎、简明的回答：{original_query}"
        )
        aggregate_messages = [
            {"role": "system", "content": "你负责把多模型协同结果聚合成最终答案。"},
            {"role": "user", "content": aggregate_prompt},
        ]
        aggregate_result = await call_step_with_fallback(
            f"聚合复杂问题最终答案：{original_query}",
            aggregate_messages,
            min(int(request.max_tokens or 1024), 520 if dispatch_mode == "fast" else int(request.max_tokens or 1024)),
            request.temperature,
            request.user,
            active_candidates,
            local_replan=solve_mode == "dynamic_subtasks",
            step_timeout=22.0 if dispatch_mode == "fast" else max(float(profile["step_timeout"]) * 2, 90.0),
            dispatch_mode=dispatch_mode,
        )
        if aggregate_result.get("result"):
            usage_items.append(aggregate_result["result"])
        final_content = aggregate_result.get("content") or "\n\n".join(item["content"] for item in partial_outputs)
        final_model = aggregate_result.get("model") or (partial_outputs[-1]["model"] if partial_outputs else "unknown")
        steps = sorted(steps, key=lambda item: item.get("index", 0))
        if solve_mode == "dynamic_subtasks":
            reason = (
                f"{mode_label}：系统先按任务类型拆成 {len(plan)} 个子任务，"
                f"再根据依赖关系以最多 {profile['concurrency']} 个步骤并行执行。"
                f"候选池为 {', '.join(active_candidates)}；慢步骤超过 {profile['step_timeout']} 秒会触发降级或结束等待。"
            )
        else:
            reason = f"{mode_label}：系统使用固定步骤顺序执行，每一步选择合适模型，最后聚合最终答案。"
        routing_payload = {
            "selected_model": final_model,
            "initial_model": aggregate_result.get("initial_model"),
            "strategy": "llmrouter",
            "algorithm": config.router.llmrouter_name,
            "solve_mode": solve_mode,
            "solve_mode_label": mode_label,
            "dispatch_mode": dispatch_mode,
            "dispatch_mode_label": profile["label"],
            "execution_policy": profile["description"],
            "candidate_pool": active_candidates,
            "candidate_scores": aggregate_result.get("routing", {}).get("candidate_scores", {}),
            "reason": reason,
            "attempted_models": aggregate_result.get("attempted_models", []),
            "fallbacks": aggregate_result.get("fallbacks", []),
            "multi_step": steps + [{
                "index": len(steps) + 1,
                "name": "最终聚合",
                "goal": "整合所有中间结果，形成最终答案。",
                "depends_on": [step.get("index") for step in steps],
                "parallel_group": (max([step.get("parallel_group", 0) for step in steps] or [0]) + 1),
                "dispatch_mode": dispatch_mode,
                "dispatch_mode_label": profile["label"],
                "selected_model": final_model,
                "initial_model": aggregate_result.get("initial_model"),
                "attempted_models": aggregate_result.get("attempted_models", []),
                "fallbacks": aggregate_result.get("fallbacks", []),
                "candidate_scores": aggregate_result.get("routing", {}).get("candidate_scores", {}),
                "status": "success" if aggregate_result.get("ok") else "partial",
                "local_replan": bool(aggregate_result.get("local_replan")),
                "excerpt": final_content[:600],
            }],
        }
        return {
            "id": f"multistep-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "model": final_model,
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": f"[{final_model}] {final_content}" if config.show_model_prefix else final_content,
                },
            }],
            "usage": merge_usage(*usage_items),
            "routing": routing_payload,
        }

    def append_request_log(entry: Dict[str, Any]) -> None:
        request_logs.appendleft({
            "id": f"req-{int(time.time() * 1000)}",
            "time": time.time(),
            **entry,
        })

    def routing_config_version() -> str:
        return hashlib.sha256(json.dumps({
            "strategy": config.router.strategy,
            "models": {name: {"model": item.model_id, "base_url": item.base_url} for name, item in config.llms.items()},
        }, sort_keys=True).encode()).hexdigest()[:16]

    def apply_verified_experience(
        routing: Dict[str, Any], query: str, candidates: List[str], user_id: Optional[str]
    ) -> Dict[str, Any]:
        """Blend verified outcomes into semantic strategies; never override manual/baseline routing."""
        strategy = str(routing.get("strategy") or "")
        if strategy in {"manual", "random", "round_robin", "rules"} or not candidates:
            return routing
        stats = experience_store.model_statistics(query, candidates, user_id=user_id, config_version=routing_config_version())
        base_scores = {name: float((routing.get("candidate_scores") or {}).get(name, 0.0)) for name in candidates}
        if not any(float(item.get("history_count") or 0.0) > 0 for item in stats.values()):
            routing["experience"] = {"applied": False, "reason": "没有相似且已验证的历史经验。"}
            return routing
        adjusted = {}
        for model in candidates:
            history = stats[model]
            confidence = min(0.30, 0.08 * math.log1p(float(history.get("history_count") or 0.0)))
            adjusted[model] = round(
                (1.0 - confidence) * base_scores.get(model, 0.0)
                + confidence * float(history.get("historical_reward") or 0.5), 4
            )
        selected = max(adjusted, key=adjusted.get)
        previous = routing.get("selected_model")
        routing.update({
            "selected_model": selected,
            "candidate_scores_before_experience": base_scores,
            "candidate_scores": adjusted,
            "experience": {
                "applied": True, "previous_model": previous, "selected_model": selected,
                "model_statistics": stats,
                "note": "仅使用 verified_positive/negative/disputed 历史；pending 不参与路由。",
            },
        })
        if selected != previous:
            routing["reason"] = f"{routing.get('reason', '')} 经已验证历史经验校正后选择 {selected}。".strip()
        return routing

    experiment_tasks = [
        {
            "id": "qa_basic",
            "query": "请用通俗语言解释什么是大模型路由。",
            "type": "通用问答",
            "complexity": 0.25,
            "risk": 0.20,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "code_sort",
            "query": "请写一个 Python 冒泡排序函数，并解释时间复杂度。",
            "type": "代码生成",
            "complexity": 0.55,
            "risk": 0.35,
            "agent_stage": "推理 Agent -> 生成 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "reasoning_compare",
            "query": "比较快速排序和归并排序的适用场景，并说明为什么。",
            "type": "逻辑推理",
            "complexity": 0.72,
            "risk": 0.45,
            "agent_stage": "规划 Agent -> 推理 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "summary",
            "query": "把一段研究背景整理成三点摘要，要求结构清晰。",
            "type": "文本摘要",
            "complexity": 0.38,
            "risk": 0.25,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "doubao", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "audit_risk",
            "query": "针对审计合规场景，分析大模型回答错误可能造成的风险。",
            "type": "专业问答",
            "complexity": 0.82,
            "risk": 0.86,
            "agent_stage": "规划 Agent -> 检索 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "creative_speech",
            "query": "帮我写一篇三分钟人工智能主题演讲稿，语言自然一点。",
            "type": "内容创作",
            "complexity": 0.42,
            "risk": 0.20,
            "agent_stage": "生成 Agent",
            "expected": ["doubao", "qwen-plus", "deepseek-chat"],
            "requires_verification": False,
        },
    ]
    experiment_tasks.extend([
        {
            "id": "finance_finqa_revenue_growth",
            "query": "某公司 2022 年营收为 120 亿元，2023 年营收为 150 亿元，请计算营收增长率并解释这个指标的含义。",
            "type": "专业问答",
            "domain": "finance",
            "complexity": 0.66,
            "risk": 0.62,
            "agent_stage": "推理 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus", "glm-5.2"],
            "requires_verification": True,
            "requires_calculation": True,
            "requires_table_reasoning": False,
            "requires_kg_reasoning": False,
        },
        {
            "id": "finance_tatqa_table_text",
            "query": "根据财报表格和管理层文字说明，分析毛利率下降可能由哪些业务因素导致，并说明需要验证哪些证据。",
            "type": "专业问答",
            "domain": "finance",
            "complexity": 0.78,
            "risk": 0.72,
            "agent_stage": "规划 Agent -> 检索 Agent -> 推理 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus", "glm-5.2"],
            "requires_verification": True,
            "requires_calculation": True,
            "requires_table_reasoning": True,
            "requires_kg_reasoning": False,
        },
        {
            "id": "finance_audit_compliance",
            "query": "分析上市公司收入确认异常可能带来的审计合规风险，并给出内控改进措施。",
            "type": "专业问答",
            "domain": "finance",
            "complexity": 0.86,
            "risk": 0.90,
            "agent_stage": "规划 Agent -> 检索 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus", "glm-5.2"],
            "requires_verification": True,
            "requires_calculation": False,
            "requires_table_reasoning": False,
            "requires_kg_reasoning": False,
        },
        {
            "id": "finance_kg_multihop",
            "query": "在金融知识图谱中，若公司 A 控股公司 B，公司 B 是公司 C 的主要供应商，请分析公司 A 与公司 C 之间可能存在的间接关联风险。",
            "type": "逻辑推理",
            "domain": "finance",
            "complexity": 0.88,
            "risk": 0.84,
            "agent_stage": "规划 Agent -> 图谱推理 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus", "glm-5.2"],
            "requires_verification": True,
            "requires_calculation": False,
            "requires_table_reasoning": False,
            "requires_kg_reasoning": True,
        },
    ])
    experiment_tasks.extend([
        {
            "id": "qa_router_layers",
            "query": "用小白能听懂的话说明服务层路由和算法层路由的区别。",
            "type": "通用问答",
            "complexity": 0.36,
            "risk": 0.22,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": False,
        },
        {
            "id": "math_cost",
            "query": "如果一个模型输入 2000 token、输出 800 token，如何估算一次调用成本？",
            "type": "逻辑推理",
            "complexity": 0.58,
            "risk": 0.32,
            "agent_stage": "推理 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "code_api",
            "query": "写一个 Python 函数，统计列表中每个元素出现的次数。",
            "type": "代码生成",
            "complexity": 0.46,
            "risk": 0.28,
            "agent_stage": "生成 Agent -> 验证 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "audit_policy",
            "query": "审计报告自动生成场景中，应该怎样降低大模型幻觉风险？",
            "type": "专业问答",
            "complexity": 0.78,
            "risk": 0.82,
            "agent_stage": "规划 Agent -> 检索 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "summary_eval",
            "query": "把模型路由系统的优势总结成三条，要求适合放在论文汇报 PPT 中。",
            "type": "文本摘要",
            "complexity": 0.35,
            "risk": 0.22,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "creative_notice",
            "query": "写一段项目演示开场白，介绍大模型路由系统的价值。",
            "type": "内容创作",
            "complexity": 0.34,
            "risk": 0.18,
            "agent_stage": "生成 Agent",
            "expected": ["doubao", "qwen-plus"],
            "requires_verification": False,
        },
        {
            "id": "reasoning_fallback",
            "query": "为什么模型调用失败时需要自动降级？请给出一个实际例子。",
            "type": "逻辑推理",
            "complexity": 0.52,
            "risk": 0.55,
            "agent_stage": "推理 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "code_validate",
            "query": "写一个判断字符串是否为回文的 Python 函数，并给出两个测试用例。",
            "type": "代码生成",
            "complexity": 0.48,
            "risk": 0.30,
            "agent_stage": "生成 Agent -> 验证 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
    ])
    experiment_tasks.extend([
        {
            "id": "qa_metric",
            "query": "请解释质量、成本、延迟、可靠性这四个路由评价指标分别是什么意思。",
            "type": "通用问答",
            "complexity": 0.32,
            "risk": 0.18,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "qa_graphrouter",
            "query": "GraphRouter 为什么可以用图结构来做模型路由？请用例子解释。",
            "type": "通用问答",
            "complexity": 0.50,
            "risk": 0.30,
            "agent_stage": "推理 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "math_weight",
            "query": "给定质量0.9、成本0.3、延迟0.4、可靠性0.8，按当前权重计算综合效用。",
            "type": "数学推理",
            "complexity": 0.50,
            "risk": 0.34,
            "agent_stage": "推理 Agent -> 验证 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "math_latency",
            "query": "如果三次模型调用耗时分别为 1.2 秒、2.0 秒、1.6 秒，平均响应时间是多少？",
            "type": "数学推理",
            "complexity": 0.30,
            "risk": 0.20,
            "agent_stage": "推理 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "math_success",
            "query": "100 次请求中成功 92 次、自动降级 6 次，请计算成功率并解释降级次数代表什么。",
            "type": "数学推理",
            "complexity": 0.42,
            "risk": 0.28,
            "agent_stage": "推理 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "code_merge",
            "query": "写一个 Python 函数合并两个有序列表，并说明时间复杂度。",
            "type": "代码生成",
            "complexity": 0.52,
            "risk": 0.35,
            "agent_stage": "生成 Agent -> 验证 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "code_json",
            "query": "写一个 Python 函数，从 JSON 字符串中读取 name 和 score 字段。",
            "type": "代码生成",
            "complexity": 0.44,
            "risk": 0.32,
            "agent_stage": "生成 Agent -> 验证 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "code_error",
            "query": "写一个 Python 示例，演示如何捕获接口请求失败异常并返回备用结果。",
            "type": "代码生成",
            "complexity": 0.60,
            "risk": 0.46,
            "agent_stage": "规划 Agent -> 生成 Agent -> 验证 Agent",
            "expected": ["qwen-plus", "deepseek-chat"],
            "requires_verification": True,
        },
        {
            "id": "audit_data",
            "query": "审计数据分析中使用大模型时，哪些数据不应该直接发送给外部模型？",
            "type": "专业问答",
            "complexity": 0.76,
            "risk": 0.88,
            "agent_stage": "规划 Agent -> 检索 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "audit_trace",
            "query": "为什么审计合规场景需要保留模型调用日志和路由日志？",
            "type": "专业问答",
            "complexity": 0.70,
            "risk": 0.80,
            "agent_stage": "推理 Agent -> 验证 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "audit_report",
            "query": "请给出一段审计合规智能问答系统的风险控制建议。",
            "type": "专业问答",
            "complexity": 0.74,
            "risk": 0.84,
            "agent_stage": "规划 Agent -> 生成 Agent",
            "expected": ["deepseek-chat", "qwen-plus"],
            "requires_verification": True,
        },
        {
            "id": "summary_router",
            "query": "把模型路由系统的工作流程总结成四个步骤。",
            "type": "文本摘要",
            "complexity": 0.34,
            "risk": 0.20,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "summary_compare",
            "query": "把固定模型调用和动态模型路由的区别整理成对比表。",
            "type": "文本摘要",
            "complexity": 0.40,
            "risk": 0.22,
            "agent_stage": "生成 Agent",
            "expected": ["qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "creative_demo",
            "query": "写一段 1 分钟项目演示讲稿，突出模型路由的创新点。",
            "type": "内容创作",
            "complexity": 0.38,
            "risk": 0.18,
            "agent_stage": "生成 Agent",
            "expected": ["doubao", "qwen-plus"],
            "requires_verification": False,
        },
        {
            "id": "creative_ppt",
            "query": "帮我写一页 PPT 的标题和三条要点，主题是多目标模型路由。",
            "type": "内容创作",
            "complexity": 0.36,
            "risk": 0.18,
            "agent_stage": "生成 Agent",
            "expected": ["doubao", "qwen-plus", "gemini-2.5-flash"],
            "requires_verification": False,
        },
        {
            "id": "creative_notice2",
            "query": "写一段系统上线通知，说明新增了模型测试、报告导出和自动降级展示。",
            "type": "内容创作",
            "complexity": 0.34,
            "risk": 0.18,
            "agent_stage": "生成 Agent",
            "expected": ["doubao", "qwen-plus"],
            "requires_verification": False,
        },
    ])

    def load_finance_router_tasks(limit: int = 110) -> List[Dict[str, Any]]:
        dataset_path = Path.cwd() / "data" / "finance_router" / "standardized" / "finance_router_tasks.jsonl"
        if not dataset_path.exists():
            return []
        loaded: List[Dict[str, Any]] = []
        try:
            for line in dataset_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                sample_id = str(item.get("id") or f"finance_{len(loaded) + 1:06d}")
                risk_level = str(item.get("risk_level") or "medium").lower()
                risk = 0.86 if risk_level == "high" else 0.62 if risk_level == "medium" else 0.35
                complexity = 0.50
                if item.get("requires_calculation"):
                    complexity += 0.12
                if item.get("requires_table_reasoning"):
                    complexity += 0.12
                if item.get("requires_kg_reasoning"):
                    complexity += 0.18
                loaded.append({
                    "id": f"finance_dataset_{sample_id}",
                    "query": str(item.get("question") or ""),
                    "type": "专业问答" if item.get("domain") == "finance" else "通用问答",
                    "domain": "finance",
                    "dataset": item.get("dataset", "finance_router"),
                    "task_type": item.get("task_type", "financial_qa"),
                    "complexity": round(min(1.0, complexity), 2),
                    "risk": risk,
                    "agent_stage": (
                        "规划 Agent -> 图谱推理 Agent -> 验证 Agent -> 生成 Agent"
                        if item.get("requires_kg_reasoning")
                        else "推理 Agent -> 验证 Agent -> 生成 Agent"
                    ),
                    "expected": ["deepseek-chat", "qwen-plus", "glm-5.2"],
                    "requires_verification": bool(item.get("requires_verification", True)),
                    "requires_calculation": bool(item.get("requires_calculation")),
                    "requires_table_reasoning": bool(item.get("requires_table_reasoning")),
                    "requires_kg_reasoning": bool(item.get("requires_kg_reasoning")),
                    "gold_answer": item.get("gold_answer"),
                    "context": item.get("context"),
                    "table": item.get("table"),
                    "evidence": item.get("evidence", []),
                    "source_url": item.get("source_url"),
                    "source_id": item.get("source_id"),
                    "review_status": item.get("review_status"),
                })
                if len(loaded) >= limit:
                    break
        except Exception as error:
            _safe_log(f"[FinanceDataset] Failed to load {dataset_path}: {error}")
            return []
        return loaded

    finance_dataset_tasks = load_finance_router_tasks()
    if finance_dataset_tasks:
        experiment_tasks.extend(finance_dataset_tasks)
        _safe_log(f"[FinanceDataset] Loaded {len(finance_dataset_tasks)} finance tasks.")

    def finance_dataset_summary() -> Dict[str, Any]:
        datasets = Counter(str(item.get("dataset", "unknown")) for item in finance_dataset_tasks)
        manifest_path = Path.cwd() / "data" / "finance_router" / "standardized" / "finance_experiment_manifest.json"
        manifest = {}
        try:
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as error:
            _safe_log(f"[FinanceDataset] Failed to read manifest: {error}")
        return {
            "loaded": len(finance_dataset_tasks),
            "datasets": dict(datasets),
            "standardized_path": "data/finance_router/standardized/finance_router_tasks.jsonl",
            "training_jsonl": "data/finance_router/routing/finance_router_train.jsonl",
            "training_csv": "data/finance_router/routing/finance_router_train.csv",
            "manifest_path": "data/finance_router/standardized/finance_experiment_manifest.json",
            "sampling_seed": manifest.get("seed"),
            "counts_by_stratum": manifest.get("counts_by_stratum", {}),
            "sources": manifest.get("sources", []),
            "note": "FinQA/TAT-QA 等金融数据集会先转成统一 JSONL，再生成路由训练标签。",
        }

    model_profiles = {
        "deepseek-chat": {
            "quality": 0.88,
            "cost": 0.55,
            "latency": 0.58,
            "reliability": 0.88,
            "strengths": {"逻辑推理": 0.12, "专业问答": 0.14, "代码生成": 0.06},
        },
        "qwen-plus": {
            "quality": 0.84,
            "cost": 0.45,
            "latency": 0.38,
            "reliability": 0.86,
            "strengths": {"代码生成": 0.14, "文本摘要": 0.08, "通用问答": 0.06},
        },
        "gemini-2.5-flash": {
            "quality": 0.78,
            "cost": 0.28,
            "latency": 0.18,
            "reliability": 0.72,
            "strengths": {"通用问答": 0.08, "文本摘要": 0.06},
        },
        "glm-5.2": {
            "quality": 0.91,
            "cost": 0.82,
            "latency": 0.90,
            "reliability": 0.86,
            "strengths": {"代码生成": 0.10, "逻辑推理": 0.10, "专业问答": 0.08},
        },
        "doubao": {
            "quality": 0.74,
            "cost": 0.34,
            "latency": 0.38,
            "reliability": 0.55,
            "strengths": {"内容创作": 0.13, "文本摘要": 0.07},
        },
    }

    experiment_weights = {
        "quality": 0.45,
        "cost": 0.20,
        "latency": 0.15,
        "reliability": 0.20,
    }

    experiment_scoring = {
        "formula": "U=0.45Q+0.20(1-C)+0.15(1-L)+0.20R",
        "overall_formula": "Overall=Σ(1+λ·risk_t)·U_t / Σ(1+λ·risk_t)",
        "risk_lambda": 1.0,
        "cost_normalization": "C=min(raw_cost_usd/0.02,1)；无价格配置时 C=min(total_tokens/3000,1)",
        "latency_normalization": "L=min(latency_ms/10000,1)",
        "reliability_definition": "R=success_count/repeat_count",
        "weights_note": "45%/20%/15%/20% 是评价偏好权重，不是实验测得比例。",
    }

    experiment_baselines = [
        {
            "id": "fixed_strong",
            "name": "固定高性能模型",
            "category": "基线",
            "description": "所有任务都调用能力较强的模型，用来观察质量上限和成本压力。",
        },
        {
            "id": "fixed_lightweight",
            "name": "固定轻量模型",
            "category": "基线",
            "description": "所有任务都调用低成本、低延迟模型，用来观察省钱提速后复杂任务的风险。",
        },
    ]

    experiment_service_strategies = [
        {
            "id": f"service_{item['id']}",
            "name": item["name"],
            "category": "服务层策略",
            "description": item["description"],
            "source_id": item["id"],
        }
        for item in service_strategy_catalog
    ]

    experiment_algorithm_strategies = [
        {
            "id": f"algorithm_{item['id']}",
            "name": item["name"],
            "category": "算法层路由器",
            "description": item["description"],
            "source_id": item["id"],
        }
        for item in algorithm_catalog
    ]

    all_experiment_strategies = (
        experiment_baselines
        + experiment_service_strategies
        + experiment_algorithm_strategies
        + [
        {
            "id": "constrained_multi_objective",
            "name": "约束 Pareto 多目标路由",
            "category": "改进策略",
            "description": "先按任务风险、预算和速度要求过滤候选模型，再在 Pareto 前沿中选择综合效用最高的模型。",
        },
        {
            "id": "finance_risk_adaptive",
            "name": "金融风险自适应非线性路由",
            "category": "改进策略",
            "description": "先用金融风险硬约束过滤模型，再用非线性效用 Q^α·R^β·exp(-γC)·exp(-δL) 在 Pareto 前沿中选择模型。",
        },
        {
            "id": "multi_objective",
            "name": "改进多目标路由",
            "category": "改进策略",
            "description": "同时考虑质量、成本、延迟、可靠性和风险约束，选择综合得分最高的模型。",
        },
        {
            "id": "pso_scheduler",
            "name": "PSO 粒子群调度",
            "category": "调度优化",
            "description": "把一批任务的模型分配看作粒子位置，通过粒子群搜索整体效用更高的调度方案。",
        },
        {
            "id": "ga_scheduler",
            "name": "GA 遗传调度",
            "category": "调度优化",
            "description": "把任务-模型分配看作个体，通过选择、交叉和变异搜索更优调度方案。",
        },
        ]
    )

    main_strategy_roles = {
        "fixed_lightweight": "低成本基线",
        "fixed_strong": "高质量基线",
        "service_random": "随机选择基线",
        "algorithm_knnrouter": "Embedding/近邻检索代表",
        f"algorithm_{contrastive_representative_id}": f"{contrastive_representative_name}：对比学习/协同过滤代表",
        "algorithm_graphrouter": "图结构路由代表",
        "algorithm_automixrouter": "传统级联路由代表",
        "service_latency_sla_pareto": "Latency-SLA 约束 Pareto 代表",
        "service_cascading_bandit_pareto": "本文方法：级联 Bandit Pareto 路由",
        "service_finance_risk_adaptive": "本文方法：金融风险自适应非线性路由",
        "pso_scheduler": "离线批量调度优化代表",
        "ga_scheduler": "进化搜索调度基线",
    }
    appendix_role_notes = {
        "algorithm_mfrouter": "如果 RouterDC 已进入主实验，MFRouter 作为矩阵分解备用范式放入附录。",
        "algorithm_dcrouter": "如果 RouterDC 未进入主实验，则作为待补充权重的对比学习范式放入附录。",
        "service_round_robin": "轮询更适合系统基线演示，论文主表中信息增量较低。",
        "service_rules": "规则路由可作为工程基线，主实验优先保留更通用的随机/学习型/级联方法。",
        "service_llm": "LLM 裁判路由成本较高，适合作为附录或消融对照。",
        "algorithm_svmrouter": "与 KNN/MLP 同属传统监督分类范式，主实验保留 KNN 作为代表。",
        "algorithm_mlprouter": "与 KNN/SVM 同属传统监督分类范式，主实验保留 KNN 作为代表。",
        "algorithm_elorouter": "Elo 排名更适合偏好排序场景，当前金融路由主线中作为附录。",
        "algorithm_hybrid_llm": "与 AutoMix/级联方法主题接近，主实验保留 AutoMix 和本文级联方法。",
        "algorithm_causallm_router": "通常需要额外生成式路由模型，当前作为附录兼容策略。",
        "algorithm_gmtrouter": "多轮/用户图关系路由属于扩展能力，主论文可放附录。",
        "algorithm_personalizedrouter": "个性化路由依赖用户画像数据，当前作为扩展能力。",
        "algorithm_knnmultiroundrouter": "多轮拆解能力保留在系统演示，主实验先聚焦单轮模型选择。",
        "algorithm_llmmultiroundrouter": "多轮拆解能力保留在系统演示，主实验先聚焦单轮模型选择。",
        "algorithm_router_r1": "智能体式路由环境要求更高，作为附录能力。",
        "algorithm_randomrouter": "与服务层随机基线重复，主实验保留服务层随机基线。",
        "algorithm_thresholdrouter": "阈值路由可作为简单消融，主实验优先保留更完整的级联代表。",
    }
    main_strategy_order = list(main_strategy_roles.keys())
    for strategy_item in all_experiment_strategies:
        strategy_id = strategy_item["id"]
        if strategy_id in main_strategy_roles:
            strategy_item["benchmark_scope"] = "main"
            strategy_item["benchmark_role"] = main_strategy_roles[strategy_id]
            strategy_item["paper_note"] = "论文主实验代表策略"
        else:
            strategy_item["benchmark_scope"] = "appendix"
            strategy_item["benchmark_role"] = appendix_role_notes.get(
                strategy_id,
                "系统完整能力保留，论文主表不展开，避免同类算法重复堆砌。",
            )
            strategy_item["paper_note"] = "附录/系统展示策略"
        if strategy_id == f"algorithm_{contrastive_representative_id}":
            strategy_item["description"] = (
                f"{strategy_item['description']} 当前作为主实验中的"
                f"{contrastive_representative_name}代表；若原生权重未覆盖当前模型，则使用兼容评分完成横向对比。"
            )

    experiment_strategies = sorted(
        [item for item in all_experiment_strategies if item["benchmark_scope"] == "main"],
        key=lambda item: main_strategy_order.index(item["id"]) if item["id"] in main_strategy_order else 999,
    )
    experiment_appendix_strategies = [
        item for item in all_experiment_strategies if item["benchmark_scope"] == "appendix"
    ]

    def model_profile(model_name: str) -> Dict[str, Any]:
        return model_profiles.get(model_name, {
            "quality": 0.70,
            "cost": 0.50,
            "latency": 0.50,
            "reliability": 0.70,
            "strengths": {},
        })

    def evaluate_model_for_task(model_name: str, task: Dict[str, Any]) -> Dict[str, float]:
        profile = model_profile(model_name)
        task_type = task["type"]
        complexity = float(task["complexity"])
        risk = float(task["risk"])
        quality = float(profile["quality"]) + float(profile.get("strengths", {}).get(task_type, 0.0))
        quality -= max(0.0, complexity - 0.6) * 0.08
        if model_name in task["expected"]:
            quality += 0.06
        reliability = float(profile["reliability"]) - max(0.0, risk - 0.65) * 0.08
        if task["requires_verification"] and reliability < 0.75:
            quality -= 0.05
        return {
            "quality": round(max(0.0, min(1.0, quality)), 3),
            "cost": round(max(0.0, min(1.0, float(profile["cost"]))), 3),
            "latency": round(max(0.0, min(1.0, float(profile["latency"]))), 3),
            "reliability": round(max(0.0, min(1.0, reliability)), 3),
        }

    def utility_score(metrics_payload: Dict[str, float]) -> float:
        return canonical_utility(metrics_payload, experiment_weights)

    def estimate_router_overhead_ms(strategy_id: str, task: Optional[Dict[str, Any]] = None) -> float:
        complexity = float((task or {}).get("complexity", 0.3))
        if strategy_id in {"fixed_strong", "fixed_lightweight"}:
            return 0.25
        if strategy_id in {"service_random", "service_round_robin", "service_rules"}:
            return round(0.8 + complexity * 0.8, 3)
        if strategy_id in {"service_llm"}:
            return round(180.0 + complexity * 120.0, 3)
        if strategy_id in {"service_constrained_multi_objective", "constrained_multi_objective", "multi_objective", "finance_risk_adaptive", "service_finance_risk_adaptive", "service_latency_sla_pareto"}:
            return round(3.0 + complexity * 4.0, 3)
        if strategy_id in {"service_contextual_bandit", "service_cascading_bandit_pareto"}:
            return round(5.0 + complexity * 7.0, 3)
        if strategy_id.startswith("algorithm_graphrouter"):
            return round(62.0 + complexity * 38.0, 3)
        if strategy_id.startswith("algorithm_"):
            return round(18.0 + complexity * 22.0, 3)
        if strategy_id in {"pso_scheduler", "ga_scheduler"}:
            return round(35.0 + complexity * 45.0, 3)
        return round(8.0 + complexity * 10.0, 3)

    def finance_task_profile(task: Dict[str, Any]) -> Dict[str, Any]:
        query = str(task.get("query", ""))
        text = query.lower()
        finance_words = (
            "finance", "financial", "risk", "audit", "compliance", "revenue",
            "profit", "cash flow", "balance sheet", "income statement",
            "金融", "财务", "财报", "审计", "合规", "风控", "风险", "营收",
            "收入", "利润", "毛利率", "现金流", "资产", "负债", "权益", "估值",
            "股票", "债券", "投资", "监管", "内控",
        )
        calculation_words = ("同比", "环比", "增长率", "利润率", "占比", "%", "计算", "表格", "table")
        kg_words = ("知识图谱", "实体", "关系", "多跳", "路径", "关联", "上游", "下游")
        profile = {
            "domain": "finance" if any(word in text for word in finance_words) or task.get("domain") == "finance" else "general",
            "requires_calculation": bool(task.get("requires_calculation")) or any(word in text for word in calculation_words),
            "requires_kg_reasoning": bool(task.get("requires_kg_reasoning")) or any(word in text for word in kg_words),
        }
        risk = float(task.get("risk", 0.0))
        if profile["domain"] == "finance":
            risk = max(risk, 0.62)
        if any(word in text for word in ("审计", "合规", "监管", "内控", "风险")):
            risk = max(risk, 0.86)
        profile["risk"] = risk
        profile["risk_level"] = "high" if risk >= 0.80 else "medium" if risk >= 0.55 else "low"
        return profile

    def finance_nonlinear_params(task: Dict[str, Any]) -> Dict[str, float]:
        risk_level = finance_task_profile(task)["risk_level"]
        if risk_level == "high":
            return {"alpha": 2.15, "beta": 1.90, "gamma": 0.42, "delta": 0.34}
        if risk_level == "medium":
            return {"alpha": 1.65, "beta": 1.40, "gamma": 0.62, "delta": 0.52}
        return {"alpha": 1.20, "beta": 1.05, "gamma": 0.95, "delta": 0.88}

    def finance_constraints(task: Dict[str, Any]) -> Dict[str, Any]:
        profile = finance_task_profile(task)
        constraints = task_constraint_profile(task)
        labels = list(constraints.get("labels", []))
        if profile["domain"] == "finance":
            constraints["min_quality"] = max(float(constraints["min_quality"]), 0.78)
            constraints["min_reliability"] = max(float(constraints["min_reliability"]), 0.76)
            labels.append("金融任务提高质量与可靠性下限")
        if profile["requires_calculation"]:
            constraints["min_quality"] = max(float(constraints["min_quality"]), 0.82)
            labels.append("财务数值推理提高质量下限")
        if profile["requires_kg_reasoning"]:
            constraints["min_quality"] = max(float(constraints["min_quality"]), 0.84)
            labels.append("金融知识图谱多跳推理提高质量下限")
        if profile["risk_level"] == "high":
            constraints["min_quality"] = max(float(constraints["min_quality"]), 0.86)
            constraints["min_reliability"] = max(float(constraints["min_reliability"]), 0.84)
            constraints["max_cost"] = max(float(constraints["max_cost"]), 0.92)
            labels.append("高风险金融任务优先保证质量和可靠性")
        elif profile["risk_level"] == "low":
            constraints["max_cost"] = min(float(constraints["max_cost"]), 0.68)
            constraints["max_latency"] = min(float(constraints["max_latency"]), 0.68)
            labels.append("低风险任务控制成本和延迟")
        constraints["labels"] = labels
        constraints["risk_level"] = profile["risk_level"]
        constraints["domain"] = profile["domain"]
        return constraints

    def finance_nonlinear_utility(metrics_payload: Dict[str, float], task: Dict[str, Any]) -> tuple[float, Dict[str, float]]:
        params = finance_nonlinear_params(task)
        quality = max(0.001, float(metrics_payload.get("quality", 0.0)))
        reliability = max(0.001, float(metrics_payload.get("reliability", 0.0)))
        cost = max(0.0, float(metrics_payload.get("cost", 0.0)))
        latency = max(0.0, float(metrics_payload.get("latency", 0.0)))
        score = (
            (quality ** params["alpha"])
            * (reliability ** params["beta"])
            * math.exp(-params["gamma"] * cost)
            * math.exp(-params["delta"] * latency)
        )
        return round(max(0.0, min(1.0, score)), 4), params

    def task_constraint_profile(task: Dict[str, Any]) -> Dict[str, Any]:
        """Build human-readable constraints for constrained multi-objective routing."""
        task_type = task.get("type", "通用问答")
        risk = float(task.get("risk", 0.0))
        complexity = float(task.get("complexity", 0.0))
        requires_verification = bool(task.get("requires_verification"))
        constraints = {
            "min_quality": 0.70,
            "max_cost": 0.82,
            "max_latency": 0.85,
            "min_reliability": 0.68,
            "labels": ["基础可用性约束"],
        }
        if complexity >= 0.65:
            constraints["min_quality"] = max(constraints["min_quality"], 0.78)
            constraints["labels"].append("复杂任务提高质量下限")
        if task_type in {"代码生成", "逻辑推理", "专业问答"}:
            constraints["min_quality"] = max(constraints["min_quality"], 0.80)
            constraints["labels"].append("推理/专业任务提高质量下限")
        if requires_verification:
            constraints["min_reliability"] = max(constraints["min_reliability"], 0.76)
            constraints["labels"].append("需要验证时提高可靠性下限")
        if risk >= 0.75:
            constraints["min_reliability"] = max(constraints["min_reliability"], 0.80)
            constraints["min_quality"] = max(constraints["min_quality"], 0.82)
            constraints["max_cost"] = max(constraints["max_cost"], 0.90)
            constraints["labels"].append("高风险任务优先质量和可靠性")
        if task_type in {"通用问答", "文本摘要", "内容创作"} and risk < 0.45:
            constraints["max_cost"] = min(constraints["max_cost"], 0.60)
            constraints["max_latency"] = min(constraints["max_latency"], 0.60)
            constraints["labels"].append("低风险任务控制成本和延迟")
        return constraints

    def constraint_violations(metrics_payload: Dict[str, float], constraints: Dict[str, Any]) -> List[str]:
        violations = []
        if float(metrics_payload.get("quality", 0.0)) < float(constraints["min_quality"]):
            violations.append("质量低于下限")
        if float(metrics_payload.get("cost", 1.0)) > float(constraints["max_cost"]):
            violations.append("成本超过上限")
        if float(metrics_payload.get("latency", 1.0)) > float(constraints["max_latency"]):
            violations.append("延迟超过上限")
        if float(metrics_payload.get("reliability", 0.0)) < float(constraints["min_reliability"]):
            violations.append("可靠性低于下限")
        return violations

    def dominates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_metrics = left["metrics"]
        right_metrics = right["metrics"]
        better_or_equal = (
            left_metrics["quality"] >= right_metrics["quality"]
            and left_metrics["reliability"] >= right_metrics["reliability"]
            and left_metrics["cost"] <= right_metrics["cost"]
            and left_metrics["latency"] <= right_metrics["latency"]
        )
        strictly_better = (
            left_metrics["quality"] > right_metrics["quality"]
            or left_metrics["reliability"] > right_metrics["reliability"]
            or left_metrics["cost"] < right_metrics["cost"]
            or left_metrics["latency"] < right_metrics["latency"]
        )
        return bool(better_or_equal and strictly_better)

    def pareto_front(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        front = []
        for item in scored:
            if not any(dominates(other, item) for other in scored if other is not item):
                front.append(item)
        return sorted(front, key=lambda item: item["score"], reverse=True)

    def task_evaluation_profile(task: Dict[str, Any]) -> Dict[str, Any]:
        task_type = task.get("type", "通用问答")
        common = {
            "reference_answer": "回答应当准确回应用户问题，概念清晰，结构完整，没有明显事实错误。",
            "criteria": [
                "是否直接回答问题",
                "是否准确、无明显事实错误",
                "是否结构清晰、表达自然",
                "是否满足任务要求",
            ],
        }
        profiles = {
            "代码生成": {
                "reference_answer": "应给出可运行代码，并解释核心思路、边界情况和时间/空间复杂度。",
                "criteria": ["代码可运行", "算法正确", "解释清楚", "复杂度说明准确"],
            },
            "逻辑推理": {
                "reference_answer": "应给出清晰的推理链条、比较依据和结论，避免只给结论。",
                "criteria": ["推理步骤完整", "比较维度合理", "结论明确", "无逻辑跳跃"],
            },
            "文本摘要": {
                "reference_answer": "应保留原始信息重点，用简洁结构化语言概括。",
                "criteria": ["覆盖重点", "结构清晰", "没有编造信息", "语言简洁"],
            },
            "专业问答": {
                "reference_answer": "应结合专业场景分析风险、原因和建议，避免泛泛而谈。",
                "criteria": ["专业概念准确", "风险分析充分", "建议可执行", "边界说明清楚"],
            },
            "内容创作": {
                "reference_answer": "应符合主题、语气和时长要求，表达自然，有完整开头、主体和结尾。",
                "criteria": ["主题贴合", "语言自然", "结构完整", "符合字数/时长要求"],
            },
            "通用问答": {
                "reference_answer": "应使用通俗语言解释概念，并给出简单例子帮助理解。",
                "criteria": ["解释准确", "通俗易懂", "例子合适", "结构清楚"],
            },
        }
        profile = {**common, **profiles.get(task_type, {})}
        if task.get("gold_answer") not in (None, ""):
            profile["reference_answer"] = str(task.get("gold_answer"))[:4000]
            profile["criteria"] = profile["criteria"] + ["与给定标准答案或证据保持一致"]
        if task.get("requires_verification"):
            profile["criteria"] = profile["criteria"] + ["对高风险内容给出谨慎说明或验证建议"]
        return profile

    def estimate_tokens(text: str) -> int:
        return max(1, int(len(text or "") / 3.5))

    def extract_response_text(result: Dict[str, Any]) -> str:
        return extract_message_text(result)

    def extract_usage(result: Dict[str, Any], prompt: str, response: str) -> Dict[str, int]:
        usage = result.get("usage") if isinstance(result, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or estimate_tokens(prompt))
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or estimate_tokens(response))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        }

    def raw_cost_usd(model_name: str, usage: Dict[str, int]) -> float:
        llm = config.llms.get(model_name)
        if llm and (llm.input_price > 0 or llm.output_price > 0):
            return round(
                (
                    usage["prompt_tokens"] * llm.input_price
                    + usage["completion_tokens"] * llm.output_price
                ) / 1000000,
                8,
            )
        return 0.0

    def normalized_cost_score(model_name: str, usage: Dict[str, int], cost_usd: Optional[float] = None) -> float:
        llm = config.llms.get(model_name)
        priced = bool(llm and (llm.input_price > 0 or llm.output_price > 0))
        raw_cost = raw_cost_usd(model_name, usage) if priced and cost_usd is None else cost_usd
        return canonical_normalized_cost(raw_cost, int(usage.get("total_tokens") or 0), priced=priced)

    def heuristic_quality(task: Dict[str, Any], response: str, ok: bool) -> float:
        if not ok or not response.strip():
            return 0.0
        text = response.lower()
        score = 0.45 + min(0.25, len(response) / 1600)
        task_type = task["type"]
        if task_type == "代码生成":
            if "def " in text:
                score += 0.18
            if "for " in text or "while " in text:
                score += 0.08
            if "o(" in text or "复杂度" in response:
                score += 0.08
        elif task_type in {"逻辑推理", "专业问答"}:
            if any(word in response for word in ["因为", "因此", "风险", "原因", "建议"]):
                score += 0.16
            if len(response) > 220:
                score += 0.08
        elif task_type in {"文本摘要", "通用问答"}:
            if any(mark in response for mark in ["1.", "一、", "第一", "：", ":"]):
                score += 0.12
        elif task_type == "内容创作":
            if len(response) > 260:
                score += 0.12
        if task["requires_verification"] and len(response) < 120:
            score -= 0.08
        return round(max(0.0, min(1.0, score)), 3)

    def parse_judge_json(text: str) -> Optional[Dict[str, Any]]:
        return parse_judge_payload(text)

    def objective_answer_score(task: Dict[str, Any], response: str) -> Optional[float]:
        """Dataset-aware objective score; gold is used only after the candidate response exists."""
        return protocol_objective_score(task, response)

    async def judge_response_quality(
        task: Dict[str, Any],
        response: str,
        candidate_model: str,
        fallback_score: float,
        judge_enabled: bool = True,
    ) -> Dict[str, Any]:
        objective_score = objective_answer_score(task, response)
        base = {
            "score": objective_score if objective_score is not None else fallback_score,
            "source": "objective_rule" if objective_score is not None else "heuristic",
            "reason": "使用标准答案进行精确匹配、数值容差或关键词覆盖评分。" if objective_score is not None else "使用规则启发式质量评分。",
            "judge_model": None, "reviewer_model": None, "judge_scores": [],
            "judge_attempts": [], "judge_cost_usd": 0.0,
            "objective_score": objective_score, "disagreement": 0.0,
            "manual_review_required": False, "dimensions": {},
        }
        if not judge_enabled:
            return base
        preferred = [name for name in ("qwen-plus", "deepseek-chat", "qwen-turbo") if name in config.llms and name != candidate_model]
        if not preferred:
            return base
        profile = task_evaluation_profile(task)
        criteria = "\n".join(f"- {item}" for item in profile["criteria"])
        judge_prompt = f"""你是大模型路由实验的独立质量裁判。请只输出 JSON，不要输出其他文字。

任务类型：{task.get('type')}
数据集：{task.get('dataset', '-')}
用户问题：{task.get('query')}
标准答案/参考要求：{profile['reference_answer']}
评分标准：
{criteria}

候选模型：{candidate_model}
候选回答：
{response[:4000]}

请输出：
{{"score": 0到1之间的小数, "dimensions": {{"accuracy": 0到1, "completeness": 0到1, "reasoning": 0到1, "clarity": 0到1, "safety": 0到1}}, "reason": "一句话说明评分原因"}}"""
        judgments, judge_attempts = [], []
        judge_cost = 0.0
        for judge_model in preferred:
            if len(judgments) >= 2:
                break
            try:
                result = await backend.call(judge_model, [{"role": "user", "content": judge_prompt}], max_tokens=220, temperature=0.0, stream=False)
                judge_text = extract_response_text(result)
                usage = extract_usage(result, judge_prompt, judge_text)
                attempt_cost = raw_cost_usd(judge_model, usage)
                judge_cost += attempt_cost
                parsed = parse_judge_json(judge_text)
                if parsed:
                    parsed["raw_score"] = parsed["score"]
                    parsed["score"] = calibrate_score(judge_model, parsed["score"], judge_calibration)
                judge_attempts.append({
                    "model": judge_model, "ok": bool(parsed), "cost_usd": attempt_cost,
                    "error": None if parsed else "unparseable_json",
                    "raw_excerpt": None if parsed else judge_text[:1000],
                    "calibration_enabled": bool(judge_calibration.get("enabled")),
                })
                if parsed:
                    judgments.append({"model": judge_model, **parsed})
            except Exception as error:
                judge_attempts.append({"model": judge_model, "ok": False, "cost_usd": 0.0, "error": str(error)[:300]})
                _safe_log(f"[ExperimentJudge] {judge_model} failed: {str(error)[:180]}")
        if not judgments:
            return {**base, "judge_attempts": judge_attempts, "judge_cost_usd": round(judge_cost, 8)}
        judge_mean = sum(item["score"] for item in judgments) / len(judgments)
        if objective_score is None:
            final_score = judge_mean
        elif objective_score < OBJECTIVE_FEASIBILITY_THRESHOLD:
            # An explanation judge cannot rescue an objectively incorrect answer.
            final_score = objective_score
        else:
            final_score = .7 * objective_score + .3 * judge_mean
        compared = [item["score"] for item in judgments] + ([objective_score] if objective_score is not None else [])
        disagreement = max(compared) - min(compared) if len(compared) > 1 else 0.0
        dimensions = {}
        for key in ("accuracy", "completeness", "reasoning", "clarity", "safety"):
            values = [item.get("dimensions", {}).get(key) for item in judgments if key in item.get("dimensions", {})]
            if values:
                dimensions[key] = round(sum(values) / len(values), 3)
        return {
            "score": round(final_score, 3), "source": "objective_plus_dual_judge" if objective_score is not None and len(judgments) > 1 else "dual_llm_judge" if len(judgments) > 1 else "single_llm_judge",
            "reason": " | ".join(f"{item['model']}: {item['reason']}" for item in judgments)[:1000],
            "judge_model": judgments[0]["model"], "reviewer_model": judgments[1]["model"] if len(judgments) > 1 else None,
            "judge_scores": [{"model": item["model"], "score": item["score"]} for item in judgments],
            "judge_attempts": judge_attempts, "judge_cost_usd": round(judge_cost, 8),
            "objective_score": objective_score, "disagreement": round(disagreement, 3),
            "manual_review_required": disagreement >= .20, "dimensions": dimensions,
        }

    async def call_model_for_experiment(
        model_name: str,
        task: Dict[str, Any],
        repeat_index: int = 1,
        judge_enabled: bool = True,
    ) -> Dict[str, Any]:
        prompt, prompt_audit = build_experiment_prompt(task)
        started = time.perf_counter()
        try:
            result = await backend.call(
                model_name,
                [{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.2,
                stream=False,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            response = extract_response_text(result)
            usage = extract_usage(result, prompt, response)
            heuristic_score = heuristic_quality(task, response, True)
            judge = await judge_response_quality(task, response, model_name, heuristic_score, judge_enabled)
            cost_usd = raw_cost_usd(model_name, usage)
            return {
                "ok": True,
                "repeat": repeat_index,
                "model": model_name,
                "task_id": task["id"],
                "response": response,
                "usage": usage,
                "latency_ms": elapsed_ms,
                "raw_cost_usd": cost_usd,
                "quality_source": judge["source"],
                "judge_model": judge["judge_model"],
                "reviewer_model": judge.get("reviewer_model"),
                "judge_scores": judge.get("judge_scores", []),
                "judge_attempts": judge.get("judge_attempts", []),
                "judge_cost_usd": judge.get("judge_cost_usd", 0.0),
                "objective_score": judge.get("objective_score"),
                "judge_disagreement": judge.get("disagreement", 0.0),
                "manual_review_required": judge.get("manual_review_required", False),
                "judge_reason": judge["reason"],
                "judge_dimensions": judge.get("dimensions", {}),
                "evaluation_profile": task_evaluation_profile(task),
                "prompt_audit": prompt_audit,
                "metrics": {
                    "quality": judge["score"],
                    "cost": normalized_cost_score(model_name, usage, cost_usd),
                    "latency": round(max(0.0, min(1.0, elapsed_ms / 10000)), 3),
                    "api_availability": 1.0,
                    "answer_correctness": judge.get("objective_score") if judge.get("objective_score") is not None else judge["score"],
                    "objective_feasible": objective_feasible(judge.get("objective_score")),
                    "reliability": round(float(judge.get("objective_score") if judge.get("objective_score") is not None else judge["score"]), 3),
                },
                "error": None,
            }
        except Exception as error:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "ok": False,
                "repeat": repeat_index,
                "model": model_name,
                "task_id": task["id"],
                "response": "",
                "usage": {"prompt_tokens": estimate_tokens(prompt), "completion_tokens": 0, "total_tokens": estimate_tokens(prompt)},
                "latency_ms": elapsed_ms,
                "raw_cost_usd": 0.0,
                "quality_source": "failed_call",
                "judge_model": None,
                "judge_reason": "模型调用失败，质量记为 0。",
                "judge_dimensions": {},
                "evaluation_profile": task_evaluation_profile(task),
                "prompt_audit": prompt_audit,
                "metrics": {
                    "quality": 0.0,
                    "cost": model_profile(model_name)["cost"],
                    "latency": 1.0,
                    "api_availability": 0.0,
                    "answer_correctness": 0.0,
                    "objective_feasible": False,
                    "reliability": 0.0,
                },
                "error": str(getattr(error, "detail", error))[:500],
            }

    def aggregate_repeated_runs(model_name: str, task: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        repeat_count = max(1, len(runs))
        success_runs = [item for item in runs if item.get("ok")]
        success_count = len(success_runs)
        usage_total = {
            "prompt_tokens": sum(int((item.get("usage") or {}).get("prompt_tokens", 0)) for item in runs),
            "completion_tokens": sum(int((item.get("usage") or {}).get("completion_tokens", 0)) for item in runs),
            "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens", 0)) for item in runs),
        }
        avg_usage = {
            key: int(round(value / repeat_count))
            for key, value in usage_total.items()
        }
        avg_latency_ms = round(
            sum(float(item.get("latency_ms") or 0.0) for item in runs) / repeat_count,
            2,
        )
        avg_quality = round(
            sum(float((item.get("metrics") or {}).get("quality", 0.0)) for item in runs) / repeat_count,
            3,
        )
        avg_cost_usd = round(
            sum(float(item.get("raw_cost_usd") or 0.0) for item in runs) / repeat_count,
            8,
        )
        api_availability = round(success_count / repeat_count, 3)
        objective_values = [float(item["objective_score"]) for item in runs if item.get("objective_score") is not None]
        avg_objective = round(sum(objective_values) / len(objective_values), 3) if objective_values else None
        answer_correctness = avg_objective if avg_objective is not None else avg_quality
        reliability = round(api_availability * answer_correctness, 3)
        best_run = max(
            runs,
            key=lambda item: float((item.get("metrics") or {}).get("quality", 0.0)),
        ) if runs else {}
        return {
            "ok": success_count > 0,
            "model": model_name,
            "task_id": task["id"],
            "repeat_count": repeat_count,
            "success_count": success_count,
            "response": best_run.get("response", ""),
            "usage": avg_usage,
            "usage_total": usage_total,
            "latency_ms": avg_latency_ms,
            "raw_cost_usd": avg_cost_usd,
            "quality_source": best_run.get("quality_source", "aggregate"),
            "judge_model": best_run.get("judge_model"),
            "reviewer_model": best_run.get("reviewer_model"),
            "judge_scores": best_run.get("judge_scores", []),
            "judge_attempts": best_run.get("judge_attempts", []),
            "judge_cost_usd": round(sum(float(item.get("judge_cost_usd") or 0.0) for item in runs) / repeat_count, 8),
            "objective_score": avg_objective,
            "objective_feasible": objective_feasible(avg_objective),
            "judge_disagreement": best_run.get("judge_disagreement", 0.0),
            "manual_review_required": any(bool(item.get("manual_review_required")) for item in runs),
            "judge_reason": best_run.get("judge_reason", "多轮运行聚合结果。"),
            "judge_dimensions": best_run.get("judge_dimensions", {}),
            "evaluation_profile": task_evaluation_profile(task),
            "runs": runs,
            "metrics": {
                "quality": avg_quality,
                "cost": normalized_cost_score(model_name, avg_usage, avg_cost_usd),
                "latency": round(max(0.0, min(1.0, avg_latency_ms / 10000)), 3),
                "api_availability": api_availability,
                "answer_correctness": answer_correctness,
                "objective_feasible": objective_feasible(avg_objective),
                "reliability": reliability,
            },
            "error": None if success_count else "; ".join(str(item.get("error", "")) for item in runs)[:500],
        }

    def metrics_for_assignment(
        task: Dict[str, Any],
        model_name: str,
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        if real_results is not None:
            real_item = real_results.get((task["id"], model_name))
            if real_item and "metrics" in real_item:
                return real_item["metrics"]
        return evaluate_model_for_task(model_name, task)

    def assignment_fitness(
        tasks: List[Dict[str, Any]],
        assignment: List[int],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> float:
        if not tasks or not models:
            return 0.0
        total = 0.0
        usage_counter = Counter()
        for task, model_idx in zip(tasks, assignment):
            model_name = models[model_idx % len(models)]
            usage_counter[model_name] += 1
            metrics_payload = metrics_for_assignment(task, model_name, real_results)
            score = utility_score(metrics_payload)
            if task["risk"] >= 0.75 and metrics_payload.get("reliability", 0.0) < 0.65:
                score = max(0.0, score - 0.12)
            total += score
        avg_score = total / len(tasks)
        ideal_load = len(tasks) / len(models)
        imbalance = sum(abs(usage_counter.get(model, 0) - ideal_load) for model in models) / max(1, len(tasks))
        return round(max(0.0, avg_score - 0.025 * imbalance), 5)

    def optimize_with_pso(
        tasks: List[Dict[str, Any]],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> List[int]:
        rng = random.Random(20260629)
        if not tasks or not models:
            return []
        particle_count = min(24, max(10, len(tasks)))
        iterations = 36
        particles = [
            [rng.randrange(len(models)) for _ in tasks]
            for _ in range(particle_count)
        ]
        personal_best = [item[:] for item in particles]
        personal_scores = [assignment_fitness(tasks, item, models, real_results) for item in particles]
        global_best = personal_best[max(range(particle_count), key=lambda idx: personal_scores[idx])][:]
        global_score = max(personal_scores)

        for _ in range(iterations):
            for idx, particle in enumerate(particles):
                for task_idx in range(len(tasks)):
                    roll = rng.random()
                    if roll < 0.42:
                        particle[task_idx] = personal_best[idx][task_idx]
                    elif roll < 0.78:
                        particle[task_idx] = global_best[task_idx]
                    elif roll < 0.90:
                        scores = [
                            utility_score(metrics_for_assignment(tasks[task_idx], model, real_results))
                            for model in models
                        ]
                        particle[task_idx] = max(range(len(models)), key=lambda model_idx: scores[model_idx])
                    else:
                        particle[task_idx] = rng.randrange(len(models))

                score = assignment_fitness(tasks, particle, models, real_results)
                if score > personal_scores[idx]:
                    personal_scores[idx] = score
                    personal_best[idx] = particle[:]
                    if score > global_score:
                        global_score = score
                        global_best = particle[:]
        return global_best

    def optimize_with_ga(
        tasks: List[Dict[str, Any]],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> List[int]:
        rng = random.Random(20260630)
        if not tasks or not models:
            return []
        population_size = min(28, max(12, len(tasks)))
        generations = 42
        population = [
            [rng.randrange(len(models)) for _ in tasks]
            for _ in range(population_size)
        ]

        def best_model_for_task(task: Dict[str, Any]) -> int:
            scores = [
                utility_score(metrics_for_assignment(task, model, real_results))
                for model in models
            ]
            return max(range(len(models)), key=lambda model_idx: scores[model_idx])

        population.append([best_model_for_task(task) for task in tasks])

        for _ in range(generations):
            ranked = sorted(
                population,
                key=lambda item: assignment_fitness(tasks, item, models, real_results),
                reverse=True,
            )
            survivors = ranked[: max(4, population_size // 3)]
            next_population = [item[:] for item in survivors[:2]]
            while len(next_population) < population_size:
                parent_a = rng.choice(survivors)
                parent_b = rng.choice(survivors)
                if len(tasks) > 1:
                    cut = rng.randrange(1, len(tasks))
                    child = parent_a[:cut] + parent_b[cut:]
                else:
                    child = parent_a[:]
                for task_idx in range(len(child)):
                    if rng.random() < 0.12:
                        child[task_idx] = rng.randrange(len(models))
                next_population.append(child)
            population = next_population

        return max(
            population,
            key=lambda item: assignment_fitness(tasks, item, models, real_results),
        )

    def build_scheduled_task_rows(
        strategy_id: str,
        tasks: List[Dict[str, Any]],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if strategy_id == "pso_scheduler":
            scheduler_method = "pso"
            reason_prefix = "PSO 粒子群调度：在预算、延迟、质量和负载均衡约束下，对整批任务搜索整体效用更高的模型分配。"
        else:
            scheduler_method = "ga"
            reason_prefix = "GA 遗传调度：把整批任务分配看作种群个体，通过选择、交叉、变异比较可行解。"

        scheduler_result: Dict[str, Any] = {}
        if solve_batch_assignment is not None and BatchConstraints is not None:
            batch_constraints = BatchConstraints(
                total_budget=max(1.0, len(tasks) * 0.78),
                total_latency=max(1.0, len(tasks) * 0.78),
                min_quality_per_task=0.58,
                min_reliability_per_task=0.58,
                max_calls_per_model=max(1, math.ceil(len(tasks) * 0.72)),
            )

            def metric_getter(task: Dict[str, Any], model_name: str) -> Dict[str, float]:
                return metrics_for_assignment(task, model_name, real_results)

            scheduler_result = solve_batch_assignment(
                tasks,
                models,
                batch_constraints,
                method=scheduler_method,
                metric_getter=metric_getter,
                utility_fn=utility_score,
            )
            assignment = scheduler_result.get("assignment", [])
        elif strategy_id == "pso_scheduler":
            assignment = optimize_with_pso(tasks, models, real_results)
        else:
            assignment = optimize_with_ga(tasks, models, real_results)

        fitness_value = scheduler_result.get("fitness")
        trace = scheduler_result.get("trace", [])
        violations = scheduler_result.get("constraint_violations", [])
        trace_tail = trace[-1] if trace else {}
        reason_suffix = ""
        if fitness_value is not None:
            reason_suffix = f" 本轮最优适应度 {float(fitness_value):.3f}"
            if trace_tail:
                step_value = trace_tail.get("iteration", trace_tail.get("generation", "-"))
                reason_suffix += f"，搜索到第 {step_value} 轮。"
            else:
                reason_suffix += "。"
        if violations:
            reason_suffix += " 仍有约束压力：" + "、".join(violations[:2]) + "。"

        rows = []
        for task, model_idx in zip(tasks, assignment):
            selected_model = models[model_idx % len(models)]
            task_metric = metrics_for_assignment(task, selected_model, real_results)
            candidate_scores = {
                model: utility_score(metrics_for_assignment(task, model, real_results))
                for model in models
            }
            real_item = (real_results or {}).get((task["id"], selected_model), {})
            rows.append({
                "task_id": task["id"],
                "task_type": task["type"],
                "query": task["query"],
                "agent_stage": task["agent_stage"],
                "risk": task["risk"],
                "requires_verification": task["requires_verification"],
                "selected_model": selected_model,
                "score": utility_score(task_metric),
                "router_overhead_ms": estimate_router_overhead_ms(strategy_id, task),
                "candidate_scores": candidate_scores,
                "metrics": task_metric,
                "reason": reason_prefix + reason_suffix,
                "scheduler_trace": trace,
                "scheduler_fitness": fitness_value,
                "constraint_violations": violations,
                "latency_ms": real_item.get("latency_ms"),
                "usage": real_item.get("usage"),
                "raw_cost_usd": real_item.get("raw_cost_usd"),
                "repeat_count": real_item.get("repeat_count"),
                "success_count": real_item.get("success_count"),
                "quality_source": real_item.get("quality_source"),
                        "judge_model": real_item.get("judge_model"),
                        "reviewer_model": real_item.get("reviewer_model"),
                        "judge_scores": real_item.get("judge_scores", []),
                        "judge_attempts": real_item.get("judge_attempts", []),
                        "judge_cost_usd": real_item.get("judge_cost_usd", 0.0),
                        "objective_score": real_item.get("objective_score"),
                        "judge_disagreement": real_item.get("judge_disagreement", 0.0),
                        "manual_review_required": real_item.get("manual_review_required", False),
                        "judge_reason": real_item.get("judge_reason"),
                "judge_dimensions": real_item.get("judge_dimensions", {}),
                "response_excerpt": (real_item.get("response") or "")[:500],
                "evaluation_profile": real_item.get("evaluation_profile"),
                "error": real_item.get("error"),
            })
        return rows

    def choose_model_by_multi_objective(task: Dict[str, Any], models: List[str]) -> Dict[str, Any]:
        scored = []
        for model_name in models:
            item_metrics = evaluate_model_for_task(model_name, task)
            if task["risk"] >= 0.75 and item_metrics["reliability"] < 0.65:
                hard_penalty = 0.12
            else:
                hard_penalty = 0.0
            score = max(0.0, utility_score(item_metrics) - hard_penalty)
            scored.append({
                "model": model_name,
                "score": round(score, 4),
                "metrics": item_metrics,
            })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return {
            "selected_model": scored[0]["model"],
            "score": scored[0]["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored},
            "metrics": scored[0]["metrics"],
            "reason": "按质量、成本、延迟、可靠性综合效用选择得分最高的模型。",
        }

    def choose_model_by_constrained_multi_objective(
        task: Dict[str, Any],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        constraints = task_constraint_profile(task)
        scored = []
        for model_name in models:
            item_metrics = metrics_for_assignment(task, model_name, real_results)
            violations = constraint_violations(item_metrics, constraints)
            scored.append({
                "model": model_name,
                "score": utility_score(item_metrics),
                "metrics": item_metrics,
                "feasible": not violations,
                "violations": violations,
            })

        feasible = [item for item in scored if item["feasible"]]
        relaxed = False
        candidate_pool = feasible
        if not candidate_pool:
            relaxed = True
            candidate_pool = scored

        front = pareto_front(candidate_pool)
        if not front:
            front = sorted(candidate_pool, key=lambda item: item["score"], reverse=True)
        selected = front[0]
        scored_sorted = sorted(scored, key=lambda item: item["score"], reverse=True)
        rejected = [
            {
                "model": item["model"],
                "violations": item["violations"],
            }
            for item in scored_sorted
            if item["violations"]
        ]
        constraint_text = (
            f"质量≥{constraints['min_quality']:.2f}、"
            f"成本≤{constraints['max_cost']:.2f}、"
            f"延迟≤{constraints['max_latency']:.2f}、"
            f"可靠性≥{constraints['min_reliability']:.2f}"
        )
        reason = (
            "约束 Pareto 多目标路由：先按任务场景约束过滤候选模型，"
            "再在 Pareto 前沿中选择综合效用最高的模型。"
            f" 本任务约束为 {constraint_text}。"
        )
        if relaxed:
            reason += " 当前没有模型完全满足约束，因此放宽为全候选 Pareto 比较。"
        else:
            reason += f" 满足约束的模型有 {', '.join(item['model'] for item in feasible)}。"
        return {
            "selected_model": selected["model"],
            "score": selected["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored_sorted},
            "metrics": selected["metrics"],
            "reason": reason,
            "constraints": {
                "min_quality": constraints["min_quality"],
                "max_cost": constraints["max_cost"],
                "max_latency": constraints["max_latency"],
                "min_reliability": constraints["min_reliability"],
                "labels": constraints["labels"],
                "relaxed": relaxed,
            },
            "pareto_front": [item["model"] for item in front],
            "feasible_models": [item["model"] for item in feasible],
            "rejected_models": rejected,
            "candidate_details": [
                {
                    "model": item["model"],
                    "score": item["score"],
                    "metrics": item["metrics"],
                    "feasible": item["feasible"],
                    "violations": item["violations"],
                    "pareto": item["model"] in {front_item["model"] for front_item in front},
                }
                for item in scored_sorted
            ],
        }

    def choose_model_by_finance_risk_adaptive(
        task: Dict[str, Any],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        constraints = finance_constraints(task)
        profile = finance_task_profile(task)
        scored = []
        for model_name in models:
            item_metrics = metrics_for_assignment(task, model_name, real_results)
            violations = constraint_violations(item_metrics, constraints)
            nonlinear_score, nonlinear_params = finance_nonlinear_utility(item_metrics, task)
            linear_score = utility_score(item_metrics)
            scored.append({
                "model": model_name,
                "score": nonlinear_score,
                "linear_score": linear_score,
                "nonlinear_score": nonlinear_score,
                "nonlinear_params": nonlinear_params,
                "metrics": item_metrics,
                "feasible": not violations,
                "violations": violations,
            })

        feasible = [item for item in scored if item["feasible"]]
        relaxed = False
        candidate_pool = feasible
        if not candidate_pool:
            relaxed = True
            candidate_pool = scored

        front = pareto_front(candidate_pool)
        if not front:
            front = sorted(candidate_pool, key=lambda item: item["score"], reverse=True)
        selected = front[0]
        scored_sorted = sorted(scored, key=lambda item: item["score"], reverse=True)
        rejected = [
            {
                "model": item["model"],
                "violations": item["violations"],
            }
            for item in scored_sorted
            if item["violations"]
        ]
        reason = (
            "金融风险自适应非线性路由：先按金融风险硬约束过滤候选模型，"
            "再在 Pareto 前沿中使用 Q^alpha * R^beta * exp(-gamma*C) * exp(-delta*L) 选择模型。"
            f" 风险等级={profile['risk_level']}，领域={profile['domain']}。"
        )
        if relaxed:
            reason += " 当前没有模型完全满足硬约束，因此放宽为全候选 Pareto 比较。"
        return {
            "selected_model": selected["model"],
            "score": selected["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored_sorted},
            "metrics": selected["metrics"],
            "reason": reason,
            "constraints": {
                "min_quality": constraints["min_quality"],
                "max_cost": constraints["max_cost"],
                "max_latency": constraints["max_latency"],
                "min_reliability": constraints["min_reliability"],
                "labels": constraints["labels"],
                "relaxed": relaxed,
                "risk_level": profile["risk_level"],
                "domain": profile["domain"],
            },
            "pareto_front": [item["model"] for item in front],
            "feasible_models": [item["model"] for item in feasible],
            "rejected_models": rejected,
            "candidate_details": [
                {
                    "model": item["model"],
                    "score": item["score"],
                    "linear_score": item["linear_score"],
                    "nonlinear_score": item["nonlinear_score"],
                    "nonlinear_params": item["nonlinear_params"],
                    "metrics": item["metrics"],
                    "feasible": item["feasible"],
                    "violations": item["violations"],
                    "pareto": item["model"] in {front_item["model"] for front_item in front},
                }
                for item in scored_sorted
            ],
            "linear_score": selected["linear_score"],
            "nonlinear_score": selected["nonlinear_score"],
            "nonlinear_params": selected["nonlinear_params"],
            "risk_level": profile["risk_level"],
            "domain": profile["domain"],
        }

    def stable_model_pick(task: Dict[str, Any], models: List[str], offset: int = 0) -> str:
        if not models:
            return "-"
        seed = sum(ord(char) for char in str(task.get("id", ""))) + offset
        return models[seed % len(models)]

    def choose_model_by_contextual_bandit(task: Dict[str, Any], models: List[str]) -> Dict[str, Any]:
        scored = []
        history = experience_store.model_statistics(str(task.get("query") or ""), models)
        total_count = sum(float(item.get("history_count") or 0.0) for item in history.values())
        for model_name in models:
            item_metrics = evaluate_model_for_task(model_name, task)
            prior = utility_score(item_metrics)
            model_history = history.get(model_name, {})
            history_count = float(model_history.get("history_count") or 0.0)
            historical_reward = float(model_history.get("historical_reward") or prior)
            positive = float(model_history.get("positive_weight") or 0.0)
            negative = float(model_history.get("negative_weight") or 0.0)
            success_rate = positive / max(1e-9, positive + negative) if positive + negative else float(item_metrics["reliability"])
            exploration = min(0.16, 0.08 * math.sqrt(math.log1p(total_count + 1.0) / (history_count + 1.0)))
            score = round(min(1.0, 0.58 * historical_reward + 0.24 * prior + 0.12 * success_rate + exploration), 4)
            scored.append({
                "model": model_name, "score": score, "metrics": item_metrics, "prior": prior,
                "historical_reward": round(historical_reward, 4), "success_rate": round(success_rate, 4),
                "exploration": round(exploration, 4), "history_count": round(history_count, 4),
            })
        scored.sort(key=lambda item: item["score"], reverse=True)
        selected = scored[0]
        return {
            "selected_model": selected["model"], "score": selected["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored},
            "metrics": selected["metrics"],
            "reason": "在线反馈路由：使用已验证路由经验的真实奖励、成功率、模型先验和探索项；pending 记录不参与学习。",
            "candidate_details": scored,
            "context_key": f"{task.get('type')}|risk={task.get('risk')}|complexity={task.get('complexity')}",
            "history_source": "run_logs/routing_experience.jsonl",
        }

    def uncertainty_from_candidate_scores(scored: List[Dict[str, Any]]) -> Dict[str, float]:
        if len(scored) < 2:
            return {"confidence": 1.0, "uncertainty": 0.0, "margin": 1.0}
        margin = float(scored[0].get("score", 0.0)) - float(scored[1].get("score", 0.0))
        uncertainty = max(0.0, min(1.0, 1.0 - margin / 0.25))
        return {
            "confidence": round(1.0 - uncertainty, 4),
            "uncertainty": round(uncertainty, 4),
            "margin": round(margin, 4),
        }

    def choose_model_by_cascading_bandit_pareto(
        task: Dict[str, Any],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        constraints = finance_constraints(task)
        profile = finance_task_profile(task)
        scored = []
        for model_name in models:
            item_metrics = metrics_for_assignment(task, model_name, real_results)
            violations = constraint_violations(item_metrics, constraints)
            nonlinear_score, nonlinear_params = finance_nonlinear_utility(item_metrics, task)
            prior = utility_score(item_metrics)
            pseudo = (sum(ord(ch) for ch in f"{task.get('id')}:{model_name}") % 9) / 100.0
            success_rate = max(0.0, min(1.0, item_metrics["reliability"] + pseudo))
            cascade_score = (
                0.30 * nonlinear_score
                + 0.22 * prior
                + 0.18 * success_rate
                + 0.18 * (1.0 - item_metrics["cost"])
                + 0.12 * (1.0 - item_metrics["latency"])
            )
            if profile["risk_level"] == "high":
                cascade_score += 0.12 * item_metrics["quality"] + 0.10 * item_metrics["reliability"]
            scored.append({
                "model": model_name,
                "score": round(max(0.0, min(1.0, cascade_score)), 4),
                "linear_score": prior,
                "nonlinear_score": nonlinear_score,
                "nonlinear_params": nonlinear_params,
                "metrics": item_metrics,
                "feasible": not violations,
                "violations": violations,
                "success_rate": round(success_rate, 4),
            })
        scored_sorted = sorted(scored, key=lambda item: item["score"], reverse=True)
        feasible = [item for item in scored_sorted if item["feasible"]]
        candidate_pool = feasible or scored_sorted
        front = pareto_front(candidate_pool) or candidate_pool
        cheap_start = sorted(
            front,
            key=lambda item: (
                item["metrics"]["cost"],
                item["metrics"]["latency"],
                -item["score"],
            ),
        )[0]
        strongest = max(
            scored_sorted,
            key=lambda item: (
                item["metrics"]["quality"],
                item["metrics"]["reliability"],
                item["score"],
            ),
        )
        uncertainty = uncertainty_from_candidate_scores(scored_sorted)
        threshold = 0.64 if profile["risk_level"] == "high" else 0.58
        selected = strongest if uncertainty["confidence"] < threshold and profile["risk_level"] == "high" else cheap_start
        escalation_chain = [
            item["model"]
            for item in scored_sorted
            if item["model"] != selected["model"]
        ][:3]
        return {
            "selected_model": selected["model"],
            "score": selected["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored_sorted},
            "metrics": selected["metrics"],
            "reason": (
                "级联 Bandit Pareto 路由：先选择低成本 Pareto 候选作为起步模型，"
                "再根据候选分差估计置信度；高风险且不确定时升级到更强模型。"
                f" 风险={profile['risk_level']}，置信度={uncertainty['confidence']:.2f}，"
                f"不确定性={uncertainty['uncertainty']:.2f}，升级链={', '.join(escalation_chain) or '-'}。"
            ),
            "constraints": {
                "min_quality": constraints["min_quality"],
                "max_cost": constraints["max_cost"],
                "max_latency": constraints["max_latency"],
                "min_reliability": constraints["min_reliability"],
                "labels": constraints["labels"],
                "risk_level": profile["risk_level"],
                "domain": profile["domain"],
            },
            "pareto_front": [item["model"] for item in front],
            "feasible_models": [item["model"] for item in feasible],
            "rejected_models": [
                {"model": item["model"], "violations": item["violations"]}
                for item in scored_sorted
                if item["violations"]
            ],
            "candidate_details": scored_sorted,
            "linear_score": selected["linear_score"],
            "nonlinear_score": selected["nonlinear_score"],
            "nonlinear_params": selected["nonlinear_params"],
            "confidence": uncertainty["confidence"],
            "uncertainty": uncertainty["uncertainty"],
            "score_margin": uncertainty["margin"],
            "escalation_chain": escalation_chain,
            "risk_level": profile["risk_level"],
            "domain": profile["domain"],
        }

    def choose_model_by_latency_sla_pareto(
        task: Dict[str, Any],
        models: List[str],
        real_results: Optional[Dict[tuple[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        profile = finance_task_profile(task)
        if profile["risk_level"] == "high":
            sla = {"max_latency": 0.72, "max_cost": 0.90, "min_quality": 0.84, "min_reliability": 0.80}
        elif float(task.get("complexity", 0.0)) >= 0.55:
            sla = {"max_latency": 0.65, "max_cost": 0.78, "min_quality": 0.80, "min_reliability": 0.74}
        else:
            sla = {"max_latency": 0.45, "max_cost": 0.62, "min_quality": 0.72, "min_reliability": 0.68}
        scored = []
        for model_name in models:
            item_metrics = metrics_for_assignment(task, model_name, real_results)
            violations = []
            if item_metrics["latency"] > sla["max_latency"]:
                violations.append("延迟超过 SLA")
            if item_metrics["cost"] > sla["max_cost"]:
                violations.append("成本超过 SLA")
            if item_metrics["quality"] < sla["min_quality"]:
                violations.append("质量低于 SLA")
            if item_metrics["reliability"] < sla["min_reliability"]:
                violations.append("可靠性低于 SLA")
            nonlinear_score, nonlinear_params = finance_nonlinear_utility(item_metrics, task)
            score = round(
                max(0.0, min(1.0, 0.42 * nonlinear_score + 0.24 * (1.0 - item_metrics["latency"]) + 0.18 * (1.0 - item_metrics["cost"]) + 0.16 * item_metrics["reliability"])),
                4,
            )
            scored.append({
                "model": model_name,
                "score": score,
                "linear_score": utility_score(item_metrics),
                "nonlinear_score": nonlinear_score,
                "nonlinear_params": nonlinear_params,
                "metrics": item_metrics,
                "feasible": not violations,
                "violations": violations,
            })
        scored_sorted = sorted(scored, key=lambda item: item["score"], reverse=True)
        feasible = [item for item in scored_sorted if item["feasible"]]
        candidate_pool = feasible or scored_sorted
        front = pareto_front(candidate_pool) or candidate_pool
        selected = front[0]
        return {
            "selected_model": selected["model"],
            "score": selected["score"],
            "candidate_scores": {item["model"]: item["score"] for item in scored_sorted},
            "metrics": selected["metrics"],
            "reason": (
                "Latency-SLA Pareto 路由：先检查延迟、成本、质量和可靠性 SLA，"
                "再在满足约束的 Pareto 前沿中选择综合得分最高的模型。"
                f" SLA={sla}，{'没有模型完全满足，已放宽为全候选比较。' if not feasible else '已找到满足 SLA 的候选。'}"
            ),
            "constraints": {
                **sla,
                "labels": ["延迟 SLA", "成本 SLA", "质量下限", "可靠性下限"],
                "relaxed": not bool(feasible),
                "risk_level": profile["risk_level"],
                "domain": profile["domain"],
            },
            "pareto_front": [item["model"] for item in front],
            "feasible_models": [item["model"] for item in feasible],
            "rejected_models": [
                {"model": item["model"], "violations": item["violations"]}
                for item in scored_sorted
                if item["violations"]
            ],
            "candidate_details": scored_sorted,
            "linear_score": selected["linear_score"],
            "nonlinear_score": selected["nonlinear_score"],
            "nonlinear_params": selected["nonlinear_params"],
            "risk_level": profile["risk_level"],
            "domain": profile["domain"],
        }

    def pick_by_service_strategy(service_id: str, task: Dict[str, Any], models: List[str]) -> tuple[str, str]:
        if service_id == "rules":
            if task["type"] in {"代码生成", "文本摘要"} and "qwen-plus" in models:
                return "qwen-plus", "服务层规则路由：代码和摘要类任务优先交给 Qwen。"
            if task["type"] in {"逻辑推理", "专业问答"} and "deepseek-chat" in models:
                return "deepseek-chat", "服务层规则路由：推理和专业问答优先交给 DeepSeek。"
            if task["type"] == "内容创作" and "doubao" in models:
                return "doubao", "服务层规则路由：内容创作优先交给豆包。"
            return models[0], "服务层规则路由：未命中特定规则，使用默认模型。"
        if service_id == "random":
            return stable_model_pick(task, models, 3), "服务层随机路由：用固定种子模拟随机选择，便于复现实验。"
        if service_id == "round_robin":
            return stable_model_pick(task, models, 7), "服务层轮询路由：按任务顺序模拟轮流分配模型。"
        if service_id == "llm":
            preferred = task.get("expected") or []
            selected = next((name for name in preferred if name in models), models[0])
            return selected, "LLM 裁判路由模拟：根据任务描述选择更可能合适的模型。"
        if service_id == "llmrouter":
            preferred = task.get("expected") or []
            selected = next((name for name in preferred if name in models), models[0])
            return selected, "服务层算法路由：把任务交给当前算法层路由器做模型选择。"
        if service_id == "cascading_bandit_pareto":
            result = choose_model_by_cascading_bandit_pareto(task, models)
            return result["selected_model"], result["reason"]
        if service_id == "latency_sla_pareto":
            result = choose_model_by_latency_sla_pareto(task, models)
            return result["selected_model"], result["reason"]
        return models[0], "未知服务层策略，使用默认模型。"

    def pick_by_algorithm_router(algorithm_id: str, task: Dict[str, Any], models: List[str]) -> tuple[str, str]:
        preferred = task.get("expected") or []
        expected_first = next((name for name in preferred if name in models), models[0])
        cheapest = min(models, key=lambda name: (model_profile(name)["cost"], model_profile(name)["latency"]))
        fastest = min(models, key=lambda name: model_profile(name)["latency"])
        strongest = max(models, key=lambda name: model_profile(name)["quality"])
        most_reliable = max(models, key=lambda name: model_profile(name)["reliability"])

        if algorithm_id == "smallest_llm":
            return cheapest, "SmallestLLM：模拟选择成本和延迟最低的轻量模型。"
        if algorithm_id == "largest_llm":
            return strongest, "LargestLLM：模拟选择基础质量最高的强模型。"
        if algorithm_id in {"graphrouter", "knnrouter", "svmrouter", "mlprouter", "mfrouter", "elorouter", "dcrouter", "causallm_router"}:
            return expected_first, f"{algorithm_id}：按任务类型和历史偏好模拟选择最匹配模型。"
        if algorithm_id == "hybrid_llm":
            selected = cheapest if task["complexity"] < 0.45 and task["risk"] < 0.4 else strongest
            return selected, "HybridLLM：简单低风险任务用轻量模型，复杂任务升级到强模型。"
        if algorithm_id == "automixrouter":
            selected = fastest if task["complexity"] < 0.5 and not task["requires_verification"] else expected_first
            return selected, "AutoMix：先偏向低延迟模型，复杂或需验证任务再升级。"
        if algorithm_id == "gmtrouter":
            selected = "qwen-plus" if "qwen-plus" in models else expected_first
            return selected, "GMTRouter：模拟结合用户、会话和任务关系后的偏好选择。"
        if algorithm_id == "personalizedrouter":
            selected = "doubao" if task["type"] == "内容创作" and "doubao" in models else expected_first
            return selected, "PersonalizedRouter：模拟根据用户偏好对创作类任务做个性化选择。"
        if algorithm_id in {"knnmultiroundrouter", "llmmultiroundrouter", "router_r1"}:
            selected = most_reliable if task["risk"] >= 0.75 else expected_first
            return selected, f"{algorithm_id}：模拟多步拆解/推理后优先选择可靠模型。"
        if algorithm_id == "randomrouter":
            return stable_model_pick(task, models, 11), "RandomRouter 插件：用固定种子模拟随机选择。"
        if algorithm_id == "thresholdrouter":
            selected = cheapest if task["complexity"] < 0.55 else strongest
            return selected, "ThresholdRouter 插件：低复杂度用轻量模型，高复杂度用强模型。"
        return expected_first, f"{algorithm_id}：使用通用兼容模式模拟路由结果。"

    async def simulate_experiment_strategy(
        strategy_id: str,
        task: Dict[str, Any],
        models: List[str],
    ) -> Dict[str, Any]:
        if not models:
            return {"selected_model": "-", "score": 0.0, "metrics": {}, "reason": "没有候选模型。"}

        if strategy_id == "fixed_strong":
            selected = "deepseek-chat" if "deepseek-chat" in models else models[0]
            reason = "固定高性能模型基线：所有任务都交给能力较强的模型。"
        elif strategy_id == "fixed_lightweight":
            selected = next((name for name in ("gemini-2.5-flash", "doubao", "qwen-plus") if name in models), models[0])
            reason = "固定轻量模型基线：所有任务都交给成本和延迟较低的模型。"
        elif strategy_id == "service_contextual_bandit":
            return choose_model_by_contextual_bandit(task, models)
        elif strategy_id == "service_cascading_bandit_pareto":
            return choose_model_by_cascading_bandit_pareto(task, models)
        elif strategy_id == "service_latency_sla_pareto":
            return choose_model_by_latency_sla_pareto(task, models)
        elif strategy_id == "service_finance_risk_adaptive":
            return choose_model_by_finance_risk_adaptive(task, models)
        elif strategy_id.startswith("service_"):
            selected, reason = pick_by_service_strategy(strategy_id.replace("service_", "", 1), task, models)
        elif strategy_id.startswith("algorithm_"):
            selected, reason = pick_by_algorithm_router(strategy_id.replace("algorithm_", "", 1), task, models)
        elif strategy_id == "constrained_multi_objective":
            return choose_model_by_constrained_multi_objective(task, models)
        elif strategy_id == "finance_risk_adaptive":
            return choose_model_by_finance_risk_adaptive(task, models)
        elif strategy_id == "multi_objective":
            return choose_model_by_multi_objective(task, models)
        else:
            selected = models[0]
            reason = "未知策略，使用第一个候选模型。"

        item_metrics = evaluate_model_for_task(selected, task)
        return {
            "selected_model": selected,
            "score": utility_score(item_metrics),
            "candidate_scores": {selected: utility_score(item_metrics)},
            "metrics": item_metrics,
            "reason": reason,
        }

    def build_experiment_process_steps(
        mode: str,
        models: List[str],
        total_tasks: List[Dict[str, Any]],
        active_tasks: List[Dict[str, Any]],
        strategies: List[Dict[str, Any]],
        case_rows: List[Dict[str, Any]],
        best_strategy: Dict[str, Any],
        real_call_count: int = 0,
    ) -> List[Dict[str, Any]]:
        active_count = len(active_tasks)
        strategy_count = len(strategies)
        case_count = len(case_rows)
        process_steps = [
            {
                "title": "准备实验任务",
                "detail": f"加载 {len(total_tasks)} 个任务，覆盖通用问答、代码生成、逻辑推理、摘要、专业问答、内容创作和审计合规场景。",
                "value": f"{active_count} 个参与本轮评分",
            },
            {
                "title": "加载候选模型",
                "detail": f"当前参与路由的模型为：{', '.join(models) if models else '暂无可用模型'}。",
                "value": f"{len(models)} 个模型",
            },
            {
                "title": "执行策略对比",
                "detail": (
                    "主实验只评估代表性范式：成本/质量基线、随机基线、KNN、"
                    f"{contrastive_representative_name}、GraphRouter、AutoMix、SLA Pareto 和本文级联/金融风险方法；"
                    "其余同类路由器保留在附录/系统展示中。"
                ),
                "value": f"{strategy_count} 个策略",
            },
        ]
        if mode == "real-sample":
            process_steps.append({
                "title": "真实抽样调用",
                "detail": "先让真实模型回答抽样任务，再把不同策略选择映射到真实回答上计算质量、成本、延迟和可靠性。",
                "value": f"{real_call_count} 次模型调用",
            })
        else:
            process_steps.append({
                "title": "模拟评分",
                "detail": "不消耗外部 API 调用，使用模型画像、任务复杂度、风险等级和多目标权重计算可复现实验分数。",
                "value": "可快速复现",
            })

        constrained_row = next((item for item in strategies if item.get("id") == "constrained_multi_objective"), None)
        constrained_cases = [
            item for item in case_rows
            if item.get("strategy") == "约束 Pareto 多目标路由"
        ]
        pareto_models = sorted({
            model
            for item in constrained_cases
            for model in item.get("pareto_front", [])
        })
        if constrained_row:
            process_steps.append({
                "title": "约束 Pareto 多目标路由",
                "detail": (
                    "先根据任务风险、是否需要验证、复杂度和任务类型生成质量/成本/延迟/可靠性约束，"
                    "再保留 Pareto 前沿候选，最后用综合效用函数做最终选择。"
                    f" 本轮进入 Pareto 前沿的模型包括：{', '.join(pareto_models) if pareto_models else '-'}。"
                ),
                "value": f"效用 {constrained_row.get('summary', {}).get('utility', 0.0):.3f}",
            })

        for strategy_id, strategy_name in (
            ("pso_scheduler", "PSO 粒子群调度"),
            ("ga_scheduler", "GA 遗传调度"),
        ):
            row = next((item for item in strategies if item.get("id") == strategy_id), None)
            selected_rows = [item for item in case_rows if item.get("strategy") == strategy_name]
            selected_counter = Counter(item.get("selected_model", "-") for item in selected_rows)
            top_models = ", ".join(
                f"{name}×{count}"
                for name, count in selected_counter.most_common(3)
            ) or "-"
            utility = row.get("summary", {}).get("utility", 0.0) if row else 0.0
            search_detail = (
                "把整批任务的模型分配看作一个整体方案，通过多轮搜索提升综合效用。"
                if strategy_id == "pso_scheduler"
                else "把任务分配方案看作种群个体，通过选择、交叉和变异逐步筛选更优方案。"
            )
            process_steps.append({
                "title": strategy_name,
                "detail": f"{search_detail} 主要选择分布：{top_models}。",
                "value": f"效用 {utility:.3f}",
            })

        process_steps.extend([
            {
                "title": "生成典型案例",
                "detail": "保留关键策略在每个任务上的候选模型评分、最终模型、选择理由和单任务指标，便于逐条解释。",
                "value": f"{case_count} 条案例",
            },
            {
                "title": "得到本轮结论",
                "detail": f"综合质量、成本、延迟和可靠性后，本轮综合效用最高的是：{best_strategy.get('name', '-')}。",
                "value": f"{best_strategy.get('summary', {}).get('utility', 0.0):.3f}",
            },
            {
                "title": "PPO 当前定位",
                "detail": "PPO 不再进入主实验表。它更适合在收集用户点赞/点踩、人工判分和长期调用日志后，作为在线反馈路由器继续研究。",
                "value": "后续扩展",
            },
        ])
        return process_steps

    async def run_route_only_experiment() -> Dict[str, Any]:
        models = list(config.llms.keys())
        strategy_rows = []
        task_rows = []
        routerbench_rows = []

        for strategy_item in experiment_strategies:
            per_task = []
            totals = Counter()
            if strategy_item["id"] in {"pso_scheduler", "ga_scheduler"}:
                per_task = build_scheduled_task_rows(strategy_item["id"], experiment_tasks, models)
                for row in per_task:
                    task_metric = row["metrics"]
                    for key in ("quality", "cost", "latency", "reliability"):
                        totals[key] += float(task_metric.get(key, 0.0))
                    totals["score"] += float(row.get("score", 0.0))
            else:
                for task in experiment_tasks:
                    result = await simulate_experiment_strategy(strategy_item["id"], task, models)
                    task_metric = result["metrics"]
                    for key in ("quality", "cost", "latency", "reliability"):
                        totals[key] += float(task_metric.get(key, 0.0))
                    totals["score"] += float(result.get("score", 0.0))
                    per_task.append({
                        "task_id": task["id"],
                        "task_type": task["type"],
                        "query": task["query"],
                        "agent_stage": task["agent_stage"],
                        "risk": task["risk"],
                        "requires_verification": task["requires_verification"],
                        "selected_model": result["selected_model"],
                        "score": result["score"],
                        "router_overhead_ms": estimate_router_overhead_ms(strategy_item["id"], task),
                        "candidate_scores": result.get("candidate_scores", {}),
                        "metrics": task_metric,
                        "reason": result["reason"],
                        "constraints": result.get("constraints"),
                        "pareto_front": result.get("pareto_front", []),
                        "feasible_models": result.get("feasible_models", []),
                        "rejected_models": result.get("rejected_models", []),
                        "candidate_details": result.get("candidate_details", []),
                        "linear_score": result.get("linear_score"),
                        "nonlinear_score": result.get("nonlinear_score"),
                        "nonlinear_params": result.get("nonlinear_params"),
                        "risk_level": result.get("risk_level"),
                        "domain": result.get("domain"),
                        "confidence": result.get("confidence"),
                        "uncertainty": result.get("uncertainty"),
                        "score_margin": result.get("score_margin"),
                        "escalation_chain": result.get("escalation_chain", []),
                    })

            count = len(experiment_tasks) or 1
            summary = {
                "quality": round(totals["quality"] / count, 3),
                "cost": round(totals["cost"] / count, 3),
                "latency": round(totals["latency"] / count, 3),
                "reliability": round(totals["reliability"] / count, 3),
                "utility": round(totals["score"] / count, 4),
            }
            strategy_rows.append({**strategy_item, "summary": summary})
            routerbench_rows.extend(
                {
                    **row,
                    "strategy": strategy_item["name"],
                    "strategy_id": strategy_item["id"],
                    "strategy_category": strategy_item.get("category"),
                }
                for row in per_task
            )
            if strategy_item.get("benchmark_scope") == "main":
                task_rows.extend({**row, "strategy": strategy_item["name"]} for row in per_task)

        best = max(strategy_rows, key=lambda item: item["summary"]["utility"])
        payload = {
            "project_basis": {
                "title": "基于模型路由的大模型协同调度优化方法研究",
                "source": "依据申报书中的“模型路由 + 多 Agent 协同调度 + 多目标优化”实验方案整理。",
                "mode": "route-only",
                "note": (
                    f"主实验只保留代表性策略，优先使用 {contrastive_representative_name} 作为"
                    "对比学习/协同过滤范式代表；其余同类策略放入附录，避免算法堆砌。"
                ),
            },
            "weights": experiment_weights,
            "scoring": experiment_scoring,
            "finance_dataset": finance_dataset_summary(),
            "task_set": experiment_tasks,
            "strategies": strategy_rows,
            "appendix_strategies": experiment_appendix_strategies,
            "all_strategies": all_experiment_strategies,
            "strategy_scope_note": (
                f"论文主实验：{len(experiment_strategies)} 个代表性策略；"
                f"附录/系统展示：{len(experiment_appendix_strategies)} 个扩展策略。"
                f" RouterDC {'已进入' if contrastive_representative_id == 'dcrouter' else '未进入'}主实验。"
            ),
            "case_results": task_rows,
            "routerbench_rows": routerbench_rows,
            "best_strategy": best["name"],
            "process_steps": build_experiment_process_steps(
                "route-only",
                models,
                experiment_tasks,
                experiment_tasks,
                strategy_rows,
                task_rows,
                best,
            ),
            "score_source": "模拟评分：模型画像分 + 任务复杂度/风险修正 + 多目标权重公式；不等同于真实线上调用统计。",
            "updated_at": time.time(),
        }
        payload["routerbench"] = build_routerbench(payload)
        experiment_state["last_run"] = payload
        experiment_state["runs"] = int(experiment_state["runs"]) + 1
        persist_experiment_run(payload)
        append_request_log({
            "type": "experiment",
            "status": "success",
            "message": f"已完成 route-only 实验评估，最优策略：{best['name']}。",
        })
        return payload

    def stratified_task_sample(tasks: List[Dict[str, Any]], limit: int, seed: int = 20260727) -> List[Dict[str, Any]]:
        """Round-robin strata so a prefix cannot overrepresent generic tasks or one dataset."""
        size = max(1, min(int(limit or 1), len(tasks), 100))
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for task in tasks:
            key = "|".join((str(task.get("dataset") or "project"), str(task.get("task_type") or task.get("type") or "unknown"), "high" if float(task.get("risk", 0)) >= .75 else "medium" if float(task.get("risk", 0)) >= .45 else "low"))
            groups.setdefault(key, []).append(task)
        rng = random.Random(seed)
        for values in groups.values():
            rng.shuffle(values)
        selected: List[Dict[str, Any]] = []
        keys = sorted(groups)
        while len(selected) < size:
            progressed = False
            for key in keys:
                if groups[key] and len(selected) < size:
                    selected.append(groups[key].pop())
                    progressed = True
            if not progressed:
                break
        rng.shuffle(selected)
        return selected

    def experiment_checkpoint_context(models: List[str], tasks: List[Dict[str, Any]], repeats: int, phase: str) -> Dict[str, Any]:
        protocol_path = Path.cwd() / "data" / "finance_router" / "frozen" / "v1" / "experiment_protocol_v1.json"
        protocol = {}
        try:
            if protocol_path.exists():
                protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        except Exception as error:
            _safe_log(f"[ExperimentCheckpoint] protocol read failed: {error}")
        signature_payload = protocol_signature_payload(
            freeze_id=protocol.get("freeze_id", "unfrozen"),
            dataset_sha256=protocol.get("dataset_sha256"), models=models, tasks=tasks,
            repeats=repeats, phase=phase,
        )
        return {"signature": protocol_signature(signature_payload), "payload": signature_payload}

    def load_experiment_checkpoint(path: Path, signature: str) -> Dict[tuple[str, str, int], Dict[str, Any]]:
        return load_successful(path, signature)

    def append_experiment_checkpoint(path: Path, record: Dict[str, Any]) -> None:
        append_record(path, record)

    def write_experiment_progress(path: Path, payload: Dict[str, Any]) -> None:
        write_progress(path, payload)

    async def run_real_sample_experiment(
        sample_limit: int = 50,
        repeats: int = 3,
        judge_enabled: bool = True,
        development_only: bool = False,
        phase: str = "formal_context_v2",
        selection_mode: str = "stratified",
    ) -> Dict[str, Any]:
        experiment_model_pool = ["deepseek-chat", "qwen-plus", "qwen-turbo", "glm-5.2"]
        healthy = set(healthy_models())
        models = [name for name in experiment_model_pool if name in healthy]
        if len(models) < 2:
            raise HTTPException(status_code=503, detail=f"预注册实验模型池可用模型不足：{models}")
        selected_tasks = (
            select_context_pilot(finance_dataset_tasks, per_dataset=3)
            if selection_mode == "context_pilot_3_per_dataset"
            else stratified_task_sample(finance_dataset_tasks, sample_limit)
        )
        safe_repeats = max(1, min(int(repeats or 1), 5))
        real_results: Dict[tuple[str, str], Dict[str, Any]] = {}
        raw_model_runs: List[Dict[str, Any]] = []
        checkpoint_path = Path.cwd() / "run_logs" / "llmrouter_experiment_checkpoint_v2.jsonl"
        progress_path = Path.cwd() / "run_logs" / "llmrouter_experiment_progress_v2.json"
        checkpoint = experiment_checkpoint_context(models, selected_tasks, safe_repeats, phase)
        completed = {} if development_only else load_experiment_checkpoint(checkpoint_path, checkpoint["signature"])
        total_calls = len(selected_tasks) * len(models) * safe_repeats
        completed_before_start = len(completed)

        for task in selected_tasks:
            for model_name in models:
                runs = []
                for repeat_index in range(1, safe_repeats + 1):
                    checkpoint_key = (str(task["id"]), model_name, repeat_index)
                    resumed = checkpoint_key in completed
                    if resumed:
                        run_result = completed[checkpoint_key]
                    else:
                        run_result = await call_model_for_experiment(
                            model_name, task, repeat_index=repeat_index, judge_enabled=judge_enabled,
                        )
                        if not development_only:
                            if run_result.get("ok") is True:
                                completed[checkpoint_key] = run_result
                            append_experiment_checkpoint(checkpoint_path, {
                                "signature": checkpoint["signature"], "task_id": task["id"],
                                "model": model_name, "repeat": repeat_index, "saved_at": time.time(),
                                "result": run_result,
                            })
                            write_experiment_progress(progress_path, {
                                "status": "running", "signature": checkpoint["signature"],
                                "completed": len(completed), "total": total_calls,
                                "fraction": round(len(completed) / max(1, total_calls), 6),
                                "current_task_id": task["id"], "current_model": model_name,
                                "current_repeat": repeat_index, "resumed_at_start": completed_before_start,
                                "updated_at": time.time(),
                            })
                    runs.append(run_result)
                    raw_model_runs.append({
                        "resumed_from_checkpoint": resumed,
                        "task_id": task["id"],
                        "task_type": task["type"],
                        "query": task["query"],
                        "model": model_name,
                        "repeat": repeat_index,
                        "ok": run_result.get("ok"),
                        "quality": (run_result.get("metrics") or {}).get("quality"),
                        "quality_source": run_result.get("quality_source"),
                        "judge_model": run_result.get("judge_model"),
                        "reviewer_model": run_result.get("reviewer_model"),
                        "judge_scores": run_result.get("judge_scores", []),
                        "judge_attempts": run_result.get("judge_attempts", []),
                        "judge_cost_usd": run_result.get("judge_cost_usd", 0.0),
                        "total_cost_with_judges_usd": round(float(run_result.get("raw_cost_usd") or 0.0) + float(run_result.get("judge_cost_usd") or 0.0), 8),
                        "objective_score": run_result.get("objective_score"),
                        "judge_disagreement": run_result.get("judge_disagreement", 0.0),
                        "manual_review_required": run_result.get("manual_review_required", False),
                        "judge_reason": run_result.get("judge_reason"),
                        "judge_dimensions": run_result.get("judge_dimensions", {}),
                        "prompt_tokens": (run_result.get("usage") or {}).get("prompt_tokens"),
                        "completion_tokens": (run_result.get("usage") or {}).get("completion_tokens"),
                        "total_tokens": (run_result.get("usage") or {}).get("total_tokens"),
                        "raw_cost_usd": run_result.get("raw_cost_usd"),
                        "latency_ms": run_result.get("latency_ms"),
                        "error": run_result.get("error"),
                        "response": run_result.get("response", ""),
                        "prompt_audit": run_result.get("prompt_audit", {}),
                        "api_availability": (run_result.get("metrics") or {}).get("api_availability"),
                        "answer_correctness": (run_result.get("metrics") or {}).get("answer_correctness"),
                        "objective_feasible": (run_result.get("metrics") or {}).get("objective_feasible"),
                    })
                real_results[(task["id"], model_name)] = aggregate_repeated_runs(model_name, task, runs)

        strategy_rows = []
        task_rows = []
        routerbench_rows = []
        for strategy_item in experiment_strategies:
            per_task = []
            totals = Counter()
            if strategy_item["id"] in {"pso_scheduler", "ga_scheduler"}:
                per_task = build_scheduled_task_rows(strategy_item["id"], selected_tasks, models, real_results)
                for row in per_task:
                    task_metric = row["metrics"]
                    for key in ("quality", "cost", "latency", "reliability"):
                        totals[key] += float(task_metric.get(key, 0.0))
                    totals["score"] += float(row.get("score", 0.0))
            else:
                for task in selected_tasks:
                    if strategy_item["id"] == "constrained_multi_objective":
                        constrained_result = choose_model_by_constrained_multi_objective(task, models, real_results)
                        selected_model = constrained_result["selected_model"]
                        score = constrained_result["score"]
                        task_metric = constrained_result["metrics"]
                        reason = constrained_result["reason"]
                        candidate_scores = constrained_result.get("candidate_scores", {})
                        constraints = constrained_result.get("constraints")
                        pareto_front_models = constrained_result.get("pareto_front", [])
                        feasible_models = constrained_result.get("feasible_models", [])
                        rejected_models = constrained_result.get("rejected_models", [])
                        candidate_details = constrained_result.get("candidate_details", [])
                        linear_score = constrained_result.get("linear_score")
                        nonlinear_score = constrained_result.get("nonlinear_score")
                        nonlinear_params = constrained_result.get("nonlinear_params")
                        risk_level = constrained_result.get("risk_level")
                        domain = constrained_result.get("domain")
                        confidence = constrained_result.get("confidence")
                        uncertainty = constrained_result.get("uncertainty")
                        score_margin = constrained_result.get("score_margin")
                        escalation_chain = constrained_result.get("escalation_chain", [])
                    elif strategy_item["id"] == "service_cascading_bandit_pareto":
                        cascade_result = choose_model_by_cascading_bandit_pareto(task, models, real_results)
                        selected_model = cascade_result["selected_model"]
                        score = cascade_result["score"]
                        task_metric = cascade_result["metrics"]
                        reason = cascade_result["reason"]
                        candidate_scores = cascade_result.get("candidate_scores", {})
                        constraints = cascade_result.get("constraints")
                        pareto_front_models = cascade_result.get("pareto_front", [])
                        feasible_models = cascade_result.get("feasible_models", [])
                        rejected_models = cascade_result.get("rejected_models", [])
                        candidate_details = cascade_result.get("candidate_details", [])
                        linear_score = cascade_result.get("linear_score")
                        nonlinear_score = cascade_result.get("nonlinear_score")
                        nonlinear_params = cascade_result.get("nonlinear_params")
                        risk_level = cascade_result.get("risk_level")
                        domain = cascade_result.get("domain")
                        confidence = cascade_result.get("confidence")
                        uncertainty = cascade_result.get("uncertainty")
                        score_margin = cascade_result.get("score_margin")
                        escalation_chain = cascade_result.get("escalation_chain", [])
                    elif strategy_item["id"] == "service_latency_sla_pareto":
                        sla_result = choose_model_by_latency_sla_pareto(task, models, real_results)
                        selected_model = sla_result["selected_model"]
                        score = sla_result["score"]
                        task_metric = sla_result["metrics"]
                        reason = sla_result["reason"]
                        candidate_scores = sla_result.get("candidate_scores", {})
                        constraints = sla_result.get("constraints")
                        pareto_front_models = sla_result.get("pareto_front", [])
                        feasible_models = sla_result.get("feasible_models", [])
                        rejected_models = sla_result.get("rejected_models", [])
                        candidate_details = sla_result.get("candidate_details", [])
                        linear_score = sla_result.get("linear_score")
                        nonlinear_score = sla_result.get("nonlinear_score")
                        nonlinear_params = sla_result.get("nonlinear_params")
                        risk_level = sla_result.get("risk_level")
                        domain = sla_result.get("domain")
                        confidence = sla_result.get("confidence")
                        uncertainty = sla_result.get("uncertainty")
                        score_margin = sla_result.get("score_margin")
                        escalation_chain = sla_result.get("escalation_chain", [])
                    elif strategy_item["id"] in {"finance_risk_adaptive", "service_finance_risk_adaptive"}:
                        finance_result = choose_model_by_finance_risk_adaptive(task, models, real_results)
                        selected_model = finance_result["selected_model"]
                        score = finance_result["score"]
                        task_metric = finance_result["metrics"]
                        reason = finance_result["reason"]
                        candidate_scores = finance_result.get("candidate_scores", {})
                        constraints = finance_result.get("constraints")
                        pareto_front_models = finance_result.get("pareto_front", [])
                        feasible_models = finance_result.get("feasible_models", [])
                        rejected_models = finance_result.get("rejected_models", [])
                        candidate_details = finance_result.get("candidate_details", [])
                        linear_score = finance_result.get("linear_score")
                        nonlinear_score = finance_result.get("nonlinear_score")
                        nonlinear_params = finance_result.get("nonlinear_params")
                        risk_level = finance_result.get("risk_level")
                        domain = finance_result.get("domain")
                        confidence = finance_result.get("confidence")
                        uncertainty = finance_result.get("uncertainty")
                        score_margin = finance_result.get("score_margin")
                        escalation_chain = finance_result.get("escalation_chain", [])
                    elif strategy_item["id"] == "multi_objective":
                        scored = []
                        for model_name in models:
                            metrics_payload = real_results[(task["id"], model_name)]["metrics"]
                            score = utility_score(metrics_payload)
                            if task["risk"] >= 0.75 and metrics_payload["reliability"] < 0.65:
                                score = max(0.0, score - 0.12)
                            scored.append((model_name, score, metrics_payload))
                        scored.sort(key=lambda item: item[1], reverse=True)
                        selected_model, score, task_metric = scored[0]
                        reason = "真实抽样实验：按真实调用得到的质量、成本、延迟和可靠性综合选择。"
                        candidate_scores = {model_name: item_score for model_name, item_score, _ in scored}
                        constraints = None
                        pareto_front_models = []
                        feasible_models = []
                        rejected_models = []
                        candidate_details = []
                        linear_score = None
                        nonlinear_score = None
                        nonlinear_params = None
                        risk_level = None
                        domain = None
                        confidence = None
                        uncertainty = None
                        score_margin = None
                        escalation_chain = []
                    else:
                        selected_result = await simulate_experiment_strategy(strategy_item["id"], task, models)
                        selected_model = selected_result["selected_model"]
                        real_item = real_results.get((task["id"], selected_model))
                        task_metric = real_item["metrics"] if real_item else selected_result["metrics"]
                        score = utility_score(task_metric)
                        reason = selected_result["reason"]
                        candidate_scores = selected_result.get("candidate_scores", {})
                        constraints = selected_result.get("constraints")
                        pareto_front_models = selected_result.get("pareto_front", [])
                        feasible_models = selected_result.get("feasible_models", [])
                        rejected_models = selected_result.get("rejected_models", [])
                        candidate_details = selected_result.get("candidate_details", [])
                        linear_score = selected_result.get("linear_score")
                        nonlinear_score = selected_result.get("nonlinear_score")
                        nonlinear_params = selected_result.get("nonlinear_params")
                        risk_level = selected_result.get("risk_level")
                        domain = selected_result.get("domain")
                        confidence = selected_result.get("confidence")
                        uncertainty = selected_result.get("uncertainty")
                        score_margin = selected_result.get("score_margin")
                        escalation_chain = selected_result.get("escalation_chain", [])

                    for key in ("quality", "cost", "latency", "reliability"):
                        totals[key] += float(task_metric.get(key, 0.0))
                    totals["score"] += float(score)
                    real_item = real_results.get((task["id"], selected_model), {})
                    per_task.append({
                        "task_id": task["id"],
                        "task_type": task["type"],
                        "query": task["query"],
                        "agent_stage": task["agent_stage"],
                        "risk": task["risk"],
                        "requires_verification": task["requires_verification"],
                        "selected_model": selected_model,
                        "score": score,
                        "router_overhead_ms": estimate_router_overhead_ms(strategy_item["id"], task),
                        "candidate_scores": candidate_scores,
                        "metrics": task_metric,
                        "reason": reason,
                        "constraints": constraints,
                        "pareto_front": pareto_front_models,
                        "feasible_models": feasible_models,
                        "rejected_models": rejected_models,
                        "candidate_details": candidate_details,
                        "linear_score": linear_score,
                        "nonlinear_score": nonlinear_score,
                        "nonlinear_params": nonlinear_params,
                        "risk_level": risk_level,
                        "domain": domain,
                        "confidence": confidence,
                        "uncertainty": uncertainty,
                        "score_margin": score_margin,
                        "escalation_chain": escalation_chain,
                        "latency_ms": real_item.get("latency_ms"),
                        "usage": real_item.get("usage"),
                        "raw_cost_usd": real_item.get("raw_cost_usd"),
                        "repeat_count": real_item.get("repeat_count"),
                        "success_count": real_item.get("success_count"),
                        "quality_source": real_item.get("quality_source"),
                "judge_model": real_item.get("judge_model"),
                "judge_reason": real_item.get("judge_reason"),
                "judge_dimensions": real_item.get("judge_dimensions", {}),
                "response_excerpt": (real_item.get("response") or "")[:500],
                        "evaluation_profile": real_item.get("evaluation_profile"),
                        "error": real_item.get("error"),
                    })

            count = len(selected_tasks) or 1
            summary = {
                "quality": round(totals["quality"] / count, 3),
                "cost": round(totals["cost"] / count, 3),
                "latency": round(totals["latency"] / count, 3),
                "reliability": round(totals["reliability"] / count, 3),
                "utility": round(totals["score"] / count, 4),
            }
            strategy_rows.append({**strategy_item, "summary": summary})
            routerbench_rows.extend(
                {
                    **row,
                    "strategy": strategy_item["name"],
                    "strategy_id": strategy_item["id"],
                    "strategy_category": strategy_item.get("category"),
                }
                for row in per_task
            )
            if strategy_item.get("benchmark_scope") == "main":
                task_rows.extend({**row, "strategy": strategy_item["name"]} for row in per_task)

        best = max(strategy_rows, key=lambda item: item["summary"]["utility"])
        payload = {
            "project_basis": {
                "title": "基于模型路由的大模型协同调度优化方法研究",
                "source": "真实抽样调用：先让真实模型回答抽样任务，再把各策略选择映射到真实结果上评分。",
                "mode": "real-sample",
                "note": f"已真实调用 {len(models)} 个模型 × {len(selected_tasks)} 个任务 × {safe_repeats} 次重复；质量优先由 LLM 裁判评分，失败时使用规则评分。",
            },
            "weights": experiment_weights,
            "scoring": experiment_scoring,
            "finance_dataset": finance_dataset_summary(),
            "task_set": experiment_tasks,
            "sampled_task_set": selected_tasks,
            "strategies": strategy_rows,
            "appendix_strategies": experiment_appendix_strategies,
            "all_strategies": all_experiment_strategies,
            "strategy_scope_note": (
                f"论文主实验：{len(experiment_strategies)} 个代表性策略；"
                f"附录/系统展示：{len(experiment_appendix_strategies)} 个扩展策略。"
                f" RouterDC {'已进入' if contrastive_representative_id == 'dcrouter' else '未进入'}主实验。"
            ),
            "case_results": task_rows,
            "routerbench_rows": routerbench_rows,
            "raw_model_runs": raw_model_runs,
            "best_strategy": best["name"],
            "process_steps": build_experiment_process_steps(
                "real-sample",
                models,
                experiment_tasks,
                selected_tasks,
                strategy_rows,
                task_rows,
                best,
                real_call_count=len(models) * len(selected_tasks) * safe_repeats,
            ),
            "score_source": "真实抽样评分：标准答案客观评分 + 双独立LLM裁判 + 真实耗时 + token/价格成本 + 多轮成功率。",
            "updated_at": time.time(),
            "experiment_phase": (
                phase if len(completed) == total_calls else f"{phase}_incomplete_retryable"
            ),
            "exclude_from_final_analysis": bool(development_only or phase != "formal_context_v2" or len(completed) != total_calls),
            "prompt_protocol": checkpoint["payload"],
            "checkpoint": {
                "enabled": not development_only, "signature": checkpoint["signature"],
                "path": str(checkpoint_path.relative_to(Path.cwd())),
                "progress_path": str(progress_path.relative_to(Path.cwd())),
                "completed": len(completed), "total": total_calls,
                "resumed_at_start": completed_before_start,
            },
        }
        if not development_only:
            is_complete = len(completed) == total_calls
            write_experiment_progress(progress_path, {
                "status": "completed" if is_complete else "incomplete_retryable",
                "signature": checkpoint["signature"],
                "completed": len(completed), "total": total_calls,
                "fraction": round(len(completed) / max(1, total_calls), 6),
                "resumed_at_start": completed_before_start, "updated_at": time.time(),
            })
        payload["routerbench"] = build_routerbench(payload)
        experiment_state["last_run"] = payload
        experiment_state["runs"] = int(experiment_state["runs"]) + 1
        if not development_only and phase == "formal_context_v2":
            persist_experiment_run(payload, legacy_real=True)
        append_request_log({
            "type": "experiment",
            "status": "success",
            "message": f"已完成真实抽样实验，最优策略：{best['name']}。",
        })
        return payload

    def build_experiment_report(payload: Dict[str, Any]) -> str:
        if not payload:
            return "# LLMRouter 实验报告\n\n暂无实验结果，请先运行实验。\n"
        lines = [
            "# LLMRouter 实验报告",
            "",
            f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 实验模式：{payload.get('project_basis', {}).get('mode', '-')}",
            f"- 实验任务总数：{len(payload.get('task_set', []))}",
            f"- 本次真实抽样任务数：{len(payload.get('sampled_task_set', []))}",
            f"- 最优策略：{payload.get('best_strategy', '-')}",
            f"- 策略范围：{payload.get('strategy_scope_note', '主实验保留代表性策略，附录保留扩展策略。')}",
            "## Finance Dataset",
            "",
            f"- Loaded finance tasks: {payload.get('finance_dataset', {}).get('loaded', 0)}",
            f"- Dataset sources: {payload.get('finance_dataset', {}).get('datasets', {})}",
            f"- Standardized JSONL: {payload.get('finance_dataset', {}).get('standardized_path', '-')}",
            f"- Router training JSONL: {payload.get('finance_dataset', {}).get('training_jsonl', '-')}",
            "",
            f"- 分数来源：{payload.get('score_source', '-')}",
            f"- 评分公式：{payload.get('scoring', {}).get('formula', '-')}",
            f"- 风险加权：{payload.get('scoring', {}).get('overall_formula', '-')}",
            f"- 归一化：{payload.get('scoring', {}).get('cost_normalization', '-')}；{payload.get('scoring', {}).get('latency_normalization', '-')}",
            "",
            "## 权重设置",
            "",
        ]
        for key, label in {"quality": "质量", "cost": "成本", "latency": "延迟", "reliability": "可靠性"}.items():
            lines.append(f"- {label}: {payload.get('weights', {}).get(key, 0) * 100:.0f}%")
        routerbench_payload = payload.get("routerbench")
        if routerbench_payload:
            lines.extend([""] + render_routerbench_markdown(routerbench_payload))
        lines.extend(["", "## 实验过程", ""])
        for index, step in enumerate(payload.get("process_steps", []), start=1):
            lines.append(
                f"{index}. **{step.get('title', '-')}**：{step.get('detail', '-')}（{step.get('value', '-')}）"
            )
        lines.extend(["", "## 论文主实验策略对比", "", "| 策略 | 类型 | 代表角色 | 质量 | 成本 | 延迟 | 可靠性 | 综合效用 |", "|---|---|---|---:|---:|---:|---:|---:|"])
        for item in payload.get("strategies", []):
            summary = item.get("summary", {})
            lines.append(
                f"| {item.get('name', '-')} | {item.get('category', '-')} | {item.get('benchmark_role', '-')} | "
                f"{summary.get('quality', 0):.3f} | {summary.get('cost', 0):.3f} | "
                f"{summary.get('latency', 0):.3f} | {summary.get('reliability', 0):.3f} | "
                f"{summary.get('utility', 0):.4f} |"
            )
        appendix_items = payload.get("appendix_strategies") or []
        if appendix_items:
            lines.extend([
                "",
                "## 附录策略与暂不进入主表原因",
                "",
                "| 策略 | 类型 | 处理方式 | 原因 |",
                "|---|---|---|---|",
            ])
            for item in appendix_items:
                lines.append(
                    f"| {item.get('name', '-')} | {item.get('category', '-')} | "
                    f"{item.get('paper_note', '附录/系统展示策略')} | {item.get('benchmark_role', '-')} |"
                )
        lines.extend(["", "## 典型案例", ""])
        for item in payload.get("case_results", [])[:24]:
            candidate_text = " > ".join(
                f"{name} {score:.3f}"
                for name, score in sorted(
                    (item.get("candidate_scores") or {}).items(),
                    key=lambda pair: float(pair[1]),
                    reverse=True,
                )[:5]
            )
            usage = item.get("usage") or {}
            judge_dimensions = item.get("judge_dimensions") or {}
            judge_dimension_text = ", ".join(
                f"{key}={float(value):.2f}" for key, value in judge_dimensions.items()
            )
            lines.extend([
                f"### {item.get('strategy', '-')}: {item.get('selected_model', '-')}",
                f"- 任务：{item.get('query', '-')}",
                f"- 理由：{item.get('reason', '-')}",
                f"- 候选评分：{candidate_text or '-'}",
                f"- 质量来源：{item.get('quality_source', '-')} / 裁判模型：{item.get('judge_model', '-')}",
                f"- 裁判理由：{item.get('judge_reason', '-')}",
                f"- 裁判维度：{judge_dimension_text or '-'}",
                f"- 重复次数：{item.get('repeat_count', '-')}，成功次数：{item.get('success_count', '-')}",
                f"- 估算真实成本：${float(item.get('raw_cost_usd') or 0):.8f}",
                f"- Token/耗时：{usage.get('total_tokens', '-')} token / {item.get('latency_ms', '-')} ms",
                f"- 路由器开销：{item.get('router_overhead_ms', '-')} ms",
                f"- 得分：{item.get('score', 0):.4f}",
                "",
            ])
        return "\n".join(lines)

    def model_is_auto_routable(model_name: str) -> bool:
        llm = config.llms.get(model_name)
        if llm and not getattr(llm, "auto_routable", True):
            return False
        return True

    def serialize_model(name: str, llm: LLMConfig) -> Dict[str, Any]:
        return {
            "id": name,
            "provider": llm.provider,
            "model_id": llm.model_id,
            "base_url": llm.base_url,
            "provider_type": llm.provider_type,
            "auth_mode": llm.auth_mode,
            "chat_path": llm.chat_path,
            "local": llm.local,
            "description": llm.description,
            "input_price": llm.input_price,
            "output_price": llm.output_price,
            "max_tokens": llm.max_tokens,
            "context_limit": llm.context_limit,
            "api_key_configured": bool(config.get_api_key(llm.provider, llm)),
            "auto_routable": model_is_auto_routable(name),
            "health": model_health_payload(name),
        }

    def validate_model_request(request: ModelConfigRequest) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", request.id):
            raise HTTPException(
                status_code=400,
                detail="模型 ID 只能包含字母、数字、点、下划线和连字符。",
            )
        if not request.provider.strip():
            raise HTTPException(status_code=400, detail="供应商不能为空。")
        if not request.model_id.strip():
            raise HTTPException(status_code=400, detail="实际模型 ID 不能为空。")
        if not re.match(r"^https?://", request.base_url.strip()):
            raise HTTPException(status_code=400, detail="API 地址必须以 http:// 或 https:// 开头。")
        if request.auth_mode not in {"auto", "bearer", "none"}:
            raise HTTPException(status_code=400, detail="认证方式必须是 auto、bearer 或 none。")
        if request.context_limit < 128 or request.max_tokens < 1:
            raise HTTPException(status_code=400, detail="上下文长度和最大输出必须为正数。")
        if request.input_price < 0 or request.output_price < 0:
            raise HTTPException(status_code=400, detail="模型价格不能为负数。")

    def persist_model_config(
        model_name: str,
        request: Optional[ModelConfigRequest],
        *,
        delete: bool = False,
        preserve_api_key: bool = True,
    ) -> None:
        if not config.config_path:
            raise HTTPException(status_code=500, detail="当前服务没有可写入的配置文件路径。")

        config_path = Path(config.config_path)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        with config_path.open("r", encoding="utf-8") as handle:
            raw_config = yaml.safe_load(handle) or {}

        llms_data = raw_config.setdefault("llms", {})
        if delete:
            llms_data.pop(model_name, None)
        else:
            previous = llms_data.get(model_name, {}) or {}
            model_payload = {
                "provider": request.provider.strip(),
                "provider_type": "openai_compatible",
                "model": request.model_id.strip(),
                "base_url": request.base_url.strip().rstrip("/"),
                "auth_mode": request.auth_mode,
                "chat_path": request.chat_path.strip() or "/chat/completions",
                "description": request.description.strip(),
                "max_tokens": int(request.max_tokens),
                "context_limit": int(request.context_limit),
                "input_price": float(request.input_price),
                "output_price": float(request.output_price),
                "auto_routable": bool(request.auto_routable),
            }
            if request.local is not None:
                model_payload["local"] = request.local
            if request.api_key:
                model_payload["api_key"] = request.api_key.strip()
            elif preserve_api_key and previous.get("api_key"):
                model_payload["api_key"] = previous["api_key"]
            llms_data[model_name] = model_payload

        with config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                raw_config,
                handle,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "strategy": config.router.strategy,
            "llms": list(config.llms.keys()),
            "healthy_llms": healthy_models(),
        }

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "description": llm.description}
                for name, llm in config.llms.items()
            ] + [{"id": "auto", "object": "model", "description": "Auto router"}]
        }

    @app.get("/api/system")
    async def system_info():
        return {
            "name": "LLMRouter Console",
            "version": "1.0.0",
            "status": "online",
            "router": {
                "strategy": config.router.strategy,
                "algorithm": config.router.llmrouter_name,
                "config": config.router.llmrouter_config,
                "loaded": bool(
                    config.router.strategy != "llmrouter"
                    or getattr(router, "_llmrouter_adapter", None)
                    and (
                        getattr(router._llmrouter_adapter, "router", None) is not None
                        or getattr(router._llmrouter_adapter, "compatibility_mode", False)
                    )
                ),
                "execution_mode": (
                    "compatibility"
                    if getattr(getattr(router, "_llmrouter_adapter", None), "compatibility_mode", False)
                    else "native"
                ),
            },
            "features": {
                "memory": config.memory.enabled,
                "media": config.media.enabled,
                "model_prefix": config.show_model_prefix,
            },
            "models": [
                serialize_model(name, llm)
                for name, llm in config.llms.items()
            ],
            "endpoints": {
                "chat": "POST /v1/chat/completions",
                "models": "GET /v1/models",
                "health": "GET /health",
                "routers": "GET /routers",
            },
        }

    @app.get("/api/models")
    async def configurable_models():
        return {"data": [serialize_model(name, llm) for name, llm in config.llms.items()]}

    @app.post("/api/models")
    async def create_model(request: ModelConfigRequest):
        validate_model_request(request)
        model_name = request.id.strip()
        if model_name in config.llms:
            raise HTTPException(status_code=409, detail=f"模型 {model_name} 已存在。")

        llm = LLMConfig(
            name=model_name,
            provider=request.provider.strip(),
            model_id=request.model_id.strip(),
            base_url=request.base_url.strip().rstrip("/"),
            provider_type="openai_compatible",
            auth_mode=request.auth_mode,
            chat_path=request.chat_path.strip() or "/chat/completions",
            local=request.local,
            api_key=request.api_key.strip() if request.api_key else None,
            description=request.description.strip(),
            max_tokens=int(request.max_tokens),
            context_limit=int(request.context_limit),
            input_price=float(request.input_price),
            output_price=float(request.output_price),
            auto_routable=bool(request.auto_routable),
        )
        persist_model_config(model_name, request, preserve_api_key=False)
        config.llms[model_name] = llm
        model_failures.pop(model_name, None)
        append_request_log({
            "type": "model_config",
            "status": "success",
            "message": f"已新增模型 {model_name}。",
        })
        return serialize_model(model_name, llm)

    @app.put("/api/models/{model_name}")
    async def update_model(model_name: str, request: ModelConfigRequest):
        if model_name not in config.llms:
            raise HTTPException(status_code=404, detail=f"模型 {model_name} 不存在。")
        if request.id.strip() != model_name:
            raise HTTPException(status_code=400, detail="编辑时不能修改模型 ID。")
        validate_model_request(request)

        previous = config.llms[model_name]
        llm = LLMConfig(
            name=model_name,
            provider=request.provider.strip(),
            model_id=request.model_id.strip(),
            base_url=request.base_url.strip().rstrip("/"),
            provider_type="openai_compatible",
            auth_mode=request.auth_mode,
            chat_path=request.chat_path.strip() or "/chat/completions",
            local=request.local,
            api_key=request.api_key.strip() if request.api_key else previous.api_key,
            api_key_env=previous.api_key_env,
            description=request.description.strip(),
            input_price=float(request.input_price),
            output_price=float(request.output_price),
            max_tokens=int(request.max_tokens),
            context_limit=int(request.context_limit),
            auto_routable=bool(request.auto_routable),
        )
        persist_model_config(model_name, request, preserve_api_key=True)
        config.llms[model_name] = llm
        model_failures.pop(model_name, None)
        append_request_log({
            "type": "model_config",
            "status": "success",
            "message": f"已更新模型 {model_name}。",
        })
        return serialize_model(model_name, llm)

    @app.delete("/api/models/{model_name}")
    async def delete_model(model_name: str):
        if model_name not in config.llms:
            raise HTTPException(status_code=404, detail=f"模型 {model_name} 不存在。")
        if len(config.llms) <= 1:
            raise HTTPException(status_code=400, detail="至少需要保留一个模型。")

        persist_model_config(model_name, None, delete=True)
        del config.llms[model_name]
        model_failures.pop(model_name, None)
        metrics["model_usage"].pop(model_name, None)
        append_request_log({
            "type": "model_config",
            "status": "success",
            "message": f"已删除模型 {model_name}。",
        })
        return {"status": "ok", "deleted": model_name}

    @app.post("/api/models/{model_name}/test")
    async def test_model(model_name: str, request: ModelTestRequest):
        if model_name not in config.llms:
            raise HTTPException(status_code=404, detail=f"模型 {model_name} 不存在。")
        started = time.perf_counter()
        try:
            result = await backend.call(
                model_name,
                [{"role": "user", "content": request.prompt}],
                max_tokens=128,
                temperature=0.2,
                stream=False,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            response = extract_response_text(result)
            usage = extract_usage(result, request.prompt, response)
            model_failures.pop(model_name, None)
            append_request_log({
                "type": "model_test",
                "status": "success",
                "selected_model": model_name,
                "latency_ms": elapsed_ms,
                "message": "模型连通性测试成功。",
            })
            return {
                "status": "ok",
                "model": model_name,
                "latency_ms": elapsed_ms,
                "usage": usage,
                "preview": response[:180],
            }
        except Exception as error:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            detail = mark_model_failure(model_name, error)
            append_request_log({
                "type": "model_test",
                "status": "failed",
                "selected_model": model_name,
                "latency_ms": elapsed_ms,
                "message": detail,
            })
            raise HTTPException(status_code=502, detail=detail)

    @app.get("/api/router/config")
    async def router_config():
        return {
            "current": {
                "strategy": config.router.strategy,
                "algorithm": config.router.llmrouter_name,
                "config": config.router.llmrouter_config,
            },
            "service_strategies": service_strategy_catalog,
            "algorithms": [
                algorithm_availability(item) for item in algorithm_catalog
            ],
        }

    @app.post("/api/router/config")
    async def update_router_config(request: RouterUpdateRequest):
        strategy = request.strategy.strip().lower()
        allowed_strategies = {"llmrouter", "constrained_multi_objective", "contextual_bandit", "cascading_bandit_pareto", "latency_sla_pareto", "finance_risk_adaptive", "random", "round_robin", "rules", "llm"}
        if strategy not in allowed_strategies:
            raise HTTPException(status_code=400, detail=f"不支持的服务策略：{strategy}")

        algorithm = request.algorithm
        config_path = None
        if strategy == "llmrouter":
            algorithm = (algorithm or "").strip().lower()
            catalog_item = next(
                (item for item in algorithm_catalog if item["id"] == algorithm),
                None,
            )
            if not catalog_item:
                raise HTTPException(status_code=400, detail=f"不支持的算法路由器：{algorithm}")
            config_path = router_configs.get(algorithm)
            force_compatibility = algorithm not in native_algorithm_ids
        else:
            force_compatibility = False

        try:
            result = router.reconfigure(
                strategy,
                algorithm,
                config_path,
                force_compatibility=force_compatibility,
            )
        except Exception as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        append_request_log({
            "type": "config",
            "status": "success",
            "strategy": strategy,
            "algorithm": algorithm,
            "message": "路由配置已更新。",
        })
        return result

    @app.get("/api/experiments")
    async def experiment_overview():
        return {
            "last_run": experiment_state["last_run"],
            "runs": int(experiment_state["runs"]),
            "task_set": experiment_tasks,
            "weights": experiment_weights,
            "scoring": experiment_scoring,
            "finance_dataset": finance_dataset_summary(),
            "project_basis": {
                "title": "基于模型路由的大模型协同调度优化方法研究",
                "source": "依据申报书中的实验验证方案整理。",
                "mode": "route-only",
                "note": (
                    f"这里展示论文主实验代表策略；其余 {len(experiment_appendix_strategies)} 个"
                    "同类或扩展策略保留在附录/系统展示中。"
                    f" 对比学习代表优先采用 {contrastive_representative_name}。"
                ),
            },
            "strategies": experiment_strategies,
            "appendix_strategies": experiment_appendix_strategies,
            "all_strategies": all_experiment_strategies,
            "strategy_scope_note": (
                f"论文主实验：{len(experiment_strategies)} 个代表性策略；"
                f"附录/系统展示：{len(experiment_appendix_strategies)} 个扩展策略。"
                f" RouterDC {'已进入' if contrastive_representative_id == 'dcrouter' else '未进入'}主实验。"
            ),
            "case_results": [],
            "score_source": "模拟评分：模型画像分 + 任务复杂度/风险修正 + 多目标权重公式；不等同于真实线上调用统计。",
        }

    @app.get("/api/experiments/chart-data")
    async def experiment_chart_data():
        payload = experiment_state["last_run"]
        if not payload:
            raise HTTPException(status_code=404, detail="暂无实验结果，请先运行一次实验。")

        strategies = payload.get("strategies", [])
        routerbench_rows = payload.get("routerbench_rows", [])

        def normalize_category(item):
            category_text = str(item.get("category") or item.get("benchmark_role") or "").lower()
            if "服务层" in category_text or "service" in category_text:
                return "服务层"
            if "算法层" in category_text or "algorithm" in category_text:
                return "算法层"
            if "baseline" in category_text or "基线" in category_text:
                return "基线"
            if "改进" in category_text:
                return "改进策略"
            if "pareto" in category_text or "调度" in category_text or "优化" in category_text:
                return "调度优化"
            return item.get("category") or item.get("benchmark_role") or "其他"

        def dominates_item(left, right):
            left_metrics = left.get("summary", {})
            right_metrics = right.get("summary", {})
            better_or_equal = (
                float(left_metrics.get("quality", 0.0)) >= float(right_metrics.get("quality", 0.0))
                and float(left_metrics.get("reliability", 0.0)) >= float(right_metrics.get("reliability", 0.0))
                and float(left_metrics.get("cost", 1.0)) <= float(right_metrics.get("cost", 1.0))
                and float(left_metrics.get("latency", 1.0)) <= float(right_metrics.get("latency", 1.0))
            )
            strictly_better = (
                float(left_metrics.get("quality", 0.0)) > float(right_metrics.get("quality", 0.0))
                or float(left_metrics.get("reliability", 0.0)) > float(right_metrics.get("reliability", 0.0))
                or float(left_metrics.get("cost", 1.0)) < float(right_metrics.get("cost", 1.0))
                or float(left_metrics.get("latency", 1.0)) < float(right_metrics.get("latency", 1.0))
            )
            return better_or_equal and strictly_better

        pareto_flags = [
            not any(dominates_item(other, item) for other in strategies if other is not item)
            for item in strategies
        ]

        task_types = []
        quality_by_type = {}
        for row in routerbench_rows:
            strategy_name = row.get("strategy") or row.get("strategy_id") or "未知策略"
            task_type = row.get("task_type") or "通用"
            if task_type not in task_types:
                task_types.append(task_type)
            metrics = row.get("metrics") or {}
            quality_by_type.setdefault((strategy_name, task_type), []).append(float(metrics.get("quality", 0.0)))

        ordered_task_types = sorted(task_types)
        sorted_by_utility = sorted(strategies, key=lambda row: float(row.get("summary", {}).get("utility", 0.0)), reverse=True)
        selected_strategies = sorted_by_utility[:6]

        task_series = []
        for strategy in selected_strategies:
            strategy_name = strategy.get("name") or strategy.get("id") or "未知策略"
            data = []
            for task_type in ordered_task_types:
                values = quality_by_type.get((strategy_name, task_type), [])
                data.append(round(sum(values) / len(values), 3) if values else 0.0)
            task_series.append({
                "name": strategy_name,
                "category": normalize_category(strategy),
                "data": data,
            })

        return {
            "pareto_points": [
                {
                    "name": item.get("name") or item.get("id") or "未知",
                    "cost": float(item.get("summary", {}).get("cost", 0.0)),
                    "quality": float(item.get("summary", {}).get("quality", 0.0)),
                    "latency": float(item.get("summary", {}).get("latency", 0.0)),
                    "reliability": float(item.get("summary", {}).get("reliability", 0.0)),
                    "utility": float(item.get("summary", {}).get("utility", 0.0)),
                    "category": normalize_category(item),
                    "pareto": pareto_flags[index],
                }
                for index, item in enumerate(strategies)
            ],
            "radar_profiles": [
                {
                    "name": item.get("name") or item.get("id") or "未知",
                    "quality": float(item.get("summary", {}).get("quality", 0.0)),
                    "costEff": round(max(0.0, 1.0 - float(item.get("summary", {}).get("cost", 1.0))), 3),
                    "latencyEff": round(max(0.0, 1.0 - float(item.get("summary", {}).get("latency", 1.0))), 3),
                    "reliability": float(item.get("summary", {}).get("reliability", 0.0)),
                    "robustness": round((float(item.get("summary", {}).get("quality", 0.0)) + float(item.get("summary", {}).get("reliability", 0.0))) / 2.0, 3),
                    "category": normalize_category(item),
                }
                for item in selected_strategies
            ],
            "task_type_quality": {
                "types": ordered_task_types,
                "series": task_series,
            },
            "utility_ranking": [
                {
                    "name": item.get("name") or item.get("id") or "未知",
                    "utility": float(item.get("summary", {}).get("utility", 0.0)),
                    "category": normalize_category(item),
                    "pareto": pareto_flags[index],
                }
                for index, item in enumerate(sorted_by_utility)
            ],
        }

    @app.post("/api/experiments/run")
    async def run_experiment(request: ExperimentRunRequest = ExperimentRunRequest()):
        if request.mode == "pilot":
            return await run_real_sample_experiment(
                min(request.sample_limit, 10), repeats=1,
                judge_enabled=request.judge_enabled, development_only=True,
                phase="development_pilot_v2",
            )
        if request.mode == "context_pilot":
            return await run_real_sample_experiment(
                12, repeats=1, judge_enabled=request.judge_enabled,
                development_only=False, phase="context_fix_validation_v2",
                selection_mode="context_pilot_3_per_dataset",
            )
        if request.mode == "real":
            return await run_real_sample_experiment(
                request.sample_limit, repeats=request.repeats,
                judge_enabled=request.judge_enabled, development_only=False,
                phase="formal_context_v2",
            )
        return await run_route_only_experiment()

    @app.get("/api/experiments/report")
    async def export_experiment_report():
        payload = experiment_state["last_run"]
        if not payload:
            raise HTTPException(status_code=404, detail="暂无实验结果，请先运行一次实验。")
        report_path = Path.cwd() / "run_logs" / "llmrouter_experiment_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(build_experiment_report(payload), encoding="utf-8")
        return FileResponse(
            str(report_path),
            media_type="text/markdown; charset=utf-8",
            filename="LLMRouter_实验报告.md",
        )

    @app.get("/api/metrics")
    async def routing_metrics():
        requests_count = int(metrics["requests"])
        successes = int(metrics["successes"])
        average_latency = (
            float(metrics["total_latency_ms"]) / successes
            if successes
            else 0.0
        )
        return {
            "requests": requests_count,
            "successes": successes,
            "failures": int(metrics["failures"]),
            "fallbacks": int(metrics["fallbacks"]),
            "success_rate": successes / requests_count if requests_count else 0.0,
            "average_latency_ms": round(average_latency, 2),
            "model_usage": dict(metrics["model_usage"]),
            "model_health": {
                name: model_health_payload(name) for name in config.llms
            },
        }

    @app.get("/api/logs")
    async def routing_logs(limit: int = 50):
        safe_limit = max(1, min(limit, 200))
        return {"data": list(request_logs)[:safe_limit]}

    @app.post("/api/feedback")
    async def submit_feedback(request: FeedbackRequest):
        rating = (request.rating or "").strip().lower()
        positive = rating in {"up", "like", "positive", "good", "1", "👍"}
        negative = rating in {"down", "dislike", "negative", "bad", "0", "👎"}
        if not positive and not negative:
            raise HTTPException(status_code=400, detail="rating 必须是 up/down。")
        normalized_rating = "up" if positive else "down"
        event = None
        if request.request_id:
            try:
                event = experience_store.apply_feedback(
                    request.request_id, rating=normalized_rating, reason=request.reason,
                    corrected_answer=request.corrected_answer,
                    preferred_model=request.preferred_model, feedback_text=request.feedback_text,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="未找到对应 request_id，反馈未写入经验库。")
        feedback = record_contextual_bandit_feedback(
            request.query,
            request.model,
            success=positive,
            latency_ms=float(request.latency_ms or (event or {}).get("latency_ms") or 0.0),
            fallback_count=int(request.fallback_count or (event or {}).get("fallback_count") or (1 if negative else 0)),
            automatic_quality=(event or {}).get("quality_score"),
            user_feedback=(event or {}).get("user_feedback_score"),
            cost_reward=(event or {}).get("cost_reward"),
            latency_reward=(event or {}).get("latency_reward"),
            reliability=(event or {}).get("reliability"),
            constraint_violation=bool((event or {}).get("constraint_violation")),
        )
        append_request_log({
            "type": "feedback", "status": "success", "request_id": request.request_id,
            "query": request.query[:300], "selected_model": request.model,
            "strategy": request.strategy or config.router.strategy,
            "rating": normalized_rating, "reason": request.reason,
            "verification_status": (event or {}).get("verification_status"),
            "routing_correct": (event or {}).get("routing_correct"),
            "bandit_feedback": feedback,
        })
        return {
            "ok": True, "rating": normalized_rating, "feedback": feedback,
            "experience": event,
            "message": "反馈已同步写入路由经验库与在线 Bandit 状态。",
        }

    @app.get("/api/experience/metrics")
    async def experience_metrics():
        return experience_store.metrics()

    @app.get("/api/experience/{request_id}")
    async def experience_detail(request_id: str):
        event = experience_store.get(request_id)
        if not event:
            raise HTTPException(status_code=404, detail="未找到路由经验事件。")
        return event

    @app.post("/api/chat/compare")
    async def ab_compare(request: ABCompareRequest):
        messages = []
        for message in request.messages:
            messages.append({"role": message.role, "content": message.content})
        query = ""
        for item in reversed(messages):
            if item.get("role") == "user":
                query = normalize_content(item.get("content"))[:500]
                break
        if not query:
            query = "general query"
        available = healthy_models()
        if not available:
            raise HTTPException(status_code=503, detail="没有可用于 A/B 对比的健康模型。")
        routing_started_at = time.perf_counter()
        routing = await router.select_model_details(
            query,
            user=request.user,
            available_models=available,
        )
        routing_overhead_ms = round((time.perf_counter() - routing_started_at) * 1000, 3)
        routing = apply_verified_experience(routing, query, available, request.user)
        selected = routing["selected_model"]
        cheapest = min(available, key=lambda name: (model_profile(name)["cost"], model_profile(name)["latency"]))
        strongest = max(available, key=lambda name: (model_profile(name)["quality"], model_profile(name)["reliability"]))
        requested_models = [model for model in (request.models or []) if model in available]
        compare_models = []
        for model in [selected, cheapest, strongest, *requested_models]:
            if model not in compare_models:
                compare_models.append(model)
            if len(compare_models) >= 4:
                break
        results = []
        task = {
            "id": "ab_compare",
            "type": "通用问答",
            "query": query,
            "risk": 0.4,
            "complexity": min(1.0, len(query) / 180.0),
            "requires_verification": False,
            "expected": [],
        }
        for model_name in compare_models:
            started = time.perf_counter()
            try:
                result = await backend.call(
                    model_name,
                    messages,
                    request.max_tokens or 768,
                    request.temperature,
                    stream=False,
                )
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                answer = extract_response_text(result)
                usage = extract_usage(result, query, answer)
                raw_cost = raw_cost_usd(model_name, usage)
                quality = heuristic_quality(task, answer, True)
                results.append({
                    "model": model_name,
                    "role": "auto_routed" if model_name == selected else "baseline",
                    "ok": True,
                    "answer": clean_response(result).get("choices", [{}])[0].get("message", {}).get("content", answer) if result.get("choices") else answer,
                    "excerpt": answer[:500],
                    "latency_ms": elapsed_ms,
                    "usage": usage,
                    "raw_cost_usd": raw_cost,
                    "quality_proxy": quality,
                    "metrics": {
                        "quality": quality,
                        "cost": normalized_cost_score(model_name, usage, raw_cost),
                        "latency": round(max(0.0, min(1.0, elapsed_ms / 10000)), 3),
                        "reliability": 1.0,
                    },
                })
            except Exception as error:
                results.append({
                    "model": model_name,
                    "role": "auto_routed" if model_name == selected else "baseline",
                    "ok": False,
                    "answer": "",
                    "excerpt": "",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "usage": {},
                    "raw_cost_usd": 0.0,
                    "quality_proxy": 0.0,
                    "metrics": {"quality": 0.0, "cost": 1.0, "latency": 1.0, "reliability": 0.0},
                    "error": str(getattr(error, "detail", error))[:500],
                })
        successful_results = [item for item in results if item.get("ok")]
        counterfactual_event = None
        if successful_results:
            observed_utilities = {}
            for item in successful_results:
                metrics_item = item["metrics"]
                observed_utilities[item["model"]] = round(experience_utility_score(
                    quality=float(metrics_item["quality"]),
                    cost_reward=1.0 - float(metrics_item["cost"]),
                    latency_reward=1.0 - float(metrics_item["latency"]),
                    reliability=float(metrics_item["reliability"]),
                ), 4)
            selected_result = next((item for item in successful_results if item["model"] == selected), successful_results[0])
            selected = selected_result["model"]
            selected_metrics = selected_result["metrics"]
            observed_regret = max(observed_utilities.values()) - observed_utilities[selected]
            counterfactual_event = experience_store.create(
                user_id=request.user, query=query, task_type=task["type"], risk_level="low",
                candidate_models=compare_models, candidate_scores=routing.get("candidate_scores", {}),
                observed_utilities=observed_utilities, selected_model=selected,
                answer=selected_result.get("answer", ""), quality_score=selected_result.get("quality_proxy", 0.0),
                objective_score=None, judge_scores=[], automatic_evaluation="ab_observed_quality_proxy",
                latency_ms=selected_result.get("latency_ms", 0.0), cost_usd=selected_result.get("raw_cost_usd", 0.0),
                cost_reward=1.0 - float(selected_metrics["cost"]),
                latency_reward=1.0 - float(selected_metrics["latency"]), reliability=float(selected_metrics["reliability"]),
                utility=observed_utilities[selected], api_success=True, fallback_count=0,
                constraint_violation=False, estimated_regret=round(observed_regret, 4),
                regret_type="observed_counterfactual", regret_epsilon=0.10, quality_threshold=0.60,
                strategy=routing.get("strategy"), routing_reason=routing.get("reason"),
                config_version=routing_config_version(),
            )
            routing["request_id"] = counterfactual_event["request_id"]
            routing["estimated_regret"] = round(observed_regret, 4)
            routing["regret_type"] = "observed_counterfactual"
        append_request_log({
            "type": "ab_compare",
            "status": "success",
            "query": query,
            "selected_model": selected,
            "models": compare_models,
            "router_overhead_ms": routing_overhead_ms,
        })
        return {
            "query": query,
            "routing": {
                **routing,
                "router_overhead_ms": routing_overhead_ms,
            },
            "results": results,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatRequest):
        print(f"============\n")
        messages = []
        for message in request.messages:
            message_payload = {
                "role": message.role,
                "content": message.content,
            }
            if message.tool_calls is not None:
                message_payload["tool_calls"] = message.tool_calls
            if message.tool_call_id is not None:
                message_payload["tool_call_id"] = message.tool_call_id
            if message.function_call is not None:
                message_payload["function_call"] = message.function_call
            messages.append(message_payload)

        # Extract user query for routing (with optional media understanding)
        user_query = ""
        media_description = None

        # Find and process the last user message
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                last_user_idx = i
                break

        if last_user_idx is not None:
            raw_content = messages[last_user_idx]["content"]

            # Process multimodal content if media is enabled
            # Supports both OpenAI format (list) and OpenClaw format (string with [media attached:...])
            if config.media.enabled:
                # Use together API key as fallback
                together_key = config.api_keys.get("together")
                processed_text, media_desc = await process_multimodal_content(
                    raw_content, config.media, fallback_key=together_key
                )
                user_query = processed_text[:500]
                media_description = media_desc
                if media_desc:
                    print(f"[Media] Processed: {media_desc[:80]}...")
                    # IMPORTANT: Replace the message content with processed text
                    # so LLM sees the image description instead of [media attached: ...]
                    messages[last_user_idx]["content"] = processed_text
            else:
                user_query = normalize_content(raw_content)[:500]

        if not user_query:
            user_query = "general query"

        request_started_at = time.perf_counter()
        metrics["requests"] += 1

        solve_mode = (request.solve_mode or "single").strip().lower()
        available_models = list(config.llms.keys())
        route_candidates = healthy_models()
        if request.model != "auto" and request.model in available_models:
            route_candidates = [request.model]
        if not request.stream and solve_mode in {"static_multi", "dynamic_subtasks"}:
            if not route_candidates:
                raise HTTPException(status_code=503, detail="没有可用于多步求解的健康模型。")
            result = await solve_complex_request(
                solve_mode,
                user_query,
                messages,
                request,
                route_candidates,
            )
            elapsed_ms = round((time.perf_counter() - request_started_at) * 1000, 2)
            selected_model = result.get("model", "unknown")
            metrics["successes"] += 1
            metrics["total_latency_ms"] += elapsed_ms
            metrics["model_usage"][selected_model] += 1
            result["routing"]["latency_ms"] = elapsed_ms
            result["routing"]["model_health"] = {
                name: model_health_payload(name) for name in available_models
            }
            append_request_log({
                "type": "chat",
                "status": "success",
                "query": user_query,
                "strategy": result["routing"].get("strategy"),
                "algorithm": result["routing"].get("algorithm"),
                "solve_mode": solve_mode,
                "dispatch_mode": result["routing"].get("dispatch_mode"),
                "selected_model": selected_model,
                "initial_model": result["routing"].get("initial_model"),
                "candidate_scores": result["routing"].get("candidate_scores", {}),
                "reason": result["routing"].get("reason"),
                "attempted_models": result["routing"].get("attempted_models", []),
                "fallbacks": result["routing"].get("fallbacks", []),
                "multi_step": result["routing"].get("multi_step", []),
                "latency_ms": elapsed_ms,
            })
            return result

        # Select model
        router_overhead_ms = 0.0
        if request.model == "auto" or request.model not in available_models:
            routing_started_at = time.perf_counter()
            routing = await router.select_model_details(
                user_query,
                user=request.user,
                available_models=route_candidates,
            )
            router_overhead_ms = round((time.perf_counter() - routing_started_at) * 1000, 3)
            selected_model = routing["selected_model"]
            # ASCII-only log to avoid Windows GBK UnicodeEncodeError.
            # print(f"[Router] Query: '{user_query[:50]}...' -> {selected_model}")
            print(f"[Router] Query: '{user_query}' -> {selected_model}")
        else:
            selected_model = request.model
            routing = {
                "selected_model": selected_model,
                "strategy": "manual",
                "algorithm": None,
                "candidate_scores": {
                    model: 1.0 if model == selected_model else 0.0
                    for model in available_models
                },
                "reason": "用户在前端手动指定了模型，因此跳过自动路由。",
            }
            router_overhead_ms = 0.0
            print(f"[Specified] Query: '{user_query}' -> {selected_model}")

        if request.model == "auto" or request.model not in available_models:
            routing = apply_verified_experience(routing, user_query, route_candidates, request.user)
            selected_model = routing["selected_model"]

        # Handle streaming
        if request.stream:
            async def generate():
                prefix_sent = False
                content_buffer = ""
                buffered_chunks = []

                def flush_buffered_prefix() -> Optional[str]:
                    nonlocal prefix_sent, content_buffer, buffered_chunks
                    if not buffered_chunks or prefix_sent:
                        return None

                    content_buffer = re.sub(r'^\[[\w\-\.]+\]\s*', '', content_buffer)
                    first = buffered_chunks[0]
                    try:
                        first_json = first[6:] if first.startswith("data: ") else first
                        first_data = json.loads(first_json.strip())
                        if first_data.get("choices") and first_data["choices"][0].get("delta"):
                            first_data["choices"][0]["delta"]["content"] = f"[{selected_model}] " + content_buffer
                            prefix_sent = True
                            buffered_chunks = []
                            return f"data: {json.dumps(first_data)}\n\n"
                    except:
                        pass
                    return None

                try:
                    prefix_disabled = False

                    stream_gen = await backend.call(
                        selected_model, messages, request.max_tokens,
                        request.temperature, stream=True,
                        tools=request.tools,
                        tool_choice=request.tool_choice,
                        stream_options=request.stream_options,
                    )
                    async for chunk in stream_gen:
                        if not config.show_model_prefix:
                            yield chunk
                            continue

                        if prefix_disabled:
                            if "[DONE]" in chunk:
                                yield chunk
                                continue
                            try:
                                json_str = chunk[6:] if chunk.startswith("data: ") else chunk
                                data = json.loads(json_str.strip())
                                cleaned = clean_streaming_chunk(data)
                                if cleaned:
                                    yield f"data: {json.dumps(cleaned)}\n\n"
                                    continue
                            except:
                                pass
                            yield chunk
                            continue

                        # Add model prefix to first content chunk
                        if "[DONE]" in chunk:
                            # Flush buffer before DONE
                            if buffered_chunks and not prefix_sent:
                                flushed_chunk = flush_buffered_prefix()
                                if flushed_chunk:
                                    yield flushed_chunk
                            yield chunk
                        else:
                            try:
                                json_str = chunk[6:] if chunk.startswith("data: ") else chunk
                                data = json.loads(json_str.strip())
                                cleaned = clean_streaming_chunk(data)

                                if cleaned:
                                    if cleaned.get("usage") and not cleaned.get("choices"):
                                        if buffered_chunks and not prefix_sent:
                                            flushed_chunk = flush_buffered_prefix()
                                            if flushed_chunk:
                                                yield flushed_chunk
                                        yield f"data: {json.dumps(cleaned)}\n\n"
                                        continue

                                    choices = cleaned.get("choices", [])
                                    if choices and "delta" in choices[0]:
                                        delta = choices[0]["delta"]

                                        if _delta_has_tool_calls(delta):
                                            if buffered_chunks and not prefix_sent:
                                                for buffered_chunk in buffered_chunks:
                                                    try:
                                                        buffered_json = buffered_chunk[6:] if buffered_chunk.startswith("data: ") else buffered_chunk
                                                        buffered_data = json.loads(buffered_json.strip())
                                                        buffered_cleaned = clean_streaming_chunk(buffered_data)
                                                        if buffered_cleaned:
                                                            yield f"data: {json.dumps(buffered_cleaned)}\n\n"
                                                        else:
                                                            yield buffered_chunk
                                                    except:
                                                        yield buffered_chunk
                                                buffered_chunks = []
                                            prefix_disabled = True
                                            yield f"data: {json.dumps(cleaned)}\n\n"
                                            continue

                                        content = delta.get("content", "")

                                        if not prefix_sent:
                                            content_buffer += content
                                            buffered_chunks.append(chunk)

                                            if len(content_buffer) > 30 or (content_buffer and not content_buffer.startswith("[")):
                                                content_buffer = re.sub(r'^\[[\w\-\.]+\]\s*', '', content_buffer)
                                                first = buffered_chunks[0]
                                                first_data = json.loads(first[6:] if first.startswith("data: ") else first)
                                                if first_data.get("choices") and first_data["choices"][0].get("delta"):
                                                    first_data["choices"][0]["delta"]["content"] = f"[{selected_model}] " + content_buffer
                                                    yield f"data: {json.dumps(first_data)}\n\n"
                                                    prefix_sent = True
                                                    buffered_chunks = []
                                        else:
                                            yield f"data: {json.dumps(cleaned)}\n\n"
                                    else:
                                        if prefix_sent:
                                            yield f"data: {json.dumps(cleaned)}\n\n"
                            except:
                                yield chunk
                except Exception as e:
                    print(f"[Stream Error] {type(e).__name__}: {e}")
                    yield f'data: {json.dumps({"error": str(e)})}\n\n'

            return StreamingResponse(generate(), media_type="text/event-stream")

        else:
            attempted_models = []
            fallback_events = []
            result = None
            final_model = selected_model
            auto_route = request.model == "auto" or request.model not in available_models
            candidates = [selected_model]
            if auto_route:
                if routing.get("escalation_chain"):
                    candidates.extend(
                        model for model in routing.get("escalation_chain", [])
                        if model in route_candidates and model != selected_model
                    )
                    candidates.extend(
                        model for model in fallback_order(
                            selected_model,
                            routing.get("candidate_scores", {}),
                            route_candidates,
                        )
                        if model not in candidates
                    )
                else:
                    candidates.extend(
                        fallback_order(
                            selected_model,
                            routing.get("candidate_scores", {}),
                            route_candidates,
                        )
                    )

            last_error = None
            for candidate in candidates:
                attempted_models.append(candidate)
                try:
                    result = await backend.call(
                        candidate, messages, request.max_tokens,
                        request.temperature, stream=False,
                        tools=request.tools, tool_choice=request.tool_choice
                    )
                    final_model = candidate
                    break
                except Exception as error:
                    last_error = error
                    error_detail = mark_model_failure(candidate, error)
                    fallback_events.append({
                        "model": candidate,
                        "error": error_detail,
                    })
                    _safe_log(f"[Fallback] {candidate} failed: {error_detail}")
                    if not auto_route:
                        break

            if result is None:
                metrics["failures"] += 1
                elapsed_ms = round((time.perf_counter() - request_started_at) * 1000, 2)
                feedback = router.record_feedback(
                    user_query,
                    selected_model,
                    success=False,
                    latency_ms=elapsed_ms,
                    fallback_count=len(fallback_events),
                )
                failed_event = experience_store.create(
                    user_id=request.user, query=user_query, task_type="unknown", risk_level="unknown",
                    candidate_models=candidates, candidate_scores=routing.get("candidate_scores", {}),
                    selected_model=selected_model, answer="", quality_score=0.0,
                    latency_ms=elapsed_ms, cost_usd=0.0, cost_reward=0.0,
                    latency_reward=max(0.0, 1.0 - elapsed_ms / 10000.0), reliability=0.0,
                    api_success=False, fallback_count=len(fallback_events),
                    constraint_violation=False, estimated_regret=1.0, regret_epsilon=0.10,
                    quality_threshold=0.60, strategy=routing.get("strategy"),
                    routing_reason=routing.get("reason"), verification_status="verified_negative",
                    routing_correct=False, error=str(getattr(last_error, "detail", last_error))[:500],
                )
                append_request_log({
                    "type": "chat",
                    "status": "failed",
                    "request_id": failed_event["request_id"],
                    "query": user_query,
                    "strategy": routing.get("strategy"),
                    "algorithm": routing.get("algorithm"),
                    "selected_model": selected_model,
                    "attempted_models": attempted_models,
                    "fallbacks": fallback_events,
                    "latency_ms": elapsed_ms,
                    "router_overhead_ms": router_overhead_ms,
                    "bandit_feedback": feedback,
                    "message": str(getattr(last_error, "detail", last_error)),
                })
                if isinstance(last_error, HTTPException):
                    raise last_error
                raise HTTPException(status_code=502, detail="所有候选模型均调用失败。")

            if final_model != selected_model:
                metrics["fallbacks"] += 1
                routing["reason"] = (
                    f"{routing.get('reason', '')} 原模型 {selected_model} 调用失败，"
                    f"系统已自动降级到 {final_model}。"
                ).strip()
            selected_model = final_model

            # Add model prefix
            if config.show_model_prefix and result.get("choices"):
                message = result["choices"][0].get("message", {})
                content = message.get("content")
                if content and not _message_has_tool_calls(message):
                    # Remove any existing prefix
                    content = re.sub(r'^\[[\w\-\.]+\]\s*', '', content)
                    message["content"] = f"[{selected_model}] {content}"

            result["model"] = selected_model
            elapsed_ms = round((time.perf_counter() - request_started_at) * 1000, 2)
            metrics["successes"] += 1
            metrics["total_latency_ms"] += elapsed_ms
            metrics["model_usage"][selected_model] += 1
            answer_text = extract_response_text(result)
            answer_usage = extract_usage(result, user_query, answer_text)
            answer_cost = raw_cost_usd(selected_model, answer_usage)
            quality_task = {
                "query": user_query, "type": "专业问答" if any(token in user_query for token in ("金融", "审计", "合规", "财务")) else "通用问答",
                "risk": 0.86 if any(token in user_query for token in ("审计", "合规", "投资", "监管")) else 0.40,
                "requires_verification": any(token in user_query for token in ("金融", "审计", "合规", "计算")),
            }
            heuristic_score = heuristic_quality(quality_task, answer_text, True)
            quality_evaluation = await judge_response_quality(
                quality_task, answer_text, selected_model, heuristic_score,
                judge_enabled=bool(request.verify_response or quality_task["risk"] >= 0.75),
            )
            automatic_quality = float(quality_evaluation.get("score") or heuristic_score)
            cost_reward = 1.0 - min(1.0, float(answer_cost or 0.0) / 0.02)
            latency_reward = 1.0 - min(1.0, elapsed_ms / 10000.0)
            candidate_scores = {key: float(value) for key, value in (routing.get("candidate_scores") or {}).items()}
            selected_estimate = candidate_scores.get(selected_model, 0.0)
            estimated_regret = max(0.0, (max(candidate_scores.values()) if candidate_scores else selected_estimate) - selected_estimate)
            constraint_violation = bool((routing.get("constraints") or {}).get("relaxed"))
            automatic_state = automatic_verification(
                api_success=True, quality_score=automatic_quality,
                quality_threshold=0.75 if quality_task["risk"] >= 0.75 else 0.60,
                risk_level="high" if quality_task["risk"] >= 0.75 else "medium" if quality_task["risk"] >= 0.45 else "low",
                objective_score=quality_evaluation.get("objective_score"),
                constraint_violation=constraint_violation,
                estimated_regret=estimated_regret, regret_epsilon=0.10,
                manual_review_required=bool(quality_evaluation.get("manual_review_required")),
                cost_reward=cost_reward, latency_reward=latency_reward, reliability=1.0,
                fallback_count=len(fallback_events),
            )
            experience_event = experience_store.create(
                user_id=request.user, query=user_query, task_type=quality_task["type"],
                risk_level="high" if quality_task["risk"] >= 0.75 else "medium" if quality_task["risk"] >= 0.45 else "low",
                candidate_models=route_candidates, candidate_scores=candidate_scores,
                selected_model=selected_model, answer=answer_text,
                quality_score=automatic_quality,
                objective_score=quality_evaluation.get("objective_score"),
                judge_scores=quality_evaluation.get("judge_scores", []),
                judge_model=quality_evaluation.get("judge_model"), reviewer_model=quality_evaluation.get("reviewer_model"),
                judge_disagreement=quality_evaluation.get("disagreement", 0.0),
                judge_reason=quality_evaluation.get("reason"),
                verification_status=automatic_state["verification_status"],
                routing_correct=automatic_state["routing_correct"], reward=automatic_state["reward"],
                automatic_evaluation=quality_evaluation.get("source", "heuristic"),
                latency_ms=elapsed_ms, cost_usd=answer_cost,
                cost_reward=round(cost_reward, 4), latency_reward=round(latency_reward, 4), reliability=1.0,
                utility=round(experience_utility_score(quality=automatic_quality, cost_reward=cost_reward, latency_reward=latency_reward, reliability=1.0), 4),
                api_success=True, fallback_count=len(fallback_events), constraint_violation=constraint_violation,
                estimated_regret=round(estimated_regret, 4), regret_epsilon=0.10,
                quality_threshold=0.75 if quality_task["risk"] >= 0.75 else 0.60,
                strategy=routing.get("strategy"), routing_reason=routing.get("reason"),
                config_version=routing_config_version(),
            )
            routing_payload = {
                **routing,
                "request_id": experience_event["request_id"],
                "verification_status": experience_event["verification_status"],
                "automatic_quality": automatic_quality,
                "quality_source": quality_evaluation.get("source"),
                "judge_disagreement": quality_evaluation.get("disagreement", 0.0),
                "estimated_regret": round(estimated_regret, 4),
                "selected_model": selected_model,
                "initial_model": routing.get("selected_model"),
                "attempted_models": attempted_models,
                "fallbacks": fallback_events,
                "latency_ms": elapsed_ms,
                "router_overhead_ms": router_overhead_ms,
                "router_overhead_ratio": round(router_overhead_ms / max(1.0, elapsed_ms), 5),
                "model_health": {
                    name: model_health_payload(name) for name in available_models
                },
            }
            feedback = router.record_feedback(
                user_query,
                selected_model,
                success=True,
                latency_ms=elapsed_ms,
                fallback_count=len(fallback_events),
            )
            if feedback:
                routing_payload["bandit_feedback"] = feedback
            result["routing"] = routing_payload
            append_request_log({
                "type": "chat",
                "status": "success",
                "query": user_query,
                "strategy": routing.get("strategy"),
                "algorithm": routing.get("algorithm"),
                "selected_model": selected_model,
                "initial_model": routing.get("selected_model"),
                "candidate_scores": routing.get("candidate_scores", {}),
                "reason": routing_payload["reason"],
                "attempted_models": attempted_models,
                "fallbacks": fallback_events,
                "latency_ms": elapsed_ms,
                "router_overhead_ms": router_overhead_ms,
                "bandit_feedback": feedback,
            })
            return result

    @app.get("/")
    async def root():
        index_path = frontend_dir / "index.html"
        if index_path.is_file():
            return FileResponse(str(index_path))

        return {
            "name": "OpenClaw Router",
            "version": "1.0.0",
            "strategy": config.router.strategy,
            "llms": list(config.llms.keys()),
            "endpoints": {
                "chat": "POST /v1/chat/completions",
                "models": "GET /v1/models",
                "health": "GET /health"
            }
        }

    @app.get("/api/info")
    async def api_info():
        return {
            "name": "OpenClaw Router",
            "version": "1.0.0",
            "strategy": config.router.strategy,
            "llms": list(config.llms.keys()),
            "endpoints": {
                "chat": "POST /v1/chat/completions",
                "models": "GET /v1/models",
                "health": "GET /health"
            }
        }

    @app.get("/routers")
    async def list_routers():
        """List available routing strategies"""
        return {
            "available_routers": router.get_available_routers(),
            "current": config.router.strategy
        }

    @app.websocket("/v1/chat/ws")
    async def chat_websocket(websocket: WebSocket):
        """WebSocket endpoint for real-time streaming"""
        await websocket.accept()
        try:
            # Receive request
            data = await websocket.receive_json()
            request = ChatRequest(**data)
            messages = [{"role": m.role, "content": m.content} for m in request.messages]

            # Extract user query for routing
            user_query = ""
            last_user_idx = None
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    last_user_idx = i
                    break

            if last_user_idx is not None:
                raw_content = messages[last_user_idx]["content"]
                if config.media.enabled:
                    together_key = config.api_keys.get("together")
                    processed_text, _ = await process_multimodal_content(
                        raw_content, config.media, fallback_key=together_key
                    )
                    user_query = processed_text[:500]
                    messages[last_user_idx]["content"] = processed_text
                else:
                    user_query = normalize_content(raw_content)[:500]

            if not user_query:
                user_query = "general query"

            # Select model
            available_models = list(config.llms.keys())
            if request.model == "auto" or request.model not in available_models:
                selected_model = await router.select_model(user_query, user=request.user)
                _safe_log(f"[WS Router] Query: '{user_query[:50]}...' -> {selected_model}")
            else:
                selected_model = request.model

            # Call LLM backend in streaming mode
            prefix_sent = False
            content_buffer = ""
            buffered_chunks = []

            stream_gen = await backend.call(
                selected_model, messages, request.max_tokens,
                request.temperature,
                stream=True,
                stream_options=request.stream_options,
            )

            async for chunk in stream_gen:
                if not config.show_model_prefix:
                    await websocket.send_text(chunk)
                    continue

                if "[DONE]" in chunk:
                    if buffered_chunks and not prefix_sent:
                        content_buffer = re.sub(r'^\[[\w\-\.]+\]\s*', '', content_buffer)
                        first = buffered_chunks[0]
                        try:
                            data_chunk = json.loads(first[6:]) if first.startswith("data: ") else {}
                            if data_chunk.get("choices") and data_chunk["choices"][0].get("delta"):
                                data_chunk["choices"][0]["delta"]["content"] = f"[{selected_model}] " + content_buffer
                                await websocket.send_text(f"data: {json.dumps(data_chunk)}\n\n")
                        except:
                            pass
                    await websocket.send_text(chunk)
                else:
                    try:
                        json_str = chunk[6:] if chunk.startswith("data: ") else chunk
                        data_chunk = json.loads(json_str.strip())
                        cleaned = clean_streaming_chunk(data_chunk)

                        if cleaned:
                            if cleaned.get("usage") and not cleaned.get("choices"):
                                if buffered_chunks and not prefix_sent:
                                    content_buffer = re.sub(r'^\[[\w\-\.]+\]\s*', '', content_buffer)
                                    first = buffered_chunks[0]
                                    try:
                                        first_data = json.loads(first[6:] if first.startswith("data: ") else first)
                                        if first_data.get("choices") and first_data["choices"][0].get("delta"):
                                            first_data["choices"][0]["delta"]["content"] = f"[{selected_model}] " + content_buffer
                                            await websocket.send_text(f"data: {json.dumps(first_data)}\n\n")
                                            prefix_sent = True
                                            buffered_chunks = []
                                    except:
                                        pass
                                await websocket.send_json(cleaned)
                                continue

                            choices = cleaned.get("choices", [])
                            if choices and "delta" in choices[0]:
                                content = choices[0]["delta"].get("content", "")

                                if not prefix_sent:
                                    content_buffer += content
                                    buffered_chunks.append(chunk)

                                    if len(content_buffer) > 30 or (content_buffer and not content_buffer.startswith("[")):
                                        content_buffer = re.sub(r'^\[[\w\-\.]+\]\s*', '', content_buffer)
                                        first = buffered_chunks[0]
                                        first_data = json.loads(first[6:] if first.startswith("data: ") else first)
                                        if first_data.get("choices") and first_data["choices"][0].get("delta"):
                                            first_data["choices"][0]["delta"]["content"] = f"[{selected_model}] " + content_buffer
                                            await websocket.send_text(f"data: {json.dumps(first_data)}\n\n")
                                            prefix_sent = True
                                            buffered_chunks = []
                                else:
                                    await websocket.send_json(cleaned)
                            else:
                                if prefix_sent:
                                    await websocket.send_json(cleaned)
                    except:
                        await websocket.send_text(chunk)

        except WebSocketDisconnect:
            _safe_log("[WS] Client disconnected")
        except Exception as e:
            _safe_log(f"[WS Error] {type(e).__name__}: {e}")
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
    """Run the server"""
    if app is None:
        app = create_app(config_path=config_path)

    print(f"""
============================================================
  OpenClaw Router
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

    parser = argparse.ArgumentParser(description="OpenClaw Router Server")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to bind")
    args = parser.parse_args()

    run_server(config_path=args.config, host=args.host, port=args.port)
