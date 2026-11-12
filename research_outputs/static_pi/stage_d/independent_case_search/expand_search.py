"""Expanded search: 2015-2018 penalty cases from cninfo + broader keywords. Zero model calls."""
import json, re, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, '.')
import search_cases as S

RAW = Path('raw'); RAW.mkdir(exist_ok=True)
OUT = Path('.')
QUERY = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
UA = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'Referer': 'http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search'}

def post(params):
    data = urllib.parse.urlencode(params).encode()
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(QUERY, data=data, headers=UA), timeout=30).read().decode())
        except Exception: time.sleep(2+i)
    return {}

def search(key, column, se_date, stock='', max_pages=30):
    out, page = [], 1
    while page <= max_pages:
        d = post(dict(pageNum=page, pageSize=30, column=column, tabName='fulltext', plate='', stock=stock,
                     searchkey=key, secid='', category='', trade='', seDate=se_date, sortName='', sortType='', isHLtitle='true'))
        anns = d.get('announcements') or []
        for a in anns: a['title'] = re.sub(r'</?em>', '', a.get('announcementTitle') or '')
        out += anns
        if not d.get('hasMore') or not anns: break
        page += 1; time.sleep(0.6)
    return out

# Search 2015-2018 with multiple keywords
pool = {}
for column in ('szse', 'sse'):
    for key in ('行政处罚决定书', '行政处罚及市场禁入事先告知书'):
        for dr in ('2015-01-01~2016-12-31', '2017-01-01~2018-12-31'):
            print(f'searching {column} "{key}" {dr}...', flush=True)
            for a in search(key, column, dr):
                if any(s in a['title'] for s in S.SKIP_TITLE): continue
                c = pool.setdefault(a['secCode'], dict(code=a['secCode'], name=a['secName'], org_id=a.get('orgId'), column=column, decisions=[]))
                if a['adjunctUrl'] not in {x['adjunct'] for x in c['decisions']}:
                    c['decisions'].append(dict(title=a['title'], adjunct=a['adjunctUrl'], time=a['announcementTime']))
            time.sleep(0.5)

print(f'\npool: {len(pool)} companies', flush=True)
# Pair with notices
for code, c in pool.items():
    notes = search('事先告知书', c['column'], '2014-01-01~2018-12-31', stock=f"{code},{c['org_id']}", max_pages=3)
    c['notices'] = [dict(title=a['title'], adjunct=a['adjunctUrl'], time=a['announcementTime']) for a in notes
                    if a.get('secCode') == code and '事先告知书' in a['title'] and not any(s in a['title'] for s in S.SKIP_TITLE)]
    time.sleep(0.4)

paired = {k: v for k, v in pool.items() if v.get('notices')}
print(f'paired: {len(paired)}', flush=True)
Path('EXPANDED_POOL.json').write_text(json.dumps(dict(paired=paired, total=len(pool)), ensure_ascii=False, indent=1), 'utf-8')

# Structure check on paired candidates
sys.path.insert(0, str(Path(__file__).parent))
from search_cases import penalty_table, PROPOSED_LINE, PENALTY_LINE, download
import unicodedata
def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))
def page_mark_sub(t): return re.sub(r'\s*\d{1,3}\s*\x0c', '', t)

survivors = []
for i, (code, c) in enumerate(paired.items()):
    dec = sorted(c['decisions'], key=lambda x: x['time'])[-1]
    try:
        dmeta, dtxt = download(dec['adjunct'], f'{code}_decision_{dec["time"]}.pdf')
    except Exception: continue
    flat = norm(page_mark_sub(dtxt))
    table = penalty_table(flat)
    parties = {p for ps, _ in table for p in ps}
    levels = {a for _, a in table}
    if len(parties) < 8 or len(levels) < 2: continue
    note = sorted((n for n in c['notices'] if n['time'] < dec['time']), key=lambda x: x['time'])
    if not note: continue
    try:
        nmeta, ntxt = download(note[-1]['adjunct'], f'{code}_notice_{note[-1]["time"]}.pdf')
    except Exception: continue
    ntable = penalty_table(ntxt)
    nflat = norm(page_mark_sub(ntxt))
    overlap = sum(p in nflat for p in parties) / len(parties)
    if not ntable or overlap < 0.5: continue
    survivors.append(dict(code=code, name=c['name'],
        decision=dict(dec, **dmeta, parties=len(parties), levels=sorted(levels), total=sum(len(ps)*a for ps,a in table)),
        notice=dict(note[-1], **nmeta), party_names=sorted(parties),
        notice_party_overlap=round(overlap,2)))
    if (i+1) % 10 == 0: print(f'  progress {i+1}/{len(paired)} survivors={len(survivors)}', flush=True)

survivors.sort(key=lambda r: (-r['decision']['parties'], r['code']))
Path('EXPANDED_SURVIVORS.json').write_text(json.dumps(survivors, ensure_ascii=False, indent=1), 'utf-8')
print(f'\nstructure survivors: {len(survivors)}')
for s in survivors[:20]:
    d = s['decision']
    print(f"  {s['code']} {s['name']:<10} parties={d['parties']} levels={len(d['levels'])} total={d['total']}")
