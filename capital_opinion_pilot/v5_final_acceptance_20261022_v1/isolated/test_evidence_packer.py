"""Regression tests for evidence_packer v2 (zero-pay, deterministic).

Locks in the fix for the 600c zero-retrieval bug: at EVERY positive budget the
packer must return a non-empty pack (or raise), must respect both the char and
token budgets, must preserve provenance metadata, and must be deterministic.
Also asserts answer-file isolation (no reference-facts dependency in selection).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import evidence_packer as ep

INDEX = ep.build_index()
RANKED = ep.rank_chunks(INDEX)
BUDGETS = [100, 300, 450, 600, 900, 1500, 3000, 6000, 10000, 19000]

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print(f'  FAIL {msg}')
    else:
        print(f'  ok   {msg}')


print('== T1: non-empty at every positive budget (the 600c bug scenario) ==')
for b in BUDGETS:
    p = ep.pack_global(b, ranked=RANKED)
    check(p['chars'] > 0, f'budget={b}: chars={p["chars"]} > 0 (v1 returned 0 at 600)')
    check(p['chars'] <= b, f'budget={b}: chars={p["chars"]} <= {b}')
    check(len(p['docs']) >= 1, f'budget={b}: docs entered = {len(p["docs"])} >= 1')

print('== T2: dual budget (chars AND estimated tokens) both respected ==')
for b in BUDGETS:
    tok_cap = int(b * 0.5) if b >= 1000 else None  # tight token caps force truncation
    p = ep.pack_global(b, budget_tokens=tok_cap, ranked=RANKED)
    check(p['est_tok'] <= (tok_cap if tok_cap is not None else ep.token_est(p['chars'])),
          f'budget={b}/tokcap={tok_cap}: est_tok={p["est_tok"]} within cap')

print('== T3: provenance metadata complete on every packed item ==')
p600 = ep.pack_global(600, ranked=RANKED)
need = {'chunk_id', 'doc_id', 'start', 'end', 'sha256', 'public_date', 'available_date', 'truncated'}
check(all(need <= set(it) for it in p600['items']), 'all metadata fields present at 600c')
check(all(isinstance(it['start'], int) and isinstance(it['end'], int) and it['end'] > it['start']
          for it in p600['items']), 'source offsets are concrete char ranges')
check('发布' in p600['text'] and 'doc_id=' in p600['text'], 'packed text carries doc/time markers')

print('== T4: sub-chunk budget truncates the top-ranked chunk (never empty) ==')
p100 = ep.pack_global(100, ranked=RANKED)
check(p100['chars'] == 100, f'budget=100: packed exactly {p100["chars"]}c of top chunk')
check(all(it['truncated'] for it in p100['items']), 'truncation flagged')
check(p100['items'][0]['chunk_id'] == RANKED[0]['chunk_id'], 'truncated item is the top-ranked chunk')

print('== T5: determinism (identical packs on repeated calls) ==')
a = ep.pack_global(3000, ranked=RANKED)
b2 = ep.pack_global(3000, ranked=RANKED)
check(a['text'] == b2['text'] and a['chars'] == b2['chars'], 'same budget -> byte-identical pack')

print('== T6: overlap dedup — no >=200c duplication within a doc ==')
p19 = ep.pack_global(19000, ranked=RANKED)
dup = False
by_doc = {}
for it in p19['items']:
    src = next(c for c in INDEX if c['chunk_id'] == it['chunk_id'])
    for prev in by_doc.get(it['doc_id'], []):
        if ep._text_overlap(prev, src['text']):
            dup = True
    by_doc.setdefault(it['doc_id'], []).append(src['text'])
check(not dup, 'no two packed chunks of one doc share a >=200c block')

print('== T7: answer-file isolation (selection cannot depend on reference facts) ==')
src = Path(__file__).with_name('evidence_packer.py').read_text()
check('reference_facts' not in src, 'no reference-facts filename in packer source')
check('open(' not in src and 'read_text' not in src,
      'packer performs ZERO file I/O (selection is a pure function of index+terms)')

print('== T8: line packing (50/50 split) non-empty on both lines ==')
lines = ep.pack_lines(600, {'line_A': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
                            'line_B': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}, ranked=RANKED)
for line, pack in lines.items():
    check(pack['chars'] > 0, f'{line}: {pack["chars"]}c at 300c/line (v1 starved lines)')

print()
if failures:
    print(f'RESULT: {len(failures)} FAILURES')
    json.dump({'status': 'FAIL', 'failures': failures}, open('test_evidence_packer_result.json', 'w'))
    sys.exit(1)
print('RESULT: ALL PASS')
json.dump({'status': 'PASS', 'budgets_tested': BUDGETS,
           't_fixed': {'600c': {'chars': p600['chars'], 'docs': len(p600['docs'])},
                       '19000c': {'chars': p19['chars'], 'docs': len(p19['docs'])}}},
          open('test_evidence_packer_result.json', 'w'), ensure_ascii=False, indent=1)
