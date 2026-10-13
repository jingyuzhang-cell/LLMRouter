# OFFLINE_TOOLKIT_DATA_INTEGRATION — 现有数据对接与剩余缺口

操作员准备包（ZIP）尚未到达本工作区（`/capital_event_zero_gpu_prep.zip`
不可见）。以下以本仓库已提交的 `offline_toolkit.py`（`b289fc3`）为基座
完成数据对接，并列出操作员工具包到达后的合并路径。

## 1. 现有真实数据清单（可直接对接）

| 数据源 | 位置 | 规模 | 与筛选的关系 |
|---|---|---|---|
| 模型池筛选（已执行） | `data/model_pool_screening_stratified_180/` | 180 查询 × 6 模型槽（small/medium/large/coder/math/reasoning），标签完成 | 已有 6 槽的真实 Q/C/L 基线（本地模型） |
| GLM 试点（已执行） | `data/pool4_glm_pilot_120/` | 120 条 GLM 真实调用（含 cost/latency/parse） | 已有 GLM 的真实成本与时延数据 |
| frozen200 任务 | `static_dag_v0/frozen200/` | 200 任务 | DAG 级正确率基准（历史执行） |
| TAT-QA train 剩余池 | `data/tatqa/tatqa_dataset_train.json` | ~1,386 未用任务（排除全历史使用后） | 新筛选样本来源 |
| 本仓库筛选面板 | `offline_toolkit.freeze_screening_panel()` | 20 任务（种子 20261013，排除全部历史 uid，**与 frozen200 零重叠**） | 80 次调用的任务集 |

## 2. 已完成的数据对接

### 筛选面板修正
`freeze_screening_panel()` 现在从**全部历史使用文件**（frozen200、P3-60、
micropilot、dev micro-trial、supplementary、evaluation panel）排除
uid——与 frozen200 的 3 任务重叠已修复为 **0 重叠**（sha
`a1acf9db…`，池 1,386）。

### 模型池筛选数据可复用性
`SCREENING_LABELS.jsonl`（180 条）包含 6 个本地模型槽的真实
quality/cost_usd/latency_ms——可作为 `NodeScreeningAnalyzer` 的输入
（离线、零调用）来预计算基线能力矩阵，为云端模型的 80 次筛选提供
本地对照。已验证可解析。

### GLM 试点数据可复用性
`pool4_glm_pilot_120/glm.jsonl`（120 条真实 GLM 调用）包含
cost/latency/parse_succeeded——可直接填入 `BudgetCalculator` 的
GLM 计费估计（而非人工猜测的费率）。

## 3. 20 槽位的真实样本对接

**当前状态**：`freeze_screening_panel()` 已从真实 TAT-QA train 池
抽取了 20 个任务 uid（确定性种子）。**任务内容（question/
ctx_table/ctx_text/derivation/answer）已存在**于
`data/tatqa/tatqa_dataset_train.json`——不是伪造的，是真实任务的
uid 冻结。尚需：

- [ ] 将 20 任务的完整字段（含上下文渲染）写入冻结文件——
  `_load_tasks()` 已在 launcher 中实现，需提取到 toolkit 层
- [ ] 为每任务生成四个节点的提示词（e1/e2/r/v——复用既有
  `RealServer.build_prompt` 的渲染逻辑）
- [ ] Gold 状态标注（v2.1 contract gold 已有——`load_native_answers()`
  覆盖全部 20 任务；"元道退 Gold 双人标注"仅适用于需要独立核验
  的子集）

## 4. 剩余缺口清单

| 缺口 | 需要什么 | 阻塞什么 |
|---|---|---|
| 模型凭据与费率 | GLM/DeepSeek/Qwen-cloud 的 API key + 确认费率 | 80 次真实调用 |
| 操作员准备包 | ZIP 下载到本工作区后合并（模板结构兼容则直接填入） | 工具层去重 |
| 元道退 Gold 标注 | 双人独立审核（模板已有，需人工执行） | Gold 独立核验 |
| 本地 Qwen 升级 | GPU 恢复 | 第 4 个模型在筛选中的参与 |
| 嵌入检索 | GPU 恢复（gte-Qwen2） | Graph Forest 的历史状态层 |

## 5. 操作员准备包合并路径

当 ZIP 到达时：
1. 解压到 `deadline_reward_v1/offline_prep_operator/`
2. 运行其测试（`python3 -m unittest discover -s tests -v`）
3. 比对模型池配置字段 → 填入 `offline_toolkit.MODEL_REGISTRY_TEMPLATE`
4. 比对样本槽位结构 → 映射到 `freeze_screening_panel()` 输出
5. 比对评分器 → 若结构不同，保留两套并声明差异（不强行合并）
6. 门禁统一：以更严格者为准（不放松）

## 6. 下一步（等操作员指示）

优先级最高的三项：
1. **凭据与费率填入**（需要你提供或授权查询 API 费率）
2. **Gold 独立核验协调**（元道退标注——需要你安排）
3. **GLM 试点数据→BudgetCalculator 的费率反推**（零调用，我可在
   下轮执行：从 120 条真实 GLM 调用的 cost 字段反推 input/output
   费率，与官方价格交叉验证）
