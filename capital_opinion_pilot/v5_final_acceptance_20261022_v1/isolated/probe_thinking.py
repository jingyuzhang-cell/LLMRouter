import json, urllib.request, sys
cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
key = next(r['config']['access']['apiKey'] for r in cfg['config']['providerConfigRules']['providerRules'] if r['providerId']=='bigmodel-api')
def call(model, extra):
    body = {"model": model, "max_tokens": 300,
            "messages": [{"role": "user", "content": "Return only this JSON: {\"ok\": true}"}]}
    body.update(extra)
    req = urllib.request.Request('https://open.bigmodel.cn/api/anthropic/v1/messages',
        data=json.dumps(body).encode(), method='POST')
    req.add_header('content-type','application/json'); req.add_header('x-api-key',key)
    req.add_header('authorization','Bearer '+key); req.add_header('anthropic-version','2023-06-01')
    t0=__import__('time').time()
    try:
        with urllib.request.urlopen(req, timeout=50) as r:
            d=json.loads(r.read().decode()); lat=__import__('time').time()-t0
            blocks=[b.get('type') for b in d.get('content',[])]
            text=''.join(b.get('text','') for b in d.get('content',[]) if b.get('type')=='text')[:80]
            return f"{model} extra={extra} -> blocks={blocks} text={text!r} usage={d.get('usage')} lat={lat:.1f}s"
    except urllib.error.HTTPError as e:
        return f"{model} extra={extra} -> HTTP {e.code}: {e.read().decode()[:200]}"
print(call('GLM-5.3', {}))
print(call('GLM-5.3', {"thinking": {"type": "disabled"}}))
print(call('GLM-5.3-Flash', {}))
print(call('GLM-5.3-Flash', {"thinking": {"type": "disabled"}}))
