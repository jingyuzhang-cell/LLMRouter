"""V9: node-level heterogeneous model capability + static allocation.
Scoring v3.1 (approved). Deterministic fact ordering (D4 fix). New file; history untouched.

Phase 0  probe glm-5.3-flash package (1 tiny call)
Phase 1  capability measurement on n1 / n9 / n10 (flash swapped in, others stay glm-5.3)
Phase 2  arms: U-S (reused from V1.2), U-F (all flash), H (allocation rule on measurements)
"""
import json, re, sys, time, hashlib, collections, statistics
sys.path.insert(0, '/root/capital_opinion_pilot'); sys.path.insert(0, '/root/cap_eval_bench_v1')
import b_arm_budget as BB

SYS_DOC = '你是资本市场文档分析助手。穷尽提取所有事实，不遗漏任何条目。只输出JSON。'
SYS_DOWN = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'
URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
KEY = open('/root/.zhipu_std_key').read().strip()
M_STRONG, M_FAST = 'glm-5.3', 'glm-5.3-flash'
MAXTOK = {'n1': 4000, 'n9': 2000, 'n10': 2000}
norm = BB.norm

zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV = ' '.join(d['text'] for d in zeda['docs']); WINDOW = EV[:4000]
N1_TEMPLATE = open('n1_revised_prompt.txt').read().split('文档：')[0]
SILVER = json.load(open('dd_v51_silver_facts.json'))
VALID = [f for f in SILVER if f['fid'] != 'A04']

