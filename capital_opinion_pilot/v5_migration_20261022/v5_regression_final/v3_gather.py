import hashlib, json, re, subprocess, urllib.request
from pathlib import Path
BASE = Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_regression_final/v3_evidence')
DOCS = {
 'A_kangdexin': {'cutoff':'2021-06-30','event':'康得新(002450)跨年度财务造假与信息披露争议', 'docs':[
  ('kdx_inquiry_2018','2018年年报问询函回复','2019-05-31','https://static.cninfo.com.cn/finalpage/2019-05-31/1200717695.PDF'),
  ('kdx_notice_2019','收到行政处罚事先告知书公告','2019-07-06','https://static.cninfo.com.cn/finalpage/2019-07-06/1200769611.PDF'),
  ('kdx_notice_2020','收到行政处罚及市场禁入事先告知书公告','2020-06-28','https://static.cninfo.com.cn/finalpage/2020-06-28/1207987672.PDF'),
  ('kdx_penalty_2020','收到行政处罚决定书及市场禁入决定书公告','2020-09-29','https://static.cninfo.com.cn/finalpage/2020-09-29/1208252711.PDF'),
  ('kdx_inquiry_2019','2019年年报问询函回复','2020-07-22','https://static.cninfo.com.cn/finalpage/2020-07-22/1208118678.PDF')]},
 'B_yujingangshi': {'cutoff':'2022-06-30','event':'豫金刚石(300064)多主体资金占用与违规担保', 'docs':[
  ('yjt_occupy_2020','2020年度关联方资金占用及违规担保专项审核报告','2021-04-27','https://static.cninfo.com.cn/finalpage/2021-04-27/1209974125.PDF'),
  ('yjt_notice_2021','收到行政处罚及市场禁入事先告知书公告','2021-08-16','https://static.cninfo.com.cn/finalpage/2021-08-16/1211116803.PDF'),
  ('yjt_reply_2021','深交所关注函部分回复公告（一）','2021-10-26','https://static.cninfo.com.cn/finalpage/2021-10-26/1211534477.PDF'),
  ('yjt_reply_2022','对深交所关注函回复的公告','2022-03-29','https://static.cninfo.com.cn/finalpage/2022-03-29/1212789929.PDF'),
  ('yjt_occupy_2021','2021年度关联方资金占用及违规担保情况专项说明','2022-04-30','https://static.cninfo.com.cn/finalpage/2022-04-30/1213052187.PDF')]},
 'C_shijuezhongguo': {'cutoff':'2019-06-30','event':'视觉中国(000681)黑洞照片重大舆情与多方回应', 'docs':[
  ('sjzg_suspend_2019','关于公司网站暂停服务的公告','2019-04-12','https://static.cninfo.com.cn/finalpage/2019-04-12/1206033293.PDF'),
  ('sjzg_abnormal_2019','股票交易异常波动公告','2019-04-17','https://static.cninfo.com.cn/finalpage/2019-04-17/1206041017.PDF'),
  ('sjzg_resume_2019','关于公司网站恢复服务的公告','2019-05-13','https://static.cninfo.com.cn/finalpage/2019-05-13/1206262992.PDF')]},
}
manifests={}
for ev, meta in DOCS.items():
    docs=[]
    for doc_id, title, date, url in meta['docs']:
        dest = BASE/ev/'raw'/f'{doc_id}.pdf'
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 Chrome/124.0'})
            blob=urllib.request.urlopen(req, timeout=60).read()
            dest.write_bytes(blob)
            r=subprocess.run(['pdftotext','-layout',str(dest),'-'],capture_output=True)
            text=re.sub(r'[ \t]+',' ',re.sub(r'\n{3,}','\n\n',r.stdout.decode('utf-8','replace'))).strip()
            (BASE/ev/'text'/f'{doc_id}.txt').write_text(text)
            docs.append({'doc_id':doc_id,'title':title,'url':url,'public_date':date,'bytes':len(blob),
                'sha256':hashlib.sha256(blob).hexdigest(),'text_chars':len(text),'status':'OK',
                'cutoff_ok':date<=meta['cutoff']})
            print(ev,doc_id,len(blob),'text',len(text))
        except Exception as e:
            docs.append({'doc_id':doc_id,'title':title,'url':url,'public_date':date,'status':f'FAIL:{e}'})
            print(ev,doc_id,'FAIL',e)
    manifests[ev]={**meta,'documents':docs}
json.dump(manifests, open(BASE/'v3_manifests.json','w'), ensure_ascii=False, indent=1)
