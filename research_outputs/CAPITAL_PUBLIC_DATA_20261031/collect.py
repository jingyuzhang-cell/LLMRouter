"""Public primary documents only. No model endpoints or credentials."""
import concurrent.futures,hashlib,json,urllib.request,importlib.util
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
SOURCES=[
('JIAYUAN_202610','CSRC_PENALTY','https://www.csrc.gov.cn/csrc/c101928/c7666388/content.shtml','2026-10-23','regulator_decision'),
('JIAYUAN_202610','ACCOUNTING_CORRECTION','https://static.cninfo.com.cn/finalpage/2026-10-17/1225609797.PDF','2026-10-17','issuer_correction'),
('RONBAY_202601','INQUIRY','https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-01-14/688005_20260114_OG2A.pdf','2026-01-14','issuer_disclosure_of_inquiry'),
('RONBAY_202601','REPLY','https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-01-19/688005_20260119_MV08.pdf','2026-01-19','issuer_reply'),
('RONBAY_202601','PENALTY_PRENOTICE','https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-02-07/688005_20260207_ZQPS.pdf','2026-02-07','issuer_disclosure_preliminary_notice_not_final'),
('JCZ_202605','INQUIRY','https://static.cninfo.com.cn/finalpage/2026-05-19/1225313541.PDF','2026-05-19','issuer_disclosure_of_inquiry'),
('JCZ_202605','REPLY','https://epaper.stcn.com/pic/202605/26/70212c4c661d6a436d18a308c6e1aad2.pdf','2026-05-26','issuer_reply_hosted_by_disclosure_newspaper')]
def collect(row):
 event,sid,url,date,role=row;directory=ROOT/event/sid;directory.mkdir(parents=True,exist_ok=False)
 item=dict(event=event,source_id=sid,url=url,publication_date_from_listing=date,document_role=role,retrieved_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),reference_grade='UNADJUDICATED_SOURCE',independence='NOT_CERTIFIED')
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (research document retrieval)'})
  with urllib.request.urlopen(req,timeout=25) as response:
   data=response.read(12*1024*1024+1);item['resolved_url']=response.geturl();item['content_type']=response.headers.get('Content-Type');item['http_status']=response.status
  if len(data)>12*1024*1024:raise ValueError('SIZE_LIMIT')
  ispdf=data.startswith(b'%PDF')
  if url.lower().endswith('.pdf') and not ispdf:raise ValueError('EXPECTED_PDF_GOT_OTHER_CONTENT')
  file=directory/('source.pdf' if ispdf else 'source.html');file.write_bytes(data)
  item.update(file=str(file.relative_to(ROOT)),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),status='DOWNLOADED')
  if ispdf:
   import fitz
   doc=fitz.open(file);pages=[]
   for i,page in enumerate(doc):
    text=page.get_text();p=directory/f'p{i+1:03d}.txt';p.write_text(text)
    pages.append({'page':i+1,'file':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(text.encode()).hexdigest(),'characters':len(text),'text_extraction_only_not_visual_adjudication':True})
   item.update(page_count=len(doc),pages=pages)
  else:
   from bs4 import BeautifulSoup
   text=BeautifulSoup(data,'html.parser').get_text('\n',strip=True);p=directory/'text.txt';p.write_text(text)
   item['text_file']=str(p.relative_to(ROOT));item['text_sha256']=hashlib.sha256(text.encode()).hexdigest()
 except Exception as exc:item.update(status='FAILED_OR_PARTIAL',error_type=type(exc).__name__,error=str(exc))
 return item
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(collect,SOURCES))
(ROOT/'SOURCE_MANIFEST.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps([{'event':x['event'],'source':x['source_id'],'status':x['status'],'pages':x.get('page_count'),'error':x.get('error')} for x in results],ensure_ascii=False))
