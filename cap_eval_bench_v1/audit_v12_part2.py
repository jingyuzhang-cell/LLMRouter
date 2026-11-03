"""Part 2: D4 sensitivity, D5 conformance, D6 narrow v3.1 rule, integrity tables."""
import json, re, statistics, collections
from audit_v12 import (score, extract_json, norm, EV, WINDOW, SILVER, VALID,
                       in_text, in_window, variants, claims, claim_supported)

resp = collections.defaultdict(list)
for line in open('st_v1_LEDGER_responses.jsonl'):
    if not line.strip(): continue
    r = json.loads(line)
    resp[r['purpose']].append((r['call_id'], r['text']))
def get(p, i=-1):
    xs = resp.get(p) or []
    return xs[i][1] if xs else ''
RES = json.load(open('st_v1_RESULTS.json'))
med = lambda xs: statistics.median(xs)

print("="*78); print("A. SELF-CHECK with last-record selection (final run semantics)"); print("="*78)
ok = True
for b in RES['blocks']:
    n1 = get(f"ST-B{b['block']}:n1")
    for arm in ('A','B'):
        s = score(get(f"ST-B{b['block']}:{arm}:n10"), n1)
        st = b[arm]
        same = s['tp']==st['tp'] and s['fp']==st['fp'] and abs(s['f1']-st['f1'])<1e-6
        ok &= same
        if not same: print(f"  MISMATCH B{b['block']}{arm}: {s['tp']}/{s['fp']}/{s['f1']} vs {st['tp']}/{st['fp']}/{st['f1']}")
print(f"  -> {'PASS: audit scorer reproduces the frozen v3 results exactly' if ok else 'FAIL'}")

print("\n" + "="*78); print("B. D4 SENSITIVITY: use the OTHER duplicate for B1"); print("="*78)
alt = resp['ST-B1:B:n10'][0][1]; n1b1 = get('ST-B1:n1')
s_alt = score(alt, n1b1); s_stored = score(resp['ST-B1:B:n10'][-1][1], n1b1)
print(f"  B1 B (call 19, other order): TP={s_alt['tp']} F1={s_alt['f1']}  missing={[f['fid'] for f in VALID if f['fid'] not in s_alt['tp_facts'] and f['fid'] in s_stored['tp_facts']]}")
print(f"  B1 B (call 30, as stored):   TP={s_stored['tp']} F1={s_stored['f1']}")
A=[b['A']['tp'] for b in RES['blocks']]
B_alt=[s_alt['tp']]+[b['B']['tp'] for b in RES['blocks'][1:]]
print(f"  A TP: {A}")
print(f"  B TP (alt B1): {B_alt}  median={med(B_alt)}")
print(f"  paired diff (alt): {[b-a for a,b in zip(A,B_alt)]} median={med([b-a for a,b in zip(A,B_alt)])}")
B_alt_f1=[s_alt['f1']]+[b['B']['f1'] for b in RES['blocks'][1:]]
print(f"  B F1 median (alt)={med(B_alt_f1):.4f} vs stored {med([b['B']['f1'] for b in RES['blocks']]):.4f}")
print(f"  H1 under alt: TP>=14 {med(B_alt)>=14} | diff>=3 {med([b-a for a,b in zip(A,B_alt)])>=3} | 4/5 pos {sum(1 for b,a in zip(B_alt,A) if b>a)>=4}")

print("\n" + "="*78); print("C. D5 CONFORMANCE"); print("="*78)
for blk in (2,):
    raw = get(f'ST-B{blk}:B:n9')
    o = extract_json(raw)
    ids = []
    for x in o:
        ids.extend([x] if isinstance(x, str) else list(x.keys()))
    b = next(b for b in RES['blocks'] if b['block']==blk)
    print(f"  B{blk}: n9 elements={len(o)}  distinct ids={len(set(ids))}  statuses={set(v for x in o if isinstance(x,dict) for v in x.values())}")
    print(f"  B{blk}: store={b['store_size']} provenance={b['store_prov']} n10_fed={b['n10_fed']}")
    print(f"  => supported set == fed set: {len(set(ids))==b['n10_fed']} ; UNVERIFIABLE_ABSENT={b['store_prov']['UNVERIFIABLE_ABSENT']}")

print("\n" + "="*78); print("D. D6 NARROW v3.1 RULE (penalty facts need decision-context evidence)"); print("="*78)
DENY = ['申辩', '请求', '陈述', '否认', '不采取', '不予处罚', '不予认定']
DECIDE = ['决定', '处罚决定', '本会决定', '作出下列']
def occ(f):
    out = []
    for v in variants(f):
        for mm in re.finditer(re.escape(v), WINDOW): out.append((mm.start(), mm.end()))
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if not out and f['kind']=='date' and m:
        el, yr = f'{int(m.group(2))}月{int(m.group(3))}日', m.group(1)+'年'
        for mm in re.finditer(re.escape(el), WINDOW):
            if yr in WINDOW[max(0,mm.start()-120):mm.end()+120]: out.append((mm.start(), mm.end()))
    return out
