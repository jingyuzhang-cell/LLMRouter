"""Documentation and integrity finalization only; does not run tests or models."""
import sys,json,hashlib,inspect,difflib,subprocess
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_quality import TaskQuality,measured_cells
import joint_scheduler_v5 as v5
from freeze_matrix import decode,encode
OUT=Path(__file__).parent;ROOT=OUT.parent
prior=json.loads((ROOT/'v5_migration_20261022/MIGRATION_MANIFEST.json').read_text())
protected=json.loads((OUT/'PROTECTED_FILES_BEFORE.json').read_text());changed=[];missing=[]
for name,h in protected.items():
 p=Path(name)
 if not p.exists():missing.append(name)
 elif hashlib.sha256(p.read_bytes()).hexdigest()!=h:changed.append(name)
expected={str(ROOT/n) for n in ['joint_scheduler_v5.py','scheduler_common.py','rule_scheduler_rl.py','v5_executor.py']}
assert set(changed)==expected,(changed,expected)
assert not missing
legacy=json.loads((ROOT/'legacy/scheduler_v4_20261022/MANIFEST.json').read_text())
for r in legacy['files']:
 assert hashlib.sha256(Path(r['snapshot']).read_bytes()).hexdigest()==r['sha256']
 assert Path(r['snapshot']).stat().st_mode&0o222==0
results=json.loads((OUT/'TEST_RESULTS.json').read_text());assert len(results)==8 and all(r['exit_code']==0 for r in results)
assert 'Ran 39 tests' in (OUT/'test_v5_migration.py.log').read_text()
assert 'Ran 10 tests' in (OUT/'test_final_acceptance.py.log').read_text()
assert not (OUT/'isolated/NETWORK_OR_CREDENTIAL_DENIALS.log').exists()
summary=json.loads((OUT/'MATRIX_SUMMARY.json').read_text());rows=decode(json.loads((OUT/'V5_VS_RL_DECISIONS.json').read_text()))
assert summary['cases']==13 and summary['deterministic_decisions']==26 and summary['same_state_and_hard_rules']
patch=[]
for filename in sorted(expected):
 p=Path(filename);old=OUT/'before_sources'/p.name
 patch.extend(difflib.unified_diff(old.read_text().splitlines(True),p.read_text().splitlines(True),fromfile='before_final_acceptance/'+p.name,tofile='after_final_acceptance/'+p.name))
with (OUT/'CODE_CHANGES.patch').open('x') as f:f.write(''.join(patch))
# Formula provenance is a scoped audit, not a new quality label or model call.
g,s,obs=measured_cells();tq=TaskQuality(g,s,obs)
plan={'keep':{'t1':'glm53'},'reexec':{'t2':'deepseek'},'facts_per_call':{('t2','deepseek'):15}}
q,identified,prov=tq.estimate('kdx',plan)
state={'ev':'kdx','children_map':{},'model_nodes':{'t1','t2'},'missing_outputs':['t2'],
       'feedback':{'confirmed':['t2']},'cache_model':{'t1':'glm53'},'pools':{'t2':['deepseek']},
       'cost_lat':{('t2','deepseek'):(10,1)},'task_quality':tq,'facts_per_call':{('t2','deepseek'):15}}
