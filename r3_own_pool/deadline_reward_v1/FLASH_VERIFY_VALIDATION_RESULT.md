# FLASH_VERIFY_VALIDATION_RESULT — 2 次 Flash verify/sink 能力核验（2026-10-27）

授权合规：**2/2 次调用（上限2）/ ¥0.0000（订阅）/ 零异常**。付费 HOLD 恢复。

## 同上游 Flash/DS verify 对照（冻结 DS 校准抽取输出，公平配对）

| 指标 | Flash verify | DS verify（校准基线） |
|---|---|---|
| 核验条目数 | **7** | 3 |
| 时延 | 16.9s | 1.7s |
| Token | 2100 in / 593 out | 308 in / 271 out |

**Flash verify 产出 +4 条核验项**（7 vs 3），但时延和 token 都约为 DS 的 4-10 倍。
核验内容：Flash 发现了公告编号互补性、披露时间线、经营状态表述、非经常性损益的
UNRESOLVED 状态——DS 的 3 条更简洁但可能遗漏了跨文档互补关系。

## 终端 Silver（注意限制）

| 链 | Silver | 说明 |
|---|---|---|
| Flash verify→Flash sink | **0.150**(3/20) | 本轮 |
| DS verify→DS sink（D=60 运行） | 0.850(17/20) | **不同上游**（D=60 运行自身的抽取，非校准抽取） |

**不可直接比较**：上游不同。且本轮同时改变了 verify 和 sink 两个节点。

## 核心发现

### 1. Flash verify 确实产出更多核验条目（7 vs 3）

这支持条件 A 的前提——Flash verify 在核验深度上可能优于 DS。但：

### 2. Flash verify→sink 链的 Silver 反而很低（0.150）

与 Flash 校准链的 sink Silver（从 CROSS_FLASH_CALIB 的推断——当时 Flash 链条也
很低）一致。可能原因：
- Flash sink 在短输入（593 token verify 输出）上生成过于简洁的结论
- **更深层原因**：Flash 的 verify/sink 输出**没有引用足够的金额/日期原文**——
  7 条核验条目主要是**定性描述**（"互补"、"一致"），而非包含可被 Silver 评分
  匹配的具体金额/日期

### 3. 混合分配的可行性评估

**如果** Flash verify 质量确实高于 DS verify（更多核验条目），混合 π =
{extract:DS, verify:Flash, sink:DS} 理论上可能优于全 DS——**但本轮证据不支持**：
Flash verify→sink 链 Silver 仅 0.150，远低于全 DS 链（D=60 的 0.850）。

**可能的原因**：Flash verify 的额外条目是**结构性核验**（"一致"/"互补"）而非
**事实性核验**（"金额 X 与金额 Y 一致"）——前者对终端 Silver（关键词匹配）无
直接贡献。

## 对 68 动作联合搜索模型的影响

| 假设 | 本轮证据 | 对模型的影响 |
|---|---|---|
| DS 节点质量不劣于 Flash | **部分支持**：verify 条目 Flash>DS 但终端 Silver Flash<<DS | "全 DS 最优"结论在本数据上仍然成立 |
| 混合 π 最优 | **不支持**：Flash verify→sink Silver=0.150 << 全DS=0.850 | 条件 A 未通过 |
| 联合搜索有独有优势 | **不支持**：当前质量模型仍为单调（全DS最优） | JOINT ≡ π-only 持续 |

## 交叉替换实验需求

要隔离 verify 模型的独立效应，需 4 臂交叉：
| 臂 | verify | sink | 需新调用 |
|---|---|---|---|
| A（已有） | DS | DS | 0 |
| B（本轮） | Flash | Flash | 0（已完成） |
| C | Flash | DS | 1 |
| D | DS | Flash | 1 |

**但本轮结果表明 Flash verify 链的终端 Silver 很低**——即使交叉隔离确认 Flash
verify 本身产出更多条目，这些条目也不转化为终端 Silver 的提升。因此交叉实验的
优先级降低。

## 结论

1. Flash verify **确实产出更多核验条目**（7 vs 3，同上游公平配对）——但这不转化为
   终端 Silver 提升（0.150 vs 0.850，不同上游但差距极大）
2. **条件 A（混合 π 最优）未通过**——在欢瑞事件上，全 DS 仍然是终端质量最优的
   分配方案
3. **68 动作联合搜索的单调性问题持续**：当前证据下最优仍为全 DS + repair_both，
   JOINT ≡ π-only ≡ SEQ-π→R ≡ Alternating
4. **下一步**：如果 Flash 的优势在于核验深度而非终端 Silver（例如检测到 DS 遗漏
   的跨文档冲突），则需要一个能区分核验质量的评价标准（当前 Silver 评分只做
   关键词匹配，不评价核验深度）

**付费 HOLD 恢复。**
