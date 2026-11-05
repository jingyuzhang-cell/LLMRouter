# 质量增强与动态调度协同优化·联合方案设计（零调用 · 待审查授权）

## 一、v1.2 审计结论（已在 V12_AUDIT.md 完成的部分）

J 节点全程缺失、ZHANGZIDAO/KDX 池空为提示偏差、Z=Joint=R 折叠无分化空间——原"Joint 无增量"结论**撤销**，不作为策略无效证据。

## 二、四组联合对照（A/B/C/D，共享同任务/Gold/v2 评分器/异常条件）

| 组 | 质量机制 | 调度 | 回答 |
|---|---|---|---|
| **A** | 原有（plain E + 无 J） | 强 Static | 基线 |
| **B** | 改进（异构 E + J-v3 + v2 规范化） | 强 Static | B−A = 质量增强独立效应 |
| **C** | 原有 | 根因感知 Dynamic | C−A = 调度独立效应 |
| **D** | 改进 | 根因感知 Dynamic | D−B = 增强后调度增量；D vs B(C/L) = 质量等价下的效率 |

### 任务与调用矩阵（修正后）

**任务**：KANGMEI（主）、ZHANGZIDAO、KDX（辅）——证据充分且已有历史基线可复用。

| 项 | 组 | 调用 | 备注 |
|---|---|---|---|
| A: Static SINK ×2 | 3 任务 | 6 | A 池 = v1.2 冻结（SHA 已核） |
| B: Static SINK ×2 | 3 任务 | 6 | B 池 = 正确异构 E + **J-v3 注入**；KANGMEI=QP8R GLM 池+J、ZHANGZIDAO/KDX=ROUND2B 定向 DS 池+J |
| C/D: 场景 A（E 坍缩·KANGMEI） | C/D 各 4 臂 | 4 | NONE/R/π/Z=UPSTREAM 定向重抽（含下游 J→V→SINK 真实执行） |
| C/D: 场景 B（J 绑定错·E06） | C/D 各 3 对照 | 3 | Z=谓词感知重绑/UNKNOWN、Joint=重绑+下游 SINK、R=重复旧规则（负对照）；**J 确定性节点不适配 π** |
| 预留 | 传输/解析 | 2 | |
| **合计** | | **≤21 次 / ≤70K tokens / ≤¥0.12** | 逐次前置检查 |

### 场景 A 臂定义（E 层证据坍缩·KANGMEI QP8R 冻结检查点）

| 臂 | 动作 | 真实调用 |
|---|---|---|
| NONE | 保留空表，UNKNOWN 全弃 | 0 |
| R | 盲重试 SINK（同模型） | 1 |
| π | 盲换 GLM SINK | 1 |
| Z/Joint | UPSTREAM：GLM-E 定向重抽 e1 → J-v3 → V → SINK | 2 |

### 场景 B 臂定义（J 绑定异常·E06 H1/H2 冻结错误状态）

| 臂 | 动作 | 真实调用 |
|---|---|---|
| Z | J 谓词感知重绑 → 失败则 UNKNOWN 掩蔽（零调用） | 0 |
| Joint | Z 动作 + 下游 SINK 重答（DS） | 1 |
| R(负对照) | 重复原 name-match 绑定 → 同错误再入 SINK | 1 |

## 三、终点

**质量**：Q_all、Q_answerable、Critical TP、Wrong、Support、UNKNOWN、Evidence Coverage（六指标+coverage）
**效率**：实际总 C（含全部恢复+下游重执行）、端到端 L（真实墙钟，e0∥e1 取 max）
**判定**：B vs A 质量增强；D vs B 调度 C/L 增量（质量非劣=单槽分辨率）；场景级恢复成功率；Pareto 真实点。

## 四、停止规则

D 未在质量非劣下降低 C 或 L（任务级配对双侧 p<0.10）→ 如实承认协同无增量；不追加条件。

**待授权后执行；零调用状态保持。**
