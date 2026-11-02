"""Shared model transports (pure functions, zero instance state).

Extracted 2026-10-14 from f7_v2_experiment.V2Meter so the KDX and ST runners
share ONE transport implementation instead of the fragile __new__-proxy reuse.
Every function takes explicit arguments only; meters keep accounting/persistence.
"""
import json
import time
import urllib.request

GLM_ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
GLM_MODELS = {'glm53': 'GLM-5.3', 'glm53flash': 'GLM-5.3-Flash'}
OPENAI_MODELS = {'deepseek': ('deepseek-flash', 'https://api.deepseek.com', 'DEEPSEEK_API_KEY'),
                 'qwen': ('qwen-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'DASHSCOPE_API_KEY')}


def glm_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    return next(r['config']['access']['apiKey']
                for r in cfg['config']['providerConfigRules']['providerRules']
                if r['providerId'] == 'bigmodel-api')


def glm_call(alias, system, user, max_tokens, timeout_s, temperature=None):
    """GLM subscription (Anthropic-compatible endpoint), thinking disabled.

    temperature=None (default) keeps the request body byte-identical to the
    pre-2026-11-01 behavior (field omitted -> API default). Explicit values are
    passed through for frozen-protocol experiments (Static-π freezes 0).
    Extension recorded: cc652395… -> see MANIFEST; zero other changes.
    """
    body = {'model': GLM_MODELS[alias], 'max_tokens': max_tokens,
            'thinking': {'type': 'disabled'}, 'system': system,
            'messages': [{'role': 'user', 'content': user}]}
    if temperature is not None:
        body['temperature'] = temperature
    req = urllib.request.Request(GLM_ENDPOINT, data=json.dumps(body).encode(), method='POST')
    key = glm_key()
    req.add_header('content-type', 'application/json')
    req.add_header('x-api-key', key)
    req.add_header('authorization', 'Bearer ' + key)
    req.add_header('anthropic-version', '2023-06-01')
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    return {'text': ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text'),
            'in': d['usage']['input_tokens'], 'out': d['usage']['output_tokens'],
            'stop': d.get('stop_reason'), 'lat': round(time.monotonic() - t0, 2)}


def openai_call(alias, system, user, max_tokens, timeout_s, temperature=None):
    """DeepSeek / Qwen OpenAI-compatible chat completions (env preloaded by meter)."""
    import os
    model_id, base, env_key = OPENAI_MODELS[alias]
    body = {'model': model_id, 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_object'}}
    if alias == 'deepseek':
        body['thinking'] = {'type': 'disabled'}
    if temperature is not None:
        body['temperature'] = temperature
    req = urllib.request.Request(base + '/chat/completions',
                                 data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + os.environ.get(env_key, ''))
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    c = d['choices'][0]['message'].get('content', '')
    if isinstance(c, list):
        c = ''.join(x.get('text', '') for x in c if isinstance(x, dict))
    u = d['usage']
    return {'text': c, 'in': u.get('prompt_tokens', u.get('input_tokens', 0)),
            'out': u.get('completion_tokens', u.get('output_tokens', 0)),
            'stop': d['choices'][0].get('finish_reason', ''), 'lat': round(time.monotonic() - t0, 2)}


def call_model(alias, system, user, max_tokens, timeout_s, temperature=None):
    if alias in GLM_MODELS:
        return glm_call(alias, system, user, max_tokens, timeout_s, temperature)
    return openai_call(alias, system, user, max_tokens, timeout_s, temperature)
