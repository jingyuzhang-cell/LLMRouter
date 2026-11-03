#!/usr/bin/env python3
"""运行时标准 GLM 适配器（不改冻结执行器）。

背景：新套餐在 bigmodel-api-6（kOSw）+ 智谱标准 OpenAI 兼容端点；
冻结 transport 走 Anthropic 端点 + FSAK，返回 429/400。
本模块仅在运行时把 transport.call_model 的 GLM 分支指向标准端点；
DS 分支保持原实现；不修改任何冻结文件。
"""
import json
import os
import time
import urllib.error
import urllib.request

import transport

ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
KEY_PROVIDER = "bigmodel-api-6"
MODEL = {"glm53flash": "glm-5.3-flash", "glm53": "glm-5.3"}


def _key():
    cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
    for r in cfg["config"]["providerConfigRules"]["providerRules"]:
        if r.get("providerId") == KEY_PROVIDER:
            return r["config"]["access"]["apiKey"]
    raise RuntimeError(f"provider {KEY_PROVIDER} not found")


def _standard_call(alias, system, user, max_tokens, timeout_s, temperature=None):
    body = {"model": MODEL[alias],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0 if temperature is None else temperature}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + _key())
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    ch = d["choices"][0]
    msg = ch.get("message") or {}
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
    u = d.get("usage") or {}
    return {"text": text, "in": u.get("prompt_tokens", 0),
            "out": u.get("completion_tokens", 0),
            "stop": ch.get("finish_reason", ""),
            "lat": round(time.monotonic() - t0, 2)}


def install():
    orig = transport.call_model

    def call_model(alias, system, user, max_tokens, timeout_s, temperature=None):
        if alias in MODEL:
            return _standard_call(alias, system, user, max_tokens, timeout_s, temperature)
        return orig(alias, system, user, max_tokens, timeout_s, temperature)

    transport.call_model = call_model
    return True
