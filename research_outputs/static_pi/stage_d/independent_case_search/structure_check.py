"""Structure check on EXPANDED_POOL paired candidates (uses already-downloaded PDFs where available)."""
import json, re, sys, time, unicodedata
from pathlib import Path
sys.path.insert(0, '.')
import search_cases as S

RAW = Path('raw')
def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
def page_mark_sub(t): return re.sub(r'\s*\d{1,3}\s*\x0c', '', t)

def penalty_table(text):
    flat = norm(page_mark_sub(text))
    rows = []
    for names, amount in S.PENALTY_RE.findall(flat):
        parties = [p for p in re.split(r'[、，,和及]', names) if 2 <= len(p) <= 40]
        try: rows.append((parties, float(amount.replace(',', ''))))
        except ValueError: pass
    return rows, flat

paired = json.loads(Path('EXPANDED_POOL.json').read_text('utf-8'))['paired']
print(f'checking {len(paired)} paired candidates...', flush=True)
survivors = []
for i, (code, c) in enumerate(paired.items()):
    dec = sorted(c['decisions'], key=lambda x: x['time'])[-1]
    try:
        dmeta, dtxt = S.download(dec['adjunct'], f'{code}_decision_{dec["time"]}.pdf')
    except Exception as e:
        continue
    table, dflat = penalty_table(dtxt)
    parties = sorted({p for ps, _ in table for p in ps})
    levels = sorted({a for _, a in table})
    if len(parties) < 8 or len(levels) < 2:
        continue
    notes = sorted((n for n in c.get('notices', []) if n['time'] < dec['time']), key=lambda x: x['time'])
    if not notes: continue
    try:
        nmeta, ntxt = S.download(notes[-1]['adjunct'], f'{code}_notice_{notes[-1]["time"]}.pdf')
    except Exception: continue
    ntable, nflat = penalty_table(ntxt)
    overlap = sum(p in nflat for p in parties) / len(parties)
    if not ntable or overlap < 0.5: continue
    survivors.append(dict(code=code, name=c['name'],
        decision=dict(dec, **dmeta, parties=len(parties), levels=levels, total=sum(len(ps)*a for ps,a in table)),
        notice=dict(notes[-1], **nmeta), party_names=parties, notice_party_overlap=round(overlap,2)))
    if (i+1) % 20 == 0: print(f'  {i+1}/{len(paired)} survivors={len(survivors)}', flush=True)

survivors.sort(key=lambda r: (-r['decision']['parties'], r['code']))
Path('EXPANDED_SURVIVORS.json').write_text(json.dumps(survivors, ensure_ascii=False, indent=1), 'utf-8')
print(f'\nstructure survivors: {len(survivors)}')
for s in survivors[:25]:
    d = s['decision']
    print(f"  {s['code']} {s['name']:<10} parties={d['parties']} levels={len(d['levels'])} total={d['total']} overlap={s['notice_party_overlap']}")
