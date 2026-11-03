"""New input version; no model/HTTP/DAG execution."""
import json,time,hashlib,shutil
from pathlib import Path
from transformers import AutoTokenizer
from kdx_execution_adapter import Corpus,KDXNodeAdapter,ROOT,sha
from strict_meter import StrictMeter
from kdx_local_single import render_tokens
out=ROOT/('kdx_t2_final_prepare_'+str(time.time_ns()));out.mkdir();c=Corpus()
requirements=[('kdx_inquiry_2018','立案调查','2019调查/2018年报回复','UNKNOWN'),('kdx_inquiry_2019','问询函','2019年报问询回复逐问题','UNKNOWN'),('kdx_notice_2019','虚增利润','2015–2018认定/2019告知','CONFLICT'),('kdx_notice_2020','虚增利润','2015–2018认定/2020告知','CONFLICT'),('kdx_penalty_2020','虚增利润','2015–2018最终认定','CONFLICT'),('kdx_penalty_2020','银行存款','2015–2018存款认定','COVERED'),('kdx_penalty_2020','关联担保','2016–2018关联担保','COVERED'),('kdx_penalty_2020','罚款','2020处罚主体及金额','COVERED'),('kdx_notice_2019','立案调查','2019立案及告知时间','COVERED'),('kdx_penalty_2020','市场禁入','收到决定/逐人员禁入期限','UNKNOWN')]
selected={};audit=[]
for doc,term,period,status in requirements:
 text=(ROOT/'v3_evidence/A_kangdexin/text'/f'{doc}.txt').read_text();p=text.find(term)
 if p<0:status='MISSING';chunks=[]
 else:
  # Retain two windows where a paragraph crosses a boundary; no gold-dependent search.
  chunks=[x for x in c.chunks if x['document_id']==doc and x['start']<=p<x['end']]
  for x in chunks:selected[x['fragment_id']]=x
 audit.append({'requirement':term,'doc':doc,'applicable_time':period,'status':status,'term_position':p,'fragments':[x['fragment_id'] for x in chunks],'basis':'direct source passage; COVERED means this limited recorded claim, not full task completeness'})
plan=json.loads((ROOT/'v3_kdx_repair.json').read_text())['arms'][0]['plan'];a=KDXNodeAdapter(c,plan,StrictMeter(out/'NOT_DISPATCHED.jsonl'))
_,_,payload=a.prepare('t2',{'t1':{'evidence_index':list(c.documents.values())}},'调查康得新跨年度披露争议；区分告知与决定，保留冲突及存疑。',list(selected.values()))
system='Produce JSON with exactly the registered output ports; citations must point to supplied source fragments. Do not adjudicate contradictory sources.';user=json.dumps(payload,ensure_ascii=False,sort_keys=True)
model=Path('/root/autodl-tmp/models/Qwen2.5-7B-Instruct');t=AutoTokenizer.from_pretrained(str(model),local_files_only=True,trust_remote_code=False);ids=render_tokens(t,system,user)
def save(n,x):(out/n).write_text(json.dumps(x,ensure_ascii=False,indent=2))
command=['/root/autodl-tmp/r3_venv/bin/vllm','serve',str(model),'--tokenizer',str(model),'--served-model-name','Qwen/Qwen2.5-7B-Instruct','--host','127.0.0.1','--port','8127','--max-model-len','16384','--dtype','auto','--gpu-memory-utilization','0.85']
save('INPUT_V2.json',{'parent':'kdx_local_single_prepare_1791802962598929453','payload':payload,'system':system,'user':user,'prompt_ids':ids,'output_contract':'doc_retrieval.v1','acceptance':'all necessary propositions audited; every returned quote localized; no lost conflict/uncertainty','upstream':'manual metadata fixture, not t1 model output'})
save('COVERAGE.json',audit)
base=Path('/root/autodl-tmp/r3_venv/lib/python3.12/site-packages/vllm')
files=['entrypoints/openai/serving_engine.py','entrypoints/openai/serving_completion.py','entrypoints/openai/protocol.py']
save('SERVICE_CONFIG.json',{'command':command,'vllm':'0.11.0','transformers':'4.57.1','tokenizers':'0.22.0','source_hashes':{f:sha((base/f).read_bytes()) for f in files},'tokenizer_config_sha':sha((model/'tokenizer_config.json').read_bytes()),'chat_template_sha':sha(t.chat_template.encode()),'special_tokens':t.special_tokens_map,'input_rules':'integer prompt, no truncate_prompt_tokens; no chat endpoint/template reapplication','response_usage_rule':'len(prompt_token_ids) in serving_completion','live_identity':'NOT_TESTED'})
save('BUDGET.json',{'request_cap':1,'input_token_count':len(ids),'output_cap':768,'reserve':len(ids)+768,'context_cap_proposed':16384,'fits_context':len(ids)+768<=16384,'load_deadline_draft':180,'request_deadline_draft':60,'cleanup_draft':10,'wall_deadline_draft':250,'runtime_time_guarantee':'Mock only; actual GPU release deadline not proven'})
shutil.copy('/tmp/kdx_t2_final_tests.log',out/'TESTS.log')
(out/'REPORT.md').write_text(f'''# 康得新t2最终离线准备

SINGLE NODE REAL EXECUTION NO-GO。未加载模型、发HTTP或执行DAG。

新输入V2冻结{len(selected)}片段，保留旧5片段版本；节点/依赖/合同不变。COVERAGE.json区分10项有限命题：COVERED为段落明确记载，利润2019/2020认定差异CONFLICT，全问询和禁入逐人员完整性UNKNOWN。原文定位不是全文完备证明；必要覆盖仍未全部通过。

完整整数prompt {len(ids)} Token，输出768，预留{len(ids)+768}；配置拟定context16384。服务源码冻结vLLM0.11.0整数prompt保留路径及usage长度统计，没有服务端chat模板添加。本地Tokenizer/chat template/特殊token身份冻结。此为已安装代码静态证据；拟启动服务真实输入token数、模型身份仍待最小验证，不宣称已真实核验。

新增OwnedService：独占锁、自有Popen新session、单请求与全局watchdog、取消失败可终止自有进程组、wait与finally关闭资源、持久日志、防重复run目录。只有本实例Popen返回的进程可被终止。Mock覆盖8项。OS调度、GPU driver和进程异常阻塞不能通过Mock证明GPU在硬截止前释放；SIGKILL不是GPU释放确认。当前不具真实GPU释放检查，不宣布READY。服务启动健康/模型身份HTTP未来应在资源授权内验证。

此前StrictMeter联合预留、unknown完整保留、fsync、重启不重发测试保留。新服务管理器与单节点传输为组合模块；尚无完成前述必要覆盖门禁的统一可运行验收入口，不允许绕过后直接执行。

全部68项相关零调用测试通过；旧回归另外运行。历史4096账本保留。阻塞收口为：必要事实覆盖UNKNOWN、部署真实身份/计数验证、GPU最终释放及整体硬截止可证明性。最小后续验证如授权应先无推理服务身份/资源检查；随后最多一个整数prompt抽取请求，预算按本V2重新冻结，不沿用5729。当前不建议执行真实t2、不申请调用。\n''')
save('FILE_HASHES.json',{p.name:sha(p.read_bytes()) for p in out.iterdir() if p.is_file()})
print(out);print('INPUT',len(ids),'RESERVE',len(ids)+768)
