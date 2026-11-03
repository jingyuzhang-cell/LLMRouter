import json, urllib.request, urllib.parse, re, time

def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
    req.add_header('Content-Type','application/x-www-form-urlencoded')
    req.add_header('User-Agent','Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

EVENTS = [
 {'dir':'A_kangdexin','code':'002450','org':'9900013433','seDate':'2019-04-01~2021-12-31',
  'kws':['行政处罚','问询','退市'],'want':6},
 {'dir':'B_yujingangshi','code':'300064','org':'9900010792','seDate':'2020-01-01~2022-12-31',
  'kws':['行政处罚','资金占用','担保','关注函'],'want':6},
 {'dir':'C_shijuezhongguo','code':'000681','org':'gssz0000681','seDate':'2019-04-01~2019-07-31',
  'kws':['关注函','暂停','网站','道歉'],'want':6},
]
out={}
for ev in EVENTS:
    hits=[]
    for kw in ev['kws']:
        d = post('http://www.cninfo.com.cn/new/hisAnnouncement/query', {
            'pageNum':1,'pageSize':30,'column':'szse','tabName':'fulltext',
            'stock': f"{ev['code']},{ev['org']}", 'searchkey': kw, 'secid':'','plate':'',
            'category':'','trade':'','seDate': ev['seDate'],'sortName':'','sortType':'','isHLtitle':'true'})
        for a in (d.get('announcements') or []):
            t = re.sub(r'<[^>]+>','',a['announcementTitle'])
            hits.append({'title':t,'date':time.strftime('%Y-%m-%d',time.localtime(a['announcementTime']/1000)),
                         'url':'https://static.cninfo.com.cn/'+a['adjunctUrl']})
        time.sleep(0.3)
    seen=set(); uniq=[]
    for h in hits:
        if h['title'] not in seen:
            seen.add(h['title']); uniq.append(h)
    out[ev['dir']]=uniq
    print(f"== {ev['dir']} ({ev['code']}) {len(uniq)} announcements")
    for h in uniq[:14]:
        print(f"  {h['date']} {h['title'][:46]}")
json.dump(out, open('/root/capital_opinion_pilot/v5_migration_20261022/v5_release/v3_cninfo_hits.json','w'), ensure_ascii=False, indent=1)
