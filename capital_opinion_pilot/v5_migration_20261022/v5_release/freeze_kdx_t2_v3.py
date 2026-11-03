"""Offline-only versioned input and separately scoped preflight plan."""
import json,time,copy,shutil
from pathlib import Path
from transformers import AutoTokenizer
from kdx_execution_adapter import ROOT,Corpus,sha
from kdx_local_single import render_tokens
out=ROOT/('kdx_t2_input_v3_'+str(time.time_ns()));out.mkdir()
parent=ROOT/'kdx_t2_final_prepare_1791803256988715710';follow=ROOT/'kdx_t2_content_followup_1791803516599627047'
old=json.loads((parent/'INPUT_V2.json').read_text());audit=json.loads((parent/'COVERAGE.json').read_text());extra=json.loads((follow/'CONTENT_UPDATE.json').read_text());c=Corpus()
byid={x['fragment_id']:x for x in c.chunks};selected={x['fragment_id']:x for x in old['payload']['evidence_fragments']}
for row in extra:
 for ident in row['chunks']:selected[ident]=byid[ident]
new=copy.deepcopy(old);new['payload']['evidence_fragments']=list(selected.values());new['user']=json.dumps(new['payload'],ensure_ascii=False,sort_keys=True)
model='/root/autodl-tmp/models/Qwen2.5-7B-Instruct';tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False);ids=render_tokens(tokenizer,new['system'],new['user']);new['prompt_ids']=ids
new['version']='kdx.t2.input.v3';new['parent_input_sha256']=sha((parent/'INPUT_V2.json').read_bytes());new['graph_unchanged']=True
# Scope is original goal, not timeline synthesis, reconciliation or final report (t3/t5/t6).
for row in audit:
 row['fact_name']=row['requirement'];row['document_sha256']=c.documents[row['doc']]['text_sha256']
 row['original_passages']=[{'chunk_id':i,'start':byid[i]['start'],'end':byid[i]['end'],'text':byid[i]['text']} for i in row['fragments']]
 if row['requirement']=='市场禁入':row['status']='COVERED';row['qualification']='person/term source passage added; no independent truth adjudication'
