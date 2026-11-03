"""W4/W8 confirmatory experiment (frozen prereg: W48_PREREG.md).

Only variable: n1 input window EV[:4000] vs EV[:8000].
Everything else identical: n1 prompt + max_tokens 5000, n9 prompt + 2000,
n10 type-partitioned 4 calls + deterministic merge, model glm-5.3, scorer v3.1.
"""
import json, re, sys, time, hashlib, statistics
sys.path.insert(0, '/root/capital_opinion_pilot'); sys.path.insert(0, '/root/cap_eval_bench_v1')
import b_arm_budget as BB

SYS_DOC = '你是资本市场文档分析助手。穷尽提取所有事实，不遗漏任何条目。只输出JSON。'
SYS_DOWN = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'
URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
KEY = open('/root/.zhipu_std_key').read().strip()
MODEL = 'glm-5.3'                     # both arms (recorded in results)
MAXTOK = {'n1': 5000, 'n9': 2000, 'n10': 2000}
norm = BB.norm
zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV = ' '.join(d['text'] for d in zeda['docs'])
WINDOWS = {'W4': EV[:4000], 'W8': EV[:8000]}
N1_TEMPLATE = open('n1_revised_prompt.txt').read().split('文档：')[0]
SILVER = json.load(open('dd_v51_silver_facts.json'))
VALID = [f for f in SILVER if f['fid'] != 'A04']
TYPES = ('date', 'amount', 'penalty', 'entity')
BUCKET = {'date': 'dates', 'amount': 'amounts', 'penalty': 'penalties', 'entity': 'entities'}


def build_store_det(n1_text, window, pad=10):
    """Deterministic store (fixes D8). Identical to BB.build_store except the
    span-less fact_id uses sha1 instead of Python's process-randomised hash()."""
    o = BB.parse(n1_text)
    kind_map = {'dates': 'date', 'amounts': 'amount', 'penalties': 'penalty', 'entities': 'entity'}
    code = {'dates': 'DTE', 'amounts': 'AMT', 'penalties': 'PEN', 'entities': 'ENT'}
    recs = []
    for key, t in kind_map.items():
        for it in (o.get(key) or []):
            v = it.get('value') or it.get('name') or ''
            if not v: continue
            role = str(it.get('nature') or it.get('role') or it.get('type') or '')[:16]
            spans = BB.locate_all(v, t, window)
            prov = ('VERIFIED_UNIQUE_SPAN' if len(spans) == 1 else
                    'VERIFIED_MULTI_SPAN' if len(spans) > 1 else 'UNVERIFIABLE_ABSENT')
            quotes = [window[max(0, s - pad):e + pad].replace('\n', ' ') for s, e in spans]
            if spans:
                sid = str(spans[0][0])
            else:
                sid = 'X' + hashlib.sha1(norm(v).encode()).hexdigest()[:8]
            recs.append(dict(fact_id=f'{code[key]}{sid}', fact_type=t, fact_role=role, value=v,
                             provenance_status=prov, spans=[[s, e] for s, e in spans], quotes=quotes))
    seen, uniq = set(), []
    for r in recs:
        k = (r['fact_type'], norm(r['value']), r['fact_role'])
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq

# ─────────── frozen prompt construction (must match w48_precheck.py) ───────────
def n1_prompt(win):
    return SYS_DOC, N1_TEMPLATE + '文档：\n' + win

def n9_prompt(store):
    return BB.build_prompts(store, 10)['n9']

def n10_type_prompt(t, facts):
    us = (f'{SYS_DOWN}\n以下为已核验支持的{BUCKET[t]}事实（类型 {t}）。任务：把下列全部 fact_id 逐条写入报告，'
          f'每条保留原始值与语义角色；不得遗漏、不得新增、不得改写数值。输出JSON，字段 report。\n'
          + json.dumps([dict(fact_id=r['fact_id'], fact_role=r['fact_role'], value=r['value']) for r in facts],
                       ensure_ascii=False, separators=(',', ':'))
          + '\n输出JSON，字段 report。')
    return SYS_DOWN, us

def merge_parts(parts):
    return {'report': {BUCKET[t]: parts.get(t, []) for t in TYPES}}

