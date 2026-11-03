"""W4/W8 zero-call pre-check.

A) grouping/merge correctness on the REAL V9 B4 fact store (61 facts)
B) structural test at ~98-fact scale (candidates derived by regex from EV[:8000],
   explicitly SIMULATED - not model output)
No model calls. No writes to frozen files.
"""
import json, re, hashlib, sys
sys.path.insert(0, '/root/cap_eval_bench_v1'); sys.path.insert(0, '/root/capital_opinion_pilot')
import b_arm_budget as BB

norm = BB.norm
EV = ' '.join(d['text'] for d in json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))['docs'])
W4, W8 = EV[:4000], EV[:8000]
TYPES = ('date', 'amount', 'penalty', 'entity')
BUCKET = {'date': 'dates', 'amount': 'amounts', 'penalty': 'penalties', 'entity': 'entities'}

def group(store):
    g = {t: [] for t in TYPES}
    for r in store:
        if r['fact_type'] not in g: raise ValueError('unknown type ' + r['fact_type'])
        g[r['fact_type']].append(r)
    return g

def merge_parts(parts):
    """Deterministic merge of the four per-type reports."""
    return {'report': {BUCKET[t]: parts.get(t, []) for t in TYPES}}

def check_completeness(store, parts):
    """Every fact_id must appear exactly once across the four parts (after merge)."""
    ids = [r['fact_id'] for r in store]
    seen, dup, missing = {}, [], []
    for t in TYPES:
        for item in parts.get(t, []):
            fid = item.get('fact_id')
            if fid is None: continue
            seen[fid] = seen.get(fid, 0) + 1
    for fid in ids:
        if fid not in seen: missing.append(fid)
    dup = [k for k, v in seen.items() if v > 1]
    extra = [k for k in seen if k not in set(ids)]
    return dict(n_store=len(ids), n_seen=len(seen), missing=missing, duplicated=dup, extra=extra)

print("=" * 90)
print("PRE-CHECK A: grouping / merge on the REAL V9 B4 store (61 facts)")
print("=" * 90)
resp = {}
for line in open('v9_LEDGER_responses.jsonl'):
    if not line.strip(): continue
    r = json.loads(line); resp[r['purpose']] = r['text']
b4_n1 = resp['V9-P1:B4:N1f:n1']
store_real = BB.build_store(b4_n1, W4, 10)
g = group(store_real)
print(f"  store={len(store_real)}  buckets={{ {', '.join(f'{k}:{len(v)}' for k,v in g.items())} }}")
assert sum(len(v) for v in g.values()) == len(store_real), "grouping lost/duplicated facts"
print(f"  sum(buckets) == store size : {sum(len(v) for v in g.values())} == {len(store_real)}  ✓")
# simulate per-type reports as {fact_id, value} (structure only)
parts = {t: [dict(fact_id=r['fact_id'], value=r['value']) for r in g[t]] for t in TYPES}
chk = check_completeness(store_real, parts)
print(f"  completeness: {chk}")
merged = merge_parts(parts)
s = json.dumps(merged, ensure_ascii=False)
print(f"  merged JSON chars={len(s)} parses={bool(json.loads(s))}")
print(f"  empty buckets (deterministically skipped at run time): "
      f"{[t for t in TYPES if not g[t]]}")

