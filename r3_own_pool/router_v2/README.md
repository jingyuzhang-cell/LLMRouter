# R3 v2：训练、验证冻结与独立评估

实现服务于“旧 Router → 模型条件化多目标 Router”主线。尚无真实全量性能结果。当前默认 TF-IDF/SVD 只用于低成本开发；传入有 query hash 的冻结 GTE 嵌入才能沿用既有表示方案。Transformer 基线仍待独立实现/冻结，不能把当前比较称为完整论文 baseline 表。

## 已实现的实验

- 每模型质量回归 + 同题严格质量 pair 的 hinge loss；每题按有效 pair 数归一化，全 tie 可反传零损失，不强造 winner。
- 同训练器比较 Hybrid、NoModelEmbedding，alpha={0,.25,.5,1}；同时保留 alpha=0 作回归消融。两结构参数量不完全相等，不能把所有差异归因于模型表示。
- Ridge / MLPReward / KNN utility / MLPWinner / RankingOnly / RandomExpected / train-selected BestSingle / train-only constrained ZeroMixture / Oracle。
- 共享 Ridge 预测请求级成本、延迟，尺度只来自 train；KNN 用邻居分项均值。RankingOnly、MLPWinner 仅评质量模式，排序分数不当校准质量减成本。
- 固定24个偏好，各自仅在 validation 选 alpha；不是在 test 选最优权重。
- 约束操作点：validation 上质量配对区间下界≥0、延迟差上界≤0，选择平均成本最低候选；无符合条件的节省候选时退回训练选出的质量最佳固定模型。区间筛选不是质量保证，test还须验证。
- ZeroMixture 在 train 解线性规划：最小成本、质量不低于 train BestSingle、延迟不高于它。是固定混合的具体约束点，不是所有预算上的最优 Zero 曲线。
- 测试：真实 Q/C/L 下的效用增益、同定义 Oracle gap/GRR、配对区间、来源分层、四个固定模型锚点、三轴非支配网格点。有限网格不代表完整 Pareto 最优解。

## 操作顺序

使用 `/root/autodl-tmp/llmrouterbench_r2_venv/bin/python`，工作目录 `/root/r3_own_pool`。训练器只用CPU；本轮不会挤占采集GPU。

1. `python -m router_v2.preflight --output router_v2/PREFLIGHT.json`：只查覆盖、split/hash，不打开测试质量。
2. 完成评分及失败处理，审计代码执行隔离、成本口径与历史holdout使用情况，再生成真实 GATE.json。不能直接把模板 false 改为 true 冒充验证。全量尚未齐全时不训练。
3. `python -m router_v2.freeze --cohort data/cohort_full_v2 --outcomes data/judged_full_v2.jsonl --gate data/GATE_v2.json --output data/frozen/full_v2`：校验完整 Q/C/L 后复制，保持既有split，拒绝覆盖。
4. `python -m router_v2.experiment fit --cohort data/cohort_full_v2 --outcomes data/frozen/full_v2/outcomes.jsonl --gate data/frozen/full_v2/GATE.json --embeddings data/full_v2_gte.npz --output router_v2/run_seed42`：只取train/validation标签；保存测试请求预测，不评分测试标签。
5. 检查 PROTOCOL.json、SELECTION.json、FROZEN.json 后，`python -m router_v2.experiment evaluate --cohort data/cohort_full_v2 --outcomes data/frozen/full_v2/outcomes.jsonl --output router_v2/run_seed42`。输入、代码、选择、预测哈希必须一致；TEST_OPENED.json以独占方式创建，拒绝静默重复打开。运行失败也保留标记，需查清原因，不能删除标记追结果。

示例里的全量文件尚未生成；命令是准确入口，不表示门禁已通过。多seed应先共同冻结全部策略再评估，不能依据seed42测试结果修改另一个seed的模型。尚未添加跨run/跨目录的中央开封登记；操作者必须遵守一次性测试协议。

