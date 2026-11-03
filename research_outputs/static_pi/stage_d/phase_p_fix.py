"""Phase P retest: DeepSeek with thinking=disabled (matching frozen transport.py).
Deviation P-D2: first DS pass was invalid (12/15 truncated, 9 empty) because thinking
consumed max_tokens. GLM cells from the first pass are valid and kept.
"""
import json, os, re, sys, time, hashlib, statistics
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1/quality_v4')
import executor as SA
import d2_executor as D2

cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
DS_KEY = ''
for r in cfg['config']['providerConfigRules']['providerRules']:
    if r.get('providerId') == 'deepseek':
        DS_KEY = (r.get('config', {}).get('access', {}) or {}).get('apiKey', '').strip()
SYS_E_POS = SA.E_SYSTEM + SA.E_POSITION_ADDENDUM
SYS_E, SYS_J1, SYS_J2, SYS_SINK = SA.E_SYSTEM, SA.J1_SYSTEM, SA.J2_SYSTEM, SA.SINK_SYSTEM
MAXTOK = {'E': 2000, 'J1': 3000, 'J2': 4000, 'SINK': 4000}
M_GLM, M_DS = 'glm-5.3-flash', 'deepseek'
TYPES = ['T1', 'T2', 'T3', 'T4', 'T5']
SNAP = json.load(open('phase_p_SNAPSHOT.json'))['snapshot']
SOURCE = ''.join(''.join(rec['text'] for rec in SA.SRC[d]['pages'].values()) for d in SA.SRC)
NORM = lambda s: re.sub(r'\s+', '', str(s))
led_path, resp_path = 'phase_p_LEDGER.jsonl', 'phase_p_LEDGER_responses.jsonl'
calls = [json.loads(l) for l in open(led_path) if l.strip()]
responses = {}
for l in open(resp_path):
    if l.strip():
        r = json.loads(l); responses[r['call_id']] = r['text']
TOKENS = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in calls)
CAP_CALLS, CAP_TOK = 75, 400000
src = {'E1': SA.e_user('E1'), 'E2': SA.e_user('E2'), 'E3': SA.e_user('E3'), 'E4': SA.e_user('E4')}

