"""Offline snapshot/tokenizer only; no weights loaded for inference or HTTP."""
import json,time,hashlib,shutil
from pathlib import Path
from transformers import AutoTokenizer
from kdx_execution_adapter import ROOT,Corpus,KDXNodeAdapter,sha
from strict_meter import StrictMeter
from kdx_local_single import render_tokens
out=ROOT/('kdx_local_single_prepare_'+str(time.time_ns()));out.mkdir()
pool=json.loads(Path('/root/r3_own_pool/collab_scheduler_v1/typed_dag_v1/stage42_execution_ready_v1/MODEL_POOL_OFFLINE.json').read_text())['medium'];model=Path(pool['path'])
def filehash(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
checked={f:filehash(model/f) for f in list(pool['config_sha256'])+list(pool['weight_sha256'])}
for key,expected in {**pool['config_sha256'],**pool['weight_sha256']}.items():
 if checked[key]!=expected:raise ValueError('MODEL_FILE_HASH:'+key)
tokenizer=AutoTokenizer.from_pretrained(str(model),local_files_only=True,trust_remote_code=False)
c=Corpus();plan=json.loads((ROOT/'v3_kdx_repair.json').read_text())['arms'][0]['plan']
a=KDXNodeAdapter(c,plan,StrictMeter(out/'NOT_DISPATCHED.jsonl'))
fragments=c.search(['问询','处罚','告知'],list(c.documents))
# Frozen single-node fixture: upstream index is independently compiled metadata, not t1 LLM output.
up={'t1':{'evidence_index':list(c.documents.values())}}
question='调查康得新2018–2019年年报问询及立案、处罚过程，保留监管认定与披露差异、原文出处和存疑。'
node,inputs,payload=a.prepare('t2',up,question,fragments)
system='Produce JSON with exactly the registered output ports; citations must point to supplied source fragments. Do not adjudicate contradictory sources.'
user=json.dumps(payload,ensure_ascii=False,sort_keys=True);ids=render_tokens(tokenizer,system,user)
request={'model':'Qwen/Qwen2.5-7B-Instruct','prompt':ids,'max_tokens':768,'temperature':0,'stream':False}
def save(n,x):(out/n).write_text(json.dumps(x,ensure_ascii=False,indent=2))
save('MODEL_IDENTITY.json',{'path':str(model),'served_model':request['model'],'hashes':checked,'scope':'full declared weight shards plus declared config and tokenizer files; undeclared files not attested','tokenizer_class':type(tokenizer).__name__,'chat_template_sha256':sha(tokenizer.chat_template.encode()),'runtime':'transformers 4.57.1','service_runtime_this_round':'NOT_LOADED'})
save('NODE_INPUT.json',{'node_id':'t2','contract':node.output_contract,'upstream_fixture':'manual metadata index; not full DAG execution or t1 success','payload':payload,'system':system,'user':user})
save('HTTP_REQUEST.json',request)
save('BUDGET.json',{'requests':1,'input_tokens_exact_local_render':len(ids),'output_max':768,'token_reserve':len(ids)+768,'service_context_cap_proposed':8192,'count_proof':'integer prompt length; conditional on vLLM not injecting tokens/truncating input','load_timeout_proposed':180,'request_timeout_proposed':60,'cleanup_timeout_proposed':30,'wallclock_proposed':270,'time_evidence':'enforceable draft deadlines only; not measured loading or termination in this round','admission':'NO-GO'})
save('FACT_SCOPE.json',{'necessary_inputs':list(c.documents),'source_dates':{d:v['public_date'] for d,v in c.documents.items()},'fragments':fragments,'requirements':'each emitted claim must cite supplied literal fragment, retain date, identity and uncertainty; do not claim full five-document fact coverage','full_node_goal_coverage':'UNKNOWN: one selected chunk/document insufficient to establish all required inquiry/penalty facts','output':'doc_extracts JSON list, full port contract unchanged','acceptance':'every emitted quote valid plus separately audited necessary facts coverage; current latter not met'})
save('HISTORICAL_HASHES.json',{f:sha((ROOT/f).read_bytes()) for f in ['v3_kdx_repair.json','model_call_ledger_v3kdxrepair.jsonl']})
(out/'REPORT.md').write_text(f'''# 本地Qwen单节点准备

NO-GO / SINGLE NODE REAL EXECUTION NOT READY。0真实请求、0模型加载。

复用Qwen2.5-7B-Instruct；重新读取并校验全部4个权重分片及既有快照声明配置/Tokenizer文件完整SHA。Tokenizer离线加载Qwen2TokenizerFast，transformers4.57.1。身份见MODEL_IDENTITY.json；不把历史服务版本当成本轮实际服务版本。

选择原A图t2抽取节点，结构、依赖、合同不变。冻结输入含独立人工元数据index及五文档检索片段；人工index仅单节点fixture，不冒充t1执行。五片段不足以证明完整抽取目标覆盖，不能为通过门禁缩减原节点任务。所有片段位置/日期/哈希保留。

kdx_local_single.attach_local_transport必须StrictMeter，仅localhost、指定本地alias；完整system/user经同一Tokenizer chat template渲染，发送整数prompt IDs到/v1/completions，避免服务端chat包装差异。输入测量{len(ids)}Token，最大输出768，预留{len(ids)+768}Token。模型字段验证、context cap、原strict fsync预留/unknown/去重路径复用。当前独立adapter可用，但没有CLI真实启动器，禁止直接切换旧远程alias。

预算证明仅在整数prompt服务按冻结配置执行的前提下成立：服务端实际参数、Tokenizer/权重身份和prompt_tokens一致性尚须授权后检查。输出超界原StrictMeter记录并锁止，但不能撤销消耗。没有以估计值充当真实硬边界。

生命周期复用此前Mock锁/取消/清理门禁，没有新增实际启动/硬终止实现。加载180秒、请求60秒、清理30秒合计270秒仅建议可执行deadline草案，不是本轮实测加载耗时或已证明的释放界限；不能据此READY。

剩余：t2必要事实覆盖内容审定；冻结服务二进制/启动参数及整数prompt完整计量语义；自有进程组硬截止与GPU清理实现。未启动模型、HTTP或整个DAG，未修改A图、历史超额或评分，未提交推送。暂不申请真实预算；上述条件离线通过后才能提交1请求/{len(ids)+768}Token及经证明墙钟的新独立信封。
''')
print(out);print('INPUT',len(ids),'TOTAL',len(ids)+768)
