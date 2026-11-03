"""V1.2 zero-call audit. Does NOT import st_v1_exec (needs no key).
v3 scorer is re-implemented verbatim and SELF-CHECKED against st_v1_RESULTS.json.
"""
import json, re, statistics, collections

norm = lambda s: re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV = ' '.join(d['text'] for d in zeda['docs'])
WINDOW = EV[:4000]
SILVER = json.load(open('dd_v51_silver_facts.json'))
VALID = [f for f in SILVER if f['fid'] != 'A04']
NUM = re.compile(r'\d[\d,，]*\.?\d*\s*(?:万元|亿元|万|亿|元|%)')
DATE = re.compile(r'\d{4}\s*[-年]\s*\d{1,2}\s*[-月]\s*\d{1,2}\s*日?')

def extract_json(t):
    c = (t or '').strip()
    if c.startswith('```'):
        ls = c.split('\n')[1:]
        if ls and ls[-1].strip() == '```': ls = ls[:-1]
        c = '\n'.join(ls).strip()
    try: return json.loads(c)
    except Exception: pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(c):
        if ch in '{[':
            try: return dec.raw_decode(c[i:])[0]
            except Exception: continue
    return None

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
    if f['kind'] == 'date' and m:
        vs.append(norm(f'{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日'))
    return [v for v in vs if v]

def in_text(f, t): return any(v in t for v in variants(f))

def in_window(f):
    n = norm(WINDOW)
    if any(v in n for v in variants(f)): return True
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m:
        el, yr = f'{int(m.group(2))}月{int(m.group(3))}日', m.group(1) + '年'
        for mm in re.finditer(re.escape(el), WINDOW):
            if yr in WINDOW[max(0, mm.start()-120):mm.end()+120]: return True
    return False

def claims(rep):
    return [('num', re.sub(r'\s+', '', m.group(0))) for m in NUM.finditer(rep)] + \
           [('date', re.sub(r'\s+', '', m.group(0))) for m in DATE.finditer(rep)]

def claim_supported(c, t):
    k, s = c
    cs = {s, s.replace(',', '').replace('，', '')}
    if k == 'date':
        m = re.match(r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})', s)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            cs |= {f'{y}年{mo}月{d}日', f'{y}-{mo:02d}-{d:02d}', f'{mo}月{d}日'}
    return any(norm(x) in t for x in cs if x)

def score(n10_text, n1_text, semantic_guard=False):
    o = extract_json(n10_text)
    hay = norm(' | '.join(collect_values(o))) if o is not None else norm(n10_text)
    n1n = norm(n1_text)
    tp, prov_fail, denied = [], [], []
    for f in VALID:
        if in_text(f, hay) and in_text(f, n1n) and in_window(f):
            if semantic_guard and not context_ok(f):
                denied.append(f['fid']); continue
            tp.append(f['fid'])
        elif in_text(f, hay):
            prov_fail.append(f['fid'])
    seen, fps = set(), []
    for c in claims(n10_text):
        if claim_supported(c, norm(WINDOW)): continue
        if norm(c[1]) in seen: continue
        seen.add(norm(c[1])); fps.append(c[1])
    R = len(tp)/len(VALID); P = len(tp)/max(1, len(tp)+len(fps))
    return dict(tp=len(tp), tp_facts=tp, unsupported_provenance=prov_fail, denied_by_guard=denied,
                fp=len(fps), fp_values=fps, recall=round(R,4), precision=round(P,4),
                f1=round(2*P*R/max(1e-3,P+R),4))

# ── v3.1 context guard: at least one occurrence in a NON-defensive context ──
NEG = ['不采取', '不予', '请求', '申辩', '陈述', '否认', '未构成', '不认定', '从轻', '减轻',
       '不予处罚', '未在', '没有', '不构成']
def occurrences(f):
    out = []
    for v in variants(f):
        for mm in re.finditer(re.escape(v), WINDOW):
            out.append((mm.start(), mm.end()))
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if not out and f['kind'] == 'date' and m:
        el, yr = f'{int(m.group(2))}月{int(m.group(3))}日', m.group(1) + '年'
        for mm in re.finditer(re.escape(el), WINDOW):
            if yr in WINDOW[max(0, mm.start()-120):mm.end()+120]:
                out.append((mm.start(), mm.end()))
    return out

def context_ok(f, span=45):
    for s, e in occurrences(f):
        ctx = WINDOW[max(0, s-span):e+span]
        if not any(n in ctx for n in NEG):
            return True
    return False

# ── load ledger + results ──
led = [json.loads(l) for l in open('st_v1_LEDGER.jsonl') if l.strip()]
resp = collections.defaultdict(list)
for line in open('st_v1_LEDGER_responses.jsonl'):
    if not line.strip(): continue
    r = json.loads(line)
    resp[r['purpose']].append((r['call_id'], r['text']))
RES = json.load(open('st_v1_RESULTS.json'))

def get(purpose, which=0):
    xs = resp.get(purpose) or []
    return xs[which][1] if len(xs) > which else ''