best,_=v5.choose(state)
audit={'source_class':'HISTORICAL_CODE_CONSTANTS_ARITHMETIC_AUDIT_NOT_NEW_MEASUREMENTS',
 'formula':{'reexecuted_t2':'0.964 * 15 * 0.70','kept_t1':'15 * 0.29','total':'4.350 + 10.122'},
 'decimal':{'t2':str(Decimal('.964')*Decimal(15)*Decimal('.70')),'t1':str(Decimal(15)*Decimal('.29')),'total':'14.472'},
 'unit':'expected_evidence_chained_fact_count_not_accuracy',
 'rate_cells':{'t2_grounding':vars(g[('kdx','t2','deepseek')]),'t2_survival':vars(s[('kdx','deepseek')]),'t1_survival':vars(s[('kdx','glm53')])},
 'observed_cached_t1':{'grounded':obs[('kdx','t1')][0],'total':obs[('kdx','t1')][1]},
 'facts_per_call':{'value':15,'source':'explicit plan input; not an independently calibrated output-count distribution'},
 'code_result':q,'identified_proxy':identified,'component_provenance':prov,
 'downstream_v5':{k:best[k] for k in ['q_task','terminal_q','terminal_q_identified','diagnostic_q_proxy','quality_term_used','quality_scope']},
 'unknown_ev_result':tq.estimate('UNSEEN_UNCALIBRATED',plan),
 'source_traceability':'PARTIAL: source labels and historical correction report exist; no per-observation independent calibration is certified',
 'warnings':['Rates are stored rounded; arithmetic does not establish calibration.','No identified normalization denominator or cross-node deduplication makes this an accuracy score.','Historical source labels do not constitute independent terminal Gold.']}
