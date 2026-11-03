"""Phase P: node-level capability heterogeneity (thinking=low).
Deviation P-D1 (pre-execution): the benchmark has ONE task (4 docs), not 3.
Executed as 1 task x 5 node types x 2 models x 3 reps = 32 calls (+1 DS precheck).
Criteria structure kept; ">=2/3 tasks" becomes ">=2/3 reps".
"""
import json, os, re, sys, time, hashlib, statistics
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
sys.path.insert(0, '/root/capital_opinion_pilot')
sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1/quality_v4')
import executor as SA
import d2_executor as D2

# ── DeepSeek key bridge (read from ZCode provider config; never printed) ──
def bridge_ds_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    for r in cfg['config']['providerConfigRules']['providerRules']:
        if r.get('providerId') == 'deepseek':
            k = (r.get('config', {}).get('access', {}) or {}).get('apiKey', '').strip()
            if k:
                os.environ['DEEPSEEK_API_KEY'] = k
                return True
    return False

SYS_E_POS = SA.E_SYSTEM + SA.E_POSITION_ADDENDUM
SYS_E = SA.E_SYSTEM
SYS_J1, SYS_J2, SYS_SINK = SA.J1_SYSTEM, SA.J2_SYSTEM, SA.SINK_SYSTEM
MAXTOK = {'E': 2000, 'J1': 3000, 'J2': 4000, 'SINK': 4000}
URL_GLM = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
KEY_GLM = open('/root/.zhipu_std_key').read().strip()
M_GLM, M_DS = 'glm-5.3-flash', 'deepseek'
TYPES = ['T1', 'T2', 'T3', 'T4', 'T5']

led_path, resp_path = 'phase_p_LEDGER.jsonl', 'phase_p_LEDGER_responses.jsonl'
calls = [json.loads(l) for l in open(led_path)] if os.path.exists(led_path) else []
responses = {}
if os.path.exists(resp_path):
    for l in open(resp_path):
        if l.strip():
            r = json.loads(l); responses[r['call_id']] = r['text']
TOKENS = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in calls)
CAP_CALLS, CAP_TOK = 75, 400000

