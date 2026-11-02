import json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent
OLD=Path('/root/research_outputs/RONBAY_DYNAMIC_PI_20261102')
B=Path('/root/research_outputs/THREE_TASK_FEASIBILITY_20261101')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):
 with (P/n).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2)
files=[OLD/n for n in ['CONFIG.json','AUTHORIZATION.json','FREEZE.json','run.py','transport.py','RESULTS.json','CLOSED.json']]+[B/'DAG_RONBAY_202601.json',B/'NODE_CONTRACT.json',B/'REFERENCE_ANSWERS.json']
before={str(p):sha(p) for p in files}
config=json.loads((OLD/'CONFIG.json').read_text());result=json.loads((OLD/'RESULTS.json').read_text());dag=json.loads((B/'DAG_RONBAY_202601.json').read_text())
req=[]
for f in sorted((OLD/'requests').glob('*/REQUEST.json')):
 a=json.loads((f.parent/'ACCOUNTING.json').read_text());r=json.loads(f.read_text());v=json.loads((f.parent/'VALIDATION.json').read_text())
 req.append({'id':f.parent.name,'requested_model':r['model'],'reported_model':a['reported_model'],'K':v['K'],'Q':None,'E_semantic':None,'task':'JCZ_202605','request_sha256':sha(f),'response_sha256':sha(f.parent/'RESPONSE.bin'),'wall_s':a['wall_s'],'usage':a['usage']})
models=['GLM-5.3-Flash','deepseek-flash','qwen-plus-2025-12-01']
roles={'INQUIRY':'接收/公告日期、监管问题与最终认定区分','REPLY':'估算、预测量、附条件最低采购、商务条款及风险','OBLIGATIONS':'条件承诺和未披露量，禁止把预测改写为保证','CROSSCHECK':'跨文档逐问覆盖、来源归属、冲突与未回答事项','FINAL':'六问事实、条件、未知和逐项支持证据'}
matrix=[]
for n in dag['nodes']:
 for m in (models if n['executor_kind']=='LLM' else [None]):
  matrix.append({'task':'RONBAY_202601','node':n['id'],'model':m,'parents':n['parents'],'role':roles.get(n['id'],'确定性单位/期间比较，不调用模型'),'current_matched_observations':0,'Q':None,'E_semantic':None,'K_rate':None,'latency':None,'token_cost':None,'actual_bill':None,'reliability':None,'profile_status':'UNKNOWN' if m else 'NOT_APPLICABLE_MODEL','planned_repeats':3 if m else 0,'input_requirements':'Same frozen source bytes, schema, fixed parent fixture and fingerprint across three models; fixtures are source-reviewed development inputs, not real parent responses','scoring':'Frozen scorer unchanged. Separate K, factual matches, semantic evidence support, unknown and coverage. No independent Gold.'})
