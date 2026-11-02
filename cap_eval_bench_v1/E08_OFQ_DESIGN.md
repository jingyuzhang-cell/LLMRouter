# E08-OFQ v2.2：E08 客观事实质量评价可行性验证——方案设计

**日期**: 2026-10-30 | **修订**: v2.2-final（落实操作员 R1–R8 + CONDITIONAL 门槛修正 + B2 单一测试点 + R7 上下文核验）
**状态**: 最终修订版，待 DESIGN PASS
**身份**: Q Foundation 评价方法实验（非调度实验）

---

## 一、适用范围与边界

**本实验即使全部通过，也只能证明**：E08 范围内的客观事实评价方法具有可行性。

**不能宣称**：完整六维 Q_terminal 已冻结；复杂语义评价已解决；SILVER 已升级为 GOLD。

## 二、统一事实清单

### 2.1 原始文书（v2.2 冻结完整 SHA256）

| doc_id | 内容 | 字节 | SHA256（完整 64 位） | 编码 |
|---|---|---|---|---|
| E08-zhongtie_20260129 | 业绩预告 | 1,989 | `3d06dd5ce12cc145e13e9ef7102abcd523a1eee24cc8e3a982d3b0ea757a7892` | UTF-8, LF, 无 BOM |
| E08-zhongtie_20260327 | 说明会公告 | 1,546 | `5b3a8cb2e79ed4dae686c4609b28fc7198d42de811147fe7d76ba72668128d23` | UTF-8, LF, 无 BOM |
| E08-zhongtie_20260918 | 立案告知书 | 1,955 | `6da0e69c009e3c63d8f8790a10cc716dc8c49155cbbb9db537e68e4a203b007b` | UTF-8, LF, 无 BOM |

**文件身份说明**：这些文件是原始 PDF 公告的**文本快照**（从 PDF 提取的纯文本），非原始 PDF 本身。SHA256 证明的是**文本快照完整性**，不替代原始 PDF 的完整性证明。

### 2.2 事实清单（17 条 + 1 条 UNKNOWN）

**来自 2026-09-18 立案告知书（F1–F10）**：

| ID | 类型 | 谓词 | 值 | 限定语 | 关键性 |
|---|---|---|---|---|---|
| F1 | entity_attribute | 证券代码 | 300374 | — | 否 |
| F2 | entity_attribute | 证券简称 | 中铁装配 | — | 否 |
| F3 | entity_attribute | 公告编号 | 2026-037 | — | 否 |
| F4 | **date_receipt** | 收到立案告知书日期 | 2026-09-18 | — | **是** |
| F5 | entity_attribute | 发文机关 | 中国证券监督管理委员会 | — | 否 |
| F6 | **identifier** | 立案编号 | 证监立案字0142026049号 | — | **是** |
| F7 | **qualified_fact** | 立案原因 | 涉嫌信息披露违法违规 | **"涉嫌"不可丢失** | **是** |
| F8 | **entity_subject** | 立案对象 | **中铁装配式建筑股份有限公司** | — | **是** |
| F9 | qualified_fact | 自查涉及业务 | 实际控制人变更前开展的相关业务 | **"可能涉及"不可丢失** | 否 |
| F10 | status_fact | 最终调查结论状态 | 尚未收到 | 截至公告日 | 否 |

**来自 2026-01-29 业绩预告（F11–F14）**：

| ID | 类型 | 谓词 | 数学下界 | 数学上界 | 单位 | 关键性 |
|---|---|---|---|---|---|---|
| F11 | numeric_range | 归母净利润区间 | -15600 | -7900 | 万元 | 否 |
| F12 | numeric_range | 扣非净利润区间 | -18600 | -9900 | 万元 | 否 |
| F13 | numeric_point | 上年同期归母 | -6371.69 | — | 万元 | 否 |
| F14 | numeric_point | 上年同期扣非 | -7701.18 | — | 万元 | 否 |

**来自 2026-03-27 说明会公告（F15–F17）**：

| ID | 类型 | 谓词 | 值 | 关键性 |
|---|---|---|---|---|
| F15 | date_event | 说明会举行日期 | 2026-04-08 | 否 |
| F16 | entity_person | 董事长姓名 | 安振山 | 否 |
| F17 | date_announcement | 年报披露日期 | 2026-03-27 | 否 |

