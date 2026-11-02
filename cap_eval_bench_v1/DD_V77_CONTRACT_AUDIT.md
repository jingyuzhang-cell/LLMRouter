# DD-V7.7 零调用生产路径数据契约审计与端到端验收

**日期**: 2026-10-30
**性质**: 零 API 调用（未产生任何付费请求；本轮全部结论来自冻结 DAGSpec、v2 已结算台账与确定性测试）
**结论**: 发现并修复 **4 处** 数据契约缺陷（v2 只暴露了其中 1 处）。修复版 Runner 通过全部 26 项零调用验收测试与 2 项负面测试。**建议批准第三次执行：23 请求 / Token 包络 100,000 / ¥0（订阅）**，待操作员七字段授权。

---

## 1. 审计方法

以冻结 `D_重大事件与市场反应_r1_spec.json`（Planner V1 产物，10 节点 13 边）为唯一契约源。该 spec 每个节点携带三个此前未被 Runner 消费的字段：

- `inputs`: 父节点 id 列表（边的定义）
- `contract.requires / contract.produces`: 字段级输入输出合同
- `evidence`: 节点绑定的证据文档 id

逐边核对三方：spec 声明的边 / v2 Runner 实际存储的键 / `build_prompt()` 实际读取的键。再用 v2 已付费的 n1、n2 真实输出（1,841 / 1,724 字符）作为 fixture 回放修复后的生产路径。

## 2. 缺陷清单（4 处）

### F1 键名不匹配（v2 已暴露的直接死因）
v2 Runner 双重存储 `upstream[nid]` 与 `upstream[role]`（如 `extraction`），但 n3/n4/n5/n6 的 `build_prompt()` 读取 `ud.get("doc_extracts")` → 恒为空串。n3 的实际 prompt 仅 66 字符（台账 `prompt_chars: 66`），信息链在 n2→n3 处断裂，ΔQ=0.000。

### F2 同角色多父覆盖（v2 未暴露，字符串替换修复会遗漏）
n5 与 n6 的父节点为 `[n1, n2]`，**两者角色同为 `extraction`**。单一角色键意味着 `upstream['extraction']` 被 n2 覆盖，n1 的输出静默丢失——即使把 `doc_extracts` 改成 `extraction` 也只能救回 n2。这正是操作员指示"不得只做字符串替换而不验证多父节点输入"所针对的情形。

### F3 抽取截断
n1/n2 的 `max_tokens=768`，台账 `stop_reason=max_tokens`，两输出 JSON 括号不平衡（19/16、10/7），尾部事实（含日期）丢失——这是 n10 终评日期命中不足的结构性风险源。

### F4 证据绑定违反冻结契约（最深的一处）
spec 明确声明：n1 只读 `zeda_csrc_penalty_2023_29`（produces `facts_main`），n2 只读 `zeda_csrc_penalty_2024_kangda`（produces `facts_intermediary`）。v2 把**两份文档拼接后同时喂给两个抽取节点**——n1/n2 的 prompt_sha256 完全相同（`cbd68c2d…`），输出近似重复，n2 本应抽取的康达律师事务所维度实际缺失。DAG 的双抽取结构（主处罚 + 中介机构）被压扁成了一次抽取的两份采样。

## 3. 逐边审计表（13 条边）

| 边 | 上游 produces | v2 实际行为 | v3 行为 |
|---|---|---|---|
| n1→n3 | facts_main | ✗ 空（F1） | ✓ 按节点 id 读取 |
| n1→n4 | facts_main | ✗ 空（F1） | ✓ |
| n1→n5 | facts_main | ✗ 空（F1） | ✓ 拼接 |
| n2→n5 | facts_intermediary | ✗ 空（F1+F2） | ✓ 拼接 |
| n1→n6 | facts_main | ✗ 空（F1） | ✓ 拼接 |
| n2→n6 | facts_intermediary | ✗ 空（F1+F2） | ✓ 拼接 |
| n3→n7 | dates | ✓（键名巧合一致） | ✓ |
| n6→n7 | entity_edges | ✓ | ✓ |
| n4→n8 | amounts | ✓（手工映射 n4→'amounts'） | ✓ 统一按 spec |
| n5→n9 | penalty_items | ✓（注入 GARBAGE） | ✓ |
| n7→n9 | stages | ✓ | ✓ |
| n8→n9 | amounts_checked | ✓ | ✓ |
| n9→n10 | checked | ✓ | ✓ |

