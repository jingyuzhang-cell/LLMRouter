# CAL5 V3 独立复核材料包

生成：2026-11-12　状态：**15/15 父节点通过；SETUP 5/5；测量 0 次（等待独立复核）**

## 一、包内结构

- `checks/`：PARENTS_V3_REVIEW.md、REQUEST_BODY_CHECK.json、SETUP_CHECK.json、INJECTION_INTEGRITY.json、PARENTS_REVIEW.json、GOLD_ISOLATION_CHECK.json、FACT_SEMANTICS_CHECK.json
- `parents/`：5 份冻结父输出（fe/tl/er 原始回答 + prompt SHA + usage + latency）
- `outputs/`：15 份逐节点原始输出（fe/tl/er × 5 任务）
- `prompts/`：15 份父节点完整用户提示词 + SYSTEM_PROMPT + 请求体模板
- `inputs/`：10 份冻结输入文本（D1/D2 × 5 任务）
- `tasks/`：CAL5_TASKS_V2.json、SHA 清单、零调用检查、任务身份追溯、输入文书清单
- `docs/`：10 份原始 PDF + 10 份抽取文本（5 组双文书）
- `code/`：calib_prompts.py、calib_harness_v3.py、calib_gate_v2.py、calib_v3_body_check.py
- `ledgers/`：V1/V2/V3 三份调用账本

## 二、四项复核对应的材料

1. **事实正确性**：`checks/FACT_SEMANTICS_CHECK.json` 给出每个任务中含目标值的完整 JSON 元素（tl 与 er 各一条），含主体、谓词、数值、`evidence_doc_id`；原始输出在 `outputs/`，原始文书在 `docs/`。
2. **Gold 信息隔离**：`checks/GOLD_ISOLATION_CHECK.json`。对每个任务，用冻结输入重建 fe/tl/er 提示词，SHA 与父输出记录逐一相符；再把任务集中的 `facts`/`injection_candidates` 字段整体删除后重建，提示词逐字节相同——证明 Gold 字段未进入父节点提示词。
3. **注入有效性**：`checks/INJECTION_INTEGRITY.json`。每个正确值在 er 中恰好出现 1 次，注入后 1 次被替换、错误值出现 1 次，tl 不变；`FACT_SEMANTICS_CHECK.json` 同时记录 `injection_single_replace=true`（原始 er 单次替换后与注入 er 完全相等）。
4. **实验可比性**：`EXPERIMENT_COMPARABILITY.md` 引用测量代码：Z0 与 Z1 使用同一 `tl_ans`、同一 `er_injected`、同一 D1/D2 输入；同一注入父输出跨两次重复复用；Gold 只在事后评分使用。

## 三、任务身份追溯

`tasks/TASK_IDENTITY_TRACE.md`：603271→600185 的替换发生在任务集 V2（提交 `b91f5fdf`），早于 GO V2 批准与 GO V3；V3 父节点运行使用 `CAL5_TASKS_V2.json` SHA `52f702c0…`；冻结后无任务替换。

## 四、预算与状态

- 累计请求 19 / 49；Token 78,719 / 300,000；记账 ¥0.0777 / ¥0.30（GLM 边际 ¥0）。
- 测量调用 **0 次**；30 次测量预算完整保留。

## 五、冻结 SHA

- 任务集 V2：`52f702c0fd62d534dd739189394ab5a5047810729687f4f2c8c04fd09b1d8adf`
- 提示词：`f2b13bc09059f437537d41399b71338a45317d0778392e55765a602763aa7c2f`
- 校准器 V3：`446ae7bb9d1ffb9b44955fe36eab8872d31a60a97d3d400f61292cf634afcb01`

所有文件 SHA256 见 `SHA256SUMS.txt`。
