# DAG_CONTRACT_V2_RESULT — 事实传递合同修复与零调用回归（2026-10-27）

## 一、旧合同事实损失的准确定位

**瓶颈位置**：`merge → verify → sink` 的旧边结构中，sink **只消费 verify 输出**。
verify 输出格式 `{item, doc_a, doc_b, verdict, note}` 不包含原始事实数据。

**量化**（Flash verify，欢瑞校准上游）：
- Merge 节点产生 31 条事实（main 13 + sup1 7 + sup2 11）
- Verify 输出 7 条核验判定，仅含 2 条关键事实引用
- **18 条关键事实（90%）在 verify→sink 传递中丢失**

**根因不是模型能力差异**（Flash verify 的 D1 事实正确性=1.00，D2 一致性判定=1.00），
而是 **verify 节点的输出契约不允许事实通过**。

## 二、新 DAG/合同设计（`dag_contract_v2.py`）

```
旧：n_main/n_sup1/n_sup2 → merge → verify → sink
                              （verify 独占 sink 输入 = 信息瓶颈）

新：n_main/n_sup1/n_sup2 → merge ──────────→ sink（完整事实集）
                              ↓                    ↑
                           verify ──────────────→（核验判定）
```

**关键变更**：
1. **新增边 merge→sink**（事实直通通道）——sink 直接消费完整事实集
2. **verify 只输出判定**：`{fact_id, verdict, note}`——不做事实搬运工
3. **sink 同时消费两者**：完整事实集（来自 merge）+ 核验判定（来自 verify）
4. **verify 失效降级**：sink 消费事实集 + 全部标记 UNVERIFIED（合法降级，
   不丢失事实）

## 三、零调用回归结果（ALL PASS，7 项测试）

| 测试 | 结果 | 详情 |
|---|---|---|
| T1 事实通过率 | **✓ 100%** | 31/31 条 merge 事实到达 sink（旧=10%） |
| T2 关键事实可用 | **✓ 16/20** | 缺失 4 条为上游抽取未提取（非传递丢失） |
| T3 判定-fact 对应 | ✓ | 每条事实有 verify_status（checked/UNCHECKED） |
| T4 verify 失效降级 | ✓ | sink 仍获全部 31 条事实（标 UNVERIFIED） |
| T5 恢复闭包 | ✓ | closure(n_sup2)={merge,verify,sink} 不变 |
| T6 缓存版本 | ✓ | n_sup2 恢复→merge hash 变化→verify/sink 需重执行 |
| T7 策略一致性 | ✓ | 新边结构对全部策略统一生效 |

**关键事实缺失 4 条的归因**：
- `2026年9月18日`、`2026年7月14日`：说明会/业绩预告公告日期——上游 DS 抽取
  **未提取**（非传递丢失）
- `处罚`、`虚假`：监管处罚相关关键词——立案告知书阶段**尚未出现**处罚决定
 （业务上合理——需等待正式处罚决定公告）

## 四、对 R/π 联合动作空间的影响

| 方面 | 旧合同 | 新合同 | 影响 |
|---|---|---|---|
| 恢复闭包 | closure(n_sup2)={n_sup2,verify,sink} | **不变** | R 的选择空间不受影响 |
| 模型选择 | verify 模型决定 sink 可用事实 | **sink 可用事实不再依赖 verify 模型** | π 的质量影响被隔离到判定质量 |
| verify 失效 | sink 无输入→完全降级 | sink 有事实+UNVERIFIED | 降级损失减小 |
| 质量传播 | verify 是瓶颈→π 影响 Silver | verify 只影响判定质量 | **混合 π 的质量差异可能减小** |

**新合同下 Flash verify 的劣势减轻**：Flash verify→sink 的 Silver 低（0.150）主要因
信息瓶颈；新合同下 sink 直接从 merge 获取事实，Flash verify 的核验质量（Verify-Q 高）
不再被事实丢失拖累——**混合 π 的真实价值需在新合同下重新评估**。

## 五、下一次真实端到端验证需求

| 项 | 数值 |
|---|---|
| 最小验证 | 2 次 sink 调用（新合同下的 sink prompt 消费事实集+判定） |
| 上游 | 使用已有冻结 DS 校准抽取（merge 零调用） |
| Flash sink | 1 次（¥0 订阅）——检验新合同下 Flash 链 Silver 是否提升 |
| DS sink | 1 次（~¥0.003）——同输入 DS 链基线 |
| 总计 | **2 次调用 / ~¥0.003** |
| 判别 | 新合同下 Flash sink Silver vs 旧合同 0.150——如果显著提升，
  证明信息瓶颈是 Flash 链低质的主因 |

**付费 HOLD 保持。**