**UNKNOWN**：U1 = 最终调查/处罚结论及金额、责任认定。

### 2.3 关键事实定义

**关键事实**：F4, F6, F7, F8。选取依据（实验前冻结）：F4=核心时间锚点；F6=唯一标识符；F7=限定语保留测试点；F8=实体绑定测试点。

### 2.4 实体名称层级（**v2.2 新增——R5**）

| 层级 | 名称 | 使用场景 | 匹配规则 |
|---|---|---|---|
| **法定全称** | 中铁装配式建筑股份有限公司 | 正式法律主体身份 | NFC 规范化后精确匹配 |
| **文书声明简称** | （文书内"以下简称'公司'"） | 文书内部指代 | 仅在该文书上下文中有效 |
| **证券简称** | 中铁装配 | 证券代码/简称字段 | 仅在 F2（证券简称谓词）中接受 |
| **其他名称** | 中国中铁、中铁二局等 | — | **不接受** |

**谓词-名称类型约束**：不同谓词只接受对应层级的实体名称——F8（立案对象）只接受法定全称；F2（证券简称）只接受证券简称；不可跨类型替代。

## 三、确定性核验规则

### 3.1 实体核验

| 规则 | 说明 |
|---|---|
| FULL_NAME_MATCH | 法定全称 NFC 规范化后精确匹配 |
| SEC_ABBR_MATCH | 证券简称仅在证券简称谓词中接受 |
| ENTITY_NOT_SUBSTITUTE | 不得替换为同行业其他实体 |
| PERSON_ROLE_MATCH | 自然人须匹配姓名+职务 |

### 3.2 日期核验

| 规则 | 说明 |
|---|---|
| DATE_TYPE_AWARE | 区分 date_receipt / date_announcement / date_event / date_decision / date_signing |
| DATE_NORMALIZE | ISO 或中文 → 类型化解析 → 标准化 ISO 比较 |
| DATE_CALENDAR_VALID | 使用 `datetime.date` 构造验证（**自动拒绝 2026-02-31 等非法日期**） |
| DATE_PARSE_FAIL | 无法解析 → UNSUPPORTED |

### 3.3 金额核验

| 规则 | 说明 |
|---|---|
| DECIMAL_EXACT | Decimal 精确比较 |
| UNIT_MATCH | 币种+单位完全匹配 |
| RANGE_NORMALIZE | 数学规范化（下界/上界按数学大小排列，非文本顺序） |
| RANGE_ENDPOINT | "至"默认闭区间 |
| RANGE_ORIGINAL | 保留原文表达顺序供溯源 |

### 3.4 推导核验

| 推导 | 操作数 | 结果 |
|---|---|---|
| D1 | 2026-01-29 → 2026-03-27 | 57 天 |
| D2 | 2026-03-27 → 2026-09-18 | 175 天 |
| D3 | 2026-01-29 → 2026-09-18 | 232 天 |

### 3.5 证据绑定核验（**v2.2 细化——R4/R7**）

| 规则 | 说明 |
|---|---|
| DOC_ID_VALID | doc_id 须在三份文书中 |
| SHA256_MATCH | 对原始**文本快照字节**计算 SHA256，与第 2.1 节冻结值比对 |
| SPAN_FROM_RAW | 从原始文书独立定位（非 SILVER 自我引用） |
| SPAN_CONTENT_VERIFY | 跨度位置原文包含声称的值 |
| SPAN_OFFSET_UNIT | Unicode 字符偏移（Python `str` 索引） |
| SPAN_SEMANTICS | `[start, end)` 左闭右开 |

**文本读取规范**（v2.2 冻结——R7）：
- 编码：UTF-8，无 BOM（已验证三份文件均无 BOM）
- 换行符：LF（`\n`，已验证三份文件均为 LF-only）
- 读取方式：`Path.read_bytes()` 后 `decode('utf-8')`——**禁止** `open(mode='r')` 的自动换行转换
- 多次出现：取**首次出现**的跨度作为标准跨度，但须验证该跨度的**上下文包含正确的主体和谓词**——不能仅凭字符串首次出现即认定证据有效（例如"中铁装配"在文书头出现是证券简称，在正文中出现可能指代公司实体；须结合谓词上下文确认）

