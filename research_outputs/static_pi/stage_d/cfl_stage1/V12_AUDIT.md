# v1.2 零调用终审审计（第一步，按操作员指令执行）

## 发现 1：P2 强 Static 的 E 池来源正确（SHA 全验证）

| 任务 | E 分配 | 池 | SHA 验证 |
|---|---|---|---|
| KANGMEI | GLM | 37 | ✓（QP8R GLM 池） |
| MVR1 | DS | 17 | ✓ |
| E06 | GLM | 14 | ✓ |
| ZHANGZIDAO | DS | 0 | ✓（ROUND2B 定向 DS 池 dedup 后为 0——**本轮探针的 DS-E 输出是 plain prompt（非定向）而非 ROUND2B 的定向重抽**，故池空） |
| KDX | DS | 0 | 同上 |
| YJT | DS | 0 | 三模型均零 |

## 发现 2：**J 节点全程缺失——这是 v1.2 最大执行偏差**

P2 prompt = `bnew_prompt(sel=True)` = 逐条表 + SEL 约束，**但无 j_block 注入**。审计确认：v12 runner 从未调用 `build_j_rows` / `joint_bind_v2/v3`。这意味着：
- KANGMEI 0.214（vs 历史 DS+J 链 0.857）**不是"GLM-E 不行"的证据——是 J 缺失的证据**；
- ZHANGZIDAO/KDX 的 DS 探针池=0 也是探针用了 plain prompt 而非 ROUND2B 已验证的定向 DS-E 池。

## 发现 3：折叠设计 Z=Joint=R 完全掩盖分化

P3 只区分了 R(DS) 和 π(GLM)，Z 和 Joint 与 R 逐字节相同——预注册的折叠在执行失败型异常下成立，但**本轮只注入了 SINK 截断一种**，E 层证据空/绑定错等根因型异常未测。

## 修复方案（待授权，零调用优先）

1. **P2 重跑**（用 J-v3 + 正确池）：KANGMEI/GLM 池 + J、ZHANGZIDAO/KDX 用 ROUND2B 定向 DS 池（11/18 行）+ J-v3 → SINK×2/任务 = 8 次；
2. **P3 补根因型异常**：至少 E 层证据空（KANGMEI 历史 QP8R 池）与 J 绑定错（E06 H1/H2）各 1 事件 × 4 臂 = 8 次；
3. 合计 ~16 次 + 预留 2 = **硬顶 18 次 / 60K tokens / ¥0.10**。

**关键结论：v1.2 的"Joint 无增量"结论无效（J 缺失 + 池空为执行偏差），不是模型能力上限的证据。**
