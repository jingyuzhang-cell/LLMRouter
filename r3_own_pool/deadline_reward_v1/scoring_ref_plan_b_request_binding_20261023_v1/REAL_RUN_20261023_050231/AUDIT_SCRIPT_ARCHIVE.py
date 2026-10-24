from pathlib import Path
import json,hashlib,re,unicodedata,collections,datetime
from decimal import Decimal,InvalidOperation
B=Path('/root/r3_own_pool/deadline_reward_v1/scoring_ref_plan_b_request_binding_20261023_v1')
run=Path(json.loads((B/'EXECUTION_CLAIM.json').read_text())['run']);assert (run/'SUMMARY.json').exists(), 'Wait for bounded batch to finish'
assert not (run/'SOURCE_CONSTRAINED_REFERENCE.json').exists(), 'No outcome overwrite'
queue=json.loads((B/'REQUESTS_NOT_AUTHORIZED.json').read_text());config=json.loads((B/'CONFIG_AND_BUDGET.json').read_text());ledger=json.loads((run/'REQUEST_LEDGER.json').read_text());summary=json.loads((run/'SUMMARY.json').read_text())
freeze=json.loads(Path(config['source_freeze']['file']).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
# Confirm acquisition artifacts before creating rule-check products.
result_manifest=json.loads((run/'RESULT_MANIFEST.json').read_text())
assert all(sha(run/p)==h for p,h in result_manifest['files'].items())
assert all(sha(p)==h for p,h in config['source_sha256'].items())
contexts={r['task_id']:json.loads(r['body']['messages'][1]['content']) for r in queue}
by_request={r['request_id']:r for r in ledger}

def norm(text):return ''.join(unicodedata.normalize('NFKC',str(text)).split())
def normalized_map(text):
 out=[];positions=[]
 for i,ch in enumerate(text):
  for c in unicodedata.normalize('NFKC',ch):
   if not c.isspace():out.append(c);positions.append(i)
 return ''.join(out),positions

def citation_check(cite,sources):
 if not isinstance(cite,dict):return {'traceable':False,'reason':'CITATION_NOT_OBJECT'}
 did=cite.get('source_doc_id',cite.get('doc_id'));quote=cite.get('quote');page=cite.get('page');doc=next((x for x in sources if x['doc_id']==did),None)
 rec={'source_doc_id':did,'model_page':page,'model_section_id':cite.get('section_id'),'traceable':False,'literal_support_only':True}
 if doc is None:rec['reason']='SOURCE_NOT_IN_ASSIGNED_TASK';return rec
 if not isinstance(quote,str) or len(norm(quote))<6:rec['reason']='QUOTE_MISSING_OR_TOO_SHORT';return rec
 matches=[]
 for p in doc['pages']:
  text=p['text'];needle=norm(quote);hay,pos=normalized_map(text);start=0
  while True:
   at=hay.find(needle,start)
   if at<0:break
   matches.append({'page':p['page'],'section_id':p.get('section_id'),'start':pos[at],'end':pos[at+len(needle)-1]+1,'source_page_text_sha256':p['text_sha256'],'matched_source_text':text[pos[at]:pos[at+len(needle)-1]+1]});start=at+1
 if not matches:rec['reason']='QUOTE_NOT_FOUND_IN_ASSIGNED_SOURCE';return rec
 declared=page
 if isinstance(declared,str) and declared.isdigit():declared=int(declared)
 located=[m for m in matches if m['page']==declared] if declared is not None else matches
 if declared is not None and not located:rec.update(reason='DECLARED_PAGE_MISMATCH',possible_source_locations=[{k:v for k,v in m.items() if k!='matched_source_text'} for m in matches]);return rec
 if doc['raw_format']=='HTML_NO_PDF_PAGE' and cite.get('section_id') not in (None,'saved_html_text'):rec['reason']='HTML_SECTION_MISMATCH';return rec
 if len(located)!=1:rec.update(reason='AMBIGUOUS_QUOTE_LOCATION',location_count=len(located));return rec
 rec.update(traceable=True,reason='SOURCE_LITERAL_LOCATED',location=located[0],location_derived_by_rule=declared is None,source_raw_sha256=doc['raw_sha256'],quote=quote)
 return rec

def dates(text):
 return {tuple(map(int,x)) for x in re.findall(r'(?<!\d)(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})(?:日)?',norm(text))}
def monetary_pairs(text):
 out=[]
 for n,u in re.findall(r'([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)',norm(text)):
  try:out.append(Decimal(n.replace(',',''))*{'元':1,'万元':10000,'亿元':100000000}[u])
  except InvalidOperation:pass
 return out

def check_fact(f,sources):
 if not isinstance(f,dict):return {'citation':{'traceable':False,'reason':'FACT_NOT_OBJECT'},'candidate_reference':False,'fact':f}
 citation=citation_check(f,sources);quote=citation.get('quote','');checks={}
 subject=f.get('subject');checks['subject_literal_in_assigned_document']=any(norm(subject) in norm(p['text']) for d in sources for p in d['pages']) if isinstance(subject,str) and subject.strip() else None
 wanted=dates(f.get('date','')) if f.get('date') else set();checks['date_literal_in_quote']=wanted<=dates(quote) if wanted else None
 amount=f.get('amount');unit=f.get('unit');want_amount=None
 if amount is not None:
  pairs=monetary_pairs(str(amount)+str(unit or ''))
  if len(pairs)==1:want_amount=pairs[0]
 checks['amount_equivalent_in_quote']=want_amount in monetary_pairs(quote) if want_amount is not None else None
 docnums=re.findall(r'[〔\[]\d{4}[〕\]]\d+号',norm(str(f.get('value',''))))
 checks['document_number_literal_in_quote']=all(n in norm(quote) for n in docnums) if docnums else None
 status=str(f.get('status','')).upper();literal_known_false=any(v is False for v in checks.values())
 candidate=citation['traceable'] and status=='SUPPORTED' and not literal_known_false
 return {'fact':f,'citation':citation,'rule_checks':checks,'candidate_reference':candidate,'grade':'SOURCE_TRACEABLE_MACHINE_CANDIDATE_NOT_INDEPENDENT_GOLD' if candidate else 'UNRESOLVED','semantic_entailment_independently_confirmed':False}

reviews={};counts=collections.Counter();source_candidates=[]
for r in queue:
 rid=r['request_id'];record=by_request.get(rid);path=run/(rid+'_PARSED.json')
 if record is None or not path.exists() or not record.get('review_container_pass'):
  reviews[rid]={'status':'MISSING_OR_INVALID_REVIEW','facts':[],'conflict_reviews':[]};continue
 parsed=json.loads(path.read_text());sources=contexts[r['task_id']]['source_documents']
 fact_checks=[check_fact(f,sources) for f in parsed['key_facts']]
 cf=[]
 expected={x['item_id'] for x in contexts[r['task_id']]['potential_conflict_checklist']}
 for item in parsed['conflict_reviews']:
  if not isinstance(item,dict):cf.append({'candidate_id':None,'valid_id':False,'reason':'NOT_OBJECT'});continue
  cid=item.get('candidate_id');citations=[citation_check(c,sources) for c in item.get('supports',[]) if isinstance(item.get('supports',[]),list)]
  verdict=str(item.get('verdict','')).upper();cf.append({'candidate_id':cid,'valid_id':cid in expected,'verdict':verdict,'verdict_valid':verdict in ['TRUE_CONFLICT','DIFFERENT_SCOPE','NO_CONFLICT','UNRESOLVED'],'citation_checks':citations,'all_citations_traceable':bool(citations) and all(x['traceable'] for x in citations),'raw_judgment':item,'semantic_conflict_confirmed':False})
 reviews[rid]={'status':'SOURCE_RULE_CHECKED_MACHINE_ONLY','task_id':r['task_id'],'family':r['family'],'facts':fact_checks,'conflict_reviews':cf,'unverifiable_claims':parsed['unverifiable_claims'],'necessary_answer_points':parsed['necessary_answer_points'],'scope_limitations':parsed['scope_limitations'],'completeness_and_relevance':'UNKNOWN_NO_FINAL_QUESTION_IN_ORIGINAL_TASK_SET'}
 counts['fact_claims']+=len(fact_checks);counts['traceable_fact_claims']+=sum(x['citation'].get('traceable',False) for x in fact_checks);counts['source_candidate_fact_claims']+=sum(x['candidate_reference'] for x in fact_checks)

# Exact fact alignment only; unmatched paraphrases are UNALIGNED, not contradictions.
def fact_key(f):return tuple(norm(f.get(k,'')) for k in ['subject','predicate','value','date','date_type','amount','unit'])
consensus=[];unaligned=[]
for task in sorted(contexts):
 ds=reviews.get(task+'_deepseek',{});qw=reviews.get(task+'_qwen',{});dd={};qq={}
 for f in ds.get('facts',[]):
  if isinstance(f.get('fact'),dict):dd.setdefault(fact_key(f['fact']),[]).append(f)
 for f in qw.get('facts',[]):
  if isinstance(f.get('fact'),dict):qq.setdefault(fact_key(f['fact']),[]).append(f)
 for key in sorted(set(dd)|set(qq)):
  left=dd.get(key,[]);right=qq.get(key,[])
  if len(left)==1 and len(right)==1:
   good=left[0]['candidate_reference'] and right[0]['candidate_reference'];entry={'task_id':task,'fact_identity_fields':list(key),'deepseek':left[0],'qwen':right[0],'status':'TWO_FAMILY_SOURCE_TRACEABLE_CANDIDATE' if good else 'UNRESOLVED_SOURCE_OR_STATUS','independent_gold':False};consensus.append(entry)
   if good:source_candidates.append(entry)
  else:unaligned.append({'task_id':task,'fact_identity_fields':list(key),'deepseek_count':len(left),'qwen_count':len(right),'status':'UNALIGNED_NOT_A_PROVEN_DISAGREEMENT'})

conflict_audit=[]
for candidate in freeze['conflict_candidates']:
 tid=candidate['task_id'];cid=candidate['item_id'];sides=[]
 for family in ['deepseek','qwen']:
  matches=[x for x in reviews.get(tid+'_'+family,{}).get('conflict_reviews',[]) if x.get('candidate_id')==cid];sides.append(matches[0] if len(matches)==1 else None)
 a,b=sides;entry={'candidate_id':cid,'task_id':tid,'original_candidate':candidate['original_candidate'],'deepseek':a,'qwen':b,'independently_confirmed_contradiction':False}
 if a is None or b is None:entry['status']='UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW'
 elif not(a.get('verdict_valid') and b.get('verdict_valid')):entry['status']='UNRESOLVED_INVALID_VERDICT'
 elif a['verdict']!=b['verdict']:entry['status']='UNRESOLVED_MODEL_DISAGREEMENT'
 elif a['verdict']=='UNRESOLVED':entry['status']='UNRESOLVED_BOTH_MODELS'
 elif not(a['all_citations_traceable'] and b['all_citations_traceable']):entry['status']='UNRESOLVED_SOURCE_TRACEABILITY'
 else:entry.update(status='SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE',consensus_verdict=a['verdict'],grade='MACHINE_SEMANTIC_CANDIDATE_NOT_INDEPENDENT_ADJUDICATION')
 conflict_audit.append(entry)
conflict_counts=dict(collections.Counter(x['status'] for x in conflict_audit));unresolved=sum(x['status']!='SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE' for x in conflict_audit)
reference={'label':'机器辅助构建、来源证据约束的评分参考','scope':'10 tasks /7 development events /16 conflict candidates; not new independent test set','run':str(run),'source_rule_counts':dict(counts),'strictly_aligned_fact_pair_count':len(consensus),'two_family_source_traceable_fact_candidates':source_candidates,'unaligned_facts':unaligned,'conflict_audit':conflict_audit,'conflict_counts':conflict_counts,'review_checks':reviews,'terminal_scoring_status':{'fact_correctness':'candidate source references only; literal grounding not proof of semantic entailment','evidence_support':'quote/source/page positions checked; full semantic support still machine-assisted','necessary_completeness':'UNKNOWN_NO_FINAL_TASK_QUESTION_OR_CONFIRMED_NECESSARY_FACT_SET','contradiction_handling':'16 per-item machine judgments with source traces, unresolved cases retained','unverifiable_refusal':'candidate source-gap findings only; absence in excerpt not proof of absence globally','question_relevance':'UNKNOWN_NO_FINAL_TASK_QUESTION'},'independent_gold':False,'human_blind_review_performed':False,'scheduler_outputs_used_to_construct_reference':False,'robustness':{'unresolved_conflict_items':unresolved,'optimistic_pessimistic_conflict_decision_bounds':[0,unresolved],'interpretation':'bounds describe unresolved reference labels only, not policy Q or gains','strategy_comparison_sensitivity':'NOT_IDENTIFIABLE_NO_MATCHED_TERMINAL_STRATEGY_OUTPUTS; no strategy output read or invented','stable_policy_ranking_claimed':False}}
(run/'SOURCE_CONSTRAINED_REFERENCE.json').write_text(json.dumps(reference,ensure_ascii=False,indent=2))
report=['# 方案B双模型核验与规则检查结果','\n**真实核验批次结束；机器辅助候选参考已生成，未认证独立Gold。**\n',f"- 请求：{summary['requests_dispatched']}/20；批次状态：{summary['status']}；停止原因：{summary['stop_reason']}。",f"- 原生JSON：{summary['native_json_pass']}；规定核验容器：{summary['review_container_pass']}；自动重试0。",f"- 输入Token：{summary['tokens']['prompt']}；输出Token：{summary['tokens']['completion']}。",f"- 保守估费（分币种）：CNY {summary['estimated_native']['CNY']}；USD {summary['estimated_native']['USD']}。实际账单仍待核验，不把估费写成现金扣款。",f"- 观测批次墙钟：{summary['wall_s']:.3f}秒；来源与算法身份保持：{summary['source_and_algorithm_identity_unchanged']}。",'\n## 原文规则核对\n',f"共核查{counts['fact_claims']}条两模型事实主张（非去重真值数）；其中{counts['traceable_fact_claims']}条引文可定位到指定源文档，{counts['source_candidate_fact_claims']}条未在已执行字面规则中发现反例。后者仍不是独立正确率。",f"两模型严格字段对齐{len(consensus)}对事实，其中{len(source_candidates)}对同时通过来源追溯并给出SUPPORTED，列为机器共识候选。表达不同而未对齐者保留UNALIGNED，不能直接判为分歧或错误。",'\n16个待核冲突项逐项结果：\n','|编号|状态|双模型共识（若有）|','|---|---|---|']
for x in conflict_audit:report.append(f"|{x['candidate_id']}|{x['status']}|{x.get('consensus_verdict','—')}|")
report+=['\n完整逐事实、逐引文的页码、文本区间、原始判断和字段核对见SOURCE_CONSTRAINED_REFERENCE.json。仅对空白/Unicode作定位规范化；未重写模型事实、替换证据或补数值答案。跨文档重复日期不自动算矛盾，TRUE_CONFLICT共识也仅为机器语义候选。', '\n## 六维参考的实际边界\n','来源事实和引文可形成候选参考；必要完整性和问题相关性仍UNKNOWN，因为原CT任务没有最终问题字段及已确认的必要事实全集。模型不能猜题补全。未进行人类双盲评审，所有7事件保留开发曝光。', '\n## 稳健性与停止\n',f'16项中有{unresolved}项仍未决；不能将它们强判为支持/反对。保留不同合理处理下的标签范围，但没有与这10任务和本批参考匹配的策略终端输出，策略排序敏感性目前不可识别。本轮不读取调度器答案来构造参考，不捏造稳健结论。', '\n批次结束后停止；无追加、无重试、无QS/Router/GPU或调度收益实验。实际账单及终端任务定义的缺口保留，不自动进入确认性实验。']
(run/'REFERENCE_AUDIT_RESULT.md').write_text('\n'.join(report))
(run/'AUDIT_MANIFEST.json').write_text(json.dumps({'reference':sha(run/'SOURCE_CONSTRAINED_REFERENCE.json'),'report':sha(run/'REFERENCE_AUDIT_RESULT.md'),'acquisition_manifest':sha(run/'RESULT_MANIFEST.json'),'request_matrix':sha(B/'REQUESTS_NOT_AUTHORIZED.json'),'new_model_calls_in_audit':0,'source_files_unchanged':all(sha(p)==h for p,h in config['source_sha256'].items())},ensure_ascii=False,indent=2))
print(json.dumps({'run':str(run),'summary':summary,'source_rule_counts':dict(counts),'aligned_fact_pairs':len(consensus),'two_model_source_candidates':len(source_candidates),'conflict_counts':conflict_counts,'unresolved':unresolved},ensure_ascii=False))