## 四、评价状态体系

**三个独立维度**：

**维度 1：参考一致性**
- MATCHED_REFERENCE：候选值 = SILVER 参考值

**维度 2：证据判定**（三态互斥）
- SOURCE_SUPPORTED：doc_id + SHA256 + span 核验通过
- CONTRADICTED：与文书原文可验证内容不符
- UNSUPPORTED：无法从文书找到依据或超出支持范围

**维度 3：完整性与不确定性**（全局终态）
- OMITTED：关键事实缺失
- UNKNOWN_ABSTAINED：正确拒判不可确认事项

**维度间规则**：MATCHED 不覆盖证据维度；OMITTED/ABSTAINED 为终态。

**CONTRADICTED vs UNSUPPORTED**：
- CONTRADICTED = 文书写 X，候选说 Y → 可证伪
- UNSUPPORTED = 文书无相关信息 → 无法判定真假

## 五、三组验证实验（v2.2 修订版）

### 实验 A：正确事实识别（7 项）

| 测试 | 输入 | 预期 |
|---|---|---|
| A1 | F4="2026-09-18"（date_receipt） | MATCHED + SOURCE_SUPPORTED |
| A2 | F6="证监立案字0142026049号" | MATCHED + SOURCE_SUPPORTED |
| A3 | F7="涉嫌信息披露违法违规" | MATCHED + SOURCE_SUPPORTED |
| A4 | F9="可能涉及实际控制人变更前开展的相关业务" | MATCHED + SOURCE_SUPPORTED |
| A5 | F11=[-15600, -7900]万元 | MATCHED + SOURCE_SUPPORTED |
| A6 | F10="尚未收到最终调查结论" | MATCHED + SOURCE_SUPPORTED |
| A7 | 全部 17 条同时提交 | NFC=4/4；事实级正确率=17/17 |

### 实验 B：错误事实识别（11 项，v2.2 修正 B2/B6）

| 测试 | 修改 | 预期 |
|---|---|---|
| B1 | 主体替换："中铁装配式建筑股份有限公司"→"中国中铁" | CONTRADICTED（entity_mismatch） |
| **B2** | **日期值+类型混淆：F4 的 date_receipt 值改为 2026-03-27（另一份文书的日期）** | **CONTRADICTED（value_mismatch：文书写 2026-09-18，候选给 2026-03-27）** |
| B3 | "2026-09-18"→"2026-09-19" | CONTRADICTED（value_mismatch） |
| B4 | "-6371.69"→"-6372.69" | CONTRADICTED（value_mismatch） |
| B5 | "万元"→"元" | CONTRADICTED（unit_mismatch） |
| **B6** | **删除"涉嫌"→"信息披露违法违规"** | **UNSUPPORTED（qualifier_lost：文书仅支持"涉嫌"表述，候选声称为确定事实）** |
| B7 | "0142026049"→"0142026050" | CONTRADICTED（value_mismatch） |
| B8 | 指向不存在的文书位置 | UNSUPPORTED（span_mismatch） |
| B9 | D2=174天（正确175） | CONTRADICTED（arithmetic_error） |
| B10 | 删除 F4 | OMITTED（completeness_gap） |
| B11 | "涉嫌"→"已确认" | UNSUPPORTED（qualifier_escalation） |

**B2 修正说明**（v2.2——R3）：~~v2.1 将 F4 标注为 date_announcement 判为 CONTRADICTED~~。修正后 B2 改为**日期值混淆**：将另一份文书的日期（2026-03-27，来自 2026-03-27 说明会公告）作为 F4 的值。本测试**单一测试点为值错误**（文书写 2026-09-18，候选给 2026-03-27）；类型混淆是隐含的副作用，不单独计为另一个错误标签。

**B6 修正说明**（v2.2——R2）：~~v2.1 判为 CONTRADICTED~~。删除"涉嫌"后候选声称"信息披露违法违规"为确定事实——但文书仅支持"涉嫌"这一限定表述。我们不能证明该事项最终一定不成立（可能确实违法），只是当前证据不支持去掉限定。因此为 **UNSUPPORTED**（qualifier_lost），与 B11（qualifier_escalation）同类。

