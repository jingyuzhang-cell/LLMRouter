"""No-call requirements inventory. Terms from original A goals, not gold."""
import json,time,shutil
from kdx_execution_adapter import ROOT,Corpus,sha
out=ROOT/('kdx_final_gate_'+str(time.time_ns()));out.mkdir();c=Corpus()
requirements={
 't1':[('五文档身份、版本及公开时间',['康得新'])],
 't2':[('问询与回复',['问询']),('告知书监管认定',['告知']),('处罚决定及适用事项',['处罚'])],
 't3':[('2018–2020问询/立案/处罚事件及日期',['问询','立案','处罚'])],
 't4':[('主体身份',['当事人','钟玉','康得集团']),('虚增利润',['虚增']),('存款',['存款']),('担保',['担保'])],
 't5':[('监管认定与披露逐项一致性及冲突',['披露','认定','处罚'])],
 't6':[('带引用报告及存疑事项',['处罚','问询'])]}
rows=[]
for node,reqs in requirements.items():
 for description,terms in reqs:
  hits=[x for x in c.chunks if any(t in x['text'] for t in terms)]
  rows.append({'node':node,'necessary_requirement':description,'requirement_basis':'original A semantic goal; no gold read','document_scope':list(c.documents),'document_public_dates':{d:v['public_date'] for d,v in c.documents.items()},'event_time_scope':'2018–2020 per A plan; passage-level applicable time UNRESOLVED','state':'UNCERTAIN' if hits else 'MISSING','candidate_count':len(hits),'locations':[{'document_id':h['document_id'],'chunk_id':h['fragment_id'],'start':h['start'],'end':h['end'],'source_hash':h['source_hash'],'text':h['text']} for h in hits[:5]],'judgment':'keyword location only; exact proposition, completeness and contradictions require source audit','semantic_coverage_confirmed':False})
(out/'SIX_NODE_REQUIREMENTS.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(out/'HASHES.json').write_text(json.dumps({p:sha((ROOT/p).read_bytes()) for p in ['v3_kdx_repair.json','model_call_ledger_v3kdxrepair.jsonl','kdx_admission.py','test_kdx_admission.py','kdx_execution_adapter.py']},indent=2))
shutil.copy('/tmp/kdx_final_tests.log',out/'TESTS.log')
(out/'REPORT.md').write_text('''# 康得新A图最终离线准入

NO-GO。0真实调用、0模型加载、未完整执行A图，原节点/依赖/合同保持不变。未读取Gold/silver。

六节点必要证据要求见SIX_NODE_REQUIREMENTS.json：要求由原计划目标导出，记录五文档范围、公开时间、片段及字符位置。逐项仅有关键词定位证据，不能证明完整事实或适用时间，因此标UNCERTAIN而非COVERED；未虚构抽取结果。t5的跨文档核查、t6报告覆盖只有实际输出才能验证。

kdx_admission.Lineage要求稳定事实ID、内容、适用时间和全部出处；原文引用/位置/版本哈希匹配。consume逐项比较完整记录，必要事实缺失、来源断裂或冲突/不确定字段丢失拒绝。不自动判定事实语义支持，不自动裁决冲突。此为新增可选门禁，不改变A图合同；历史JSON输出并不会自动拥有这些证据。

FinalNodeGate禁止旧入口，准备完整HTTP请求体后交部署对应TokenBoundary计数，再通过原KDXNodeAdapter/StrictMeter预留与派发。当前真实HTTP路径为远程GLM-5.3，未获得可信配套Tokenizer、服务端包装计数及最大输出限制证明。TokenBoundary没有这些依据即拒绝。Mock counter仅验证接口，不能提供真实Token上下界证明。直接调用旧Meter或KDXNodeAdapter底层仍可绕过该可选门禁，真实验收只能使用FinalNodeGate；尚无全仓库防绕过保证。

Lifecycle提供独占锁、原子运行目录防重复、加载/请求/清理时间准入、身份hook、异常cancel/stop/finally与主错误隔离。Mock正常、超时、占锁、重复启动、清理失败通过。真实start/cancel/stop hook未实现受控进程及硬截止机制；阻塞hook可能越墙钟，现仅记录而不能保证硬限额。不能宣称真实服务生命周期接线完整。未启动服务，无自有GPU资源需要释放。

50项零调用测试通过：新增13项门禁、既有13项适配、9项StrictMeter及15项相关回归。历史4096/4000超额账本未改。未把Mock单节点测试当作全图执行。

剩余硬阻塞：可信部署Token计数及输出上限；逐必要事实的人工/独立来源内容核验与适用时间；实际节点输出血统接入及最后文本报告的引用守卫；真实服务进程加载、取消、关闭硬截止与最终锁释放验证。不得启动真实执行，无精确真实资源信封可提交。下一步保持零调用完成这些接口，不重新生成A图。
''')
print(out)