嵌入NPZ必须含 `ids`（精确query_id）、`vectors`（有限二维数组）、`query_sha256`（标量字符串）。只允许query输入；不能把答案、结果推导难度、test成本等编码进去。GATE应记录encoder、revision、截断/编码配置与生成脚本来源；当前代码检查hash和id，不能自动证明外部embedding没有泄漏。

## Gate字段

必需：outcomes_sha256 / queries_sha256 / split_sha256；scoring_complete / failures_accounted / cost_provenance_verified / code_sandbox_verified / holdout_uncontaminated 全为经过审计的 true；currency="USD"；cost_basis 为可复查的统一计费说明。字段由审计证据支持，程序只校验绑定与声明，不替代审计。`role="synthetic_smoke"`仅供独立合成夹具；此角色的结果永远是软件验证，不是实测。

费用缺失、质量缺失或非法数值会拒绝训练，不静默删除题目/填0。失败响应应按冻结的失败评分/实际资源记录规则处理后输入。人民币API牌价必须明确换算依据后才能与USD列合用，本地GPU费用不能靠tokens代理冒充实际账单。

## 已知限制

- 尚未完成真实全量训练、GTE全量编码、Transformer基线、跨seed汇总、独立重复生成噪声上界。
- 输出是离线实验预测，尚未导出含encoder与预测器的部署服务。
- 计时仅模型预测部分，未计encoder、资源预测器/dispatch全链路开销；不能声称已经覆盖Router overhead。
- 配对区间条件于已训练模型，不计重训方差；多权重/多方法区间未作同时覆盖校正。
- 这是源内query泛化，不是未见任务域或未见模型泛化。pilot与full cohort重叠，holdout历史污染必须另外审计，不能用新hash抹掉已知信息。
- 旧 `freeze.py` / `train_router.py` 已限pilot，旧机会分析默认仅train、judge可靠性仅train。旧后处理watcher已停止，旧脚本加了退出保护；原采集进程继续。当前后台补训练分区数学/选择题及隔离代码评分，并生成query嵌入；外部judge已获用户明确授权并开始train批量评分，不自动打开test。


## 下一阶段已经执行（2026-09-08）

- `score_available` 已实际评分训练分区已有 GSM8K/MMLUPro 响应，启动时6479条，后台首次补跑后6940条。结果在 `data/scored_train_v2/SCORES.jsonl`；每条绑定query/ground-truth、原始响应和评分器hash，失败/解析失败记0但保留标志，截断按实际交付答案评分。跳过代码与开放题，不执行候选程序，不调用新judge API。
- `watch_scoring` 每300秒补新到达响应，最长24小时；数学/选择题覆盖齐全即停止。它不代表四任务评分齐全。`WATCHER_STATUS.json`提供真实状态。
- `embed_queries` 已完成本地tokenizer与权重存在性预检：5000 query、最大8419 tokens、无截断、3584维GTE。编码任务已后台启动等待：三个本地模型原始记录齐全、采集GPU锁可用、nvidia-smi确认无计算进程，三项同时满足才加载encoder。预检不等于已生成嵌入。
- 编码使用本地模型、fp16、batch1、请求文本、归一化，远程访问关闭；以16题分块保存并可恢复，完成后生成 `data/embeddings_full_v2/EMBEDDINGS.npz`，可直接传给fit的 `--embeddings`。缓存绑定模型权重/配置/源文件与query hash。
- 暴露审计实际发现train/validation/test分别有354/65/81题进入pilot；原750题test不能整体认证未触碰。原split没有修改，剩余669题仅是排除已知pilot后的审查名单，不能自动当作新确认集。详见 `exposure_audit/REPORT.md`。
- 当前任务登记：`BACKGROUND_JOBS.json`。27项测试通过。尚未运行真实全量Router训练或测试评估。


## 评分与编码恢复（2026-09-09）