### 实验 C：UNKNOWN 边界（6 项）

| 测试 | 场景 | 预期 |
|---|---|---|
| C1 | 给出最终处罚金额 | UNSUPPORTED |
| C2 | 给出责任认定 | UNSUPPORTED |
| C3 | 标注"UNKNOWN" | UNKNOWN_ABSTAINED |
| C4 | "涉嫌"→"已确认违法" | UNSUPPORTED |
| C5 | "可能涉及"→"确认涉及" | UNSUPPORTED |
| C6 | "尚未收到"→"已收到" | **CONTRADICTED**（文书明确写"尚未收到"） |

## 六、评价指标（v2.2 修正——R1/R6）

**统计单位声明**：A1–A6 各为一条测试（各含 1 条事实）；A7 为一条测试（含 17 条事实）。FAR 的分母为**测试条数**（7），事实级正确率单独报告。

| 指标 | 分子 | 分母 | 统计单位 |
|---|---|---|---|
| **FAR** | A 组中 MATCHED + SOURCE_SUPPORTED 的**测试**条数 | 7 | 测试条数 |
| **EIR** | B 组中 CONTRADICTED / UNSUPPORTED / OMITTED 的**测试**条数 | 11 | 测试条数 |
| **ELP** | B 组中错误**类型标签正确**的条数 | B 组已识别条数 | 测试条数 |
| **NFC** | **正确呈现**的关键事实数 | 4 | 事实条数 |
| **ESR** | SOURCE_SUPPORTED 的事实条数 | 有证据绑定的事实条数 | 事实条数 |
| **UPR** | **C 组实际输出与预期状态完全一致的测试数** | 6 | 测试条数 |

**NFC 修正说明**（v2.2——R6）：~~v2.1 仅统计事实是否"在场"~~。修正为"**正确呈现**"——须同时满足主体、谓词、值、限定语和时间范围全部正确。若 F4 在场但日期错误，不计入 NFC 分子。

**UPR 修正说明**（v2.2——R1）：~~v2.1 公式 UNSUPPORTED+UNKNOWN_ABSTAINED / 6 在 C6（CONTRADICTED）正确时无法达到 100%~~。修正为"实际输出与预期完全一致的测试数 / 6"——C6 正确判为 CONTRADICTED 也计入正确处理。

### 验收门槛（v2.2 修正关键事实引用——R6）

**关键事实相关测试**（任何一项误接受 → 直接 FAIL）：

| 测试 | 涉及关键事实 |
|---|---|
| B1 | F8 |
| B2 | F4 |
| B3 | F4 |
| B6 | F7 |
| B7 | F6 |
| B10 | F4 |

| 等级 | 条件 | 附加 |
|---|---|---|
| **PASS** | A 7/7 + B 11/11 + C 6/6 | 全部指标=100% |
| **CONDITIONAL** | A ≥6/7 + B ≥10/11 + C ≥5/6 | FAR ≥6/7、EIR ≥10/11、UPR ≥5/6（与各组最低通过数一致，**不设统一百分比**）；NFC ≥3/4；ESR ≥85%；**上表 6 项关键事实测试不得在失败项中** |
| **FAIL** | 其他 | 含任一组 <80%；关键事实误接受；UNKNOWN 误升级 |

## 七、T1 执行器要求

| 要求 | 说明 |
|---|---|
| 独立测试脚本 | 新建 `e08_ofq_test.py`，不调用 Conservative Parser |
| 读取冻结文书 | `read_bytes()` + `decode('utf-8')`，禁自动换行转换 |
| 独立跨度定位 | 从原始文书重新搜索定位 |
| 不修改现有代码 | 不修改 Parser/Silver/评分器/账本 |
| 不产生正式 Q | 输出为诊断性六态 |
| 零模型调用 | 无 LLM/GPU/API |
| 日期合法性 | 使用 `datetime.date` 构造验证 |

## 八、研究局限

1. 单案例、不外推
2. SILVER ≠ GOLD
3. 客观事实 ≠ 复杂语义
4. 对抗测试仅覆盖已知错误类型
5. Conservative Parser 仍为 NEEDS FIX

## 九、与 Q Foundation 的关系

补充路径，非替代。两条路径在 P3 汇合。