assert abs(q-14.472)<1e-9 and best['q_task'] is None and best['terminal_q'] is None and not best['quality_term_used']
with (OUT/'QUALITY_CALCULATION_AUDIT.json').open('x') as f:json.dump(audit,f,ensure_ascii=False,indent=2)
quality_md='''# 质量计算与下游用途审计

结果：**乘法和加总正确；14.472是历史代理下的期望事实数，不是节点准确率或终端任务质量。来源追溯完整性仍为PARTIAL，不升级为独立质量校准。**

| 项 | 源码输入与声明来源 | 单位 | 核验值 |
| --- | --- | --- | --- |
| t2重执行 | grounding=0.964，n=28，`f7v2 saved`；facts_per_call=15为计划显式输入；survival=0.70，n=10，`RF2-signal trace` | 无量纲接地率×事实数×无量纲存活率 | 10.122 |
| t1保留 | 已接地15/22个缓存事实，模型glm53；survival=0.29，n=7，`RF2-signal trace` | 已接地事实数×无量纲存活率 | 4.350 |
| 合计 | t1项+t2项 | 期望链式事实数 | 14.472 |

`0.964×15×0.70=14.47`单独作为等式不成立。现有代码实际计算`4.35+10.122`；旧解释漏写缓存项，已有历史[S6更正报告](../S6_V5_DECISION_GATE.md)说明。本轮使用Decimal独立核对算术，再核对TaskQuality实际返回值与下游候选字段，保留浮点返回值的表示误差。

t1的15已经是接地事实数，不能再无依据乘一次接地率。t2的15是调用者传入的事实数假设，不是本轮新观测的真实输出数量。0.964等常数经过舍入，样本数和来源字符串已记录；本轮没有重新判读历史响应、签署Gold或验证可迁移的预测概率。

代码数据出处是[task_quality.py](../task_quality.py)中的`measured_cells`及计划输入，逐观察的原始响应/证据位置没有在Cell中完全标出，因此来源可追溯性为PARTIAL。不能把这些字符串引用当作独立终端参考，也不能把总数除以任意15、22或37当准确率；跨节点重复事实与终端必要项集合未经确认。

下游核验：TaskQuality返回14.472及`historical_chained_fact_proxy`；正式V5候选的`diagnostic_q_proxy`保留该值，`q_task=null`、`terminal_q=null`、`terminal_q_identified=false`、`quality_term_used=false`。终端质量约束存在而缺独立校准时拒绝。未校准事件、遗漏必要质量单元和缺参数传播为未知，不补零或扩大范围奖励。

原V5研究兼容测试中的`allow_proxy_objective=True`只用于原逻辑回归；正式执行器强制关闭，不能将测试日志里的“Q̂”写成研究收益。完整分项和下游输出见[JSON审计](QUALITY_CALCULATION_AUDIT.json)。
'''
with (OUT/'QUALITY_CALCULATION_AUDIT.md').open('x') as f:f.write(quality_md)
# Reports are versioned here; older root-level reports remain byte-identical.
report='''# JOINT OPTIMIZER V5 零调用最终验收

日期：2026-10-22。**本轮零调用验收PASS；真实优化收益尚未证明，不启动付费实验。** 本报告为新增版本，上一轮根目录同名报告、原始日志、冻结协议和legacy归档均未覆盖。

## 回归执行与真实修复

开工检查没有正在运行的隔离回归；已有原39项及7套件日志完整、源码匹配上一版清单。本轮只启动一个带文件锁的顺序隔离运行器，没有并行重复测试。

本轮补齐汇合节点自身失效的验收，首次8项检查出现2个ERROR：确定性join作为失效根被错误拒绝，且其重算时延未进入候选预测。修复后另发现预算拒绝时仍可能在返回字典携带已失效旧终端值，首次9项检查保留1个FAIL。它们是实现缺口，非预算或截止期预期变更，也非删除断言后PASS。

| 改动文件 | 有限修复 |
| --- | --- |
| [joint_scheduler_v5.py](../joint_scheduler_v5.py) | 失效根按完整DAG校验，R仍仅包含模型节点；候选独立记录`tools`及其影响；统一反馈标准化；任务计划含确定性重算信息。 |
| [scheduler_common.py](../scheduler_common.py) | 保留所有受影响顶点，显式把join等工具节点重算时延计入预测。 |
| [v5_executor.py](../v5_executor.py) | 执行候选中确定性工具；选择前剔除已确认失效根及下游输出，包括拒绝执行路径；拒绝状态记录零执行费用和实际本地规划开销。 |
| [rule_scheduler_rl.py](../rule_scheduler_rl.py) | 与V5、执行器使用同一反馈标准化接口；规则选择机制未因结果调整。 |

没有修改task_quality数值、Prompt、预算、截止期、原39项测试或历史预期；本轮新增10个定向测试。旧31项已在上一轮扩展到39项，本轮完整执行39项，没有删减为31。源码差异见[补丁](CODE_CHANGES.patch)；首次失败和最终日志均保留。

## 测试与验收覆盖

8个套件全部退出0：原预算、dry-run、FakeMeter计量、合同/截止期、联合执行器、原V5、39项迁移测试及10项最终验收测试。后两套unittest共49项；套件之间存在覆盖重叠，不将所有检查相加当独立实验样本量。

- Z/R/π通过选定动作与实际模型回调逐节点核对，恢复输出提交，Lineage输入指纹更新。
- 模型输出或join合同失效阻止终端执行；硬失效缓存及后继不会在预算拒绝时作为有效结果发布。
- 预算不足在任何回调前拒绝，未放宽截止期、缓存有效性或合同。
- VERIFY只在有目标和冲突证据引用时执行，无依据请求被拒绝，健康缓存不失效。
- 历史入口仍显式导入独立legacy模块；正式入口没有回退旧算法。

完整退出码、日志、失败分类和文件哈希见[零调用日志索引](ZERO_CALL_TEST_SUMMARY.md)。运行器使用新沙箱复制输入、重定向硬编码路径，拒绝HTTP/socket连接和凭据读取，未出现网络或凭据访问尝试。没有GPU调用或Git推送。

## V5/RL公平对照

冻结13个合成场景后顺序执行两策略，共26次策略验收。准备状态哈希相同；反馈检测器、能力单元、候选集合、硬约束拒绝原因和计量回调一致。26次重复求解动作一致，5个场景动作不同。详见[逐场景对照](V5_VS_RL_DECISION_AUDIT.md)、[全状态协议](SCENARIO_MATRIX.json)及[完整执行轨迹](V5_VS_RL_DECISIONS.json)。

所有场景的真实模型终端Q预测不可识别；完成后的数值Q只来自预先冻结的合成算术参考，不是独立真实Gold。动作差异主要表现为π及一项扩大范围选择；这只说明策略会作不同选择，不证明V5具有真实、稳定或独立收益。

## 质量与证据边界

`10.122 + 4.350 = 14.472`已核对到源码分项与下游用途。单位为历史期望链式事实数，正式终端Q仍null，不参与正式质量目标。历史率值/样本数有源码声明来源，但没有逐观察独立校准证明，来源追溯完整性PARTIAL。[质量审计](QUALITY_CALCULATION_AUDIT.md)。

本轮只验证机制实现、执行契约和有限合成决策差异。串行注入式执行器不是网络并行性能证据；回调Token/现金/执行时长是合成数据，本地规划耗时才是实测CPU时间。RL目前复用完整候选枚举与Pareto评分设施，但规则选择不利用Pareto；不能据这些原型CPU开销宣称高效RL实现不如V5。未校准真实终端质量、动作增量概率或跨事件稳定性。

## 冻结与停止

旧源码116份只读文件与全部受保护原文件（除本轮明确4份代码修改）保持原哈希。新场景、代码身份、测试退出码与交付物见最终清单。本轮未修改ZCODE、QS、Gold、旧实验结果或根目录旧报告；没有commit/push、API或GPU。

完成后停止。后续真实收益验证仍需要可信限定终端参考、同起始状态配对方案以及该实验的独立付费授权；本次PASS不自动解除真实实验门禁。
'''
with (OUT/'JOINT_OPTIMIZER_V5_MIGRATION_REPORT.md').open('x') as f:f.write(report)
# Human-readable per-scenario decisions and resource predictions / observations.
parts=['''# V5 / RL 公平逐决策对照（最终验收版）

**来源：13个冻结合成场景，不是历史真实模型回放或独立真实质量实验。** V5先、RL后是冻结执行顺序，CPU计时没有随机化，不能作算法速度显著性结论。两策略同状态、同检测器、同模型能力/硬约束和同计量口径。

完整初始状态、缓存内容、反馈原文/引用、能力表与冻结参考均见[场景JSON](SCENARIO_MATRIX.json)；矩阵在执行前冻结，SHA256见[MATRIX_FREEZE](MATRIX_FREEZE.json)。[完整决策与执行JSON](V5_VS_RL_DECISIONS.json)记录准备状态哈希、全部候选、拒绝原因、预测Q/C/L、实际回调、输出提交、输入指纹及来源类别；未执行候选实际结果为null。

| 场景／能力维度 | V5 Z、R、π；tools | RL Z、R、π；tools | 候选/可行 V5；RL | 执行状态 V5／RL | 动作不同 |
| --- | --- | --- | --- | --- | --- |
''']
def dtext(d):
 if d is None:return 'REFUSE'
 return d['Z']+'；R='+','.join(d['R'])+'；π='+','.join(n+'→'+m for n,m in d['pi'].items())+'；tools='+','.join(d.get('tools',[]))
