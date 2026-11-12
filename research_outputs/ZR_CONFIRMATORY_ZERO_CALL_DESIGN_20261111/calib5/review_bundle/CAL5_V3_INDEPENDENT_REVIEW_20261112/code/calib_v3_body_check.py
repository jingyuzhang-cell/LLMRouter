#!/usr/bin/env python3
"""零调用核对：拦截 urlopen，捕获 V3 Transport 实际构建的 HTTP 请求体。不联网。"""
import json, os, sys, urllib.request, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('STAGE_D_GLM_KEY', 'BODYCHECK-NO-NETWORK')
import calib_harness_v3 as H

captured = {}

class FakeResp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self):
        return json.dumps(dict(content=[dict(type='text', text='OK')],
                               usage=dict(input_tokens=10, output_tokens=1),
                               stop_reason='end_turn', model='GLM-5.3-Flash')).encode()

def fake_urlopen(req, timeout=None):
    captured['url'] = req.full_url
    captured['headers'] = {k: ('<redacted>' if k.lower() in ('x-api-key', 'authorization') else v)
                           for k, v in req.header_items()}
    captured['body_raw'] = req.data.decode('utf-8')
    captured['body'] = json.loads(captured['body_raw'])
    return FakeResp()

urllib.request.urlopen = fake_urlopen
o = H.Transport(real=True).call('BODY-CHECK-PROMPT', 123, 'bodycheck')
body = captured['body']
checks = dict(
    endpoint=captured['url'],
    model=body.get('model'),
    max_tokens=body.get('max_tokens'),
    has_thinking=body.get('thinking', {}).get('type') == 'enabled',
    has_output_effort=body.get('output_config', {}).get('effort') == 'low',
    thinking=body.get('thinking'),
    output_config=body.get('output_config'),
    reasoning_effort=body.get('reasoning_effort'),
    body_sha256=hashlib.sha256(captured['body_raw'].encode()).hexdigest(),
    headers_keys=sorted(captured['headers'].keys()),
    no_network=True,
)
print(json.dumps(checks, ensure_ascii=False, indent=1))
assert checks['has_thinking'] and checks['has_output_effort'], 'MISSING THINKING CONTROL FIELDS'
assert checks['endpoint'] == H.GLM_URL and checks['model'] == H.MODEL
Path('runs_v3').mkdir(exist_ok=True)
Path('runs_v3/REQUEST_BODY_CHECK.json').write_text(json.dumps(checks, ensure_ascii=False, indent=1))
print('BODY CHECK PASS')
