import json, urllib.request, urllib.parse

def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
    req.add_header('Content-Type','application/x-www-form-urlencoded')
    req.add_header('User-Agent','Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

for code, kw in [('002450','行政处罚'), ('300064','行政处罚'), ('000681','')]:
    try:
        tops = post('http://www.cninfo.com.cn/new/information/topSearch/query', {'keyWord': code, 'maxNum': 10})
        org = tops[0]['orgId'] if tops else None
        print(code, 'orgId=', org, 'name=', tops[0].get('zwjc') if tops else None)
    except Exception as e:
        print(code, 'topSearch ERR', e); continue
