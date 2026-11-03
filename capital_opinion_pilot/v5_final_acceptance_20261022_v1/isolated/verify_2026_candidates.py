"""Zero-pay verification of 2026 candidate events against OFFICIAL sources (cninfo API).
News reports are leads only. For each candidate: resolve company identity (code/orgId),
query real announcements in 2026, record doc URLs/dates; download core PDFs for SHA256.
"""
import json, re, time, urllib.request, urllib.parse, hashlib
from pathlib import Path
P = Path('/root/capital_opinion_pilot/v5_final_acceptance_20261022_v1/isolated/benchmark_v1')

def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
    req.add_header('Content-Type','application/x-www-form-urlencoded')
    req.add_header('User-Agent','Mozilla/5.0 Chrome/124.0')
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read().decode())

CANDS = [  # (pool_id, search_name, keyword, note)
 ('E03-yuandao','元道退','行政处罚','欺诈发行处罚+禁入(复盘型)'),
 ('E04-zhuoran','卓然','立案','立案+事先告知(复盘/当时)'),
 ('E05-nachuan','纳川','立案','2023年报信披立案(当时型)'),
 ('E06-huanrui','欢瑞世纪','立案','证监立案字0152026005(当时型)'),
 ('E07-xiwang','西王食品','立案','公司+实控人立案(当时型)'),
 ('E08-zhongtie','中铁装配','立案','证监会立案(当时型)'),
 ('E09-guitiancheng','贵天成','行政处罚','贵州局事先告知(当时型)'),
 ('E10-xiangyuan','祥源文旅','立案','实控人被查(当时型)'),
 ('E10b-jiaojian','交建股份','立案','实控人被查(同源E10)'),
]
out={}
for pid,name,kw,note in CANDS:
    try:
        tops=post('http://www.cninfo.com.cn/new/information/topSearch/query',{'keyWord':name,'maxNum':10})
        if not tops: out[pid]={'status':'IDENTITY_NOT_FOUND','search':name}; print(pid,'NO IDENTITY'); continue
        t0=tops[0]; code,org,realname=t0['code'],t0['orgId'],t0.get('zwjc') or t0.get('name','')
        hits=[]
        for searchkey in [kw]:
            d=post('http://www.cninfo.com.cn/new/hisAnnouncement/query',{
             'pageNum':1,'pageSize':30,'column':'szse','tabName':'fulltext',
             'stock':f'{code},{org}','searchkey':searchkey,'secid':'','plate':'','category':'','trade':'',
             'seDate':'2026-01-01~2026-10-13','sortName':'','sortType':'','isHLtitle':'true'})
            for a in (d.get('announcements') or []):
                title=re.sub(r'<[^>]+>','',a['announcementTitle'])
                hits.append({'title':title,
                    'date':time.strftime('%Y-%m-%d',time.localtime(a['announcementTime']/1000)),
                    'url':'https://static.cninfo.com.cn/'+a['adjunctUrl']})
        time.sleep(0.25)
        out[pid]={'status':'IDENTITY_OK','name':realname,'code':code,'orgId':org,'note':note,
                  'n_hits':len(hits),'hits':hits[:6]}
        print(pid, realname, code, 'hits:', len(hits))
        for h in hits[:3]: print('   ', h['date'], h['title'][:44])
    except Exception as e:
        out[pid]={'status':f'ERR:{type(e).__name__}','detail':str(e)[:100]}; print(pid,'ERR',e)
json.dump(out, open(P/'verify_raw.json','w'), ensure_ascii=False, indent=1)
