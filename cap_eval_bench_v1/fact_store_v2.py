"""Fact store v2 — fixes D10 (penalty facts silently dropped).

b_arm_budget.build_store takes value = item.get('value') or item.get('name').
n1 emits penalties as {"type": "罚款", "subject": "...", "context": "..."} — no value key
-> every penalty item was skipped. This module maps `type` -> value for penalties.

Also keeps the D8 determinism fix (sha1 for span-less ids).
Frozen files are NOT modified; this is a new versioned module.
"""
import json, re, hashlib
import b_arm_budget as BB

norm = BB.norm
TYPES = ('date', 'amount', 'penalty', 'entity')
CODE = {'dates': 'DTE', 'amounts': 'AMT', 'penalties': 'PEN', 'entities': 'ENT'}
KIND = {'dates': 'date', 'amounts': 'amount', 'penalties': 'penalty', 'entities': 'entity'}

def item_value(key, it):
    v = it.get('value') or it.get('name')
    if not v and key == 'penalties':
        v = it.get('type')            # D10 fix: penalty kind IS the fact value
    return v or ''

def item_role(key, it):
    if key == 'penalties':
        # role carries the subject (who was penalised); keeps 罚款/警告 separable per person
        return str(it.get('subject') or 'unspecified')[:24]
    return str(it.get('nature') or it.get('role') or it.get('type') or '')[:16]

def build_store_v2(n1_text, window, pad=10):
    o = BB.parse(n1_text)
    recs = []
    for key in ('dates', 'amounts', 'penalties', 'entities'):
        for it in (o.get(key) or []):
            v = item_value(key, it)
            if not v: continue
            spans = BB.locate_all(v, KIND[key], window)
            prov = ('VERIFIED_UNIQUE_SPAN' if len(spans) == 1 else
                    'VERIFIED_MULTI_SPAN' if len(spans) > 1 else 'UNVERIFIABLE_ABSENT')
            quotes = [window[max(0, s - pad):e + pad].replace('\n', ' ') for s, e in spans]
            sid = str(spans[0][0]) if spans else 'X' + hashlib.sha1(norm(v).encode()).hexdigest()[:8]
            recs.append(dict(fact_id=f'{CODE[key]}{sid}', fact_type=KIND[key],
                             fact_role=item_role(key, it), value=v,
                             provenance_status=prov, spans=[[s, e] for s, e in spans],
                             quotes=quotes,
                             context=str(it.get('context') or '')[:120]))
    seen, uniq = set(), []
    for r in recs:
        k = (r['fact_type'], norm(r['value']), r['fact_role'])
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq

if __name__ == '__main__':
    import collections, statistics
    EV = ' '.join(d['text'] for d in json.load(
        open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))['docs'])
    resp = {}
    for line in open('w48_LEDGER_responses.jsonl'):
        if not line.strip(): continue
        r = json.loads(line); resp[r['purpose']] = r['text']
    print(f"{'block':6s} {'v1 store':>9s} {'v2 store':>9s} {'penalty v1':>11s} {'penalty v2':>11s}  penalty values (v2)")
    for b in range(1, 6):
        n1 = resp[f'W48-W8-B{b}:n1']
        s1 = BB.build_store(n1, EV[:8000], 10)
        s2 = build_store_v2(n1, EV[:8000], 10)
        p1 = [r for r in s1 if r['fact_type'] == 'penalty']
        p2 = [r for r in s2 if r['fact_type'] == 'penalty']
        vals = sorted({r['value'] for r in p2})
        print(f"B{b:<5d} {len(s1):>9d} {len(s2):>9d} {len(p1):>11d} {len(p2):>11d}  {vals}")