coverage={'original_t2_goal':'提取问询回复、告知书、处罚决定书关键事实','output_contract':'doc_retrieval.v1: question+evidence_index -> doc_extracts JSON','necessary_claims':audit,'added_claims':extra,'conflict_handling':'2019/2020 profit differences must remain source/time labelled; no automatic reconciliation','input_admission':'UNKNOWN','reason':'inquiry reply source-response substance still incomplete in selected windows; receipt-date paragraphs alone do not cover company replies; future output must keep evidence/time/conflict','not_required_here':['full timeline synthesis','all inquiry questions reproduced','conflict adjudication','final report']}
preflight={'status':'PLAN_READY / REAL_START_NOT_AUTHORIZED','no_inference_stage':{'model_requests':0,'inference_tokens':0,'checks':['exclusive lock and no duplicate run','frozen weight/tokenizer/command hashes','spawn own process session','GET health/models/config evidence where version supports','installed vLLM source/actual startup command identity','stop own process group and verify all owned GPU PIDs gone','nonblocking same-inode lock reacquisition after cleanup'],'wall_cap_proposal_seconds':300,'phase_deadlines_seconds':{'loading_and_identity':240,'termination_wait':5,'gpu_verification':30,'margin':25},'evidence':'enforced limits proposed; no actual load-time bound measured','http_metadata_requests':'not model inference; nevertheless separately authorized; not performed here'},'optional_inference_meter_stage':{'model_requests':1,'input':'frozen token IDs for user: Reply OK; system: Return one word','output_max':8,'automatic_retry':False,'purpose':'compare prompt_tokens to exact submitted ID count; not t2 execution','wall_cap_proposal_seconds':360,'request_timeout_seconds':30,'separate_authorization_required':True},'on_cleanup_failure':'QUARANTINE: no further dispatch, retain resource lock until confirmed clean; write failed GPU/PID state; do not remove lock file or terminate other sessions','implementation_gap':'current OwnedService closes flock even when cleanup fails and verifies no GPU PID state; do not use unchanged manager for authorized real start; watchdog client also cannot guarantee service process kill under OS/driver stall'}
small=render_tokens(tokenizer,'Return one word.','Reply OK.');preflight['optional_inference_meter_stage']['input_ids']=small;preflight['optional_inference_meter_stage']['input_tokens']=len(small);preflight['optional_inference_meter_stage']['joint_token_reserve']=len(small)+8
budget={'t2_input_tokens':len(ids),'max_output_tokens':768,'joint_reserve':len(ids)+768,'context_limit':16384,'context_remaining_after_reserved_output':16384-len(ids)-768,'bound_scope':'exact local rendered integer IDs; live server equality remains to be verified','t2_wall_budget':'NOT_APPROVED_OR_PROVEN'}
def save(n,x):(out/n).write_text(json.dumps(x,ensure_ascii=False,indent=2))
save('INPUT_V3.json',new);save('NECESSARY_FACTS.json',coverage);save('TOKEN_BUDGET.json',budget);save('PREFLIGHT_PLAN.json',preflight);shutil.copy(parent/'SERVICE_CONFIG.json',out/'SERVICE_CONFIG.json')
(out/'REPORT.md').write_text(f'''# 康得新t2输入V3与服务预检准备

SINGLE NODE REAL EXECUTION NO-GO；预检方案已冻结，不代表真实服务启动器READY。本轮只加载Tokenizer，未启动模型或发送HTTP。

输入V3纳入问询日期和禁入期限原文，{len(selected)}个片段。V1/V2原件保持，V3哈希见FREEZE_HASHES.json。必要事实表保留利润跨来源CONFLICT；问询回复关键实质仍UNKNOWN。收到问询函的日期不是公司回复内容，不能靠日期片段宣布覆盖通过。t2不需要完成其他节点的时间线合成/最终报告。输出768Token只作为硬限额，不能保证能完整输出全部必要事实。

完整消息{len(ids)}输入Token，输出768，联合预留{len(ids)+768}，16384上下文余量{16384-len(ids)-768}。整数Token ID依据已安装vLLM静态路径；实际服务一致性由独立预检验证。旧9232不沿用。

无推理预检建议：0模型请求/0推理Token，300秒，核验文件、实际启动身份、健康、锁及GPU生命周期；健康/models GET也需独立服务预检授权，本轮未做。若另批一次计量检查，建议总360秒、1请求、{len(small)+8}Token占额（输入{len(small)}、输出8），固定短输入，不执行t2；不能从预检预算挪作抽取。

Mock已验证watchdog/自有process group终止/锁/异常退出，真实driver释放待确认。当前服务管理器发现真实硬缺口：cleanup失败仍释放锁，且无GPU所有权进程退出核验。计划要求QUARANTINE保留锁/no further dispatch、5秒child wait+30秒GPU核验；这些是时间上限而非GPU必然释放保证。真实启动前必须落实隔离分支和GPU退出验证，不能在NO-GO下直接运行现有manager。

取消或socket超时后服务可能继续处理，须终止仅本实例新session进程组；不得触及其他会话。若期限内GPU无法释放，安全停止并保留隔离状态，不宣称成功清理。此机器驱动异常不能被Mock排除。

结论：冻结输入和预检协议齐备，但真实预检入口仍有上述资源隔离硬阻塞；t2还有回复实质覆盖与输出容量验证。等待后续明确授权和最小隔离修复，不自动执行。原A图、历史4096/4000及评分保持，未Git提交推送。
''')
save('FREEZE_HASHES.json',{p.name:sha(p.read_bytes()) for p in out.iterdir() if p.is_file()});print(out);print(budget);print('PREFLIGHT_METER_RESERVE',len(small)+8)
