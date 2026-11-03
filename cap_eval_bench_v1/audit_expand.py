"""Zero-call feasibility audit: n1 input window 4000 -> 8000. Read-only."""
import json, re
norm = lambda s: re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
DOCS = [d['text'] for d in zeda['docs']]
EV = ' '.join(DOCS)
W4, W8 = EV[:4000], EV[:8000]
S = json.load(open('dd_v51_silver_facts.json'))
VALID = [f for f in S if f['fid'] != 'A04']

def forms(f):
    out = {f['value'], f['value'].replace(',', ''), f['value'].replace('，','')}
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
    if f['kind'] == 'date' and m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        out |= {f'{y}年{mo}月{d}日', f'{y}年{mo}月{d}'}
    return sorted(out, key=len, reverse=True)

def spans(f, text):
    found = []
    for p in forms(f):
        for mm in re.finditer(re.escape(p), text):
            found.append((mm.start(), mm.end(), p))
    # elided date form (M月D日) when no full form found
    if not found and f['kind'] == 'date':
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', f['value'])
        if m:
            el = f'{int(m.group(2))}月{int(m.group(3))}日'
            for mm in re.finditer(re.escape(el), text):
                found.append((mm.start(), mm.end(), el + ' (elided)'))
    seen, out = set(), []
    for s, e, p in sorted(found):
        if (s, e) in seen: continue
        seen.add((s, e)); out.append((s, e, p))
    return out

ctx_of = lambda s, e, w=70: EV[max(0,s-w):e+w].replace('\n', ' ')
NEG_DEF = ['申辩', '请求', '陈述', '否认', '不采取', '不予', '未构成', '不构成', '从轻', '减轻',
           '没有提供', '不应', '不认定', '假设', '如果', '假如', '据称', '声称']
DECIDE = ['决定', '处罚决定', '本会决定', '作出下列']
def context_class(f, s, e, w=120):
    c = EV[max(0, s-w):e+w]
    neg = [k for k in NEG_DEF if k in c]
    dec = [k for k in DECIDE if k in c]
    if neg and dec: return 'mixed', neg, dec
    if neg: return 'defensive/negated', neg, dec
    if dec: return 'decision', neg, dec
    return 'neutral', neg, dec

print("="*100)
print("TASK 1: Silver fact reachability under 4000 / 8000 windows")
print("="*100)
rows = []
for f in VALID:
    sp = spans(f, EV)
    in4 = [x for x in sp if x[0] < 4000]
    in48 = [x for x in sp if 4000 <= x[0] < 8000]
    in8 = [x for x in sp if x[0] < 8000]
    beyond = [x for x in sp if x[0] >= 8000]
    first = sp[0] if sp else None
    cls = context_class(f, first[0], first[1]) if first else ('absent', [], [])
    rows.append(dict(fid=f['fid'], kind=f['kind'], value=f['value'],
                     n_occ=len(sp), first_offset=first[0] if first else None,
                     in4=len(in4), new_4_8=len(in48), in8=len(in8), beyond=len(beyond),
                     ctx_class=cls[0], neg=cls[1], dec=cls[2],
                     first_ctx=ctx_of(first[0], first[1]) if first else ''))
    print(f"{f['fid']:4s} {f['kind']:8s} {f['value'][:20]:22s} occ={len(sp):2d} first@{str(first[0] if first else '-'):>6s} "
          f"in4={len(in4)} new(4-8k)={len(in48)} in8={len(in8)} beyond8k={len(beyond)} ctx={cls[0]}")

print("\n--- NEW-AT-8000 candidate facts (no evidence before 4000) ---")
new = [r for r in rows if r['in4'] == 0 and r['new_4_8'] > 0]
for r in new:
    print(f"  {r['fid']} {r['value']} @{r['first_offset']} ctx={r['ctx_class']} neg={r['neg']} dec={r['dec']}")
    print(f"      ...{r['first_ctx'][:200]}...")
print(f"\n  count(new at 8000): {len(new)}")

print("\n--- STILL-BEYOND-8000 ---")
for r in [r for r in rows if r['in8'] == 0]:
    print(f"  {r['fid']} {r['value']} first@{r['first_offset']} ctx={r['ctx_class']}")

print("\n" + "="*100)
print("Window-boundary composition")
print("="*100)
print(f"  EV total chars: {len(EV)}  (docs: {[len(d) for d in DOCS]})")
print(f"  facts with evidence in [0,4000):   {sum(1 for r in rows if r['in4']>0)}/22")
print(f"  facts with evidence in [0,8000):   {sum(1 for r in rows if r['in8']>0)}/22")
print(f"  facts only in [4000,8000):         {sum(1 for r in rows if r['in4']==0 and r['new_4_8']>0)}")
json.dump(rows, open('audit_expand_facts.json','w'), ensure_ascii=False, indent=1)