# ─────────── STARTUP: verify all 12 frozen hashes (no drift since precheck) ───────────
def verify_freeze():
    frozen = json.load(open('w48_PROMPT_FREEZE_V2.json'))['hashes']
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()
    resp = {}
    for line in open('v9_LEDGER_responses.jsonl'):
        if not line.strip(): continue
        r = json.loads(line); resp[r['purpose']] = r['text']
    store_real = build_store_det(resp['V9-P1:B4:N1f:n1'], EV[:4000], 10)
    g_real = {t: [r for r in store_real if r['fact_type'] == t] for t in TYPES}
    # replicate precheck's simulated W8 store for the n10 template instance hashes
    FNUM = re.compile(r'\d[\d,，]*\.?\d*\s*(?:万元|亿元|万|亿|元)')
    FDATE = re.compile(r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日')
    FPEN = re.compile(r'罚款|警告|市场禁入|责令改正')
    FENT = re.compile(r'[\u4e00-\u9fa5]{2,12}(?:股份有限公司|有限公司|事务所)')
    W8 = EV[:8000]; sim = []
    for i, m in enumerate(FDATE.finditer(W8), 1):
        sim.append(dict(fact_id=f'DTE{i:03d}', fact_type='date', fact_role='SIM',
                        value=m.group(0).replace(' ', ''), provenance_status='VERIFIED_UNIQUE_SPAN',
                        spans=[[m.start(), m.end()]], quotes=['']))
    for i, m in enumerate(FNUM.finditer(W8), 1):
        sim.append(dict(fact_id=f'AMT{i:03d}', fact_type='amount', fact_role='SIM',
                        value=m.group(0).replace(' ', ''), provenance_status='VERIFIED_UNIQUE_SPAN',
                        spans=[[m.start(), m.end()]], quotes=['']))
    for i, m in enumerate(FPEN.finditer(W8), 1):
        sim.append(dict(fact_id=f'PEN{i:03d}', fact_type='penalty', fact_role='SIM', value=m.group(0),
                        provenance_status='VERIFIED_UNIQUE_SPAN', spans=[[m.start(), m.end()]], quotes=['']))
    seen = set()
    for i, m in enumerate(FENT.finditer(W8), 1):
        v = m.group(0)
        if v in seen: continue
        seen.add(v)
        sim.append(dict(fact_id=f'ENT{i:03d}', fact_type='entity', fact_role='SIM', value=v,
                        provenance_status='VERIFIED_UNIQUE_SPAN', spans=[[m.start(), m.end()]], quotes=['']))
    g_sim = {t: [r for r in sim if r['fact_type'] == t] for t in TYPES}
    checks = {
        'n1.system': h(SYS_DOC), 'n1.template': h(N1_TEMPLATE),
        'n9.system': h(n9_prompt(store_real)[0]),
        'n9.user_template': h(n9_prompt(store_real)[1]),
    }
    for t in TYPES:
        sy, us = n10_type_prompt(t, g_sim[t])
        checks[f'n10.{t}.system'] = h(sy)
        checks[f'n10.{t}.user_template'] = h(us)
    bad = [k for k in checks if checks[k] != frozen.get(k)]
    print(f"=== STARTUP FREEZE CHECK: {len(checks)} hashes, mismatches={bad}")
    if bad:
        for k in bad: print(f"   {k}: now={checks[k][:16]} frozen={frozen.get(k,'-')[:16]}")
        raise SystemExit('PROMPT DRIFT — aborting (prereg §7)')
    return checks

# ─────────── metering ───────────
class Meter:
    def __init__(self, ledger='w48_LEDGER.jsonl', resp='w48_LEDGER_responses.jsonl',
                 cap_calls=68, cap_tok=210000):
        import os
        self.ledger, self.resp = ledger, resp
        self.calls = [json.loads(l) for l in open(ledger)] if os.path.exists(ledger) else []
        self.responses = {}
        if os.path.exists(resp):
            for l in open(resp):
                if l.strip():
                    r = json.loads(l); self.responses[r['call_id']] = r['text']
        self.cap_calls, self.cap_tok = cap_calls, cap_tok
        self.tokens = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in self.calls)
    def call(self, model, system, user, max_tokens, purpose, timeout_s=180):
        sha = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()
        for c in self.calls:
            if c['purpose'] == purpose and c['prompt_sha256'] == sha:
                return c, self.responses.get(c['call_id'], '')
        if len(self.calls) >= self.cap_calls: raise RuntimeError('call cap 68 (prereg §8)')
        import urllib.request, urllib.error
        body = {'model': model, 'max_tokens': max_tokens, 'thinking': {'type': 'enabled'},
                'reasoning_effort': 'low',
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        last = None
        for att, delay in enumerate((0, 20, 45, 90), 1):
            if delay: time.sleep(delay)
            try:
                t0 = time.monotonic()
                req = urllib.request.Request(URL, data=json.dumps(body).encode(), method='POST')
                req.add_header('content-type', 'application/json')
                req.add_header('authorization', 'Bearer ' + KEY)
                with urllib.request.urlopen(req, timeout=timeout_s) as r:
                    d = json.loads(r.read().decode())
                lat = time.monotonic() - t0
                ch = d['choices'][0]; u = d.get('usage', {})
                stop = {'stop': 'end_turn', 'length': 'max_tokens'}.get(ch.get('finish_reason'), ch.get('finish_reason'))
                text = ch.get('message', {}).get('content') or ''
                rec = {'call_id': len(self.calls) + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
                       'model': model, 'purpose': purpose, 'max_tokens': max_tokens,
                       'prompt_sha256': sha, 'prompt_chars': len(system) + len(user),
                       'response_chars': len(text),
                       'usage': {'input_tokens': u.get('prompt_tokens', 0),
                                 'output_tokens': u.get('completion_tokens', 0)},
                       'latency_s': round(lat, 3), 'stop_reason': stop}
                self.calls.append(rec); self.responses[rec['call_id']] = text
                self.tokens += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
                with open(self.ledger, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                with open(self.resp, 'a') as f:
                    f.write(json.dumps({'call_id': rec['call_id'], 'purpose': purpose,
                                        'model': model, 'text': text}, ensure_ascii=False) + '\n')
                if self.tokens > self.cap_tok: raise RuntimeError('token cap 210K (prereg §8)')
                return rec, text
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504): raise
                print(f'    [retry {att}] HTTP {e.code} {purpose}')
            except Exception as e:
                last = e
                print(f'    [retry {att}] {type(e).__name__} {purpose}')
        raise last

M = Meter()

# ─────────── v3.1 scorer (identical to audit_v12 + penalty guard) ───────────
NUM = re.compile(r'\d[\d,，]*\.?\d*\s*(?:万元|亿元|万|亿|元|%)')
DATE = re.compile(r'\d{4}\s*[-年]\s*\d{1,2}\s*[-月]\s*\d{1,2}\s*日?')
def collect_values(o, acc=None):
    if acc is None: acc = []
    if isinstance(o, dict):
        for v in o.values(): collect_values(v, acc)
    elif isinstance(o, list):
        for v in o: collect_values(v, acc)
    elif isinstance(o, str): acc.append(o)
    else: acc.append(str(o))
    return acc
def variants(f, win):
    vs = [norm(f['value'])]
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m: vs.append(norm(f'{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日'))
    return [v for v in vs if v]
def occ(f, win):
    wn = norm(win); out = []
    for v in variants(f, win):
        for mm in re.finditer(re.escape(v), wn): out.append((mm.start(), mm.end()))
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if not out and f['kind'] == 'date' and m:
        el = norm(f'{int(m.group(2))}月{int(m.group(3))}日'); yr = m.group(1) + '年'
        for mm in re.finditer(re.escape(el), wn):
            if yr in wn[max(0, mm.start()-120):mm.end()+120]: out.append((mm.start(), mm.end()))
    return out
DENY = ['申辩', '请求', '陈述', '否认', '不采取', '不予处罚', '不予认定']
DECIDE = ['决定', '处罚决定', '本会决定', '作出下列']
def penalty_ok(f, win, span=120):
    wn = norm(win)
    for s, e in occ(f, win):
        c = wn[max(0, s-span):e+span]
        if any(d in c for d in DECIDE) and not any(n in c for n in DENY): return True
    return False
def claim_supported(c, t):
    k, s = c
    cs = {s, s.replace(',', '').replace('，', '')}
    if k == 'date':
        m = re.match(r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})', s)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            cs |= {f'{y}年{mo}月{d}日', f'{y}-{mo:02d}-{d:02d}', f'{mo}月{d}日'}
    return any(norm(x) in t for x in cs if x)

