"""Content audit extracts actual source passages; no model/silver access."""
import json,time,shutil
from kdx_execution_adapter import ROOT,Corpus,sha
c=Corpus();out=ROOT/('kdx_route_decision_'+str(time.time_ns()));out.mkdir()
# Explicit requirements from A goals; selections by source content, never reference answers.
def passage(doc,term,before=100,after=700):
 text=(ROOT/'v3_evidence/A_kangdexin/text'/f'{doc}.txt').read_text();i=text.find(term)
 if i<0:return None
 start=max(0,i-before);end=min(len(text),i+after)
 return {'document_id':doc,'start':start,'end':end,'original_text':text[start:end],'source_hash':c.documents[doc]['text_sha256'],'public_date':c.documents[doc]['public_date'],'chunk_ids':[x['fragment_id'] for x in c.chunks if x['document_id']==doc and x['start']<end and x['end']>start],'support':'document reports this statement; not independently adjudicated truth'}
rows=[
 {'nodes':['t1','t2'],'requirement':'五份文档身份版本','status':'COVERED','basis':'local full PDF/text hashes and manifest','documents':c.documents},
 {'nodes':['t2','t3'],'requirement':'2019年1月22日立案及2019年7月5日告知','status':'COVERED','applicable_time':'2019-01-22 / 2019-07-05','evidence':[passage('kdx_notice_2019','立案调查',250,160)]},
 {'nodes':['t2','t3'],'requirement':'2020年6月28日告知及9月27日收到决定','status':'COVERED','applicable_time':'2020-06-28 / 2020-09-27','evidence':[passage('kdx_notice_2020','2020 年 6 月 28'),passage('kdx_penalty_2020','2020 年 9 月 27')]},
 {'nodes':['t2','t4','t5'],'requirement':'2015–2018虚增利润分年度认定差异','status':'CONFLICT','applicable_time':'2015–2018; documents 2019 notice vs 2020 notice/decision','basis':'2019 notice amounts differ from 2020 notice/decision; retain procedural dates, no automatic reconciliation','evidence':[passage(d,'虚增利润') for d in ['kdx_notice_2019','kdx_notice_2020','kdx_penalty_2020']]},
 {'nodes':['t2','t4'],'requirement':'银行账户归集及2015–2018存款披露','status':'COVERED','applicable_time':'2015–2018 per decision','evidence':[passage('kdx_penalty_2020','银行存款')]},
 {'nodes':['t2','t4'],'requirement':'2016–2018关联担保与披露认定','status':'COVERED','applicable_time':'2016–2018','evidence':[passage('kdx_penalty_2020','关联担保')]},
 {'nodes':['t4','t5'],'requirement':'主体及处罚结果','status':'COVERED','applicable_time':'2020 decision','evidence':[passage('kdx_penalty_2020','罚款',100,750)]},
 {'nodes':['t4','t5'],'requirement':'市场禁入逐人员期限及法律地位','status':'UNKNOWN','basis':'receipt of market-ban decision confirmed; complete person/term list not audited','evidence':[passage('kdx_penalty_2020','市场禁入',0,600)]},
 {'nodes':['t2','t3','t5'],'requirement':'2018/2019年报问询逐问题与回复覆盖','status':'UNKNOWN','basis':'five-document index available; complete inquiry reconciliation not audited','evidence':[passage('kdx_inquiry_2019','问询函')]},
 {'nodes':['t5','t6'],'requirement':'全部公司披露与监管事实一致性及最终报告完整引用','status':'UNKNOWN','basis':'requires proposition-by-proposition review and actual node outputs; cannot infer from retrieved fragments','evidence':[]}
]
(out/'FACT_CONTENT_AUDIT.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
urls=['https://docs.bigmodel.cn/llms.txt','https://docs.bigmodel.cn/api-reference/模型-api/文本分词器']
(out/'REMOTE_CAPABILITY_AUDIT.json').write_text(json.dumps({'client_endpoint':'https://open.bigmodel.cn/api/anthropic/v1/messages','client_alias':'GLM-5.3','actual_server_build':'UNKNOWN: alias is not backend version','official_tokenizer_endpoint':'https://open.bigmodel.cn/api/paas/v4/tokenizer','tokenizer_documented_models_include':'glm-5.3','anthropic_complete_request_equivalence':'NOT_ESTABLISHED','local_tokenizer_identity':'NOT_ESTABLISHED','client_max_tokens':'present; remote enforcement/total budget guarantee not audited','cancel_and_after_disconnect':'UNKNOWN; current client no server cancel operation','client_timeout':'urllib socket timeout; not absolute server execution deadline','decision':'REMOTE_MODEL_RESOURCE_NO-GO','references':urls,'no_api_probe_performed':True},ensure_ascii=False,indent=2))
shutil.copy('/tmp/kdx_decision_tests.log',out/'TESTS.log')
(out/'HASHES.json').write_text(json.dumps({p:sha((ROOT/p).read_bytes()) for p in ['v3_kdx_repair.json','model_call_ledger_v3kdxrepair.jsonl','test_kdx_lineage_chain.py','audit_kdx_route_decision.py']},indent=2))
(out/'REPORT.md').write_text('''# 康得新路线收口决策

暂停当前远程GLM-5.3真实执行：REMOTE_MODEL_RESOURCE_NO-GO。只进行文档浏览、本地证据审计和Mock，无模型API请求。A图及历史4096/4000账本保持。

官方文档存在 /paas/v4/tokenizer，且枚举glm-5.3；此前不能据未发现接口断言不存在。当前是 /anthropic/v1/messages，公开计数接口与该请求包装/隐藏token一致性未证明。未获取可验证本地Tokenizer、服务实际构建版本、server input/output/total cap与可靠同步取消合同。Alias不是服务版本，响应usage不是派发前上界，urllib timeout不是服务端硬截止。断开后是否继续推理UNKNOWN，不能视为已停止。无需为相同缺证据继续加测试。

文档内容审计见FACT_CONTENT_AUDIT.json：已确认立案、告知、处罚收到时间，银行存款归集、担保及处罚相关段落；全部以文档记载为范围，保留引用和字符位置。2019/2020虚增利润认定存在数值差异，标CONFLICT并保留程序阶段，不能自动择一。市场禁入人员期限、全部问询逐问题及监管/披露比对完整性仍UNKNOWN。必要事实覆盖未达到整体验收门槛，未将关键词命中计为事实证明。

Mock证据链：检索片段→facts→多来源汇合→推理→报告，传播完整事实记录及冲突。新增5项测试验证四阶段保留与各阶段破坏拒绝；全部57项相关零调用测试通过。这是证据sidecar守卫闭环，未验证自由文本报告内容逐句支持、实际LLM输出符合sidecar，也没有完整执行A图。

方案A：已具独立语料、合同、预算journal、远程HTTP请求构造；缺完整请求计数等价、服务端硬限制与取消终止证明。最小动作是取得服务商合同/接口依据并重新冻结适配，不原样重试。现无法严格保证信封，非READY。

方案B：本地可控模型服务更适合硬限制验证；须重新冻结权重/Tokenizer/chat template/推理服务版本、实际请求计数、context/max_new_tokens与硬截止进程管理、独立预算、锁/清理。历史medium/large/coder身份和加载证据不能代替本轮检查；本轮未假定它们现在可用。不能视为原GLM-5.3实验。完成这些加事实覆盖后可考虑READY，当前非READY。

最小下一次真实验收：替代服务离线冻结通过后，仅一个真实抽取节点，五文档受限证据输入→有出处的结构化输出→确定性血统验证。不是全图、不评分、不搜索、不重试；请求数1，Token与墙钟必须按冻结Tokenizer/片段及加载清理实测重新计算，本轮不虚构额度或启动。若服务商仍无法提供等价计数及停止保证，原GLM路线的硬阻塞在现有可用证据下不可解决。

文档来源：[官方索引](https://docs.bigmodel.cn/llms.txt)、[官方Tokenizer](https://docs.bigmodel.cn/api-reference/模型-api/文本分词器)。不提交/推送。
''')
print(out)