plan={'status':'DESIGN_COMPLETE_EXECUTION_HOLD','paid_authorized':False,'previous_budget_transferred':False,'models':models,'measurement_calls_max':45,'measurement_design':'5 actual Rongbay LLM contracts x 3 models x 3 repeats. This exposes Rongbay for allocation development. Same-node fixtures identical across models and repeats; provenance-certified parent fixtures pending. Not independent confirmatory calibration.','pair_repeats':3,'independent_events':1,'common_prefix_calls_max':6,'continuation_calls_max':18,'total_calls_max':69,'per_model_calls_max':39,'input_reserve_per_request':65536,'output_cap_per_request':3072,'input_total_reserve':69*65536,'output_total_cap':69*3072,'input_certified_hard_bound':False,'USD_to_CNY_planning_factor':8,'cash_threshold_approved':None,'cash_threshold_proposed':None,'bill_cap_certified':False,'qwen_rate_CNY_per_M':{'input':.8,'output':2},'deepseek_peak_rate_USD_per_M':{'input':.3,'output':1.2},'glm_rate':None,'per_call_reserve_CNY':{'qwen':.0585728,'deepseek_at_8':.1867776,'glm':'g=(65536*p_input_CNY_per_M+3072*p_output_CNY_per_M)/1000000'},'batch_estimate_formula_CNY':'15*(g+0.0585728+0.1867776)+24*max(g,0.0585728,0.1867776)','estimate_is_not_worst_bill':True,'K_m':1,'global_concurrency':1,'request_timeout_s':180,'per_arm_deadline_s':240,'batch_wall_s':14400,'Z':'FIXED','R':'NO_RETRIES; invalid parent blocks descendants equally','planning':'Before evaluation: choose supported-fact coverage then latency then public cost with missing Q explicitly unknown; use only completed measurement-set reviews. No fallback selected from evaluation. Unknown infeasibility is reported as refusal. Resolve ties by predeclared model name order; Qwen a measured candidate, not automatic fallback.','feedback':'Natural source/contract failure blocks descendants; no artificial F2/F3. After healthy common prefix, observed model per-node latency ratio >1.5 against same-contract calibration median triggers reselection of all pending nodes. Apply max observed ratio only to that observed model; no unobserved quality updates. Same quality eligibility and budget/deadline rules; no private reference at runtime.','arm_order':['Static-Dynamic','Dynamic-Static','Static-Dynamic'],'main_outcome':'Frozen terminal Q only if admissible references/relevance assessment available. Otherwise prespecified six-item source-constrained exploratory Q/E with coverage and UNKNOWN intervals, not full Q or Gold.','stats':'3 paired repeats, one exposed event. Report all pair differences and ranges. No population superiority, no six facts treated as independent tasks, no cross-event p-value; optional exact paired sign/randomization calculation explicitly low powered and conditional on randomized order, not with fixed order here.','no_switch':'Retain pair in denominator; report no action divergence, not causal reassignment benefit','termination':'One authorized batch only; no retries/extra samples. API or usage/accounting anomaly, aggregate reserved spend limit, batch deadline -> stop. Normal model failure -> retain costs and block dependent nodes, continue independent cells. Invalid measurement fixtures or unresolved semantic scoring -> do not dispatch.','unresolved':['GLM exact provider/account-specific API model identity and tariff not certified','Same-input parent fixtures for 5 actual Rongbay roles not frozen','Quality/evidence independent review absent; Silver diagnostic evaluator must be executable and fixed before payment','Existing runner does not support GLM and cannot be reused as-is; no patches applied in this audit','Joined request envelope exceeds cap in old run; future batch must bound complete parent+source payload without discarding evidence','New complete cash quote and authorization absent']}
audit={'expected_pool_basis':'Current user states prior frozen pool GLM + DeepSeek, Qwen reserve; treated as research requirement. No matching original three-model freeze artifact located within inspected local report/config scope.','disk_frozen_pool':[m['request_model'] for m in config['models']],'runtime_matches_disk_freeze':True,'research_protocol_matches_user_required_pool':False,'GLM_omitted_at':['MODELS list','CONFIG.models','guard.models','transport whitelist','credential routing'],'GLM_disabled_by_historical_error':False,'finding_limit':'No historical-failure read/health blacklist exists in this runner; psychological motivation cannot be inferred from code. Historical successful GLM record refutes blanket permanent-unavailability claim, not certifies current access.','Qwen_priority':'First calibration loop model; default pick fallback when all K fail. It was not chosen using measured superiority.','priority_change_approval_record_found':False,'authorization_record_scope':'Generated AUTHORIZATION.json confirms budget/run permission only; does not establish approval to replace GLM. It is assistant-generated, not a separate user model-list approval.','dispatches':req,'initial_allocation_reached':False,'paired_calls':0,'observations_not_current_task_profiles':True}
write('AUDIT_AND_PLAN.json',{'audit':audit,'measurement_matrix':matrix,'next_batch':plan,'input_hashes':before})
text='''# 模型池协议偏差审计与容百三模型测量方案

结论：**模型池存在实质偏差；当前容百三模型画像为 UNKNOWN，下一批真实执行 HOLD。** 本轮只读原始资产、零模型调用；报告和配置写入独立新目录，不修改旧批次或 ZCode。

## 1. 模型池审计

| 检查 | 原始证据 | 裁决 |
|---|---|---|
| 研究要求 | 用户明确 GLM-5.3-Flash、DeepSeek-Flash 主候选，Qwen-Plus 原备选 | 作为本次审计协议基准；已查目录未找到匹配的原始三模型冻结文件，不能伪称核实其历史哈希 |
| 磁盘冻结配置 | 旧 CONFIG.json models 只有 Qwen、DeepSeek；DAG 候选列表也只有两者 | 研究意图与落盘配置偏离；不是运行中篡改冻结配置 |
| 运行配置 | run.py:11 MODELS 两元素；预算 guard.models 同样两者 | GLM 在创建批次时已被排除 |
| Provider 映射 | Qwen -> dashscope compatible-mode/chat/completions；DeepSeek -> api.deepseek.com/chat/completions | 五次 request_model 与返回 model 一致；DeepSeek 别名底层版本仍未知 |
| GLM 适配 | transport.py:43 其他模型 UNBOUND_MODEL；凭证只路由 Qwen/DeepSeek | 即使只往配置添加 GLM，也不能执行；本轮不打补丁 |
| 模型优先级 | run.py:128 按 MODELS 顺序校准；124 无合格 K 时回退 MODELS[0] | Qwen 既被提升为常规测量模型，又被置为默认回退；无性能论证 |
| 授权记录 | AUTHORIZATION.json 仅记 ¥10 风险/请求授权，没有三模型变更批准记录 | 未发现明确授权将 Qwen 取代 GLM；自动生成授权文件不能代替用户模型池变更许可 |
| 历史 GLM 异常 | 当前执行代码不读取历史故障、不含健康黑名单 | 无证据显示本轮因历史故障禁用 GLM；上一答复把此作为可能原因不能当成事实 |
| 历史可用性 | static_pi/stage_b/runs/run3/E_S1.json：GLM-5.3-Flash，end_turn，error=null，usage 545/377，4.93秒 | 证明一次历史成功，不证明当前端点可用，不是容百质量画像 |

GLM 历史端点是 `https://open.bigmodel.cn/api/anthropic/v1/messages`，与这次两个 OpenAI 兼容端点协议不同。历史记录中的大写 `GLM-5.3-Flash`、其他画像 `glm-5.3`、第三方小写别名不能默认视为同一型号/同价。需确认实际账户接口和版本，但本轮不发探测请求、不读取或展示密钥。

### 五次派发依据

| 顺序 | 请求 | 依据 | K |
|---|---|---|---|
| 1 | Qwen INQUIRY | 第一个硬编码校准模型的无依赖节点 | PASS |
| 2 | Qwen REPLY | 同一模型另一无依赖节点 | FAIL：缺 unknown_reason |
| 3 | DeepSeek INQUIRY | 校准循环第二模型，无性能择优 | PASS |
| 4 | DeepSeek REPLY | 无依赖节点 | PASS |
| 5 | DeepSeek OBLIGATIONS | REPLY K 通过后按 DAG 执行 | PASS |

Qwen 后继被阻断；DeepSeek CROSSCHECK 在派发前报文超限。没有 INITIAL_ALLOCATION.json，没有容百请求，选模函数及动态重分配尚未产生评测行为。五次不是 GLM 失败后的 fallback，也不是优化器选择 Qwen 的证据。校准模型顺序固定，还不能排除时间/服务负载混杂。

## 2. 容百节点能力测量矩阵

| 节点 | 实际任务与输入 | 测量重点 | GLM / DeepSeek / Qwen 当前画像 |
|---|---|---|---|
| INQUIRY | 问询原文 | 收到日/公告日、监管提问与认定区别 | 全部 UNKNOWN |
| REPLY | 回复原文 | 1200亿估算、305万吨预测、附条件最低采购、未来条款与风险 | 全部 UNKNOWN |
| OBLIGATIONS | 固定 REPLY 父记录及原文 | 条件保留、最低量未知、未来商务条件不外推 | 全部 UNKNOWN |
| CROSSCHECK | 固定四个父节点输出及双来源 | 问题/回复对应、遗漏、冲突、证据链 | 全部 UNKNOWN |
| FINAL | 固定 CROSSCHECK 与双来源 | 六问完整性、条件语义、逐事实支持 | 全部 UNKNOWN |
| CAPACITY | 固定 REPLY | 确定性单位与期间核算，不测 LLM、不制造模型差异 | 不适用 |

共15个模型—节点单元，每单元3次，最多45次。节点隔离测量采用来源核查过的**相同父输入夹具**，明确不是模型真实上游输出；避免各模型消费自己不同父输出导致“同节点比较”不公平。夹具尚未构建/冻结，本轮没有冒称已完成。按节点、重复轮次轮换三个模型顺序，保留全部失败；温度、输出上限、资料范围、提示及 schema 一致，不启用联网或额外工具。

这45次是在容百开发任务上测量并选择分配，不能把随后的同事件配对称为独立测试。配对使用新响应和自然执行父输出，不复用测量响应为测试样本；这隔离的是响应，不消除任务曝光。金橙子5次观测只作旁证，不能填入任何容百单元。

每单元分别保存：
- HTTP/传输状态、K、引用定位、语义 E、事实 Q、完整性与 UNKNOWN，不能互相替代。
- 原始 usage、缓存和思考 Token、公开估费与实际账单状态；未结算为 UNKNOWN。
- 从派发到完成的实际时延；失败/超时不是成功时延，不删除。
- 合同/执行成功的分子分母、3次离散性；3/3不等于0.95可靠性保证，重复不是独立事件。

评分沿用冻结语义及评分器，不将匹配引用当成语义支持。6项参考仍是非独立 Silver。正式 Q 不能计算时保持 null；探索指标报告已审阅正确、错误、PENDING及分母/覆盖率。若六项中c项确认正确、u项不可判，报告覆盖率和区间[c/6,(c+u)/6]，而不是把u记零后宣称完整Q。任何新增诊断实现须在响应前冻结，不改变原评分器/旧成绩。

## 3. Dynamic-π 当前真实决策空间

当前只有模型身份差异，没有容百合同匹配的多模型 Q/C/L 测量。五个LLM节点均有三个名义候选，但“多个合理候选”“质量交叉”“不值得切换”现在都不能判定。OBLIGATIONS/CROSSCHECK/FINAL是前缀后可改派的节点；已完成 INQUIRY/REPLY 不重复执行。CAPACITY无模型切换动作。

值得检验的假设是条件语义/跨来源合并节点存在可用能力差异，而不是预设GLM更强或DeepSeek更快。仅有最快模型排名不变、未观察到自然反馈、或切换开销超过节省时，动态收益可为零或负。校准K失败不能生成虚构Q；语义支持未知不得冒充满足质量约束。

## 4. 下一批 Static / Dynamic-π 计划（尚未授权）

- 单个曝光开发事件，3组配对；Z固定，R固定为不重试。两臂完全相同初始分配、证据、前缀快照、资源、剩余时间和预算。
- 三模型均测量；是否由Qwen作为可分配候选须在新配置明确，本方案建议三者等权候选，取消暗设备选/自动替换。GLM不可用时记录不可用，不能偷偷换为Qwen。
- 测量集的语义复核完成后，按已支持事实覆盖、时延、成本的固定字典序选择共同初始分配；同覆盖不代表可靠性保证。缺Q不补值、不可评估则拒绝相关质量约束。
- 自然前缀反馈仅当观察时延/同节点校准中位数>1.5时，按观测比值更新该模型剩余时延预测；用相同质量资格、预算及截止规则重选全部未执行节点。无反馈不强制切换。没有可验证语义守卫时不使用私有Silver答案触发“质量故障”。
- 拒绝、非法父输出和失败保留；非法输出阻断依赖。自然合同失败可能让两臂都无法完成，这是结果；不人为故障、不通过放宽证据规则救活分支。
- 每模型槽位1、全局并发1，本批只研究π，不主张并行调度优势。单请求180秒、每臂含共同前缀240秒、整批14400秒。相同配置仍执行各自新响应，不当作新独立事件。
- 三对执行顺序固定 A/B、B/A、A/B；公开其顺序不平衡限制。不将固定顺序写成随机对照。
- 主要终点为配对终端事实/证据质量差异；正式Q缺失则只能降为预声明Silver探索，报告覆盖及区间。次要终点为含规划/队列/失败的真实墙钟、成本、按期率、完成率和决策开销。校准成本单列，并同时给本次总成本和不摊销/摊销口径。
- 逐对报告B−A，不用3个重复或6条事实冒充多事件样本；n=1事件，只给描述性差异、范围和不确定性，不作跨事件显著性/普遍收益结论。质量非劣界未规定前不声称“质量不下降”；Pareto仅对可观测维度、相同覆盖作描述。

### 请求与预算

45次节点测量 + 6次共同前缀 + 18次续执行 = **最多69次**；每模型测量15次、续执行及前缀至多24次，故每模型上限39次，三个上限不能同时达到。
输入预留65,536/请求，输出3,072/请求；合计输入预留4,521,984，输出上限211,968。输入预留不是认证Token硬上界。完整汇合报文必须按来源注册表单份原文＋父记录引用ID传递，保留可解析证据和父哈希，禁止为过门禁任意截断；实施前检查所有完整输入边界，而非只检查源材料。旧执行器及其131,072字节上限本轮未改。

以固定8元/美元记账系数（非现汇报价）计：Qwen每请求预留约¥0.0585728，DeepSeek峰值无缓存折扣约¥0.1867776。GLM官方价格页仅返回JavaScript壳，本轮无法核实该账户及协议对应费率，**不引用第三方价格冒充官方确认**。
令g为GLM单请求预留费用，则批次条件估费为：
`15 × (g + 0.0585728 + 0.1867776) + 24 × max(g, 0.0585728, 0.1867776)`。
这是按预留Token计算的条件费用，不是现金最坏账单保证。新人民币总停止阈值、GLM价目、模型版本及账户映射未冻结，因此总额为待定，**旧¥10不转移**。不能据此派发新请求。公开价依据为Qwen/DeepSeek官方页面；冻结前需复核新批费率。

## 5. 最终判断与边界

**零调用审计/设计完成；真实执行HOLD。** 具体缺口：GLM账户接口与费率/版本；三模型相同父输入夹具；可执行且冻结的Silver语义评价（或合格Gold）；包含全部父输出的报文界限；支持GLM的真实派发绑定；新完整预算及授权。它们没有用假测量填充，本轮未修改代码来伪称接通。

可能的科学贡献：在明确曝光的单事件中，测得节点级能力差异，并观察自然反馈后改派是否改变终端质量或费用/时延。可能的负结果：同一模型各节点占优、没有反馈、两臂同分配、切换更慢/更贵、全部失败或Q未知。这些都必须保留；不能据本批支持R、Z、跨事件泛化或完整联合优化收益。

原始证据路径及哈希、15单元机器矩阵、69请求公式详见 AUDIT_AND_PLAN.json。未发起任何模型调用，未执行旧批次，未修改历史或 ZCode。

官方价格入口：[Qwen](https://help.aliyun.com/zh/model-studio/qwen-plus)、[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/)、[智谱（本次无法解析价目）](https://open.bigmodel.cn/pricing)。
'''
(P/'MODEL_POOL_AUDIT_AND_PLAN.md').write_text(text)
assert all(sha(Path(f))==h for f,h in before.items())
write('READ_ONLY_CHECK.json',{'old_asset_hashes_unchanged':True,'new_model_calls':0,'original_files':before,'new_files_only_in':str(P)})
print(json.dumps({'status':'AUDIT_COMPLETE_EXECUTION_HOLD','matrix_llm_cells':sum(x['model'] is not None for x in matrix),'max_new_batch_requests':69,'historical_files_unchanged':True}))