- `judge_full.py`：完整问题与回答送审，无8000字符截断；沿用原锚定rubric，严格校验总分和分项；先记intent再调用，每响应最多2次且SDK不自动重试，连续3次失败停止。外部试评分被自动审批拒绝，尚无请求执行，详见 `JUDGE_APPROVAL_STATUS.json`。当前实现仅train，不能用“继续”替代对该外发动作的明确授权。
- `code_sandbox.py` / `code_worker.py`：在独立只读Python运行时内降至UID/GID65534，Landlock限制读取路径，seccomp默认拒绝未允许系统调用；禁网络、进程创建、外部exec与文件写入，并限制CPU/内存/输出。最终运行时 `/tmp/r3-code-runtime-v3` 的7项探针通过。它是纯函数stdlib评测环境，未认证第三方依赖、写文件任务或对抗性评分防作弊。
- `score_code.py`：训练集MBPP/HumanEval按既有测试拼接逻辑评分，异常分为程序错误、隔离失败、环境/依赖待审查；后两类不填0。32条真实小批量已完成后，批量任务已启动；最新进度见 `data/scored_code_train_v2/STATUS.json`，结果缓存绑定响应、协议和运行时hash。
- 编码修复：原local_complete将collect加入sys.path，导致其datasets包遮蔽Hugging Face datasets。已改为按文件加载storage，独立进程验证SentenceTransformer导入成功；原失败目录保留，新任务输出为 `data/embeddings_full_v2_recovery1/EMBEDDINGS.npz`，生成完成后再交fit使用。
- 数学/选择题补评分任务已恢复；35项回归测试通过。任务登记 `BACKGROUND_JOBS_20260909.json`。尚未运行真实全量Router训练和独立测试。


## 外部judge授权执行更新

用户已明确批准向DashScope/qwen-max发送train开放题和模型完整回答。8次试评分全部得到有效评分，随后已启动watch_judge批量与增量评分；所有成功结果复用，单条未变响应最多2次，连续错误即停止。旧的审批拒绝是已解除的历史状态，不应再次就同一发送范围要求确认。实时状态见data/judged_train_full_v2/STATUS.json，任务登记见JUDGE_BACKGROUND_JOB.json。


## 矩阵汇总与评分恢复（2026-09-09）

- 全量GTE已完成，5000×3584向量的query id、输入hash、文件hash、有限性与单位范数全部核验通过。正式fit可引用 `data/embeddings_full_v2_recovery1/EMBEDDINGS.npz`。
- 严格judge因17次总分/分项和不一致中断。`judge_primary.py`恢复原始项目 `score/10` 标签口径，分项不一致单列；按首个有效主分数重放，不选更高分、不用分项和替代总分。该解析修订是开发分支，不是已验证的标签可靠性修复。
- 旧日志不变，59次已消耗调用全部继承；从42条严格标签得到50条主评分，其中2条旧成功标签在新口径下改变，10条带分项不一致标志。原严格结果保留用于敏感性分析，详见 `data/judged_train_primary_v2/AMENDMENT.json`。新watcher继续同一已授权train数据与qwen-max目的地，不重置尝试预算。
- 唯一NumPy依赖已通过独立NumPy运行时的7项隔离探针及NumPy运算canary后补评；原候选、测试和旧记录均未修改。补充标签在 `data/scored_code_numpy_train_v2/SCORES.jsonl`，审计在NUMPY_SANDBOX_AUDIT.json。仅以环境前置设置限制OpenBLAS/OMP线程数，不改变代码计算逻辑。
- `assemble_development.py`按source/response hash拼接auto、stdlib code、NumPy补充与primary judge；保留缺失与不一致标志，不用后来的较高judge分覆盖首个有效值。快照 `data/train_matrix_snapshot_20260909a/`含3500题/14000单元、11165个标签、2084个四槽齐全query；属于动态收集过程中的已封存快照，不是完整训练gate。
- `watch_code.py`已启动每300秒补评新到达训练代码。与数学/选择题、judge watcher共同运行。41项回归测试通过。真正的独立测试与多目标收益结论尚未产生。

训练 judge 的只读敏感性检查已加入：`python -m router_v2.audit_judge_sensitivity --output <new-directory>`。它报告主总分与分项总和对标签及同题排序的影响，不替换标签或认证可靠性。首次结果及后续处理原则见 [JUDGE_SENSITIVITY_20260909.md](JUDGE_SENSITIVITY_20260909.md)。