def score(n10_text, n1_text, win):
    o = BB.extract_json(n10_text)
    hay = norm(' | '.join(collect_values(o))) if o is not None else norm(n10_text)
    n1n = norm(n1_text); wn = norm(win)
    tp, prov, removed = [], [], []
    for f in VALID:
        if (any(v in hay for v in variants(f, win)) and any(v in n1n for v in variants(f, win))
                and occ(f, win)):
            if f['kind'] == 'penalty' and not penalty_ok(f, win):
                removed.append(f['fid']); continue
            tp.append(f['fid'])
        elif any(v in hay for v in variants(f, win)):
            prov.append(f['fid'])
    seen, fps = set(), []
    for c in ([('num', re.sub(r'\s+', '', m.group(0))) for m in NUM.finditer(n10_text)] +
              [('date', re.sub(r'\s+', '', m.group(0))) for m in DATE.finditer(n10_text)]):
        if claim_supported(c, wn) or norm(c[1]) in seen: continue
        seen.add(norm(c[1])); fps.append(c[1])
    R = len(tp)/len(VALID); P = len(tp)/max(1, len(tp)+len(fps))
    return dict(tp=len(tp), tp_facts=tp, fp=len(fps), fp_values=fps, semantic_removed=removed,
                unsupported_provenance=prov, recall=round(R,4), precision=round(P,4),
                f1=round(2*P*R/max(1e-3,P+R),4), report_json=o is not None)