def call(model, system, user, max_tokens, purpose, timeout_s=180):
    global TOKENS
    sha = hashlib.sha256((model + '\x00' + system + '\x00' + user).encode()).hexdigest()
    for c in calls:
        if c['purpose'] == purpose and c['prompt_sha256'] == sha:
            return c, responses.get(c['call_id'], '')
    if len(calls) >= CAP_CALLS: raise RuntimeError('call cap 75')
    import urllib.request, urllib.error
    if model == M_GLM:
        body = {'model': M_GLM, 'max_tokens': max_tokens, 'thinking': {'type': 'enabled'},
                'reasoning_effort': 'low',
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        req = urllib.request.Request(URL_GLM, data=json.dumps(body).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('authorization', 'Bearer ' + KEY_GLM)
    else:
        body = {'model': 'deepseek-flash', 'max_tokens': max_tokens,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        # DS requires the word "json" when response_format=json_object is set
        if 'json' in (user or '').lower():
            body['response_format'] = {'type': 'json_object'}
        req = urllib.request.Request('https://api.deepseek.com/chat/completions',
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', 'Bearer ' + os.environ.get('DEEPSEEK_API_KEY', ''))
    last = None
    for att, delay in enumerate((0, 20, 45), 1):
        if delay: time.sleep(delay)
        try:
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                d = json.loads(r.read().decode())
            lat = time.monotonic() - t0
            if model == M_GLM:
                ch = d['choices'][0]; u = d.get('usage', {})
                text = ch.get('message', {}).get('content') or ''
                stop = {'stop': 'end_turn', 'length': 'max_tokens'}.get(ch.get('finish_reason'), ch.get('finish_reason'))
                tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
            else:
                ch = d['choices'][0]; u = d.get('usage', {})
                c = ch.get('message', {}).get('content', '')
                text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or '')
                stop = {'stop': 'end_turn', 'length': 'max_tokens'}.get(ch.get('finish_reason'), ch.get('finish_reason'))
                tin, tout = u.get('prompt_tokens', 0), u.get('completion_tokens', 0)
            rec = {'call_id': len(calls) + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'model': model,
                   'purpose': purpose, 'max_tokens': max_tokens, 'prompt_sha256': sha,
                   'prompt_chars': len(system) + len(user), 'response_chars': len(text),
                   'usage': {'input_tokens': tin, 'output_tokens': tout},
                   'latency_s': round(lat, 3), 'stop_reason': stop}
            calls.append(rec); responses[rec['call_id']] = text
            TOKENS += tin + tout
            with open(led_path, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            with open(resp_path, 'a') as f:
                f.write(json.dumps({'call_id': rec['call_id'], 'purpose': purpose, 'model': model,
                                    'text': text}, ensure_ascii=False) + '\n')
            if TOKENS > CAP_TOK: raise RuntimeError('token cap 400K')
            return rec, text
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504): raise
            print(f'    [retry {att}] HTTP {e.code} {purpose}')
        except Exception as e:
            last = e
            print(f'    [retry {att}] {type(e).__name__} {purpose}')
    raise last

SOURCE = ''.join(''.join(rec['text'] for rec in SA.SRC[d]['pages'].values()) for d in SA.SRC)
NORM = lambda s: re.sub(r'\s+', '', str(s))

def parse(t):
    try: return D2.extract_json(t)
    except Exception: return None

REQ_KEYS = {'T1': ['subjects', 'notice_numbers', 'dates', 'cause', 'quotes', 'positions'],
            'T2': ['subjects', 'notice_numbers', 'dates', 'cause', 'quotes'],
            'T3': ['judgments'], 'T4': ['subject_binding', 'notice_binding', 'cause_specificity', 'counts'],
            'T5': ['answers']}

def grounded_ratio(obj):
    vals = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('quote', 'evidence') and isinstance(v, str): vals.append(v)
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
    ok = sum(1 for v in vals if NORM(v)[:40] and NORM(v)[:40] in NORM(SOURCE))
    return ok / len(vals)

if __name__ == '__main__':
    print('=== key bridge ===')
    print('  DeepSeek key bridged:', bridge_ds_key())
    print('=== PRECHECK: DeepSeek ===')
    rec, txt = call(M_DS, 'ping', '只回复两个字：收到', 16, 'PP-PRE:ds', timeout_s=60)
    print(f"  OK in={rec['usage']['input_tokens']} out={rec['usage']['output_tokens']} text={txt[:14]!r}")

    print('\n=== REFERENCE CHAIN (GLM) ===')
    snap = {}
    src = {'E1': SA.e_user('E1'), 'E2': SA.e_user('E2'), 'E3': SA.e_user('E3'), 'E4': SA.e_user('E4')}
    for n in ('E1', 'E2', 'E3', 'E4'):
        rec, t = call(M_GLM, SYS_E_POS if n in ('E1', 'E2') else SYS_E, src[n], MAXTOK['E'], f'PP-REF:{n}')
        snap[n] = t
        print(f"  {n}: {len(t)} chars, out={rec['usage']['output_tokens']}")
    rec, t = call(M_GLM, SYS_J1, SA.j1_user(json.dumps({'E1': snap['E1'], 'E2': snap['E2']}, ensure_ascii=False)),
                  MAXTOK['J1'], 'PP-REF:J1')
    snap['J1'] = t; print(f"  J1: {len(t)} chars")
    rec, t = call(M_GLM, SYS_J2, SA.j2_user(json.dumps({'J1': snap['J1'], 'E3': snap['E3'], 'E4': snap['E4']},
                                                       ensure_ascii=False)), MAXTOK['J2'], 'PP-REF:J2')
    snap['J2'] = t; print(f"  J2: {len(t)} chars")
    rec, t = call(M_GLM, SYS_SINK, SA.sink_user(snap['J2']), MAXTOK['SINK'], 'PP-REF:SINK')
    snap['SINK'] = t; print(f"  SINK: {len(t)} chars")
    snap_sha = hashlib.sha256(json.dumps(snap, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    print(f"  snapshot sha256={snap_sha[:16]}")
    json.dump({'snapshot': snap, 'sha256': snap_sha}, open('phase_p_SNAPSHOT.json', 'w'), ensure_ascii=False, indent=1)

# ─────────── measurements ───────────
def user_for(t, snap):
    if t == 'T1': return src['E1'], SYS_E_POS, MAXTOK['E']
    if t == 'T2': return src['E3'], SYS_E, MAXTOK['E']
    if t == 'T3': return SA.j1_user(json.dumps({'E1': snap['E1'], 'E2': snap['E2']}, ensure_ascii=False)), SYS_J1, MAXTOK['J1']
    if t == 'T4': return SA.j2_user(json.dumps({'J1': snap['J1'], 'E3': snap['E3'], 'E4': snap['E4']}, ensure_ascii=False)), SYS_J2, MAXTOK['J2']
    return SA.sink_user(snap['J2']), SYS_SINK, MAXTOK['SINK']

def score_cell(t, text):
    obj = parse(text)
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
        # Q = contract * grounding (grounding is the only objective, Gold-free signal for E/J nodes)
        out['Q'] = round((1.0 if contract else 0.0) * (g if g is not None else 0.0), 4)
    return out

# ─────────── run measurements with interleaving ───────────
MEAS = []   # list of dicts
# GLM rep1 comes from the reference chain (it IS a GLM call on the same input)
ref_map = {'T1': 'E1', 'T2': 'E3', 'T3': 'J1', 'T4': 'J2', 'T5': 'SINK'}
for t in TYPES:
    MEAS.append(dict(type=t, model=M_GLM, rep=1, text=snap[ref_map[t]], from_ref=True,
                     score=score_cell(t, snap[ref_map[t]])))

# measurements: GLM rep2/3 and DS rep1/2/3; model order alternates to avoid order bias
for t in TYPES:
    for rep in (2, 3):
        order = [M_GLM, M_DS] if ((TYPES.index(t) + rep) % 2 == 0) else [M_DS, M_GLM]
        for m in order:
            u, sy, mt = user_for(t, snap)
            rec, txt = call(m, sy, u, mt, f'PP:{t}:{m.replace(".","")}:r{rep}')
            MEAS.append(dict(type=t, model=m, rep=rep, text=txt, from_ref=False,
                             score=score_cell(t, txt), tokens=rec['usage'], latency=rec['latency_s'],
                             stop=rec['stop_reason']))
    u, sy, mt = user_for(t, snap)
    rec, txt = call(M_DS, sy, u, mt, f'PP:{t}:{M_DS}:r1')
    MEAS.append(dict(type=t, model=M_DS, rep=1, text=txt, from_ref=False,
                     score=score_cell(t, txt), tokens=rec['usage'], latency=rec['latency_s'],
                     stop=rec['stop_reason']))

print(f"\n=== measurements collected: {len(MEAS)} (calls={len(calls)}) ===")
json.dump(MEAS, open('phase_p_MEASUREMENTS.json', 'w'), ensure_ascii=False, indent=1)

# ─────────── analysis: P-H1..P-H4 ───────────
def collect(t, m):
    return [x for x in MEAS if x['type'] == t and x['model'] == m]

print('\n=== PER-TYPE RESULTS (Q per rep) ===')
rows = {}
for t in TYPES:
    g = sorted(collect(t, M_GLM), key=lambda x: x['rep'])
    d = sorted(collect(t, M_DS), key=lambda x: x['rep'])
    qg = [x['score']['Q'] for x in g]; qd = [x['score']['Q'] for x in d]
    drep = [round(a - b, 4) for a, b in zip(qg, qd)]
    mean_d = round(statistics.mean(drep), 4)
    sd = round(statistics.pstdev(drep), 4) if len(set(drep)) > 1 else 0.0
    sign_agree = all((x > 0) == (drep[0] > 0) for x in drep) if drep and drep[0] != 0 else False
    rows[t] = dict(Q_glm=qg, Q_ds=qd, delta=drep, mean_delta=mean_d, sd_rep=sd,
                   sign_agree=sign_agree, delta_range=round(max(drep) - min(drep), 4) if drep else None,
                   cost_glm=[x.get('tokens') for x in g], cost_ds=[x.get('tokens') for x in d],
                   lat_glm=[x.get('latency') for x in g], lat_ds=[x.get('latency') for x in d])
    print(f"  {t}: GLM={qg} DS={qd} d={drep} mean={mean_d:+.4f} sd={sd:.4f} sign_agree={sign_agree}")

print('\n=== P-H1: sign reversal (|d|>=0.05, reps agree) ===')
rev = []
for i in range(len(TYPES)):
    for j in range(i+1, len(TYPES)):
        a, b = TYPES[i], TYPES[j]
        da, db = rows[a]['mean_delta'], rows[b]['mean_delta']
        if abs(da) >= 0.05 and abs(db) >= 0.05 and (da > 0) != (db > 0):
            if rows[a]['sign_agree'] and rows[b]['sign_agree']:
                rev.append((a, b, da, db))
print('  reversal pairs:', rev if rev else 'NONE')

print('\n=== P-H3: stability (sign agreement + delta_range<=0.10) ===')
stable = {t: (rows[t]['sign_agree'] and (rows[t]['delta_range'] is not None and rows[t]['delta_range'] <= 0.10))
          for t in TYPES}
print('  ', stable)

print('\n=== P-H4: contract compliance ===')
for t in TYPES:
    for m in (M_GLM, M_DS):
        cs = [x['score']['contract'] for x in collect(t, m)]
        print(f"  {t} {m:14s} contract={sum(cs)}/{len(cs)}")

print('\n=== P-H2: one-way zones (symmetric) ===')
def tok_mean(t, m):
    xs = [x['tokens']['input_tokens'] + x['tokens']['output_tokens'] for x in collect(t, m) if x.get('tokens')]
    return statistics.mean(xs) if xs else None
def lat_mean(t, m):
    xs = [x['latency'] for x in collect(t, m) if x.get('latency')]
    return statistics.mean(xs) if xs else None
for t in TYPES:
    rg, rd = rows[t], None
    cg, cd = tok_mean(t, M_GLM), tok_mean(t, M_DS)
    lg, ld = lat_mean(t, M_GLM), lat_mean(t, M_DS)
    print(f"  {t}: mean_d={rows[t]['mean_delta']:+.4f} tok GLM={cg if cg is None else round(cg)} DS={cd if cd is None else round(cd)} "
          f"lat GLM={lg if lg is None else round(lg,1)} DS={ld if ld is None else round(ld,1)}")

P_H1 = bool(rev)
P_H3 = all(stable[t] for t, _ in [(a, b) for a, b, _, _ in rev]) if rev else False
P_H4 = all(sum(x['score']['contract'] for x in collect(t, m)) >= 3 for t in TYPES for m in (M_GLM, M_DS))
print(f"\n=== VERDICT ===  P-H1={P_H1}  P-H3={P_H3}  P-H4={P_H4}")
json.dump(dict(deviation='P-D1: 1 task (benchmark has one 4-doc task) instead of 3; 3 reps instead of 2',
               snapshot_sha256=snap_sha, rows=rows, reversal_pairs=rev, stable=stable,
               gates=dict(P_H1=P_H1, P_H3=P_H3, P_H4=P_H4),
               calls=len(calls), tokens=TOKENS),
          open('phase_p_RESULTS.json','w'), ensure_ascii=False, indent=1)
print(f'\nSaved phase_p_RESULTS.json | calls={len(calls)}/75 tokens={TOKENS}/400000')
