"""Offline A graph and hard-budget audit; no scoring data or HTTP."""
import hashlib,json,shutil,time
from pathlib import Path
import semantic_plan as SP,assemble_dag as AD
root=Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final');out=root/('a_feasibility_budget_audit_'+str(time.time_ns()));out.mkdir()
def save(n,o):(out/n).write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
original=json.loads((root/'v3_kdx_repair.json').read_text());A=next(x for x in original['arms'] if x['arm']=='A');ledger=[json.loads(l) for l in (root/'model_call_ledger_v3kdxrepair.jsonl').read_text().splitlines()];record=next(x for x in ledger if x['call_id']==A['call_id']);save('A_ORIGINAL.json',A)
save('A_IDENTITY.json',{'generation_ledger_timestamp':record['ts'],'timezone':'UNKNOWN — ledger has no offset','ledger_call_id':record['call_id'],'raw_response_sha256':hashlib.sha256(A['raw_response'].encode()).hexdigest(),'saved_graph_sha256':hashlib.sha256(json.dumps(A['graph'],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'saved_graph_protocol':A['graph']['schema_version'],'graph_version':A['graph']['graph_version'],'original_file_sha256':sha(root/'v3_kdx_repair.json'),'original_graph_task_id':A['graph']['task_id'],'identity_warning':'Historical assembler default is Shuntian ID; original kept unmodified. KDX execution requires explicit correct task identity.'})
manifest=json.loads((root/'v3_evidence/v3_manifests.json').read_text())['A_kangdexin'];sources=[]
for d in manifest['documents']:
 raw=root/'v3_evidence/A_kangdexin/raw'/(d['doc_id']+'.pdf');text=root/'v3_evidence/A_kangdexin/text'/(d['doc_id']+'.txt');full=sha(raw) if raw.exists() else None
 sources.append({'doc_id':d['doc_id'],'url':d['url'],'public_date':d['public_date'],'raw_path':str(raw),'text_path':str(text),'local_accessible':raw.is_file() and text.is_file(),'raw_sha256':full,'manifest_prefix_matches':bool(full and full.startswith(d['sha256'])),'text_sha256':sha(text) if text.exists() else None,'text_chars':len(text.read_text()) if text.exists() else None,'manifest_chars':d['text_chars'],'date_within_cutoff':d['public_date']<=manifest['cutoff'],'remote_availability':'NOT_RECHECKED','date_semantic_verification':'Manifest metadata; not new document-content proof'})
save('SOURCE_AUDIT.json',sources)
p=A['plan'];issues=SP.validate_plan(p,[d['doc_id'] for d in sources]);gv,errors=AD.assemble(p,task_id='kdx_002450_a_feasibility_only');g,v=gv;save('CURRENT_VALIDATION.json',{'semantic_errors':issues,'typed_errors':errors,'graph':g.to_dict(),'scope':'Offline validation/reassembly, NOT new LLM generation','critical_path_node_count':len(v.layers),'layer_width_max':max(map(len,v.layers))})
rows=[]
for n in g.nodes:
 rows.append({'node':n.node_id,'contract':n.output_contract,'bindings':[b.__dict__ for b in n.inputs],'outputs':AD.C.td.CONTRACTS[n.output_contract][2],'dependencies':n.dependencies,'structural_status':'PASS','retrieval_status':'ALL_FIVE_DOCS_DECLARED_BUT_NO_EXECUTED_QUERIES' if n.output_contract=='doc_retrieval.v1' else 'NOT_A_RETRIEVAL_NODE','execution_status':'NOT_VALIDATED','issues':{'evidence_registry.v1':['Existing execute_v2 uses Shuntian task and evidence index, not this frozen KDX manifest'], 'doc_retrieval.v1':['Five docs total exceeds3300 direct-injection limit','No executed segmented queries or evidence-location records','Existing evidence_pack injects a different task corpus'],'timeline.v1':['Upstream output schema/content/size not observed','Dates and references not verified'],'entity_facts.v1':['Conflicts and unresolved ambiguity not established without actual extracts'],'fact_check_full.v1':['Typed JSON ports do not enforce claim-level provenance or adjudication','Semantic correctness not verified'],'report.v1':['Report only sees verified_facts; supporting corpus trace must survive upstream','No final report executed']}[n.output_contract]})
save('NODE_FEASIBILITY.json',rows)
save('BUDGET_REPLAY.json',{'call1':record,'call2':ledger[1],'first_actual':1970,'second_actual':2126,'total':4096,'overrun':96,'correct_second_reservation_if_known':1486+640,'correct_total_if_reserved':1970+1486+640,'original_guard':'1.5*640 output-only=960; omitted input','original_dispatch_condition':1970+960,'current_estimator':'Character-ratio empirical estimate is NOT certified hard input bound','http_payload':'Meter._transport passes max_tokens and thinking disabled; Mock HTTP asserts actual serialized payload','server_enforcement':'No server configuration evidence; request field and usage do not prove upper bound for every future request','usage_unknown':'StrictMeter keeps entire fsynced reservation and prevents retransmitting same payload','legacy_ledger_modified':False})
for name,src in [('COMBINED_TESTS.log','/tmp/kdx_combined.log'),('OLD_CONTRACT_TESTS.log','/tmp/kdx_contract2.log'),('METER_TESTS.log','/tmp/kdx_meter2.log'),('GUARD_TESTS.log','/tmp/kdx_guard2.log'),('DRY_TESTS.log','/tmp/kdx_dry2.log')]:shutil.copy(src,out/name)
report=f'''# A图执行可行性与Token硬预算审计

结论：**NO_GO for real execution**。本轮真实模型调用0，未加载GPU、未执行完整DAG、未读silver、未提交或推送。

## A图身份及结构
A_ORIGINAL.json保存既有6节点模型计划/图；A_IDENTITY.json记录原始响应SHA、图SHA、协议typed-dag.v1、版本1与原始账本时间。账本无时区，不补造。原图有错误的顺天默认task_id；原件不改，离线重装配才明确KDX身份。不是新的真实生成成功。
结构：t1索引→t2原证据检索→t3时间线/t4主体事实→t5全面核查→t6报告。所有声明依赖有匹配端口，全部节点贡献最终report；不存在显式孤立接受分支。深度5、最大拓扑层宽2，仅结构指标，不是实际时延或最大反链。
逐节点输入/输出/依赖及阻塞见NODE_FEASIBILITY.json。原A并未调用新的facts汇合适配器；不能把该适配器的合成测试当作A执行证据。

## 来源与执行
五文档本地PDF和文本逐个核验、哈希及manifest前缀比较见SOURCE_AUDIT.json；可访问不等于检索覆盖或语义正确。远端URL本轮未联网复核，公开日期仅沿用来源manifest并核对截止条件。
检索节点声明全部5文档，总全文127598字，远超3300字直接注入上限；没有真实分段查询、截取位置或上下文计量。是否存在跨来源冲突只能标NOT_ESTABLISHED，不能依据没有输出就判无冲突。新的merge保留和标记能力是独立离线证据。
现有execute_v2导入execute_dag.TASK_QUESTION/build_ctx_table/evidence_pack，绑定的是江苏舜天语料；直接运行会使用错误任务。它未提供完整KDX分段检索适配，也没有给下游JSON成长设置已验证的Token边界。结构可被Typed DAG接受，但整个工作流尚不能据此准入真实执行。

## 4096超额根因与修复
原第一调用1970，第二输入1486+输出640=2126，总4096。旧guard仅预留1.5×640=960，派发时误以为1970+960=2930小于4000；若完整输入+输出预留则4096，第二请求应提前拒绝。原记录、响应和超额量保留。
客户端max_tokens及thinking disabled在真实传输构造中存在，Mock HTTP验证了实际请求体。B输出640且stop_reason=max_tokens，但这不证明所有服务端调用永远遵守限额；没有服务端配置证据，不能声称硬边界已经外部认证。
当前budget_guard字符比例经验估计并非硬上界，不足以完成严格启动门禁。
新增可选strict_meter.StrictMeter复用Meter._transport：要求明确可信输入上界及其依据；派发前独占flock并fsync RESERVE；已知usage用包含原始响应的原子SETTLE记录核销；超时/未知usage完整预留继续占额；同一模型和请求内容跨purpose仍不重发。崩溃后根据journal恢复，已结算响应可复用。截断已知消耗核销但判失败；provider超边界会保存实际用量并锁止后续调用，不能撤销已发生费用。旧账本无预留事件则拒绝迁移运行。
summary报告actual+pending，而非把全部历史max_tokens重复相加。严格路径是可选新入口，未修改旧Meter及其其他实验语义；现有历史脚本不会自动获得该保护。缺少可信远程输入Tokenizer/计数与服务端输出边界证据时，StrictMeter应拒绝启动，不使用经验比例伪装保证。

## 零调用测试
strict_meter9/9、已有merge/身份/预算15/15，共24项通过；旧契约10项、计量8项、guard5项、Dry-run13项通过。包括恰好边界、预算不足拒绝、未知输入拒绝、超时/崩溃预留保留、重启去重、截断不重试、provider超量锁止以及真实HTTP请求体Mock。没有发送HTTP请求。日志保存在本目录。

## 下一步门禁及最小预算
首先离线完成正确KDX任务身份、五文档manifest、确定性分段检索及证据定位，并设置各阶段可执行输入长度边界；再确认可信模型输入计数及服务端输出限制。尚不建议启动六节点全图，也不能提供未经测量的总Token包络。
可考虑后续单独授权仅一次检索节点试验，最多1请求、最大输出384Token、不恢复/不重试；总Token额度必须等冻结证据片段后按可信input_upper+384确定，不能现在虚构数值。这不是本轮授权，不自动执行；如仅验证本地检索工具，可保持0模型请求。

四层结论：原始A结构证据有效；修复适配器仅离线能力；检索/执行/质量均未验收；资源感知规划因果收益无证据。

证据目录：{out}
'''
(out/'A_EXECUTION_FEASIBILITY_REPORT.md').write_text(report)
save('CODE_HASHES.json',{str(root/n):sha(root/n) for n in ['strict_meter.py','test_strict_meter.py','audit_a_feasibility.py','pilot_common.py','execute_v2.py','execute_dag.py']})
print(out)
