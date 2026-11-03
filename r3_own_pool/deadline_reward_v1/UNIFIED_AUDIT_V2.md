# UNIFIED_AUDIT_V2 — 完整行为审计与反馈机制修正设计（2026-10-30，零调用）

## 一、完整审计结果（回应 operator "π 相同不自动意味着行为完全相同"）

| 维度 | frozen vs feedback 差异 | 说明 |
|---|---|---|
| **模型选择 π** | **0/96 不同** | 两种画像选择了完全相同的模型 |
| **恢复范围 R** | **0/24 不同** | 两种画像选择了完全相同的 R 集 |
| **Z 结构决策** | 均为 IDENTITY（本批无结构替代） | 无差异 |
| **提示词哈希** | 50 不同 / 4 相同 | 上游 LLM 输出随机不同 → 下游提示词随之不同 |
| **证据注入** | 传输级 f2=15,308 字符；证据失效 f2=12,284 | 证据失效确实移除了一份文档（差 3,024 字符） |

**结论**：调度决策（π、R、Z）完全一致；提示词差异来自上游 LLM 随机
输出传导（非调度差异）。**Q 差异确实主要由生成随机性解释**——但严谨
表述为"调度决策等价的两臂，其 Q 差异不能归因于画像更新"。

## 二、根因：为什么反馈更新是空操作

当前 `predict_pi` 决策规则：
```python
if total + glm_cost <= budget and glm_q > flash_q:
    assign[n] = 'glm53'  # GLM 质量总是更高 → 永远选 GLM
else:
    assign[n] = 'flash'  # 只在预算不够时被迫选 Flash
```

**问题**：GLM 质量估计在两种画像中均未变且始终高于 Flash——
更新 Flash 的参数不影响"GLM > Flash"这一不等式。反馈是空操作。

## 三、修正设计：三种使反馈真正影响决策的机制

### 机制 A：联合 Q/C/L 效用优化（替代纯质量贪心）

```python
# 当前（无效）：
pick GLM if glm_q > flash_q and budget allows

# 修正：优化效用而不仅是质量
utility(m, node) = q̂(node, m) × w_Q
                 − (cost(m, node) / C_max) × w_C
                 − (latency(m, node) / D_remaining) × w_L
assign[n] = argmax_m utility(m, n)  s.t.  Σcost ≤ C_max, Σlat ≤ D
```

**反馈如何生效**：当反馈更新表明 Flash 在某类节点上实际时延 1.5×
于估计值，时延惩罚项增加，效用比较可能翻转——某节点从 Flash 切换
到 GLM（GLM 更快）或反之（Flash ¥0 现金成本优势放大）。

### 机制 B：预算约束下的真实分配问题

```python
# 当前：budget=5000 足够全选 GLM → 无选择空间
# 修正：budget 由任务约束决定（如 ¥0.02 现金上限 + 25s 剩余时延）
# → 全 GLM 不可行 → 必须在某节点上选 Flash → 反馈决定选哪些节点
```

### 机制 C：节点类型级质量画像更新（替代全局参数微调）

```python
# 当前：全局调 Flash 质量估计 → 无效
# 修正：从 Stage-B/C 真实数据提取节点类型级画像：
#   report: GLM cite=1.00, Flash cite=0.00 → report 必须用 GLM
#   index: GLM cite=1.00, Flash cite=1.00 → Flash 免费 → 用 Flash
#   timeline: GLM Q=0.75, Flash Q=0.60, 但两者 lat 差 1.2s → 边界
```

## 四、下一步（不立即执行，待授权后一次性运行）

1. **实现机制 A+B+C**（零调用代码工作）
2. **在 2 个新的独立任务**（非 T-P3、非 T-P2/T-D1——需从外部获取或
   扩充冻结池）上统一验证：
   - frozen vs feedback（机制 A+B+C 更新后是否真正改变决策）
   - 6 策略完整对照（含 Simple-Dynamic）
   - 2 种异常 × ≥3 重复
3. **判定标准**：feedback 改变 ≥30% 节点决策 AND 改变后的 Q/C/L
   不劣于 frozen（反馈有效性的最低门槛）

**付费 HOLD 维持。论文暂停。**
