"""Offline corpus audit only; never dispatches a model or executes the DAG."""
import json,time,hashlib,shutil
from pathlib import Path
from kdx_execution_adapter import Corpus,KDXNodeAdapter,ROOT,sha
from strict_meter import StrictMeter
out=ROOT/('kdx_retrieval_budget_audit_'+str(time.time_ns()));out.mkdir()
def save(name,obj):(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
c=Corpus();original=ROOT/'v3_kdx_repair.json';before=sha(original.read_bytes());plan=json.loads(original.read_text())['arms'][0]['plan']
a=KDXNodeAdapter(c,plan,StrictMeter(out/'NOT_DISPATCHED.jsonl'))
save('CORPUS_CONFIG.json',{'task_id':c.task_id,'corpus_identity':c.identity,'documents':c.documents,'text_parser':'existing parsed text; PDF page mapping NOT_AVAILABLE','index_identity':sha(json.dumps(c.chunks,ensure_ascii=False,sort_keys=True).encode()),'source_integrity_scope':'full local PDF/text hashes; manifest PDF prefix checked; no remote revalidation'})
save('CHUNK_INDEX.json',c.chunks);save('A_ORIGINAL_PLAN.json',plan);save('A_ADAPTED_GRAPH.json',a.graph.to_dict())
# Query terms are declared goals/domain vocabulary, never silver or final answers.
queries={'t1':['康得新'],'t2':['问询','告知','处罚'],'t3':['立案','处罚','问询'],'t4':['虚增','存款','担保'],'t5':['处罚','披露'],'t6':['处罚','问询']}
rows=[]
for node in a.graph.nodes:
 try:
  fragments=c.search(queries[node.node_id],list(c.documents));status='LOCAL_RELEVANT_FRAGMENTS_LOCATED'
 except ValueError as e:fragments=[];status=str(e)
 rows.append({'node_id':node.node_id,'contract':node.output_contract,'dependencies':node.dependencies,'query_terms':queries[node.node_id],'retrieval':status,'fragments':fragments,'query_is_diagnostic_only':node.node_id!='t2','actual_inputs':'registered upstream outputs; local documents injected only at retrieval','necessary_fact_coverage':'NOT_PROVEN','execution':'NOT_EXECUTED','semantic_correctness':'NOT_TESTED'})
save('NODE_RETRIEVABILITY.json',rows)
paths=['v3_kdx_repair.json','model_call_ledger_v3kdxrepair.jsonl','model_call_ledger_v3kdxrepair_responses.jsonl','initial_dag_v3_kdx_A_repaired.json']
save('HISTORICAL_HASHES.json',{p:sha((ROOT/p).read_bytes()) for p in paths})
save('SOURCE_HASHES.json',{p:sha((ROOT/p).read_bytes()) for p in ['kdx_execution_adapter.py','test_kdx_execution_adapter.py','strict_meter.py','merge_contract_v2.py','audit_kdx_adapter.py']})
shutil.copy('/tmp/kdx_adapter_tests.log',out/'TESTS.log')
assert sha(original.read_bytes())==before
(out/'REPORT.md').write_text('''# 康得新A图检索与严格预算接线

结论：NO-GO for real execution。本轮0真实调用、0模型加载，未执行完整DAG、未读silver，未修改历史证据。

独立Corpus只读取A_kangdexin五份PDF与既有解析文本，核验manifest PDF哈希前缀并冻结完整PDF/文本哈希。347个重叠分段覆盖文本尾部；每段保存document_id、fragment_id、原文、字符起止、全文及片段哈希、文档日期和URL。位置基于已解析文本，不宣称PDF页码或解析准确性已经独立验证。语料身份进入节点请求，错误任务索引与未知文档明确拒绝。

A图6节点、原节点/边/合同保持；另存正确任务身份的适配图，不覆盖原图，不计为新的LLM生成。逐节点本地查询及定位见NODE_RETRIEVABILITY.json。相关片段能定位不等于必要事实已覆盖；除t2外查询仅作离线可检索性诊断，实际节点输入仍来自声明的上游结果。

KDXNodeAdapter为独立单节点拟用入口，复用原合同注册表、装配器及严格图验证器。prepare不派发；dispatch_node只能使用StrictMeter。抽取返回须含合法fragment_id、文档及来源哈希和原文子串证据，错误拒绝。输出端口和基础类型检查已接入。多来源合并复用merge_contract_v2，保留不同来源、日期和冲突标记，不自动裁决。

严格预算要求可信input_upper及依据，联合最大输出预留，先fsync后派发；未知usage保留全部占额，重启同请求不重发。缺乏可信输入Token计数与远程输出上限证据时不可启动。旧execute_v2及其他Meter入口仍可能绕过该保护；未修改它们，禁止用于本康得新验收。新入口拒绝旧Meter，但这不是全仓库安全隔离。

37项测试通过：新增适配器13项、StrictMeter9项、merge及既有相关15项。Mock仅执行单节点调用链，不执行完整DAG。未申请GPU/启动服务，因此本轮无资源待释放；临时文件由测试cleanup释放，锁生命周期复用StrictMeter上下文。真实服务清理与GPU资源生命周期尚未在此入口接线，不能把测试清理当作服务清理证据。

剩余硬阻塞：可信模型Tokenizer/请求输入上界与服务端输出限制；必要事实覆盖的预冻结检索需求；下游分析/报告逐事实引用血统及冲突消费验证；真实执行的统一墙钟与服务finally清理。现有JSON合同只证明端口类型，不能证明分析正确、报告无遗漏或结论有依据。不得以子串引用正确等同事实语义正确。

本轮不提出未经测量的全图预算。下一步优先0调用完善必要证据需求与下游血统约束。任何真实调用另行授权，精确输入界定后才能计算Token信封。
''')
print(out)