# ─────────── run ───────────
def parse_n9(text):
    o = BB.extract_json(text)
    out = set()
    if isinstance(o, dict):
        for k in ('supported', 'SUPPORTED', '支持'):
            v = o.get(k)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, str): out.add(x)
                    elif isinstance(x, dict) and x.get('fact_id'): out.add(x['fact_id'])
        if not out:
            for k, v in o.items():
                if isinstance(v, str) and v.lower().startswith(('support', '确认', 'verif')): out.add(k)
    elif isinstance(o, list):
        for x in o:
            if isinstance(x, str): out.add(x)
            elif isinstance(x, dict):
                if 'fact_id' in x:
                    st = str(x.get('status') or x.get('verdict') or '').lower()
                    if st.startswith(('support', '确认', '已确认', 'verif')): out.add(x['fact_id'])
                elif len(x) == 1:
                    k, v = next(iter(x.items()))
                    if str(v).lower().startswith(('support', '确认', 'verif')): out.add(k)
    return out, o

def run_arm(arm, blk, win):
    out = {}
    sy, us = n1_prompt(win)
    rec1, n1_text = M.call(MODEL, sy, us, MAXTOK['n1'], f'W48-{arm}-B{blk}:n1')
    out['n1'] = rec1
    store = build_store_det(n1_text, win, 10)
    sy9, us9 = n9_prompt(store)
    rec9, t9 = M.call(MODEL, sy9, us9, MAXTOK['n9'], f'W48-{arm}-B{blk}:n9')
    sup, raw9 = parse_n9(t9)
    parts_dbg = {t: [r for r in store if r['fact_type'] == t and r['fact_id'] in sup] for t in TYPES}
    if not any(parts_dbg.values()):
        parts_dbg = {t: [r for r in store if r['fact_type'] == t] for t in TYPES}
    n10_results, n10_recs = {}, []
    for t in TYPES:   # always 4 calls, even for empty buckets (prereg §3)
        sy10, us10 = n10_type_prompt(t, parts_dbg[t])
        rec, txt = M.call(MODEL, sy10, us10, MAXTOK['n10'], f'W48-{arm}-B{blk}:n10:{t}')
        n10_results[t] = BB.extract_json(txt) if BB.extract_json(txt) is not None else txt
        n10_recs.append(rec)
    merged = merge_parts({t: (n10_results[t] if isinstance(n10_results[t], list) else
                              ([n10_results[t]] if n10_results[t] else [])) for t in TYPES})
    merged_text = json.dumps(merged, ensure_ascii=False)
    # completeness: every fed fact_id must appear exactly once in its part
    fed_ids = {t: {r['fact_id'] for r in parts_dbg[t]} for t in TYPES}
    got_ids = {t: {x.get('fact_id') for x in merged['report'][BUCKET[t]] if isinstance(x, dict)} for t in TYPES}
    missing = sum(len(fed_ids[t] - got_ids[t]) for t in TYPES)
    return dict(arm=arm, block=blk, n1_text=n1_text, n1_rec=rec1,
                store=len(store), n9_text=t9, n9_supported=len(sup), n9_shape=type(raw9).__name__,
                fed={t: len(parts_dbg[t]) for t in TYPES}, missing_ids=missing,
                merged_text=merged_text, score=score(merged_text, n1_text, win),
                n10_calls=[dict(tokens=r['usage']['input_tokens'] + r['usage']['output_tokens'],
                                lat=r['latency_s'], stop=r['stop_reason'], type=p.split(':')[-1])
                           for r, p in zip(n10_recs, [f'x:{t}' for t in TYPES])],
                tokens=rec1['usage']['input_tokens'] + rec1['usage']['output_tokens']
                       + rec9['usage']['input_tokens'] + rec9['usage']['output_tokens']
                       + sum(r['usage']['input_tokens'] + r['usage']['output_tokens'] for r in n10_recs),
                latency=rec1['latency_s'] + rec9['latency_s'] + sum(r['latency_s'] for r in n10_recs),
                n1_truncated=(rec1['stop_reason'] == 'max_tokens'),
                any_truncated=any(r['stop_reason'] == 'max_tokens' for r in [rec1, rec9] + n10_recs))

