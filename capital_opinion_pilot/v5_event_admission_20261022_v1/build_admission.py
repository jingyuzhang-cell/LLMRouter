"""Public-source acquisition and metadata admission only; no model/scheduler imports."""
import json,hashlib,datetime,pathlib,requests,csv,re
import pymupdf
BASE=pathlib.Path(__file__).resolve().parent
assert not (BASE/'EVENT_ADMISSION.json').exists(), 'Never overwrite frozen admission'
items=[
('ANKER','安克创新','300866','https://static.cninfo.com.cn/finalpage/2025-08-29/1224614835.PDF','2025-08-29','2025半年度报告','投资募集/使用/账户余额核对'),
('ECOVACS','科沃斯','603486','https://static.cninfo.com.cn/finalpage/2025-04-26/1223323880.PDF','2025-04-26','2024募集资金专项报告','账户余额、资金来源调整及项目投入核对'),
('TUOPU','拓普集团','601689','https://static.cninfo.com.cn/finalpage/2026-03-24/1225026446.PDF','2026-03-24','2025年度报告','项目投入、募集资金及余额口径核对'),
('BULL','公牛集团','603195','https://static.cninfo.com.cn/finalpage/2026-04-30/1225265197.PDF','2026-04-30','2025年度报告','募集净额、使用额、利息与结项核对'),
('UNITED','联影医疗','688271','https://static.cninfo.com.cn/finalpage/2026-04-29/1225233728.PDF','2026-04-29','2025年度报告','财务指标、现金流与研发口径交叉核对'),
('HIK','海康威视','002415','https://static.cninfo.com.cn/finalpage/2026-04-18/1225123062.PDF','2026-04-18','2025年度报告','业务分部、年度指标与现金流核对'),
('CATL','宁德时代','300750','https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF','2026-03-10','2025年度报告','业务分部与合并财务指标口径核对'),
('BYD','比亚迪','002594','https://static.cninfo.com.cn/finalpage/2026-03-28/1225045351.PDF','2026-03-28','2025年度报告','业务分部、利润与现金流口径核对')]
freeze=json.loads(pathlib.Path('/root/capital_opinion_pilot/v5_zero_call_outcome_audit_20261022_v1/ALGORITHM_FREEZE.json').read_text())['algorithm_sha256']
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
assert all(sha(p)==h for p,h in freeze.items())
# Deliberately restricted to development code/report text, never sealed/eval/test/raw payloads.
roots=[pathlib.Path('/root/capital_opinion_pilot'),pathlib.Path('/root/r3_own_pool')]
exclude=('legacy','isolated','v5_migration_20261022','v5_final_acceptance_20261022_v1','qs_independent','qs_label_preparation','eval_only','sealed','holdout','reserved','raw','responses','REAL_RUN','REAL_BATCH','test','review','v5_event_admission_20261022_v1')
files=[]
for root in roots:
 for p in root.rglob('*'):
  if p.suffix not in ('.md','.py','.csv'):continue
  rel=str(p.relative_to(root))
  if any(x.lower() in rel.lower() for x in exclude):continue
  if p.stat().st_size>2_000_000:continue
  files.append(p)
contents=[]
for p in sorted(files):
 try:contents.append((p,p.read_text(errors='replace')))
 except OSError:pass