for row in rows:
 a,b=row['V5'],row['RL']
 parts.append(f"| {row['id']} {row['dimension']} | {dtext(a['decision'])} | {dtext(b['decision'])} | {a['n_candidates']}/{a['n_feasible']}；{b['n_candidates']}/{b['n_feasible']} | {a['execution']['status']}／{b['execution']['status']} | {'是' if not row['same_action'] else '否'} |\n")
parts.append('''
所有可行候选的终端质量预测均为未知，不用0代替；没有可行候选时预测对象为null。下表中Q为**执行后、有效终端输出的合成算术精确匹配**；无合法交付时为null，不能读成内容错误率0。C与L的数值均为合成回调计量，不是真实账单或网络墙钟。

| 场景 | 预测Token V5/RL | 预测串行完成时长秒 V5/RL | 回调Token V5/RL | 合成现金CNY V5/RL | 合成执行秒 V5/RL | 合成终端Q V5/RL | 拒绝原因（两策略相同） |
| --- | --- | --- | --- | --- | --- | --- | --- |
''')
def val(x):return 'null' if x is None else str(round(x,6)) if isinstance(x,float) else str(x)
for row in rows:
 a,b=row['V5'],row['RL'];pa,pb=a['prediction'] or {},b['prediction'] or {};ea,eb=a['execution'],b['execution']
 def pair(x,y):return val(x)+' / '+val(y)
 ca,cb=ea.get('actual_cash'),eb.get('actual_cash')
 parts.append(f"| {row['id']} | {pair(pa.get('tokens'),pb.get('tokens'))} | {pair(pa.get('path_s'),pb.get('path_s'))} | {pair(ea.get('actual_tokens'),eb.get('actual_tokens'))} | {pair(ca.get('CNY',0) if ca is not None else None,cb.get('CNY',0) if cb is not None else None)} | {pair(ea.get('actual_execution_s'),eb.get('actual_execution_s'))} | {pair(a['terminal_fixture_q'],b['terminal_fixture_q'])} | {', '.join(a['rejection_counts']) or '无'} |\n")
