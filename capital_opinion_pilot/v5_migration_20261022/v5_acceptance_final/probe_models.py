import json, urllib.request, sys

cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
rules = cfg['config']['providerConfigRules']['providerRules']
key = None
for r in rules:
    if r['providerId'] == 'bigmodel-api':
        key = r['config']['access']['apiKey']
if not key:
    print('NO KEY FOUND'); sys.exit(1)

def try_call(base, path, model, headers_extra=None, body=None):
    url = base + path
    body = body or {"model": model, "max_tokens": 24,
                    "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type', 'application/json')
    req.add_header('x-api-key', key)
    req.add_header('authorization', 'Bearer ' + key)
    if headers_extra: req.headers.update(headers_extra)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            txt = r.read().decode()
            d = json.loads(txt)
            usage = d.get('usage')
            content = ''
            if isinstance(d.get('content'), list) and d['content']:
                content = d['content'][0].get('text', '')[:60]
            return f"HTTP {r.status} model={model} usage={usage} content={content!r}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} model={model} err={e.read().decode()[:200]}"
    except Exception as e:
        return f"FAIL model={model} {type(e).__name__}: {e}"

ANTH = 'https://open.bigmodel.cn/api/anthropic'
for m in ['GLM-5.3', 'GLM-5.3-Flash']:
    print(try_call(ANTH, '/v1/messages', m, {'anthropic-version': '2023-06-01'}))
