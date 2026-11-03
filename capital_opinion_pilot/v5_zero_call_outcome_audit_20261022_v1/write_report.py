"""Produce the outcome report from audited originals. No algorithm execution."""
import json,hashlib
from pathlib import Path
ROOT=Path('/root/capital_opinion_pilot');OUT=Path(__file__).parent
D=json.loads((OUT/'V5_ZERO_CALL_OUTCOME_AUDIT.json').read_text());S=D['summary']
obs=json.loads((OUT/'HISTORICAL_OBSERVATION_RECONSTRUCTION.json').read_text());q=D['quality_metrics'];rates=D['minimum_future_plan']['conditional_budgets']
index=json.loads((OUT/'SOURCE_INDEX.json').read_text());freeze=json.loads((OUT/'ALGORITHM_FREEZE.json').read_text())
for p,v in freeze['algorithm_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==v
for p,v in index.items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==v['sha256']
# Metrics are quotations / arithmetic summaries of existing records, not rescoring.
assert S['current_V5_RL_strict_matching_replays']==0
assert S['own_input_legal_commit_reconstructions']==11 and S['invalid_response_inspection_only']==3
assert q['historical_numeric_branch_diagnostics']['assigned_amount_matches']==36
assert all(r['benefit_status']=='UNIDENTIFIABLE_NOT_ZERO_NOT_NO_EFFECT' for r in D['scenarios'])

report='''# V5 零调用决策收益审计

2026-10-22（北京时间）。**结论：五个动作差异全部定位；真实收益均不可识别，当前真实配对执行NO-GO。** 没有修改V5/RL或公共模块，没有重新运行合成场景、真实API、GPU或付费实验，没有改历史评分或响应。

本轮以最新版[V5最终验收](../v5_final_acceptance_20261022_v1/JOINT_OPTIMIZER_V5_MIGRATION_REPORT.md)及[逐决策对照](../v5_final_acceptance_20261022_v1/V5_VS_RL_DECISION_AUDIT.md)为准，较早根目录报告只作历史来源。所有原文件与算法SHA256登记在[来源索引](SOURCE_INDEX.json)和[算法冻结](ALGORITHM_FREEZE.json)。本次结论不是“V5无收益”，也不是“V5更优”，而是没有合法实测反事实可识别其收益。

## 一、全部五个差异场景

| 场景 | 状态与反馈 | V5动作 | RL动作 | 差异维度 | 候选/可行（两臂相同） |
| --- | --- | --- | --- | --- | --- |
| S01 | a输出合同失效，b缓存健康，join/out旧结果需失效 | LOCAL；R={a,out}；π={a:fast,out:fast}；工具join | LOCAL；R={a,out}；π={a:cheap,out:cheap}；工具join | π | 6/4 |
| S02 | join自身合同失效；a/b有效；out依赖join | LOCAL；R={out}；π={out:fast}；重算join | LOCAL；R={out}；π={out:cheap}；重算join | π | 4/2 |
| S03 | b缓存输入指纹变更；a有效；join/out依赖b | LOCAL；R={b,out}；π={b:fast,out:fast}；工具join | LOCAL；R={b,out}；π={b:cheap,out:cheap}；工具join | π | 6/4 |
| S10 | a合同失效；b的证据接地检查1/3，属怀疑；终端质量预测未知 | LOCAL；R={a,out}；π={a:fast,out:fast} | EXPAND；R={a,b,out}；π均cheap | Z、R、π | 21/20 |
| S11 | 明确冲突及b目标链接；必须核验；缓存数值仍有效 | VERIFY；R={}；π={verify_b:fast} | VERIFY；R={}；π={verify_b:cheap} | π | 3/2 |

完整状态、反馈原文、缓存内容、能力表、预算/截止期、逐候选拒绝原因及准备状态哈希均保存在[机读审计](V5_ZERO_CALL_OUTCOME_AUDIT.json)的scenarios中。两臂同状态/硬约束只对这些**合成验收**成立；其`fast/cheap`没有冻结的真实供应商映射，不能事后将其解释成Qwen或DeepSeek。

模型成本与时延是合成常数：cheap每调用10 Token/4秒/¥0.01，fast为20 Token/1秒/¥0.02；join为确定性工具，声明时延0.1秒。普通场景预算100 Token、¥1、30秒，单资源串行；工具和模型节点分开记录。质量预测均null，所有来源仍是SYNTHETIC_TEST，不是模型能力实测。

| 场景 | 已有合成Token V5/RL | 合成执行秒 V5/RL | 合成现金V5/RL | 实际真实Q/C/L |
| --- | --- | --- | --- | --- |
| S01 | 40 / 20 | 2.1 / 8.1 | ¥0.04 / ¥0.02 | null / null / null |
| S02 | 20 / 10 | 1.1 / 4.1 | ¥0.02 / ¥0.01 | null / null / null |
| S03 | 40 / 20 | 2.1 / 8.1 | ¥0.04 / ¥0.02 | null / null / null |
| S10 | 40 / 30 | 2.1 / 12.1 | ¥0.04 / ¥0.03 | null / null / null |
| S11 | 20 / 10 | 1 / 4 | ¥0.02 / ¥0.01 | null / null / null |

上表只是读取已有合成结果，没有新增执行。五项均是“更多合成资源成本换更少合成时间”，不是无条件Pareto支配；冻结算术检查同为1也不能证明模型终端质量相同。S11的终端数值本来就在健康缓存中，注解成功不等于重新生成任务答案或提高质量。

## 二、严格回放门槛及实际结果

只有任务材料、模型身份、请求内容、源/合同身份、输入与缓存版本、依赖和合法提交均对应，才允许把历史响应归给指定动作。预测Q、相似节点名、相同数字、相同模型类别都不足以满足该门槛。

本次检查限定于原始规范目录：六对数值重复实验12笔、单次受控数值实验2笔、F7v2原始19笔，共33笔；排除测试沙箱副本和密封留出集，不宣称穷尽仓库中所有历史文件。

| 数据组 | 实际存在记录 | 本次可做的核对 | 不能做什么 |
| --- | --- | --- | --- |
| 数值六对重复 | 12笔，有请求、原HTTP、模型文本、动作、缓存身份、终端提交 | 9笔合法响应在其自身原始输入内重建核对；3笔非法数组只检查，未提交 | 不归给V5/RL，也不包装数组以回填成功 |
| 数值单次受控 | 2笔，有同类完整材料 | 2笔自身历史输入内核对，保留一次正向时延观测 | 不将单次观测当稳定优势，不与重复实验拼成确认性结果 |
| F7v2 | 19笔响应与账本 | 19笔call/run/node/model一一关联，Token和记录时延可追溯 | 缺完整请求体及消费缓存版本，不能作严格同输入执行回放 |
| 当前五场景 | 只有已冻结合成回调 | 保留原合成结果及硬约束审计 | **匹配的真实响应0笔，真实双臂对照0组** |

对14笔数值响应核对了：请求体/消息规范哈希、请求模型、原HTTP与原文本一致、实际用量、动作π与请求模型一致、恢复R、共同快照身份、有效采购缓存的源/合同/上游指纹及payload哈希、原终端提交。重复实验还与原RESULT_MANIFEST逐文件核验。依赖和来源文件均未修改。

11笔合法响应只在各自历史上下文中核对提交，3笔非法响应不进入任何下游。这是**历史观察重建**，不是重新执行旧调度器或新V5。详情见[历史观察机读核对](HISTORICAL_OBSERVATION_RECONSTRUCTION.json)。

五场景与历史输入均未匹配：合成任务与真实资本市场材料不同；无fast/cheap真实模型映射；合成动作无供应商请求体；缓存指纹/版本体系不等价；合成整数回调合同与历史items/report合同不同。缺失动作结果统一标记UNOBSERVABLE/UNIDENTIFIABLE，未用预测或旧答案补齐。

## 三、质量、完成率、合同、成本和时延分开解释

### 事实级指标

已有冻结数值诊断对12次余额响应所分配的3项目标记录36/36金额MATCH，包含3次被拒裸数组的9个正确数字。这只反映**在实体、时期和字段已经给定条件下的数值内容**，不证明其完整角色、来源语义或合法提交。不得把每次只答3项、却用6项目标评分产生的2/3误读为该分支数值准确率。

`task_quality.py`的0.964/n=28等是历史接地率代理，来源标签为`f7v2 saved`；存活率0.70/n=10和0.29/n=7标签为`RF2-signal trace`。它们不是独立终端质量概率；逐观察追溯/校准证明仍不完整，来源状态PARTIAL。

### 端到端范围与完成率

六对重复实验按原记录：A合法恢复6/6，B为3/6；原生Schema同为6/6与3/6，有限数值合同分别6/6与3/6；完整舆情合同NOT_EVALUATED。合法且正确目标A为36/36、B为27/36。B的75%是目标提交覆盖；平均原F1约0.8333，二者不能互换。金额本身正确不改变非法数组不能提交的冻结判定。

完整舆情终端Q仍null；F7原有代理/候选参考没有独立确认，不能据其报告当前V5质量收益。不能把局部接地改善当作终端提升。

### 真实费用与时延

重复实验实际输入62,916 Token、输出2,439 Token；实际现金账单仍PENDING_BILL/null。A缓存调整估费USD0.001613088，B为CNY0.00600402；币种不直接相加。估费不是实际扣款，也不是现金硬上限。

A恢复墙钟均值2.795017秒，B为3.191793秒；A在5/6对更快。双方均合法完成的3对中A均更快。更早单次受控观测A9.791648秒、B2.711697秒且均6/6合法完成；这条正向记录保留，但六对重复没有复现该优势。

这些都是旧静态规则/旧成本优先策略及各自模型组合的观测，不是冻结V5与RL。恢复阶段墙钟不是完整DAG墙钟，真实初始前缀联合墙钟不完整，保持null。当前五场景真实ΔQ、ΔC、ΔL和成功概率均不可识别。

## 四、逐场景GO/NO-GO

| 场景 | 可用真实相关经验 | 当前可公平比较指定两动作？ | 收益状态 | 下一轮建议 |
| --- | --- | --- | --- | --- |
| S01 | 数值恢复中换模既有正例也有重复负例；不是本场景两节点输入 | 否 | 不可识别 | NO-GO；若真实模型分配/终端参考齐备，可作π条件化对照，不声称范围优化 |
| S02 | 确定性join重算机制已离线通过，没有本场景真实out模型对照 | 否 | 不可识别 | NO-GO；不为再次证明免费join计算而花钱。自然存在模型下游和独立参考时才有最小配对意义 |
| S03 | 历史有缓存身份资料，但不是该b/out输入版本 | 否 | 不可识别 | NO-GO；与π研究合并准备，不当作独立R优化成果 |
| S10 | 没有同状态LOCAL与EXPAND完整真实结果 | 否 | 不可识别 | 当前NO-GO；具备最直接的联合范围研究价值，优先补真实任务、额外异常证据和终端参考，不预设V5应获胜 |
| S11 | 历史t5不是verify_b注解合同，没有匹配核验响应 | 否 | 不可识别 | NO-GO；能确定性核验的内容不花模型费用。仅真实语义冲突且有独立核验标准时再考虑付费 |

准备GO与执行GO不同。当前没有一个场景达到真实执行GO；这不是“已证明无收益”，也不能通过换模型标签或调整预算阈值把它变成GO。若质量约束要求校准终端Q而数据仍未知，保持拒绝，不能为启动实验取消该约束。

## 五、最小可识别配对方案（仅记录，不实施）

1. 选择**自然存在**的真实开发DAG和一个状态检查点，不新增为制造优势而设的模型节点；保存完整Prompt、源内容、合同、已提交输出、缓存输入/版本身份、剩余资源和可用模型。
2. 用同一冻结V5/RL及同一份实际能力数据/约束确定两动作。若同选，或只有没有模型价值的确定性差异，停止，不调用。不得用已观察终端答案反推模型分配或调参。
3. 终端参考必须独立可核查、范围明确；现有六项数值参考仅在确实覆盖新任务合同且证据核验通过时可复用，不自动充当全舆情Gold。所有动作对同一参考评价，仍分别记录内容、证据、Schema、完整合同、合法完成和实际成本/时延。
4. 从同一快照各执行一次，两臂同样允许缓存复用和合法闭包；预先固定顺序、失败停止和无追加规则。全部策略开销、前缀获取和重执行费用入账。没有匹配的历史响应时需要新专项付费授权，本轮不执行。

**最少调用**：S02型若真实out本来就是一个模型节点、a/b缓存合法可直接复用，则每对V5/RL各1次模型调用，共2次。1对只验证可执行差异；预先安排3对则6次，仍是单事件探索性重复，不能证明稳定排名或广泛净收益。

**联合范围版本**：S10型沿用已确认2节点LOCAL对3节点EXPAND，则每对最多5次恢复调用，3对最多15次。它更贴近Z/R/π研究，但必须先取得真实额外缓存异常与独立终端评价，不能通过人为质量奖励使扩大或缩小范围胜出。

上述请求数只在已有合法初始缓存可复用、无需新前缀调用时成立。若必须重新生成初始状态，前缀请求数和费用须另行核实并重算整个信封，不把前缀当免费、也不默默突破2/6/5/15次。模型不可用、全部候选不可行、预算/时限不足、输入计量不明时均停止；本轮尚无执行授权。

### 条件预算估算

仅使用已保存2026-10-19价格快照，不声称为当前有效价格。假定每次输入监测上界16,384 Token、输出限制1,024 Token，按冷缓存公开价估算；输入上界未认证，实际账单上界仍未知。请求前必须重新核价、确认计量与现金安全，否则NO-GO。

| 恢复调用上限 | 输入监测合计 / 输出上限 | 全Qwen-Flash估费CNY | 全Qwen-Plus估费CNY | 全GLM-5.3估费CNY | 全DeepSeek-Flash估费USD |
| --- | --- | --- | --- | --- | --- |
'''
for b in rates:
 p=b['conditional_prices']
 report+=f"| {b['recovery_calls']} | {b['input_monitor_total']} / {b['output_cap_total']} | {p['qwen-flash']['all_calls_same_model_estimate']} | {p['qwen-plus']['all_calls_same_model_estimate']} | {p['glm-5.3']['all_calls_same_model_estimate']} | {p['deepseek-flash']['all_calls_same_model_estimate']} |\n"
report+='''
表中“全某模型”是相同调用数的费用上界情形，不是强行指定两策略用某模型；实际按各币种分开加总，不能用汇率转换兜底。6次探索性恢复可暂建议CNY1/USD0.05估费停止阈值；15次则CNY3/USD0.12。它们未授权、非现金硬上限，未包含尚不明确的新初始前缀及额外服务费，也不保证截至执行时价格不变。数据来源为[既有PRICE_CHECK](../../r3_own_pool/ab_numeric_recovery_repeat_v1/REAL_BATCH_20261019_030355/PRICE_CHECK.json)。

## 六、冻结、复核与停止

本轮未修改算法、调参、历史数据、评分、旧报告或冻结协议；没有生成新的合成替代响应，没有将旧响应注入输入不匹配的当前执行器。机读JSON明确区分SYNTHETIC_TEST、HISTORICAL_REAL_EXECUTION_OBSERVATION、历史观察重建、代理预测与UNIDENTIFIABLE。

[机读主报告](V5_ZERO_CALL_OUTCOME_AUDIT.json)、[原始来源索引](SOURCE_INDEX.json)、[历史核对](HISTORICAL_OBSERVATION_RECONSTRUCTION.json)、[审计汇总](AUDIT_SUMMARY.json)与最终清单可复核全部结论。首次审计输出曾因tuple键序列化退出1，只修本轮报告生成器，并保留未完成文件与说明；算法和输入数据没有修改。

**完成后停止，等待后续明确授权。** 任何真实配对仍须同时具备可信终端参考、同状态完整输入/缓存方案和专项付费授权，并重新确认研究目标、对照与预算，不能沿用历史授权。
'''
# Correct relative link to /root/r3_own_pool from this directory.
report=report.replace('(../../r3_own_pool/', '(../../r3_own_pool/')
with (OUT/'V5_ZERO_CALL_OUTCOME_AUDIT.md').open('x') as f:f.write(report)
# Verify all source identities and all frozen algorithms after documentation.
for p,v in index.items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==v['sha256'],p
for p,h in freeze['algorithm_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
manifest={'kind':'READ_ONLY_V5_OUTCOME_AUDIT','algorithm_files_unchanged':True,'source_files_unchanged':len(index),
 'new_api_calls':0,'gpu_runs':0,'algorithm_or_parameter_changes':0,'new_synthetic_or_real_responses':0,
 'difference_scenarios':5,'selected_historical_call_records':33,'strict_matching_current_action_replays':0,
 'own_input_legal_historical_commit_reconstructions':11,'invalid_responses_inspected_not_submitted':3,
 'real_benefit':'UNIDENTIFIABLE','real_execution_gate':'NO_GO',
 'artifacts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='FINAL_MANIFEST.json'}}
with (OUT/'FINAL_MANIFEST.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
print('Report generated; protected sources',len(index),'algorithms unchanged; actual matching V5/RL replays 0')
