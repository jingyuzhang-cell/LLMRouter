# KDX_NONE_UTILITY_FIX_REPORT — NONE 效用函数修复报告（零付费）

## 1. 发现的 bug

**V1 代码**：`JS.choose()` 中 NONE 得分硬编码为 `-1`。
**问题**：当 w_q 低时，恢复动作得分 ≈ -w_c×cost（小负数），NONE 的 -1 可能优于高成本恢复
→ **产生错误的放弃激励**。

**V2 尝试**：给所有 feasible 动作加 `completion_bonus=100`——但 NONE 也获得了 bonus
→ NONE(100.0) vs LOCAL(~99.8) → NONE 仍然赢。**回归测试捕获了此 bug。**

## 2. V3 修复（已通过全部回归测试）

**设计原则：词典序优先级**
1. **完成优先**：只有非 NONE 动作获得 COMPLETION_BONUS=100.0
2. **质量次优**：Q_output_ratio×10.0
3. **成本/时延**：微弱惩罚项

**NONE 语义（五种状态明确区分）**：

| 状态 | 定义 | 得分 | 发生条件 |
|---|---|---|---|
| NO_RECOVERY_NEEDED | 无故障 | 不进入决策 | 正常流程 |
| NO_FEASIBLE_ACTION | 全部候选被约束拒绝 | 0（无 bonus） | 预算/截止/质量全不过 |
| SAFE_ABANDON | 质量代理判定不可行 | 0 + 审计日志 | q_min 过滤后无可用模型 |
| RECOVERY_FAILED | 恢复执行后仍失败 | 0 + 浪费成本 | 执行层处理（当前未模拟） |
| TASK_COMPLETE | 全部节点完成 | 标准 Q/C/L 评分 | 正常完成 |

## 3. Q 代理地板移除

原 `gs()` 函数对 Q_output_ratio 施加 `max(Q, 0.01)` 地板——导致 Q=0 的模型（如 Flash 做
跨源核查）永远不被质量约束过滤。修复后 Q=0 保持为 0，允许 q_min>0 的质量门禁正确工作。

**同时明确**：Q_output_ratio=0 不等于模型客观上无完成能力——可能是提示词适配问题。
因此 q_min 的推荐值为 0.0（不自动过滤），仅在有硬约束依据时使用 q_min>0。

## 4. 回归测试（5/5 PASS）

| 测试 | 预期 | 实际 | 状态 |
|---|---|---|---|
| t1 DS 屏蔽, q_min=0 | 找到动作 | LOCAL | ✓ |
| t1 GLM 屏蔽, q_min=0 | 找到动作 | LOCAL | ✓ |
| t5 GLM 屏蔽, q_min=0 | 找到动作（Q=0 模型可用） | LOCAL | ✓ |
| t5 GLM 屏蔽, q_min=0.1 | NONE（质量门禁） | NONE | ✓ |
| budget=1 | NONE（预算不可行） | NONE | ✓ |