print("\n" + "=" * 90)
print("PRE-CHECK B: structural test at ~98-fact scale (SIMULATED candidates)")
print("=" * 90)
FNUM = re.compile(r'\d[\d,，]*\.?\d*\s*(?:万元|亿元|万|亿|元)')
FDATE = re.compile(r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日')
FPEN = re.compile(r'罚款|警告|市场禁入|责令改正')
FENT = re.compile(r'[\u4e00-\u9fa5]{2,12}(?:股份有限公司|有限公司|事务所)')
def cand_facts(window):
    out = []
    for i, m in enumerate(FDATE.finditer(window), 1):
        out.append(dict(fact_id=f'DTE{i:03d}', fact_type='date', fact_role='SIM',
                        value=m.group(0).replace(' ', ''), provenance_status='VERIFIED_UNIQUE_SPAN',
                        spans=[[m.start(), m.end()]], quotes=[window[max(0,m.start()-10):m.end()+10]]))
    for i, m in enumerate(FNUM.finditer(window), 1):
        out.append(dict(fact_id=f'AMT{i:03d}', fact_type='amount', fact_role='SIM',
                        value=m.group(0).replace(' ', ''), provenance_status='VERIFIED_UNIQUE_SPAN',
                        spans=[[m.start(), m.end()]], quotes=[window[max(0,m.start()-10):m.end()+10]]))
    for i, m in enumerate(FPEN.finditer(window), 1):
        out.append(dict(fact_id=f'PEN{i:03d}', fact_type='penalty', fact_role='SIM', value=m.group(0),
                        provenance_status='VERIFIED_UNIQUE_SPAN', spans=[[m.start(), m.end()]],
                        quotes=[window[max(0,m.start()-10):m.end()+10]]))
    seen = set()
    for i, m in enumerate(FENT.finditer(window), 1):
        v = m.group(0)
        if v in seen: continue
        seen.add(v)
        out.append(dict(fact_id=f'ENT{i:03d}', fact_type='entity', fact_role='SIM', value=v,
                        provenance_status='VERIFIED_UNIQUE_SPAN', spans=[[m.start(), m.end()]],
                        quotes=[window[max(0,m.start()-10):m.end()+10]]))
    return out
sim = cand_facts(W8)
g2 = group(sim)
print(f"  SIMULATED store at EV[:8000]: {len(sim)} facts  "
      f"{{ {', '.join(f'{k}:{len(v)}' for k,v in g2.items())} }}")
parts2 = {t: [dict(fact_id=r['fact_id'], value=r['value']) for r in g2[t]] for t in TYPES}
chk2 = check_completeness(sim, parts2)
print(f"  completeness: missing={len(chk2['missing'])} duplicated={len(chk2['duplicated'])} extra={len(chk2['extra'])}")
merged2 = json.dumps(merge_parts(parts2), ensure_ascii=False)
print(f"  merged JSON chars={len(merged2)} parses={bool(json.loads(merged2))}")

# per-type prompt sizes (n10 partitioned) at both scales
print("\n  per-type n10 prompt sizes (system+user chars)  [template frozen below]")
SYS_DOWN = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'
def n10_type_prompt(t, facts):
    us = (f'{SYS_DOWN}\n以下为已核验支持的{BUCKET[t]}事实（类型 {t}）。任务：把下列全部 fact_id 逐条写入报告，'
          f'每条保留原始值与语义角色；不得遗漏、不得新增、不得改写数值。输出JSON，字段 report。\n'
          + json.dumps([dict(fact_id=r['fact_id'], fact_role=r['fact_role'], value=r['value']) for r in facts],
                       ensure_ascii=False, separators=(',', ':'))
          + '\n输出JSON，字段 report。')
    return SYS_DOWN, us
for tag, gg in (('W4(real store 61)', g), ('W8(simulated 98)', g2)):
    print(f"   {tag}:")
    for t in TYPES:
        sy, us = n10_type_prompt(t, gg[t])
        print(f"     {t:8s} facts={len(gg[t]):3d} prompt={len(sy)+len(us):5d} chars")

# n1 / n9 capacity projections at 98 facts
print("\n  capacity projections at 98 facts:")
print(f"     n1 output (fit 2431 + 14.9*facts) = {2431 + 14.9*98:.0f} tokens vs cap 5000 -> margin {5000-(2431+14.9*98):.0f}")
print(f"     n9 input  (62.7 tok/fact + 200)   = {62.7*98+200:.0f} tokens")
print(f"     n9 output (ID list ~7 chars each) = {98*7:.0f} chars ~ {98*7*0.45:.0f} tokens vs cap 2000")
print(f"     n10 per-type input (max bucket)   = amounts bucket, ~{len(g2['amount'])} facts")

# prompt hashes for freeze
print("\n" + "=" * 90)
print("PROMPT FREEZE HASHES")
print("=" * 90)
h = lambda s: hashlib.sha256(s.encode()).hexdigest()
N1_SY = '你是资本市场文档分析助手。穷尽提取所有事实，不遗漏任何条目。只输出JSON。'
N1_TPL = open('n1_revised_prompt.txt').read().split('文档：')[0]
N9_SY, N9_US = BB.build_prompts(store_real, 10)['n9']
frozen = {
 'n1.system': h(N1_SY), 'n1.template': h(N1_TPL),
 'n9.system': h(N9_SY), 'n9.user_template': h(N9_US),
}
for t in TYPES:
    sy, us = n10_type_prompt(t, g2[t])
    frozen[f'n10.{t}.system'] = h(sy)
    frozen[f'n10.{t}.user_template'] = h(us)
for k, v in frozen.items(): print(f"  {k:24s} {v}")
json.dump(dict(frozen_at='2026-11-02', note='templates frozen; per-block user text derives deterministically from the fact store',
               hashes=frozen), open('w48_PROMPT_FREEZE.json','w'), ensure_ascii=False, indent=1)
print("\nSaved w48_PROMPT_FREEZE.json")
