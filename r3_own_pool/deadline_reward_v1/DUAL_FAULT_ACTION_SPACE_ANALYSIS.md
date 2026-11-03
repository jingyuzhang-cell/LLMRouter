# DUAL_FAULT_ACTION_SPACE_ANALYSIS — 双故障 DAG 零调用枚举（2026-10-27）

## 一、双故障 DAG 与业务依据

**故障场景**：n_sup1（说明会公告）与 n_sup2（业绩预告）**同时独立失效**。
业务真实性：两类公告格式/内容差异大（说明会=日程性文本、业绩预告=金额密集表格），
各自独立发生截断/契约违反的可能性真实存在。

**R 选项（依赖合法，5 种）**：
- accept（双占位降级）
- repair_sup1（仅修说明会分支）
- repair_sup2（仅修业绩预告分支）
- repair_both（双分支修复）
- full（全 DAG 重执行）

**动作空间**：5 种 R × 各自 π 子空间（2^节点数）= **68 个联合动作**。

## 二、七策略枚举结果（D=60s，预测质量模型）

| 策略 | 最终动作 | eU | 与 JOINT 差 |
|---|---|---|---|
| R-only | accept+Flash | +0.123 | **−0.553** |
| SEQ-R→π | accept+Flash | +0.123 | **−0.553** |
| **π-only** | repair_both+全DS | **+0.676** | **0** |
| **SEQ-π→R** | repair_both+全DS | +0.676 | **0** |
| **Alternating** | repair_both+全DS | +0.676 | **0** |
| **JOINT** | repair_both+全DS | +0.676 | — |
| Oracle | repair_both+全DS | +0.676 | = |

**结论：在当前质量模型下，JOINT ≡ π-only ≡ SEQ-π→R ≡ Alternating。**
只有 R-only 和 SEQ-R→π（Flash 先行检查）失败——与单故障时相同的模式。

## 三、为什么联合搜索仍无独有优势

**根因：质量模型的单调性。** 在当前估计中：
- DS 在**每个节点**上都不劣于 Flash（抽取质量更高、verify/sink 更快）
- 因此最优 π 是"全 DS"——任何考虑到 DS 的策略都能找到
- 混合 π（如 DS 抽取+Flash verify）不优于全 DS

**纯 DS (eU=+0.676) > 最佳混合 π (eU=+0.671) > 纯 Flash (eU=+0.110)。**

## 四、联合搜索真正需要什么条件（分析）

联合搜索优于所有顺序/交替策略，需要搜索空间中存在**任何顺序策略无法到达的
局部最优陷阱**。具体条件：

### 条件 A：混合 π 是最优的（非全 DS 也非全 Flash）

如果 Flash 在 verify 上质量更高（校准数据支持：Flash verify 5-12 条 vs DS 3-4 条），
则最优可能是：
```
π* = {n_sup1: DS, n_sup2: DS, verify: Flash, sink: DS}
```
- SEQ-π→R 先假设全 DS → 不会尝试 Flash verify
- π-only 的 Flash→DS fallback → 也不会产生混合
- **只有联合枚举才能发现混合最优**

### 条件 B：R 选择改变 π 最优

如果 repair_sup2 的最优 π 是 {sup2:DS, verify:Flash}，而 repair_both 的最优是
{sup1:Flash, sup2:DS, verify:DS}——则先定 R 再定 π 或先定 π 再定 R 都会选错。

### 条件 C：资源竞争

Flash 和 DS 各有 K=1 资源槽，如果两个恢复节点都需要 Flash，会产生排队延迟
——联合搜索可以将一个分配给 DS 避免竞争，顺序策略不会考虑这种重组。

## 五、验证条件 A 的最小需求（零调用推断 + 付费验证）

从校准数据推断 Flash verify 是否真的质量更高：
- 欢瑞 Flash verify：5 条核验项 vs DS 3 条
- 卓然 Flash verify：12 条核验项 vs DS 4 条
- **但条目数≠质量**——Flash verify 的额外条目是否转化为终端 Silver 提升未知

**最小付费验证**：1 次 Flash verify + Flash sink（在已有的 DS 抽取输出上），
对比已有的 DS verify + DS sink 结果——~2 次调用 / ~¥0 / 即可判断 Flash verify
的终端质量是否更高。如果 Flash verify 质量 > DS verify，条件 A 成立，
混合 π 场景可用。

## 六、效用函数审查

卓然暴露的问题：全迟到时 eU 将质量置零，排序由 token/迟到决定——高质量动作
被惩罚。**建议新实验冻结双口径**：
- 原始 eU（当前公式，保留历史可比性）
- **修正 eU**：全迟到时质量贡献不完全归零，改为 `q * (1 - late_ratio * 0.5)`
  （迟到越多质量折扣越大，但不完全取消）
- 报告两种口径的敏感性分析

## 七、交付总结

| 交付项 | 结果 |
|---|---|
| 新 DAG 动作规模 | 68 联合动作（5R × 各自π） |
| 七类策略动作对比 | JOINT≡π-only≡SEQ-π→R≡Alt；R-only/SEQ-R→π 差 −0.55 |
| JOINT 独有优势状态 | **当前质量模型下不存在**（单调性→全DS最优→任何DS-aware策略等价） |
| 业务依据 | ✓ 双公告独立失效真实可能 |
| 最小验证需求 | 2 次 Flash verify/sink 调用（判断混合π是否最优） |
| 效用函数建议 | 双口径（原始+修正迟到质量折扣） |

**付费 HOLD 保持。**
