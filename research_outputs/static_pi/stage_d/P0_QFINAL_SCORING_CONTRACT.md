# P0: Q_final 结构性 NULL 根因分析与评分合同冻结方案（零调用；2026-11-04）

---

## 一、Q_final = NULL 的三层根因（terminal_quality v1.2.3）

| # | Blocking 条件 | 层面 | 根因 | 可否解除 |
|---|---|---|---|---|
| 1 | `GOLD_CONTRACT_INVALID_VALUE:E3` | **合同层** | E3 value `"2(公司+自然人王勇)"` 为 number 类型但含文字 → 合同结构违规 | ✅ V3 已修正（→`"2"`） |
| 2 | `QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED` | **评分器设计** | v1.2.3 需 relevance 维度评分但无内置 relevance judge | ❌ 需外部通道（设计缺陷） |
| 3 | `DELIVERY_INVALID_SEMANTIC_QUALITY_UNAVAILABLE` | **投递层** | SINK 输出 doc_id 用节点名（E1/E2）而非文档 ID（D1/D2）→ R_delivery=0 | ⚠️ 需 A1 DOCMAP 适配器 |

**三层叠加 → Q_final 192/192 均为 NULL。这不是模型能力问题，是评分管线的结构性阻断。**

## 二、三条解除路径

| 路径 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A: 修复 v1.2.3 | V3 合同 + DOCMAP + relevance judge | 保留历史可比性 | 工程量大；relevance judge 需新设计校准 |
| **B: 用 Q_raw 代替** | Q_raw = TP+证据+完备性（无 relevance/delivery gate） | 零改动；192 条已有数据 | 不是"正式 Q"；需声明 |
| **C: 新实验新合同** | 为三臂实验定义新 Q_terminal，直接用任务合同 Gold | 干净起点；无 NULL 问题 | 需新评分器校准 |

## 三、冻结方案

### 推荐：**路径 C（新实验）+ 路径 B（历史基线）**

**新三臂实验的评分合同**（路径 C）：

```
Q_terminal = w₁ × FactCorrectness + w₂ × EvidenceSupport + w₃ × Completeness
```

- **FactCorrectness** = 逐槽位值匹配率（与 Gold 合同值精确/归一比较）
- **EvidenceSupport** = 证据引用合规率（doc_id 正确 + quote 逐字命中）
- **Completeness** = 已断言槽位数 / 合同总槽位数
- **权重**：w₁=0.5, w₂=0.3, w₃=0.2（预冻结，可做敏感性）
- **不包含**：relevance judge、delivery gate（避免 v1.2.3 的结构阻断）
- **Gold 来源**：独立任务合同（MVR2/P11 式 required_facts），非 PHASE2B 合同
- **评分器**：新建（或复用 MVR2 编码归一 + P11 state_scorer 模式）

**历史基线**（路径 B）：
- Stage D 192 条的 TP（旧合同 + V3 + A1 三口径）作为诊断级历史基线
- 明确声明：TP 非正式 Q_final；Q_final 因评分器结构限制不可用

### 新评分合同的验证条件

| 条件 | 通过标准 |
|---|---|
| 区分度 | 正确答案 Q > 错误答案 Q |
| 非 NULL | ≥90% 执行产出非 NULL Q_terminal |
| 与人工判断一致 | 抽检 10 条与人工判断一致率 ≥80% |
| 三臂可比较 | 同一评分合同对三臂公平适用 |

---

## 四、对三臂实验的影响

| 此前 | 修正后 |
|---|---|
| 使用 terminal_quality v1.2.3 → Q_final 全 NULL | 使用新评分合同 → Q_terminal 非 NULL |
| 依赖 PHASE2B 合同的 delivery gate | 独立任务合同，无 delivery gate 阻断 |
| relevance 维度无法评分 | 不包含 relevance 维度 |

**解除 Q_final NULL 后，三臂实验的终端质量评分首次可产出有效结果。**

---

## 五、P1（独立任务选择）的前置条件

| 条件 | 候选 |
|---|---|
| 非 PHASE2B（避免历史耦合） | MVR2 / P11 / 新任务 |
| 有独立 Gold 合同 | MVR2 (27 槽) ✅ / P11 (17 项) ✅ |
| 评分可产出非 NULL | MVR2 编码归一 ✅ / P11 state_scorer ✅ |
| DAG 有分支+汇合 | MVR2 (E×3→J1→J2→SINK) ✅ |
| 基线足够低（有改善空间） | MVR2 Static ~21% ✅（vs PHASE2B 57%） |
| 模型池异构可行 | 需验证（MVR2 J1 用 GLM 但有截断风险） |

**推荐：MVR2 元道（满足全部条件，且 Stage C 已有全部提示词和管线）**