## 4. 修复设计（`integration/dd_v77_runner_v3.py`，sha256 fb8a549f…）

下游上下文一律由 spec 的 `inputs` 列表按节点 id 组装（`parent_ctx()`），每个父节点标注角色与 `produces` 字段；同角色父节点拼接（F2）。抽取节点只读 `node_docs(nid)` 返回的**单篇**声明文档，声明文档缺失即 FAIL-CLOSED 抛错（F4）。抽取输出上限 1536、其余 768，父输出复用上限 2,600 字符（F3）。prompt 文本除证据绑定外与 v2 逐字节一致（含 v2 的 `doc_ex extracts` 原样拼写，最小偏差原则）。purpose 全部改用 `V77-*`。执行前置 `auth_gate.require('dd_v77_n5_paired_v3')`。

## 5. 零调用验收结果（`dd_v77_dryrun/DD_V77_DRYRUN_RESULTS.json`，26/26 PASS）

- **T1 真实 fixture 回放**: n1 prompt 只含 2023_29、不含康达（F4 回归测试）；n3/n4 见 n1 且**隔离** n2；n5/n6 同时见 n1+n2；最小 prompt 1,943 字符（v2 回归值 66）。
- **T2 确定性全路径**: 23 请求按冻结清单执行，每条 prompt 的父集合与 spec **精确相等**（含反向隔离——父输出标记不得出现在非子节点 prompt 中）；GARBAGE 故障注入正确传播至全部 4 个 n9 prompt。
- **T3 调度保真**: 与 `dd_v74_request_manifest.json` 的 (node, model) 请求集合完全一致（8 glm53 / 15 flash）；执行序拓扑有效；A_alt n6/n7=flash、B_ib n6/n7=glm53、n9/n10 恒 flash。
- **T4 评分隔离**: `score_q` 签名不含动作/臂信息；文本跨臂换标签后分数随文本走。
- **T5 缓存合法性**: V77 与 V76 purpose 不相交；v2 的 n1/n2 prompt 同一性异常（sha 相等）已被 F4 打破且互相不等；运行内 23 个 (purpose, sha) 互异。
- **T6 预算重核**: 按实测 0.6295 字符/Token 比率 + 各角色输出上限，保守合计 65,776 Token；+30% 余量 ≈ 85.5K。

负面测试：语义门禁 PASS（10 日期/50 金额/5 处罚词）；无七字段记录时 Runner 抛 `PermissionError` 拒绝启动（auth_gate 已验证 FAIL-CLOSED）。

## 6. 缓存与复用裁决

v2 的 23 次调用**均不可复用**：n1/n2 违反 F4 且截断（F3）；n3/n4 为空输入产物；n5/n8 的 prompt 因上游变化而改变。第三次执行需完整 23 请求。

## 7. 第三次执行准入建议（待操作员授权）

| 项 | 值 |
|---|---|
| batch_name | `dd_v77_n5_paired_v3` |
| max_calls | 23（glm53 8 / glm53flash 15） |
| max_tokens | 100,000（保守估计 65.8K + 52% 余量；分模型 glm53 36K / flash 54K） |
| models | glm53, glm53flash（订阅，¥0 边际） |
| tasks | D_r1-n5-IB-vs-Alt-2rep（同 v74 清单结构） |
| 通过判据 | 生产路径数据契约 26/26（本文件第 5 节） |

**残留风险（如实声明）**: ① 修复后的 n1/n2 单文档抽取未经真实模型验证，抽取质量存在采样风险；② 2×2 重复的描述性设计不变，即使第三次执行成功，ΔQ 结论仍是探索性 n=2；③ 语义门禁与评分锚定同一证据库，评分对证据内事实的覆盖度依赖抽取完整性。
