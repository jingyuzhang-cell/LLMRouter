"""Stage D V2.0 transport (GLM thinking=low / DeepSeek thinking=disabled).

Independent version; does NOT modify transport.py or any frozen file.
Every ledger record carries thinking_mode + reasoning_effort (Phase P gap D-P4).
Offline-testable via MockTransport (no network).
"""
import json, os, time, hashlib

GLM_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
DS_URL = 'https://api.deepseek.com/chat/completions'
# D2 accounting basis (same as historical, for comparability)
PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6

def glm_key():
    """Resource-package key (standard endpoint) from a local file if present;
    otherwise fall back to the provider config. Never printed."""
    import os, json as _j
    p = '/root/.zhipu_std_key'
    if os.path.exists(p):
        k = open(p).read().strip()
        if k: return k
    cfg = _j.load(open('/root/.zcode/v2/provider_config.json'))
    for r in cfg['config']['providerConfigRules']['providerRules']:
        if r.get('providerId') == 'bigmodel-standard-api':
            k = (r['config']['access']['apiKey'] or '').strip()
            if k: return k
    raise RuntimeError('glm key not found')

def ds_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    for r in cfg['config']['providerConfigRules']['providerRules']:
        if r.get('providerId') == 'deepseek':
            return (r['config']['access']['apiKey'] or '').strip()
    raise RuntimeError('ds key not found')

MODEL_CFG = {
    'glm53flash': dict(model='glm-5.3-flash', thinking='enabled', effort='low', url=GLM_URL, vendor='glm'),
    'deepseek':   dict(model='deepseek-flash', thinking='disabled', effort=None, url=DS_URL, vendor='deepseek'),
}

def build_request(alias, system, user, max_tokens, temperature=None):
    c = MODEL_CFG[alias]
    if c['vendor'] == 'glm':
        body = {'model': c['model'], 'max_tokens': max_tokens,
                'thinking': {'type': 'enabled'}, 'reasoning_effort': c['effort'],
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}]}
    else:
        body = {'model': c['model'], 'max_tokens': max_tokens,
                'thinking': {'type': 'disabled'},
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}]}
        if 'json' in (user or '').lower():
            body['response_format'] = {'type': 'json_object'}
    if temperature is not None:
        body['temperature'] = temperature
    return body

def accounting_yuan(tin, tout):
    return round(tin * PRICE_IN + tout * PRICE_OUT, 8)

class Ledger:
    def __init__(self, path):
        self.path = path
        self.records = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
        self.tokens = sum(r['usage']['input_tokens'] + r['usage']['output_tokens'] for r in self.records)
        self.cost = sum(r['accounting_yuan'] for r in self.records)
        self.index = {(r.get('purpose'), r.get('prompt_sha256')): r for r in self.records}
    def add(self, rec):
        self.records.append(rec)
        self.tokens += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
        self.cost += rec['accounting_yuan']
        with open(self.path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

class Transport:
    """Real transport. call() returns a record; never raises on 429/timeout without retry."""
    def __init__(self, ledger, cap_calls=10**9, cap_tokens=10**12, retries=(0, 20, 45)):
        self.ledger, self.cap_calls, self.cap_tokens, self.retries = ledger, cap_calls, cap_tokens, retries
    def call(self, alias, system, user, max_tokens, purpose, timeout_s=180):
        body = build_request(alias, system, user, max_tokens)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        hit = self.ledger.index.get((purpose, sha))
        if hit is not None:
            return hit
        if len(self.ledger.records) >= self.cap_calls: raise RuntimeError('call cap')
        import urllib.request, urllib.error
        last = None
        for att, delay in enumerate(self.retries, 1):
            if delay: time.sleep(delay)
            try:
                t0 = time.monotonic()
                req = urllib.request.Request(MODEL_CFG[alias]['url'],
                                             data=json.dumps(body).encode(), method='POST')
                req.add_header('content-type', 'application/json')
                if alias == 'glm53flash':
                    k = glm_key(); req.add_header('authorization', 'Bearer ' + k)
                else:
                    req.add_header('Authorization', 'Bearer ' + ds_key())
                with urllib.request.urlopen(req, timeout=timeout_s) as r:
                    d = json.loads(r.read().decode())
                lat = time.monotonic() - t0
                ch = d['choices'][0]; u = d.get('usage', {})
                c = ch.get('message', {}).get('content', '')
                text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
                tin = u.get('prompt_tokens', 0); tout = u.get('completion_tokens', 0)
                rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), alias=alias,
                           model=MODEL_CFG[alias]['model'],
                           thinking_mode=MODEL_CFG[alias]['thinking'],
                           reasoning_effort=MODEL_CFG[alias]['effort'],
                           purpose=purpose, max_tokens=max_tokens, prompt_sha256=sha,
                           prompt_chars=len(system) + len(user), response_chars=len(text),
                           usage=dict(input_tokens=tin, output_tokens=tout),
                           accounting_yuan=accounting_yuan(tin, tout),
                           latency_s=round(lat, 3),
                           stop_reason={'stop': 'end_turn', 'length': 'max_tokens'}.get(
                               ch.get('finish_reason'), ch.get('finish_reason')),
                           attempt=att, text=text)
                self.ledger.add(rec)
                self.ledger.index[(purpose, sha)] = rec
                if self.ledger.tokens > self.cap_tokens: raise RuntimeError('token cap')
                return rec
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504): raise
            except Exception as e:
                last = e
        raise last