parts.append('''
拒绝原因列是候选审计统计，可能包含未选候选的拒绝，并非该行最终选中动作失败；所有逐候选理由和数量均在JSON。没有模型回调的NONE/REFUSED在明确无执行的情况下现金为0，不代表未知供应商费用被记成0。

## 公平性与可复制性

13/13场景两臂准备状态哈希相同，候选数、硬约束和逐候选拒绝原因一致。26/26重复求解得到同一Z/R/π/tools；不重复执行模型回调来制造样本量。实际执行的模型逐节点与选定π核对，工具重算与R分别记录。重复性指决策，不包括随机器负载变化的本地墙钟。

- S00证明健康完整缓存可直接NONE，两策略均零回调，不无故重执行。
- S01/S02/S03分别覆盖上游、join自身与指纹失效，均按合法依赖更新结果；join自身异常无需重跑健康a/b分支。
- S04/S05/S07展示可用性、预算和截止期改变π；S06/S08/S09拒绝不足预算、截止期及未知质量下限，没有非法调用。
- S10中V5不对未知扩大收益加分；RL严重异常规则选择EXPAND。最终合成数值都正确，但成本与时延出现取舍，不能直接认定V5更优，也不能将保留数值正确缓存等同于证据质量已得到验证。
- S11有依据VERIFY只产注解，S12没有冲突依据时不执行。注解不是确认性Gold。

5/13动作不同，均未产生独立真实收益证据。有效合成终端交付的数值检查满分，不能证明模型质量异质性。规划CPU秒、实际本地函数墙钟、合成回调执行秒均分别存储，不能相加后冒充真实网络性能；本轮也不做显著性或跨任务普遍收益声明。

## 剩余限制及冻结

全部能力表、价格和时延是明确的合成单元，不是新采集模型表现。没有新真实模型响应，没有拿历史未执行的反事实动作填充结果。RL共享候选枚举/Pareto设施的原型开销不代表高效纯规则实现的最优CPU开销；本轮只验收公平信息、合法动作与计量口径，不宣称规划速度优势。

复现须在新目录使用冻结矩阵与对应源码，并保留失败日志；现有运行器独占锁且拒绝覆盖旧沙箱/输出。不能重跑后筛选有利结果。执行器、规则与矩阵冻结后，本轮停止，不启动付费或GPU实验。
''')
with (OUT/'V5_VS_RL_DECISION_AUDIT.md').open('x') as f:f.write(''.join(parts))
# Test index includes first failures and exact unchanged tests.
index=['# 零调用测试汇总与原始日志索引\n\n本轮一个顺序隔离运行器，8套件全部退出0。原31项已扩展到39项，本轮运行完整39项迁移单测及10项新定向单测；其余套件另列，不将覆盖重叠当独立样本。\n\n| 套件 | 退出码 | 原始完整日志 |\n| --- | --- | --- |\n']
for r in results:index.append(f"| {r['suite']} | {r['exit_code']} | [{Path(r['log']).name}]({Path(r['log']).name}) |\n")
index.append('''
## 首次失败与分类（未删除）

| 记录 | 结果 | 分类／处理 |
| --- | --- | --- |
| [FIRST_GAP_TESTS.log](FIRST_GAP_TESTS.log) | 8项中2 ERROR | 真正实现缺口：join根未支持、其时延未纳入；同断言修复后通过。 |
| [FIRST_REFUSAL_SAFETY_TEST.log](FIRST_REFUSAL_SAFETY_TEST.log) | 9项中1 FAIL | 真正安全缺口：拒绝恢复返回失效终端；提前剔除硬失效闭包后通过。 |
| [GAP_FIX_TESTS.log](GAP_FIX_TESTS.log) / [REFUSAL_AND_JOIN_FIXED.log](REFUSAL_AND_JOIN_FIXED.log) | 定向修复检查通过 | 仅对已暴露缺口回归，没有修改预算/时限或删失败断言。 |
| [MATRIX_RUN.log](MATRIX_RUN.log) | 退出0 | 13固定场景×2策略，26次合成验收；不是真实模型调用。 |

本轮没有修改原39项、原V5或FakeMeter套件的测试源码，哈希与上轮一致；全部运行在新沙箱。新增断言文件[test_final_acceptance.py](test_final_acceptance.py)包含Z/R/π实执行、提交/Lineage、健康缓存NONE、拒绝安全、join重算、legacy显式入口及历史代理不混用检查。

[退出码JSON](TEST_RESULTS.json)、[完整场景执行JSONL](MATRIX_EXECUTION.jsonl)、[公平性汇总](MATRIX_SUMMARY.json)与最终清单提供哈希。没有删原始失败日志，没有覆盖旧版报告、账本、协议或归档。
''')
with (OUT/'ZERO_CALL_TEST_SUMMARY.md').open('x') as f:f.write(''.join(index))
# Final manifest: protect old artifacts, snapshot current code and new reports.
code={str(ROOT/n):hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['joint_scheduler_v5.py','scheduler_common.py','rule_scheduler_rl.py','v5_executor.py','task_quality.py','feedback_detector.py','cache_lineage.py']}
deliverables={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='FINAL_MANIFEST.json'}
final={'version':'v5_final_acceptance_20261022_v1','source':'ZERO_API_ACCEPTANCE',
 'regression_suites':8,'migration_unit_tests':39,'new_final_tests':10,'matrix_cases':13,'strategy_runs':26,
 'different_actions':summary['different_actions'],'deterministic_decisions':summary['deterministic_decisions'],
 'same_state_and_constraints':True,'new_api_calls':0,'gpu_runs':0,'new_commits':0,'git_pushes':0,
 'modified_existing_files':changed,'unchanged_preexisting_files':len(protected)-len(changed),
 'legacy_source_files_verified':len(legacy['files']),'real_benefit_verified':False,
 'git_head':subprocess.check_output(['git','-C','/root','rev-parse','HEAD'],text=True).strip(),
 'current_code_sha256':code,'new_artifact_sha256':deliverables,
 'historical_root_reports_unchanged':True,'decision':'ZERO_CALL_ACCEPTANCE_PASS; NO_REAL_BENEFIT_CLAIM; STOP'}
with (OUT/'FINAL_MANIFEST.json').open('x') as f:json.dump(final,f,ensure_ascii=False,indent=2)
print(json.dumps({k:final[k] for k in ['regression_suites','migration_unit_tests','new_final_tests','matrix_cases','different_actions','unchanged_preexisting_files','legacy_source_files_verified','decision']},ensure_ascii=False))
