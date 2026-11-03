# Q0_ROOT_CAUSE_AUDIT — JOINT Q=0.000 的根因（2026-10-27，零调用）

## 发现：JOINT 的 sink 输入仅 118 token（SEQ-π→R 为 980 token）——facts_json 几乎为空

| 臂 | sink 输入 | sink 输出 | Silver |
|---|---|---|---|
| SEQ-π→R (repair_sup2) | **980 token** | 593 token | 0.550 |
| JOINT (repair_both) | **118 token** | **1 token** | **0.000** |

**JOINT 的 sink 收到的事实集几乎是空的**——不是"噪声事实淹没信号"，是**根本没有事实到达 sink**。

## 根因：`json.loads(dv)` 在 markdown 围栏输出上静默失败

`facts_json` 构造代码对每个 `n_` 前缀的输出做 `json.loads(dv)` → 若输出被 markdown
围栏（\`\`\`json ... \`\`\`）包裹，解析失败 → `except: pass` → **该来源的所有事实被
静默丢弃**。

- **n_main（Flash 前缀输出）**：有 markdown 围栏 → 解析失败 → 事实丢失
- **n_sup1（Flash 重执行输出）**：有 markdown 围栏 → 解析失败 → 事实丢失
- **n_sup2（DS 重执行输出）**：可能也有围栏或格式问题 → 事实丢失

结果：`all_facts = []` → `facts_json = "[]"` → sink 收到空事实集 + 空核验判定 +
提示词模板 = **118 token**。

**在 SEQ-π→R 中**，同样的代码从 n_sup2（DS）成功解析出事实（~980 token）——
说明 DS 输出在那种情况下没有围栏，或围栏被正确处理。

## 为什么这不是"恢复 n_sup1 导致质量下降"的研究发现

**Q=0.000 是实现缺陷，不是质量传播现象。** 恢复 n_sup1 本身不会使 n_sup2 的事实
消失——丢失发生在 facts_json 构造层，与恢复决策无关。

## 修复

使用已有的 `parse_a()` 函数（正确剥离 markdown 围栏）替代裸 `json.loads(dv)`：
```python
# 修复前（有 bug）：
items = json.loads(dv)  # markdown 围栏 → 失败

# 修复后：
items = parse_a(dv)  # 剥离围栏 → 正确解析
```

**影响范围**：上一轮 CASH30 的所有 repair_both 臂（JOINT/π-only/Alternating）
的 Q=0.000 都受此 bug 影响。STATIC/SD-FC（repair_sup2）和 SEQ-π→R（repair_sup2）
不受影响（它们没有触发同样的代码路径问题）。

## 对实验结论的修正

| 原结论 | 修正后 |
|---|---|
| "repair_both 质量 0.000，repair_sup2 质量 0.550" | **无效比较**——repair_both 的 sink 收到空事实集 |
| "额外恢复 n_sup1 导致质量下降" | **无证据**——Q=0 是 facts_json 构造 bug |
| "JOINT 联合搜索选择了错误的恢复方案" | **不能判定**——JOINT 的选择被 bug 掩盖 |
| "SEQ-π→R 胜出 +0.51" | **仍有效**——但其对手（JOINT）被 bug 削弱 |

**修复后需重跑才能得出有效结论。**

## 预测失准审计（任务二）

JOINT 的预测器认为 repair_both(q̂=0.750) > repair_sup2(q̂=0.700)：
- 预测假设"多修复 → 多事实 → 高质量"
- **未建模**：额外节点的输出可能使 facts_json 构造路径更容易出错
- **未建模**：低相关性事实（n_sup1 仅 13% 独有探针）可能不增加终端 Silver

但这不是预测器的缺陷——**预测器假设代码正确运行**。根因是实现层的 facts_json
解析失败，预测器无法预见运行时 bug。

**付费 HOLD 保持。**
