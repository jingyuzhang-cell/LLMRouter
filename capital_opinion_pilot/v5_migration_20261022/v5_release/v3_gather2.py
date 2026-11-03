import hashlib, json, re, subprocess, time, urllib.request, urllib.parse
from pathlib import Path
BASE = Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_release/v3_evidence')
def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
    req.add_header('Content-Type','application/x-www-form-urlencoded')
    req.add_header('User-Agent','Mozilla/5.0 Chrome/124.0')
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read().decode())

EVENTS = [
 {'dir':'A_kangdexin','code':'002450','org':'9900013433','seDate':'2019-04-01~2021-06-30',
  'kws':['行政处罚','问询函的回复'],'cutoff':'2021-06-30',
  'pick':['2018年年报的问询函的回复','行政处罚事先告知书','市场禁入事先告知书','行政处罚决定书','2019年年报的问询函的回复']},
 {'dir':'B_yujingangshi','code':'300064','org':'9900010792','seDate':'2021-01-01~2022-06-30',
  'kws':['行政处罚','资金占用','关注函'],'cutoff':'2022-06-30',
  'pick':['行政处罚及市场禁入事先告知书','关联方非经营性资金占用及清偿情况和违规担保及解除情况的专项审核','关注函回复的公告','关注函的部分回复公告（一）','2021年度关联方非经营性资金占用及清偿情况和违规担保及解除情况']},
 {'dir':'C_shijuezhongguo','code':'000681','org':'gssz0000681','seDate':'2019-04-01~2019-06-30',
  'kws':['','关注函','异常波动'],'cutoff':'2019-06-30',
  'pick':['网站暂停服务','异常波动','网站恢复服务','关注函']},
]
for ev in EVENTS:
    hits={}
    for kw in ev['kws']:
        d=post('http://www.cninfo.com.cn/new/hisAnnouncement/query',{
         'pageNum':1,'pageSize':50,'column':'szse','tabName':'fulltext',
         'stock':f"{ev['code']},{ev['org']}",'searchkey':kw,'secid':'','plate':'','category':'','trade':'',
         'seDate':ev['seDate'],'sortName':'','sortType':'','isHLtitle':'true'})
        for a in (d.get('announcements') or []):
            t=re.sub(r'<[^>]+>','',a['announcementTitle'])
            hits[t]=('https://static.cninfo.com.cn/'+a['adjunctUrl'],
                     time.strftime('%Y-%m-%d',time.localtime(a['announcementTime']/1000)))
        time.sleep(0.2)
    json.dump(hits, open(BASE/ev['dir']/'hits.json','w'), ensure_ascii=False, indent=1)
    print('==',ev['dir'],len(hits),'candidates')
    for t,(u,dt) in sorted(hits.items(), key=lambda x:x[1][1]):
        print(f'  {dt} {t[:48]}')
