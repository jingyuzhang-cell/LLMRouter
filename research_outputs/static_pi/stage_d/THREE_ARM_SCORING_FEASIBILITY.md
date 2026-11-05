# 三臂评分可行性判定（零调用；2026-11-04）

**纠正声明**：此前 DATA_ADMISSION 更新中"Phase-Pi V2 包含三臂 (Static + Fixed-Composite + Proposed-Dynamic)"的说法**错误**。Phase-Pi V2 的臂为 Static-GLM / Static-DS / Retry-only / Z-only / π-only / Joint，与 M8 所需三臂**名称和语义均不匹配**。

---

## 一、Phase-Pi V2：不可作为三臂 VAL ❌

| 项 | 实际情况 |
|---|---|
| 臂 | Static-GLM / Static-DS / Retry-only / Z-only / π-only / Joint |
| 与三臂映射 | **不可映射**（"Joint" = Z+R+π 机械组合 ≠ 诊断驱动联合调度） |
| Q_final | **36/36 均为 NULL** |
| TP 中位 | Static-GLM 6.0 / Retry 6.5 / Joint 6.0（Joint 无增益） |
| 材料正确性 | Joint 19.0 vs Static 15.5（诊断改善但非正式评分） |
| 可绑定证据 | Joint **19/138** vs Static **45/138**（模型切换恶化证据） |

**结论**：Phase-Pi V2 是真实的六臂机制实验，可提供探索性数据，但**不可作为 M8 三臂 VAL 数据**。

## 二、Stage D 192-run：可作为三臂比较数据源 ✅（有条件）

### 臂映射

| M8 所需臂 | Stage D 臂 | 映射依据 |
|---|---|---|
| Static | Static | 完全匹配（无恢复动作） |
| Fixed-Recovery | Fixed-Composite | 语义等价（始终执行修复动作集） |
| Joint-Dynamic | Proposed-Dynamic | 语义等价（诊断驱动联合调度） |

### 评分状态

| 项 | 状态 |
|---|---|
| 执行 | 192/192 真实 ✅ |
| 评分管线 | Stage A 对齐后三口径均有效 ✅ |
| Proposed vs Simple | old p=0.0009 / V3 p=0.0009 / A1 p=0.0061 ✅ |
| Q_final | 结构性 NULL（不影响 TP 比较）⚠️ |
| R1 安全 | **FAIL**（54/1152 倒退，主体=基础设施 42/54）⚠️ |

### 三臂已有结果（从 Stage D 提取）

| 臂 | TP（旧合同） | TP（V3） | 成本 | Makespan |
|---|---|---|---|---|
| Static | 11.25 | 14.44 | ¥0.0363 | 97s |
| Fixed-Composite | 11.84 | 13.81 | ¥0.0403 | 143s |
| **Proposed-Dynamic** | **13.16** | **15.06** | ¥0.0418 | 165s |

### 条件限制

1. **子集分析**：Stage D 是六臂实验，提取三臂做比较是子集分析（需标注非预注册三臂设计）
2. **Q_final 全 NULL**：TP 是诊断指标非正式 Q（结构性阻断，不因分析而改变）
3. **R1 FAIL**：安全门禁未通过，不能宣称生产级可靠性
4. **收益场景依赖**：质量收益主要来自 S4 格式异常（+5.38 TP）；S3 仅 +1.88

## 三、π 独立贡献确认

| 证据 | 结果 |
|---|---|
| 真实换模是否执行 | Stage D v2 执行器中 swap 动作**退化为同模型重跑**（AROUT 覆盖） |
| v3 执行器修复后 | J1 swap **真实切到 DS**（mock 16/16 验证） |
| B-4 四臂实验 | A2 诊断换 TP=14 vs A0 不换 TP=0（+14） |
| Stage C MVR2 | Proposed 4/4 链路 vs Best-Single 2/4 |
| Stage C P11 | 全 DS 路由→无替代模型→诊断换模无法执行（0/17） |
| **终端传导** | MVR2 Proposed TP **低于** Static（恢复≠正确） |
| **Phase-Pi V2** | Joint 可绑定证据 **19/138** < Static **45/138**（换模恶化证据） |

**结论**：π 的独立贡献在**节点级恢复**有强证据（+14 TP），但在**终端质量传导**上证据混合——PHASE2B 正向（+14）、MVR2 负向（TP 低于 Static）、Phase-Pi V2 证据恶化（19 vs 45/138）。**不能宣称 π 独立贡献已充分证明。**

---

## 四、统一三臂评分可行性判定

| 条件 | Phase-Pi V2 | Stage D | 判定 |
|---|---|---|---|
| 三臂存在 | ❌ 臂不匹配 | ✅ 臂匹配 | Stage D 唯一可行 |
| 执行真实 | ✅ 36 次 | ✅ 192 次 | 均真实 |
| 评分有效 | ❌ Q_final 全 NULL | ⚠️ TP 有效但 Q_final NULL | TP 可用作诊断 |
| 配对完整 | ✅ 同任务同条件 | ✅ 同任务同条件 | 均可配对 |
| 统计支持 | ❌ Joint 无增益 | ✅ Proposed vs Simple p<0.001 | Stage D 有支持 |
| 成本时延 | 有记录 | 有记录 | 均可核算 |
| 安全通过 | 未审计 | ❌ R1 FAIL | 均未通过 |

**判定：Stage D 是唯一可形成有效三臂比较的数据源，但需标注四个条件限制（子集分析/Q_final NULL/R1 FAIL/场景依赖）。**

---

## 五、对 M8 v0.2 的影响

| 项 | 影响 |
|---|---|
| CAP 节点层代理 | ✅ 不受影响（380 行独立于三臂问题） |
| VAL 终端层校准 | ⚠️ 只能用 Stage D TP（诊断级）作校准；不能用 Q_final（全 NULL） |
| Phase-Pi V2 | ❌ 从 VAL 候选中移除 |
| 三臂标签 | 必须用 Stage D 原始臂名（Static/Fixed-Composite/Proposed-Dynamic），不做映射重命名 |

---

## 六、对操作者核心问题"三臂评分问题查透"的回答

1. **Phase-Pi V2 不能形成三臂比较**——臂名和语义不匹配，Q_final 全 NULL。

2. **Stage D 可以形成三臂比较**——Static / Fixed-Composite / Proposed-Dynamic 均存在且有配对评分。但结果是**子集分析**而非预注册三臂设计。

3. **三臂比较的核心结果**（Stage D S3+S4 16 对）：
   - Proposed > Fixed-Composite：TP +1.32（方向正向，未达统计显著）
   - Proposed > Static：TP +1.91, p=0.0002
   - Fixed-Composite > Static：TP +0.59（微弱）

4. **缺失**：没有一个**预注册的、独立任务上的、Q_final 有效的**三臂对照实验。这是论文核心命题的最重要证据缺口。

5. **π 独立贡献**：节点级强（+14 TP）但终端传导混合（正向+负向+证据恶化）——**不能宣称已证明**。
