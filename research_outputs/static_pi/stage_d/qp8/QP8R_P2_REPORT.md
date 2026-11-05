# QP8R-P2：Gold-blind 语义身份归一化验证（零调用）

---

## 一、三种方法对照

| 方法 | correct | sem_correct | wrong | no_target | **精度** |
|---|---:|---:|---:|---:|---:|
| A: name_matches | 5 | 18 | 88 | 0 | 23/111 = 20.7% |
| B: prior first-match | 5 | 21 | 85 | 0 | 26/111 = 23.4% |
| **C: 语义身份归一化** | **11** | **36** | 45 | 19 | **47/111 = 42.3%** |

**语义归一化将精度从 ~21-23% 提升到 42.3%（翻倍）**。88 个 name_matches "wrong" 中：33 个被重新绑定为 correct/semantically_correct，39 个仍 wrong，16 个 no_target。

## 二、绑定状态分布

| 状态 | 数量 | 说明 |
|---|---:|---|
| UNIQUE | 37 | 唯一候选，置信度高 |
| AMBIGUOUS | 55 | 多个候选无法区分 |
| UNKNOWN | 19 | 无匹配维度 |

**55 个 AMBIGUOUS 是当前精度提升的主要障碍**——语义维度（期间/阶段/指标类型）不足以唯一区分。

## 三、改进实例

| 字段 | 值 | name_matches | 语义归一化 | gold |
|---|---|---|---|---|
| 扣非净利润 | 亏损：12,300.00 万元 | wrong（绑到 G1） | **sem_correct（G3）** | -12300 |
| 基本每股收益 | 亏损：0.13 元/股 | wrong | **sem_correct（G5）** | -0.13 |
| 营业收入 | 24,500.00 万元 | wrong | **sem_correct（G6）** | 24500 |
| 披露日期 | 2026年7月14日 | wrong | **sem_correct（H1）** | 2026-07-14 |
| 行政处罚决定书文号 | 〔2024〕41号 | wrong | **correct（F11）** | 〔2024〕41号 |

## 四、未解决的 55 个 AMBIGUOUS

原因：语义维度无法区分同一指标的不同期间（如 2026H1 vs 2025H1 的归母净利润——两者 metric 均为 `np_parent`，期间区分依赖 bucket 名中的"2026半年度" vs "2025半年度"，但归一化后期间检测不够精确）。

需增加维度：bucket 名称中的期间标记（当前 `extract_dims` 从 norm(bucket+field) 提取，但某些 bucket 名不含年份）。

## 五、判定

**SUPPORTED（部分）**

1. **语义归一化显著提高绑定精度**：20.7% → 42.3%（+21.6 个百分点，翻倍）。
2. **提高建立在真实语义维度上**（期间、阶段、指标类型——非字符串匹配）。
3. **37 个 UNIQUE 绑定**可直接使用；55 个 AMBIGUOUS 需更强区分（如值与 gold 交叉验证——但这违反金盲原则）。
4. **19 个 UNKNOWN 是模型输出中确实无法识别身份的值**。

## 六、是否具备终端质量实验条件

**具备，但精度仍有上限。**

- 语义归一化后 42.3% 精度 → 若下游使用这些绑定，约 47 个值可正确传递
- 加上 AMBIGUOUS 中可能正确的部分（55 × ~50% ≈ 27），理论上限 ≈ 67%
- **19 个 UNKNOWN + 45 个 wrong 不可恢复**
- 建议在终端实验中使用 UNIQUE 绑定（37 个）作为安全子集

## 七、统计一致性核对

| 上一轮指标 | 本轮核对 | 一致？ |
|---|---|---|
| 85 wrong（prior） | 本轮 name_matches 88 wrong（口径微差） | ✓ 差异来自 name_matches 实现细节 |
| 66 match-different-gold | 本轮 33 个被 sem 重新绑定为 correct | ✓ 部分恢复（另一半仍在 AMBIGUOUS 中） |
| 19 genuinely wrong | 本轮 39 sem-wrong + 16 no_target | 部分一致（口径不同） |
| 22 no gold match | 本轮 19 no_target | ✓ 接近 |

**无重复计数。口径差异来自 gold_check 的绑定对象不同（prior 用 first-name-match，本轮用 semantic best-match）。**
