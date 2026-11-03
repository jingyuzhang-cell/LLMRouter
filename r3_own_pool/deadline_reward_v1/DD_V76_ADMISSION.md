# DD_V76_ADMISSION — 证据绑定修复与配对重试准入（2026-10-30，零调用）

> 按 operator 裁决：修复证据绑定、测试语义门禁、重算预算。零模型调用。

## 一、证据绑定修复

| 项 | 修复前（BUG） | 修复后 |
|---|---|---|
| 加载方式 | `sorted(glob('evidence/texts/*.txt'))[:2]`（无身份验证 fallback） | **从 h1v8_docs/zeda_docs.json 显式加载**（SHA 核验 + 事件身份检查） |
| 事件身份 | 未验证 | **Fail-Closed**：非泽达易盛文档 → PermissionError |
| 评分参考 | 使用错误事件文本 | 使用泽达易盛处罚书文本 |

## 二、语义门禁测试结果（4/4 PASS）

| 测试 | 预期 | 结果 | 拒绝原因 |
|---|---|---|---|
| 正确泽达文书 | 通过 | **PASS** | — |
| 卓然文书 | 拒绝 | **PASS（正确拒绝）** | DOC_EVENT_MISMATCH + INSUFFICIENT_DATES |
| 空证据 | 拒绝 | **PASS（正确拒绝）** | NO_EVIDENCE |
| 评分者事件不匹配 | 拒绝 | **PASS（正确拒绝）** | SCORER_MISMATCH |

## 三、预算重算（关键发现：Token 上限需大幅调高）

**新证据（17,204 字处罚决定书）vs 旧证据（3,317 字公告）→ 输入 Token 增长 ~5.2×**

| 节点 | 调用数 | 输入 Token/次 | 小计 |
|---|---|---|---|
| n1, n2（extraction） | 各 1 | **~11,602** | 24,740 |
| n3-n6 | 1+1+2+4 | ~2,800 | 28,544 |
| n7-n10 | 4+1+4+4 | ~1,500-2,100 | 35,378 |
| **总计** | **23** | | **~87,662** |

| 项 | 旧值 | 新值 |
|---|---|---|
| max_calls | 23 | 23（不变） |
| max_tokens | 35,000 | **~114,000**（+30% 余量） |
| max_cash | ¥0 | ¥0（不变） |

**注意**：旧 35K Token 上限在新证据下**不足**——截断证据会重蹈 DD-V7.4 覆辙。Token 上限必须调高至 ~114K。

## 四、四字段授权建议

```
batch_name: dd_v76_n5_paired_v2
max_calls: 23
max_tokens: 114000
per_model_quota: glm53={calls:8, tokens:45000}, glm53flash={calls:15, tokens:69000}
max_cash: 0
allowed_models: glm53, glm53flash
tasks: D_r1-n5-IB-vs-Alt-2rep-v2-correct-evidence
```

## 五、全部门禁状态

| 门禁 | 状态 |
|---|---|
| 证据绑定修复 | ✅ FAIL-CLOSED 实现完成 |
| 语义门禁测试 | ✅ 4/4 PASS |
| 正确证据在库 | ✅ 2 份处罚书 SHA 核验通过 |
| 评分参考身份 | ✅ 使用泽达文本 |
| 请求预算重算 | ✅ 23 次 / 114K Token / ¥0 |
| IB/Alt 动作冻结 | ✅ 不变 |
| DAG 结构冻结 | ✅ D_r1 指纹 f34478eb |
| 原 23 次错误记录保留 | ✅ dd_v74_n5_paired/ 归档 |

## 六、验收判定

**全部硬门槛通过，READY for authorization。**

等待操作者七字段完整授权（batch_name=dd_v76_n5_paired_v2,
max_calls=23, max_tokens=114000）。

**付费 HOLD 维持。论文暂停。**