source_index={str(p):sha(p) for p,_ in contents}
rows=[]
(BASE/'raw').mkdir();(BASE/'evidence').mkdir()
for tag,name,ticker,url,date,title,dimension in items:
 eid='V5SCREEN_'+tag+'_'+date.replace('-','')
 row=dict(event_id=eid,issuer=name,ticker=ticker,cluster_scope='issuer/report-period candidate; event boundary NOT independently certified',source_url=url,source_date_from_disclosure_path=date,source_date_semantic_confirmation='PENDING',report=title,proposed_task_dimension=dimension,proposed_task_not_frozen=True)
 hits=[]
 for p,txt in contents:
  lines=[i for i,line in enumerate(txt.splitlines(),1) if name in line or ticker in line]
  if lines:hits.append(dict(path=str(p),lines=lines))
 row['development_search_hits']=hits
 row['development_exposure']='POSSIBLE_EXPOSURE_REQUIRES_ADJUDICATION' if hits else 'NO_HIT_IN_SCOPED_SEARCH_NOT_CERTIFIED_UNSEEN'
 try:
  now=datetime.datetime.now(datetime.timezone.utc).isoformat()
  resp=requests.get(url,timeout=(15,60));resp.raise_for_status()
  assert resp.content.startswith(b'%PDF'), 'not PDF'
  assert len(resp.content)<=32*1024*1024,'PDF too large'
  path=BASE/'raw'/f'{eid}.pdf';path.write_bytes(resp.content)
  doc=pymupdf.open(path)
  evidence=[]
  for i,page in enumerate(doc):
   txt=page.get_text()
   labels=[s for s in ['主要会计数据','合并利润表','合并现金流量表','募集资金','本年度募集资金实际使用情况','单位：','单位:'] if s in txt]
   if labels:evidence.append(dict(pdf_page_1based=i+1,matched_headings=labels,page_text_sha256=hashlib.sha256(txt.encode()).hexdigest()))
  first=doc[0].get_text(); titlepage=BASE/'evidence'/f'{eid}_title.txt';titlepage.write_text(first)
  idx=BASE/'evidence'/f'{eid}_page_index.json';idx.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
  row.update(source_status='DOWNLOADED_PARSED_NOT_SEMANTICALLY_ACCEPTED',http_status=resp.status_code,retrieved_at_utc=now,raw_path=str(path),raw_sha256=sha(path),pdf_pages=len(doc),candidate_evidence_index=str(idx),title_identity_check='ISSUER_SHORT_NAME_PRESENT' if name in first else 'NEEDS_REVIEW',source_completeness='FULL_PDF_SAVED; necessary fact/evidence completeness NOT established')
 except Exception as e:row.update(source_status='ACQUISITION_FAILED',source_error=str(e))
 row.update(terminal_reference=None,independent_gold_status='HOLD_NO_INDEPENDENT_CONFIRMATION',terminal_q_formula=None,terminal_q_denominator=None,unknown_boundary='UNRESOLVED attributes must remain UNKNOWN; no score/denominator invented',natural_multi_branch_dag='NOT_YET_ESTABLISHED',runtime_feedback_value='NOT_YET_ESTABLISHED',paired_state_package=None,fee_hard_upper=None,decision='NO-GO',missing=['complete historical exposure/cluster independence clearance','task-specific required terminal facts and evidence spans','independent terminal reference and scoring formula/denominator/UNKNOWN rules','natural DAG and runtime decision-space qualification','identical V5/RL state package and enforceable fee cap'])
 rows.append(row)
 print(eid,row['source_status'],len(hits),flush=True)
assert all(sha(p)==h for p,h in freeze.items())
assert all(sha(p)==h for p,h in source_index.items())
out=dict(status='SCREENING_COMPLETE_0_OF_8_ADMITTED',candidates=rows,scope='Only screening, not a confirmed independent test set; no algorithm tuning, model outputs or new Gold certification',algorithm_sha256=freeze,development_search=dict(files=len(contents),excluded_path_terms=exclude,limitation='No hit is not proof of no development exposure; omitted sealed/raw/history areas remain unchecked. Existing QS test contents not opened.'),requests_to_models=0,paid_execution_authorized=False,admitted_event_count=0)
(BASE/'EVENT_ADMISSION.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
(BASE/'DEVELOPMENT_SEARCH_SOURCE_INDEX.json').write_text(json.dumps(source_index,ensure_ascii=False,indent=2))
with (BASE/'EVENT_ADMISSION.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['event_id','issuer','source_date','PDF','pages','exposure','reference','terminal_Q','decision','missing'])
 for r in rows:w.writerow([r['event_id'],r['issuer'],r['source_date_from_disclosure_path'],r.get('raw_path',''),r.get('pdf_pages',''),r['development_exposure'],r['independent_gold_status'],'NOT_DEFINED',r['decision'],'; '.join(r['missing'])])