if __name__ == '__main__':
    hashes = verify_freeze()
    print(f"  model={MODEL}  n1_max_tokens={MAXTOK['n1']}  windows: W4=4000 W8=8000")
    rows = []
    t0 = time.time()
    for blk in range(1, 6):
        got = {}
        for arm in ('W4', 'W8'):
            r = run_arm(arm, blk, WINDOWS[arm])
            got[arm] = r
            s = r['score']
            print(f"  B{blk} {arm}: TP={s['tp']:2d} FP={s['fp']:2d} F1={s['f1']:.4f} "
                  f"store={r['store']:3d} n9sup={r['n9_supported']:3d} missing_ids={r['missing_ids']:2d} "
                  f"n1_trunc={r['n1_truncated']} tok={r['tokens']:6d} lat={r['latency']:6.1f}s")
        rows.append(dict(block=blk, W4={k: got['W4'][k] for k in
                                        ('store','n9_supported','fed','missing_ids','score','tokens','latency','n1_truncated','any_truncated','n9_shape')},
                         W8={k: got['W8'][k] for k in
                                        ('store','n9_supported','fed','missing_ids','score','tokens','latency','n1_truncated','any_truncated','n9_shape')},
                         W4_tp=got['W4']['score']['tp'], W8_tp=got['W8']['score']['tp']))
    med = lambda xs: statistics.median(xs)
    w4 = [r['W4_tp'] for r in rows]; w8 = [r['W8_tp'] for r in rows]
    pooled = lambda key, f: (sum(f(r[key]) for r in rows))
    tp4 = sum(r['W4']['score']['tp'] for r in rows); fp4 = sum(r['W4']['score']['fp'] for r in rows)
    tp8 = sum(r['W8']['score']['tp'] for r in rows); fp8 = sum(r['W8']['score']['fp'] for r in rows)
    date_ok = all(any(fid.startswith('D') for fid in r['W8']['score']['tp_facts']) for r in rows)
    n1_ok = all(not r['W4']['n1_truncated'] and not r['W8']['n1_truncated'] for r in rows)
    gates = dict(H_W1=bool(med(w8) >= 18), H_W2=bool(tp8/(tp8+fp8) >= 0.85),
                 H_W3=bool(date_ok), H_W4=bool(n1_ok))
    verdict = ('CONFIRMED' if all(gates.values())
               else 'NEGATIVE' if (med(w8) <= med(w4) or not date_ok or not n1_ok)
               else 'PARTIAL')
    print(f"\n=== RESULT ===")
    print(f"  W4 TP {w4} median={med(w4)} | W8 TP {w8} median={med(w8)}")
    print(f"  paired diff (W8-W4): {[b-a for a,b in zip(w4,w8)]} median={med([b-a for a,b in zip(w4,w8)])} "
          f"worst={min(b-a for a,b in zip(w4,w8))}")
    print(f"  pooled Precision: W4={tp4/(tp4+fp4):.4f} W8={tp8/(tp8+fp8):.4f}")
    print(f"  gates: {gates}")
    print(f"  VERDICT: {verdict}")
    newfacts = ['D07','D08','A02','A08','P01','P02','P04']
    for b in range(1, 6):
        r = next(x for x in rows if x['block'] == b)
        print(f"  B{b} new-fact hits (W8): {[f for f in newfacts if f in r['W8']['score']['tp_facts']]}")
    json.dump(dict(prereg='W48_PREREG.md', model=MODEL, max_tokens=MAXTOK,
                   prompt_hashes=hashes, blocks=rows, median=dict(W4=med(w4), W8=med(w8)),
                   paired_median=med([b-a for a,b in zip(w4,w8)]),
                   pooled_precision=dict(W4=round(tp4/(tp4+fp4),4), W8=round(tp8/(tp8+fp8),4)),
                   gates=gates, verdict=verdict,
                   calls=len(M.calls), tokens=M.tokens, elapsed_s=round(time.time()-t0,1)),
              open('w48_RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"\nSaved w48_RESULTS.json | calls={len(M.calls)}/68 tokens={M.tokens}/210000")