# ── deterministic metering (dedup by purpose+sha; crash-safe replay) ──
class Meter:
    def __init__(self, ledger='v9_LEDGER.jsonl', resp='v9_LEDGER_responses.jsonl', cap_calls=80, cap_tok=600000):
        self.ledger, self.resp = ledger, resp
        self.calls = [json.loads(l) for l in open(ledger)] if __import__('os').path.exists(ledger) else []
        self.responses = {}
        if __import__('os').path.exists(resp):
            for l in open(resp):
                if l.strip():
                    r = json.loads(l); self.responses[r['call_id']] = r['text']
        self.cap_calls, self.cap_tok = cap_calls, cap_tok
        self.tokens = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in self.calls)
    def call(self, model, system, user, max_tokens, purpose, timeout_s=150, retries=(0, 20, 45, 90)):
        sha = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()
        for c in self.calls:
            if c['purpose'] == purpose and c['prompt_sha256'] == sha:
                return c, self.responses.get(c['call_id'], '')
        if len(self.calls) >= self.cap_calls: raise RuntimeError(f'call cap {self.cap_calls}')
        import urllib.request, urllib.error
        body = {'model': model, 'max_tokens': max_tokens, 'thinking': {'type': 'enabled'},
                'reasoning_effort': 'low',
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        last = None
        for att, delay in enumerate(retries, 1):
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
                       'usage': {'input_tokens': u.get('prompt_tokens', 0), 'output_tokens': u.get('completion_tokens', 0)},
                       'latency_s': round(lat, 3), 'stop_reason': stop, 'attempt': att}
                self.calls.append(rec); self.responses[rec['call_id']] = text
                self.tokens += rec['usage']['input_tokens'] + rec['usage']['output_tokens']
                with open(self.ledger, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                with open(self.resp, 'a') as f: f.write(json.dumps({'call_id': rec['call_id'], 'purpose': purpose,
                                                                   'model': model, 'text': text}, ensure_ascii=False) + '\n')
                if self.tokens > self.cap_tok: raise RuntimeError(f'token cap {self.cap_tok}')
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

# ── prompts (identical to V1.2) ──
def n1_prompt():
    return SYS_DOC, N1_TEMPLATE + '文档：\n' + WINDOW

def n9_prompt(store):
    return BB.build_prompts(store, 10)['n9']

def n10_prompt(fed):
    us = (f'{SYS_DOWN}\n以下为已核验支持的 facts。任务：组织完整调查报告，逐项包含所有日期、金额（保留原始数字与单位）、处罚、主体。'
          f'不得新增事实。输出JSON，字段 report。\n'
          + json.dumps([dict(fact_id=r['fact_id'], fact_type=r['fact_type'], fact_role=r['fact_role'], value=r['value'])
                        for r in fed], ensure_ascii=False, separators=(',', ':')) + '\n输出JSON，字段 report。')
    return SYS_DOWN, us

# ── deterministic fed-list (D4 fix): semantic ordering, stable across processes ──
ORDER = {'date': 0, 'amount': 1, 'penalty': 2, 'entity': 3}
def order_key(r):
    sp = r.get('spans') or []
    s = sp[0][0] if sp else None
    return (ORDER.get(r['fact_type'], 9), s if s is not None else 10**9, r['fact_id'])
def det_fed(store, supported):
    picked = [r for r in store if r['fact_id'] in supported] or \
             [r for r in store if r['provenance_status'] != 'UNVERIFIABLE_ABSENT']
    return sorted(picked, key=order_key)

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

# ── v3.1 scoring ──
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
def variants(f):
    vs = [norm(f['value'])]
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m: vs.append(norm(f'{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日'))
    return [v for v in vs if v]
def in_text(f, t): return any(v in t for v in variants(f))
WINDOW_N = norm(WINDOW)
def occ(f):
    """Spans in the NORMALIZED window (variants are normalized too)."""
    out = []
    for v in variants(f):
        for mm in re.finditer(re.escape(v), WINDOW_N): out.append((mm.start(), mm.end()))
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if not out and f['kind'] == 'date' and m:
        el, yr = norm(f'{int(m.group(2))}月{int(m.group(3))}日'), m.group(1) + '年'
        for mm in re.finditer(re.escape(el), WINDOW_N):
            if yr in WINDOW_N[max(0, mm.start()-120):mm.end()+120]: out.append((mm.start(), mm.end()))
    return out
def in_window(f): return len(occ(f)) > 0
DENY = ['申辩', '请求', '陈述', '否认', '不采取', '不予处罚', '不予认定']
DECIDE = ['决定', '处罚决定', '本会决定', '作出下列']
def penalty_ok(f, span=120):
    for s, e in occ(f):
        ctx = WINDOW_N[max(0, s-span):e+span]
        if any(d in ctx for d in DECIDE) and not any(n in ctx for n in DENY): return True
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

def score(n10_text, n1_text):
    o = BB.extract_json(n10_text)
    hay = norm(' | '.join(collect_values(o))) if o is not None else norm(n10_text)
    n1n = norm(n1_text); win = norm(WINDOW)
    tp, prov_fail, removed = [], [], []
    for f in VALID:
        if in_text(f, hay) and in_text(f, n1n) and in_window(f):
            if f['kind'] == 'penalty' and not penalty_ok(f):
                removed.append(f['fid']); continue
            tp.append(f['fid'])
        elif in_text(f, hay): prov_fail.append(f['fid'])
    seen, fps = set(), []
    for c in ([('num', re.sub(r'\s+', '', m.group(0))) for m in NUM.finditer(n10_text)] +
              [('date', re.sub(r'\s+', '', m.group(0))) for m in DATE.finditer(n10_text)]):
        if claim_supported(c, win) or norm(c[1]) in seen: continue
        seen.add(norm(c[1])); fps.append(c[1])
    R = len(tp)/len(VALID); P = len(tp)/max(1, len(tp)+len(fps))
    return dict(tp=len(tp), tp_facts=tp, fp=len(fps), fp_values=fps, semantic_removed=removed,
                unsupported_provenance=prov_fail, recall=round(R,4), precision=round(P,4),
                f1=round(2*P*R/max(1e-3,P+R),4), report_json=o is not None)

# ── phase 0: flash availability ──
print('=== PHASE 0: glm-5.3-flash availability ===')
try:
    rec, txt = M.call(M_FAST, 'ping', '只回复两个字：收到', 16, 'V9-P0:flash-probe', timeout_s=60)
    print(f'  OK  in={rec["usage"]["input_tokens"]} out={rec["usage"]["output_tokens"]} text={txt[:16]!r} latency={rec["latency_s"]}s')
    FLASH_OK = True
except Exception as e:
    print(f'  FAIL {type(e).__name__}: {str(e)[:200]}')
    FLASH_OK = False
if not FLASH_OK:
    print('  Flash unavailable -> aborting V9.'); sys.exit(2)

# ── load V1.2 baseline snapshots (zero cost) ──
base_n1, base_n9, base_n10 = {}, {}, {}
for line in open('st_v1_LEDGER_responses.jsonl'):
    if not line.strip(): continue
    r = json.loads(line)
    for b in range(1, 6):
        if r['purpose'] == f'ST-B{b}:n1': base_n1[b] = r['text']
        if r['purpose'] == f'ST-B{b}:B:n9': base_n9[b] = r['text']
        if r['purpose'] == f'ST-B{b}:B:n10': base_n10[b] = r['text']
RES12 = json.load(open('st_v1_RESULTS.json'))
base_scores = {b['block']: b['B'] for b in RES12['blocks']}

def run_pipeline(tag, blk, n1_model, n9_model, n10_model, n1_text=None):
    """Structured-transfer terminal path: n1 -> store -> n9 -> n10."""
    out = {}
    if n1_text is None:
        sy, us = n1_prompt()
        rec, n1_text = M.call(n1_model, sy, us, MAXTOK['n1'], f'{tag}:n1')
        out['n1'] = dict(rec=rec, text=n1_text)
    else:
        out['n1'] = dict(rec=None, text=n1_text)
    store = BB.build_store(n1_text, WINDOW, 10)
    sy, us = n9_prompt(store)
    rec9, t9 = M.call(n9_model, sy, us, MAXTOK['n9'], f'{tag}:n9')
    sup, raw9 = parse_n9(t9)
    out['n9'] = dict(rec=rec9, text=t9, store=store, supported=sorted(sup),
                     shape=type(raw9).__name__, parse_ok=bool(sup) or raw9 is not None)
    fed = det_fed(store, sup)
    sy, us = n10_prompt(fed)
    rec10, t10 = M.call(n10_model, sy, us, MAXTOK['n10'], f'{tag}:n10')
    out['n10'] = dict(rec=rec10, text=t10, fed=len(fed))
    out['score'] = score(t10, n1_text)
    out['tokens'] = sum((d['rec']['usage']['input_tokens'] + d['rec']['usage']['output_tokens']) for d in out.values()
                        if isinstance(d, dict) and d.get('rec'))
    out['latency'] = sum(d['rec']['latency_s'] for d in out.values() if isinstance(d, dict) and d.get('rec'))
    return out

print('\n=== PHASE 1: node-level capability (flash swapped into one node at a time) ===')
meas = []
for b in range(1, 6):
    n1b = base_n1[b]; sb = BB.build_store(n1b, WINDOW, 10)
    sup_b, _ = parse_n9(base_n9[b])
    fed_b = det_fed(sb, sup_b)
    row = dict(block=b, base=dict(score=base_scores[b],
                                  n9_supported=len(sup_b), n10_fed=len(fed_b)))
    # U-S-d: glm-5.3 n10 on the SAME deterministic fed list used by every V9 arm
    sy, us = n10_prompt(fed_b)
    rec10d, t10d = M.call(M_STRONG, sy, us, MAXTOK['n10'], f'V9-P1:B{b}:USd:n10')
    row['U_S_det'] = dict(score=score(t10d, n1b),
                          tokens=rec10d['usage']['input_tokens'] + rec10d['usage']['output_tokens'],
                          latency=rec10d['latency_s'])
    # N1(flash): flash n1 -> strong n9/n10
    r = run_pipeline(f'V9-P1:B{b}:N1f', b, M_FAST, M_STRONG, M_STRONG)
    row['N1_flash'] = dict(score=r['score'], tokens=r['tokens'], latency=r['latency'],
                           store=len(r['n9']['store']), n9_supported=len(r['n9']['supported']))
    n1_flash_text = r['n1']['text']; store_flash = r['n9']['store']
    # N9(flash): baseline n1 store -> flash n9 -> strong n10
    r = run_pipeline(f'V9-P1:B{b}:N9f', b, M_STRONG, M_FAST, M_STRONG, n1_text=n1b)
    row['N9_flash'] = dict(score=r['score'], tokens=r['tokens'], latency=r['latency'],
                           n9_supported=len(r['n9']['supported']), n9_shape=r['n9']['shape'],
                           parse_ok=r['n9']['parse_ok'])
    # N10(flash): baseline fed -> flash n10
    sy, us = n10_prompt(fed_b)
    rec10, t10 = M.call(M_FAST, sy, us, MAXTOK['n10'], f'V9-P1:B{b}:N10f:n10')
    row['N10_flash'] = dict(score=score(t10, n1b), tokens=rec10['usage']['input_tokens'] + rec10['usage']['output_tokens'],
                            latency=rec10['latency_s'])
    # U-F: flash n1 -> store_flash -> flash n9 -> flash n10 (n1 reused, no extra call)
    sy, us = n9_prompt(store_flash)
    rec9, t9 = M.call(M_FAST, sy, us, MAXTOK['n9'], f'V9-P1:B{b}:UF:n9')
    sup_f, _ = parse_n9(t9); fed_f = det_fed(store_flash, sup_f)
    sy, us = n10_prompt(fed_f)
    rec10, t10 = M.call(M_FAST, sy, us, MAXTOK['n10'], f'V9-P1:B{b}:UF:n10')
    row['U_F'] = dict(score=score(t10, n1_flash_text), tokens=rec9['usage']['input_tokens'] + rec9['usage']['output_tokens']
                      + rec10['usage']['input_tokens'] + rec10['usage']['output_tokens'],
                      latency=rec9['latency_s'] + rec10['latency_s'], n9_supported=len(sup_f))
    meas.append(row)
    bs = row['base']['score']
    print(f"  B{b}: U-S TP={bs['tp']} F1={bs['f1']:.4f} | "
          f"N1f TP={row['N1_flash']['score']['tp']} F1={row['N1_flash']['score']['f1']:.4f} | "
          f"N9f TP={row['N9_flash']['score']['tp']} F1={row['N9_flash']['score']['f1']:.4f} (shape={row['N9_flash']['n9_shape']}) | "
          f"N10f TP={row['N10_flash']['score']['tp']} F1={row['N10_flash']['score']['f1']:.4f} | "
          f"U-F TP={row['U_F']['score']['tp']} F1={row['U_F']['score']['f1']:.4f}")

json.dump(meas, open('v9_MEASUREMENT.json', 'w'), ensure_ascii=False, indent=1)

# ── allocation rule (pre-registered): cheaper model if median TP drop <= 1 vs U-S ──
print('\n=== PHASE 2: allocation rule ===')
med = lambda xs: statistics.median(xs)
base_tp = [m['base']['score']['tp'] for m in meas]
print(f"  U-S TP: {base_tp} median={med(base_tp)}")
dec = {}
for node, key in (('n1', 'N1_flash'), ('n9', 'N9_flash'), ('n10', 'N10_flash')):
    tps = [m[key]['score']['tp'] for m in meas]
    delta = med(tps) - med(base_tp)
    use_fast = delta >= -1
    dec[node] = (M_FAST if use_fast else M_STRONG)
    print(f"  {node}: flash TP={tps} median={med(tps)} (delta {delta:+}) -> {'FAST' if use_fast else 'STRONG'}")
print(f"  allocation H = {dec}")

# LOO stability of the same rule (zero extra calls)
folds = []
for hold in range(5):
    idx = [i for i in range(5) if i != hold]
    btp = med([base_tp[i] for i in idx]); d2 = {}
    for node, key in (('n1','N1_flash'),('n9','N9_flash'),('n10','N10_flash')):
        t = med([meas[i][key]['score']['tp'] for i in idx])
        d2[node] = M_FAST if (t - btp) >= -1 else M_STRONG
    folds.append(d2)
stable = all(f == dec for f in folds)
print(f"  LOO fold allocations: {folds}")
print(f"  stable across all folds: {stable}")

if all(v == M_STRONG for v in dec.values()):
    print('  H == U-S : reuse baseline, no calls needed')
    H = dict(arms_identical='U-S', scores=[m['base']['score'] for m in meas])
elif all(v == M_FAST for v in dec.values()):
    print('  H == U-F : reuse U-F, no calls needed')
    H = dict(arms_identical='U-F', scores=[m['U_F']['score'] for m in meas])
else:
    hs = []
    for b in range(1, 6):
        r = run_pipeline(f'V9-P2:B{b}:H', b, dec['n1'], dec['n9'], dec['n10'])
        hs.append(dict(block=b, score=r['score'], tokens=r['tokens'], latency=r['latency'],
                       n9_supported=len(r['n9']['supported'])))
        print(f"  H B{b}: TP={r['score']['tp']} F1={r['score']['f1']:.4f}")
    H = dict(arms_identical=None, blocks=hs)

out = dict(prereg='V9_DESIGN_DRAFT.md (updated 2026-11-02)', scorer='v3.1',
           models={'strong': M_STRONG, 'fast': M_FAST},
           decision_markers={'D4_fix': 'det_fed sorts by (fact_type, span_start, fact_id)',
                             'v3.1': 'penalty facts require decision-context evidence'},
           measurement=meas, allocation=dec, loo_stable=stable, loo_folds=folds, H=H,
           total_calls=len(M.calls), total_tokens=M.tokens)
json.dump(out, open('v9_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
print(f"\nSaved v9_RESULTS.json | calls={len(M.calls)} tokens={M.tokens}")
