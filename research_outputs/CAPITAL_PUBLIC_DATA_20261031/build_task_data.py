"""Local source indexing only; no network, model, or frozen experiment imports."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent
manifest=json.loads((R/'SOURCE_MANIFEST.json').read_text())
queries={
'JIAYUAN_202610':[
('CSRC_PENALTY','600万元','公司处罚结论和金额是什么？'),
('CSRC_PENALTY','上述两项违法行为','违法事实合计影响哪些年度及财务指标？'),
('CSRC_PENALTY','不具备商业实质','无商业实质交易与提前确认收入是否属于不同事项？'),
('ACCOUNTING_CORRECTION','2024 年度','更正覆盖年度是否等于违法行为涉及年度？'),
('ACCOUNTING_CORRECTION','10 月16 日','收到处罚决定与公告公开日期分别是什么？'),
('ACCOUNTING_CORRECTION','1,327.95','单项影响与合计影响怎样对应，能否混用？')],
'RONBAY_202601':[
('INQUIRY','1 月13 日','何时收到问询，公告何时公开？'),
('REPLY','1200 亿元','1200亿元是合同约定还是公司估算？'),
('REPLY','305 万吨','305万吨是保证采购量还是预测需求？'),
('REPLY','6 万吨','现有产能与预计需求有什么口径区别？'),
('REPLY','2027 年','哪些未来商务条件尚待约定？'),
('REPLY','不确定性','哪些履约风险仍未消除，能否推定收入必然实现？')],
'JCZ_202605':[
('INQUIRY','2026年5月18日','问询接收时间与公告公开时间分别是什么？'),
('REPLY_CNSTOCK','55.00%','拟收购主体、股权比例及支付方式是什么？'),
('REPLY_CNSTOCK','32,525.46','本次评估值、上次评估值及下降金额如何核对？'),
('REPLY_CNSTOCK','2025年12','评估基准日与回复日期是否混淆？'),
('REPLY_CNSTOCK','尚需经上市公司股东会','交易审批是否完成，是否可以写成已完成收购？'),
('REPLY_CNSTOCK','2025年5月14日','原文董事会日期与2026年方案时间线是否有疑点？保留原文，不自行纠正。')]
}
rows=[];tasks=[]
for event,qs in queries.items():
 refs=[]
 for i,(sid,needle,q) in enumerate(qs,1):
  doc=next(x for x in manifest if x['event']==event and x['source_id']==sid and x['status']=='DOWNLOADED')
  files=doc.get('pages') or [{'file':doc['text_file'],'page':None}]
  hits=[]
  for page in files:
   t=(R/page['file']).read_text();start=0
   while (pos:=t.find(needle,start))>=0:
    a=max(0,pos-160);b=min(len(t),pos+len(needle)+300)
    hits.append(dict(file=page['file'],page=page.get('page'),start=a,end=b,quote=t[a:b],offset_unit='unicode_codepoint_in_extracted_text',text_sha256=hashlib.sha256(t.encode()).hexdigest(),source_sha256=doc['sha256'],source_url=doc['url']))
    start=pos+len(needle)
  ref=dict(id=f'{event}_T{i}',question=q,search_literal=needle,evidence=hits,reference_status='PENDING',answer=None,adjudicator=None,match_status='LOCATED' if hits else 'NOT_LOCATED',support_verified=False)
  refs.append(ref);rows.append(ref)
 tasks.append(dict(task_id=event,reference_ids=[x['id'] for x in refs],source_scope=next(e for e in json.loads((R/'EVENT_INDEX.json').read_text()) if e['event']==event),output_contract={'items':[{'reference_id':'string','answer':'string or null','status':'ASSERTED or UNKNOWN','evidence':[{'source_id':'string','quote':'exact source text','page':'integer or null'}]}],'require_distinguish':['document_statement','regulator_finding','forecast','derived_calculation','unresolved_conflict']},reference_role='PRIVATE_REVIEW_CANDIDATES_NOT_GOLD',runtime_status='DATA_ONLY_NOT_BOUND_TO_FROZEN_RUNNER',unknown_rule='证据缺失、口径冲突和无法确认时保留UNKNOWN；不得依赖后续文档填补早期截止任务。'))
(R/'REFERENCE_CANDIDATES.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(R/'TASK_INPUTS.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2))
checks=[]
for row in rows:
 for h in row['evidence']:
  t=(R/h['file']).read_text();assert t[h['start']:h['end']]==h['quote'];assert hashlib.sha256(t.encode()).hexdigest()==h['text_sha256']
 checks.append({'id':row['id'],'located':bool(row['evidence']),'matches':len(row['evidence'])})
(R/'DATA_CHECK.json').write_text(json.dumps({'checks':checks,'all_offsets_verified':True,'reference_adjudication':'PENDING','model_calls':0,'gold_count':0},ensure_ascii=False,indent=2))
print(json.dumps(checks,ensure_ascii=False))