def penalty_ok(f, span=120):
    for s,e in occ(f):
        ctx = WINDOW[max(0,s-span):e+span]
        if any(d in ctx for d in DECIDE) and not any(n in ctx for n in DENY): return True
    return False
print("  penalty facts in window:")
for f in VALID:
    if f['kind']=='penalty' and in_window(f):
        n = len(occ(f))
        print(f"    {f['fid']} {f['value']}: occurrences={n} decision_context={penalty_ok(f)}")
print("  non-penalty facts unaffected by this rule (rule applies to kind=='penalty' only)")

def score31(n10_text, n1_text):
    s = score(n10_text, n1_text)
    removed = [fid for fid in s['tp_facts'] if
               (next(f for f in VALID if f['fid']==fid)['kind']=='penalty')
               and not penalty_ok(next(f for f in VALID if f['fid']==fid))]
    if removed:
        s = dict(s); s['tp_facts']=[x for x in s['tp_facts'] if x not in removed]
        s['tp']=len(s['tp_facts']); s['semantic_removed']=removed
        R=s['tp']/len(VALID); P=s['tp']/max(1,s['tp']+s['fp'])
        s['recall']=round(R,4); s['precision']=round(P,4); s['f1']=round(2*P*R/max(1e-3,P+R),4)
    else:
        s = dict(s); s['semantic_removed']=[]
    return s

print("\n  per-block v3 vs v3.1:")
rows=[]
for b in RES['blocks']:
    blk=b['block']; n1=get(f'ST-B{blk}:n1')
    a3=score(get(f'ST-B{blk}:A:n10'),n1); b3=score(get(f'ST-B{blk}:B:n10'),n1)
    a31=score31(get(f'ST-B{blk}:A:n10'),n1); b31=score31(get(f'ST-B{blk}:B:n10'),n1)
    rows.append(dict(block=blk,A3=a3,B3=b3,A31=a31,B31=b31))
    print(f"   B{blk}: A v3 TP={a3['tp']} F1={a3['f1']:.4f} | A v3.1 TP={a31['tp']} F1={a31['f1']:.4f} removed={a31['semantic_removed']}"
          f" || B v3 TP={b3['tp']} F1={b3['f1']:.4f} | B v3.1 TP={b31['tp']} F1={b31['f1']:.4f} removed={b31['semantic_removed']}")
json.dump(rows, open('audit_v12_v31_scores.json','w'), ensure_ascii=False, indent=1)

for tag,keyA,keyB in (('v3','A3','B3'), ('v3.1','A31','B31')):
    A=[r[keyA] for r in rows]; B=[r[keyB] for r in rows]
    tpA=sum(x['tp'] for x in A); fpA=sum(x['fp'] for x in A)
    tpB=sum(x['tp'] for x in B); fpB=sum(x['fp'] for x in B)
    d=[y['tp']-x['tp'] for x,y in zip(A,B)]
    print(f"\n  [{tag}] A TP={[x['tp'] for x in A]} med={med([x['tp'] for x in A])} F1 med={med([x['f1'] for x in A]):.4f} pooledP={tpA/(tpA+fpA):.4f}")
    print(f"        B TP={[x['tp'] for x in B]} med={med([x['tp'] for x in B])} F1 med={med([x['f1'] for x in B]):.4f} pooledP={tpB/(tpB+fpB):.4f}")
    print(f"        paired diff={d} med={med(d)} positive={sum(1 for x in d if x>0)}/5")

print("\n" + "="*78); print("E. INTEGRITY: token attribution"); print("="*78)
led=[json.loads(l) for l in open('st_v1_LEDGER.jsonl') if l.strip()]
n1tok=sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in led if r['purpose'].endswith(':n1'))
Atok=sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in led if ':A:' in r['purpose'])
Btok=sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in led if ':B:' in r['purpose'])
dup=sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in led if r['purpose']=='ST-B1:B:n10')-max(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in led if r['purpose']=='ST-B1:B:n10')
print(f"  n1 calls total: {n1tok} (5 blocks)")
print(f"  A arm n2..n10: {Atok}")
print(f"  B arm n2..n10: {Btok}  (includes one duplicate worth {dup})")
print(f"  ACTUAL spend = n1 + A + B = {n1tok+Atok+Btok}  (ledger sum = {n1tok+Atok+Btok})")
print(f"  ATTRIBUTED cost: C_A = n1 + A = {n1tok+Atok}  C_B = n1 + B = {n1tok+Btok}")
print(f"  attributed sum (double-counts n1) = {2*n1tok+Atok+Btok}")
print(f"  C_B/C_A (attributed) = {(n1tok+Btok)/(n1tok+Atok):.4f}")
print(f"  actual-based ratio (B excl. duplicate)/(A) = {(n1tok+Btok-dup)/(n1tok+Atok):.4f}")
print(f"  makespan (wall clock, whole experiment incl. 3 restarts): see run log; per-block:")
for b in RES['blocks']:
    tt=[r for r in led if r['purpose'].startswith(f"ST-B{b['block']}:")]
    print(f"    B{b['block']}: calls={len(tt)} tokens={sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in tt)}")