def call_ds(system, user, max_tokens, purpose, timeout_s=180):
    global TOKENS
    sha = hashlib.sha256((M_DS + '\x00' + system + '\x00' + user).encode()).hexdigest()
    for c in calls:
        if c['purpose'] == purpose and c['prompt_sha256'] == sha:
            return c, responses.get(c['call_id'], '')
    if len(calls) >= CAP_CALLS: raise RuntimeError('call cap 75')
    import urllib.request, urllib.error
    body = {'model': 'deepseek-flash', 'max_tokens': max_tokens,
            'thinking': {'type': 'disabled'},          # ← the fix
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    if 'json' in (user or '').lower():
        body['response_format'] = {'type': 'json_object'}
    last = None
    for att, delay in enumerate((0, 20, 45), 1):
        if delay: time.sleep(delay)
        try:
            t0 = time.monotonic()
            req = urllib.request.Request('https://api.deepseek.com/chat/completions',
                                         data=json.dumps(body).encode(), method='POST')
            req.add_header('Content-Type', 'application/json')
            req.add_header('Authorization', 'Bearer ' + DS_KEY)
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                d = json.loads(r.read().decode())
            lat = time.monotonic() - t0
            ch = d['choices'][0]; u = d.get('usage', {})
            c = ch.get('message', {}).get('content', '')
            text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
            stop = {'stop': 'end_turn', 'length': 'max_tokens'}.get(ch.get('finish_reason'), ch.get('finish_reason'))
            rec = {'call_id': len(calls) + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'model': M_DS,
                   'purpose': purpose, 'max_tokens': max_tokens, 'prompt_sha256': sha,
                   'prompt_chars': len(system) + len(user), 'response_chars': len(text),
                   'usage': {'input_tokens': u.get('prompt_tokens', 0), 'output_tokens': u.get('completion_tokens', 0)},
                   'latency_s': round(lat, 3), 'stop_reason': stop}
            calls.append(rec); responses[rec['call_id']] = text
            TOKENS += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
            with open(led_path, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            with open(resp_path, 'a') as f:
                f.write(json.dumps({'call_id': rec['call_id'], 'purpose': purpose, 'model': M_DS,
                                    'text': text}, ensure_ascii=False) + '\n')
            if TOKENS > CAP_TOK: raise RuntimeError('token cap')
            return rec, text
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504): raise
            print(f'    [retry {att}] HTTP {e.code}')
        except Exception as e:
            last = e
            print(f'    [retry {att}] {type(e).__name__}')
    raise last

REQ_KEYS = {'T1': ['subjects', 'notice_numbers', 'dates', 'cause', 'quotes', 'positions'],
            'T2': ['subjects', 'notice_numbers', 'dates', 'cause', 'quotes'],
            'T3': ['judgments'], 'T4': ['subject_binding', 'notice_binding', 'cause_specificity', 'counts'],
            'T5': ['answers']}
def grounded_ratio(obj):
    vals = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == 'quote' and isinstance(v, str): vals.append(v)
                elif k == 'evidence' and isinstance(v, list):
                    for e in v:
                        if isinstance(e, dict):
                            for kk in ('quote', 'sentence', 'text'):
                                if isinstance(e.get(kk), str): vals.append(e[kk])
                else: walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(obj)
    if not vals: return None
    return sum(1 for v in vals if NORM(v)[:40] and NORM(v)[:40] in NORM(SOURCE)) / len(vals)

def score_cell(t, text):
    obj = D2.extract_json(text) if text else None
    contract = bool(obj is not None and all(k in obj for k in REQ_KEYS[t]))
    g = grounded_ratio(obj) if obj is not None else None
    out = dict(json_parsed=obj is not None, contract=contract, grounding=(round(g, 4) if g is not None else None))
    if t == 'T5' and obj is not None:
        try:
            from terminal_quality import evaluate_terminal_quality
            term = SA.build_terminal_output(json.loads(json.dumps(obj)))
            r = evaluate_terminal_quality(SA.CONTRACT, term, SA.SRC)
            tp = sum(1 for c in r['claim_results'] if c['status'].startswith('CORRECT'))
            out['tp'] = tp; out['Q'] = round(tp / 23, 4)
        except Exception as e:
            out['tp'] = 0; out['Q'] = 0.0; out['score_err'] = str(e)[:80]
    else:
        out['Q'] = round((1.0 if contract else 0.0) * (g if g is not None else 0.0), 4)
    return out

def user_for(t):
    if t == 'T1': return src['E1'], SYS_E_POS, MAXTOK['E']
    if t == 'T2': return src['E3'], SYS_E, MAXTOK['E']
    if t == 'T3': return SA.j1_user(json.dumps({'E1': SNAP['E1'], 'E2': SNAP['E2']}, ensure_ascii=False)), SYS_J1, MAXTOK['J1']
    if t == 'T4': return SA.j2_user(json.dumps({'J1': SNAP['J1'], 'E3': SNAP['E3'], 'E4': SNAP['E4']}, ensure_ascii=False)), SYS_J2, MAXTOK['J2']
    return SA.sink_user(SNAP['J2']), SYS_SINK, MAXTOK['SINK']

if __name__ == '__main__':
    print('=== DS retest with thinking=disabled ===')
    new = {}
    for t in TYPES:
        for rep in (1, 2, 3):
            u, sy, mt = user_for(t)
            rec, txt = call_ds(sy, u, mt, f'PP2:{t}:{M_DS}:r{rep}')
            sc = score_cell(t, txt)
            new[(t, rep)] = dict(model=M_DS, rep=rep, score=sc, text=txt,
                                 tokens=rec['usage'], latency=rec['latency_s'], stop=rec['stop_reason'])
            print(f"  {t} r{rep}: Q={sc['Q']:.4f} contract={sc['contract']} grounding={sc['grounding']} "
                  f"out={rec['usage']['output_tokens']} stop={rec['stop_reason']} chars={len(txt)}")
    json.dump({f'{t}:r{r}': v for (t, r), v in new.items()}, open('phase_p_DS_RETEST.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f'\ncalls={len(calls)}/75 tokens={TOKENS}/400000')