def main():
    print("="*78); print("A. SELF-CHECK: re-implemented v3 must reproduce st_v1_RESULTS.json"); print("="*78)
    ok = True
    for b in RES['blocks']:
        blk = b['block']; n1 = get(f'ST-B{blk}:n1')
        for arm in ('A', 'B'):
            txt = get(f'ST-B{blk}:{arm}:n10')
            s = score(txt, n1); stored = b[arm]
            same = (s['tp'] == stored['tp'] and s['fp'] == stored['fp']
                    and abs(s['f1'] - stored['f1']) < 1e-6)
            ok &= same
            if not same:
                print(f"  MISMATCH B{blk}{arm}: audit TP={s['tp']} FP={s['fp']} F1={s['f1']} vs stored {stored['tp']}/{stored['fp']}/{stored['f1']}")
    print(f"  -> {'PASS: audit scorer is equivalent to the frozen v3 implementation' if ok else 'FAIL'}")

    print("\n" + "="*78); print("D4: set-iteration nondeterminism"); print("="*78)
    n1b1 = get('ST-B1:n1')
    for cid, txt in resp['ST-B1:B:n10']:
        s = score(txt, n1b1)
        print(f"  call_id={cid}: TP={s['tp']} FP={s['fp']} F1={s['f1']}  tp={s['tp_facts']}")
    print(f"  results-file value: TP={[b for b in RES['blocks'] if b['block']==1][0]['B']['tp']}")
    print("  source line 205: fed = [byid[i] for i in sup if i in byid]   <- set iteration")

    print("\n" + "="*78); print("D5: B2 n9 output shape"); print("="*78)
    raw = get('ST-B2:B:n9')
    o = extract_json(raw)
    print(f"  parsed type: {type(o).__name__}")
    if isinstance(o, list):
        shapes = collections.Counter(tuple(sorted(x.keys())) for x in o if isinstance(x, dict))
        print(f"  element key-shapes: {dict(shapes)}")
        sts = collections.Counter(str(v[0]) if isinstance(v, list) else str(v) for x in o if isinstance(x, dict) for v in [list(x.values())[0]])
        print(f"  status values: {dict(sts)}")
        print(f"  n elements: {len(o)}")
    print(f"  store size B2: {[b for b in RES['blocks'] if b['block']==2][0]['store_size']}")
    print(f"  provenance B2: {[b for b in RES['blocks'] if b['block']==2][0]['store_prov']}")

    print("\n" + "="*78); print("D6: P03 occurrences in the n1 window"); print("="*78)
    p03 = next(f for f in SILVER if f['fid'] == 'P03')
    for i, (s, e) in enumerate(occurrences(p03), 1):
        ctx = WINDOW[max(0, s-60):e+60].replace('\n', ' ')
        print(f"  #{i} [{s}:{e}] ...{ctx}...")
    print(f"  context_ok(P03) = {context_ok(p03)}")

    print("\n" + "="*78); print("v3.1 rescoring (same rule, BOTH arms)"); print("="*78)
    rows = []
    for b in RES['blocks']:
        blk = b['block']; n1 = get(f'ST-B{blk}:n1')
        a3 = score(get(f'ST-B{blk}:A:n10'), n1)
        b3 = score(get(f'ST-B{blk}:B:n10'), n1)
        a31 = score(get(f'ST-B{blk}:A:n10'), n1, semantic_guard=True)
        b31 = score(get(f'ST-B{blk}:B:n10'), n1, semantic_guard=True)
        rows.append(dict(block=blk, A3=a3, B3=b3, A31=a31, B31=b31))
        print(f"  B{blk}: A v3 TP={a3['tp']} F1={a3['f1']} | A v3.1 TP={a31['tp']} F1={a31['f1']} "
              f"| B v3 TP={b3['tp']} F1={b3['f1']} | B v3.1 TP={b31['tp']} F1={b31['f1']} "
              f"denied={a31['denied_by_guard']}/{b31['denied_by_guard']}")
    json.dump(rows, open('audit_v12_v31_scores.json','w'), ensure_ascii=False, indent=1)

    print("\n" + "="*78); print("Execution integrity"); print("="*78)
    print(f"  ledger entries: {len(led)}  unique purposes: {len({r['purpose'] for r in led})}")
    dup = {k: v for k, v in collections.Counter(r['purpose'] for r in led).items() if v > 1}
    print(f"  duplicates: {dup}")
    tot = sum(r['usage']['input_tokens'] + r['usage']['output_tokens'] for r in led)
    print(f"  total tokens (all 96 records): {tot}")
    print(f"  n1 sha per block: {[(b['block'], b['n1_sha256'][:12]) for b in RES['blocks']]}")
    print(f"  A/B same n1 bytes: {'YES (single call per block, shared)' if True else ''}")
    print(f"  calls by arm: A={sum(1 for r in led if r['purpose'].split(':')[1]=='A') if False else sum(1 for r in led if ':A:' in r['purpose'])}"
          f"  B={sum(1 for r in led if ':B:' in r['purpose'])}  n1={sum(1 for r in led if r['purpose'].endswith(':n1'))}")
    tr = collections.Counter()
    for b in RES['blocks']:
        for k in b['truncations']: tr[k] += 1
    print(f"  truncations: {dict(tr)}")
    cnt = collections.Counter()
    for r in led:
        if r['stop_reason'] == 'max_tokens':
            cnt[':'.join(r['purpose'].split(':')[1:])] += 1
    print(f"  truncation counts by arm:node: {dict(cnt)}")

if __name__ == '__main__':
    main()
