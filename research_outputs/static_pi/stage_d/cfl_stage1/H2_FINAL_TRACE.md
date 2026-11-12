# H2 Gold 来源字段追溯终版（零调用 · 2026-11-05）

## 一、逐步骤 Gold 来源表

| 步骤 | 读取字段 | 来源 | Gold 依赖？ | 备注 |
|---|---|---|---|---|
| J 绑定输出 | subject, predicate, value_kind | contract.required_facts | **否** | 仅使用主体/谓词字符串做匹配，不读 value |
| J posthoc 核验 | fact.get('value') | Gold 值 | **是** | 仅用于报告验证，**不进入 J 块输出** |
| verify_pass | source_pages 文本 + entry 字段 | 合同文档 | **否** | 四部件核验（doc/page/quote/value_in_quote）全金盲 |
| **异常检测** | **V2 Q 分** | **Gold 值** | **是 ← 唯一泄漏点** | Q<0.3 → 异常分类 |
| 动作选择 | anomaly_type + vp | 上游信号 | 否* | *依赖第 4 步输出的类型标签 |
| 恢复执行（E/J/SINK） | source_pages + 提示 | 文档+冻结提示 | **否** | 真实模型调用 |

## 二、J 绑定的 Gold 使用边界澄清

J-v3 的 **绑定输出是金盲的**（只用 subject/predicate 做匹配、从 quote 提取金额），Gold 值仅在 posthoc 核验中使用且**不进入 SINK 提示的 J 块**。

但 J 绑定读取了 `contract.required_facts` 中的 **subject / predicate / value_kind** 字段——这些是合同元数据（事实槽位定义），不是 Gold 答案值。若将其视为"任务规格"而非"金标"，则 J 绑定全程金盲。

**需要操作员裁定**：subject/predicate/value_kind 归类为"任务合同元数据（部署时可获得）"还是"测试 Gold 专有信息"？

## 三、J=0 信号语义修正（按操作员指令）

**修正前**（H2 中的标签）：J=0 → "E坍缩" → Z/UPSTREAM
**修正后**：J=0 → "**证据-绑定异常**（根因待诊断）" → 需进一步区分：
- E 层证据质量不足（verify_pass 低 → UPSTREAM）
- J 约束过严致安全绑定失败（verify_pass 高但 J=0 → 放宽约束或 UNKNOWN）
- 候选歧义（多行匹配但无法唯一 → UNKNOWN）

## 四、H2 最终证据定位（降级后）

| 内容 | 最终裁定 |
|---|---|
| KANGMEI 正常→不干预 | 真实执行观察（有效） |
| ZHANGZIDAO 异常→UPSTREAM +0.438 | 真实质量恢复收益（有效） |
| 异常检测信号 | Gold-assisted（不可作为部署有效性证据） |
| J=0 替代信号 | 两任务事后一致性证据（可行性，非前瞻验证） |
| 完整金盲控制器 | **尚未完成独立前瞻验证** |
| Joint 相对 Z 额外收益 | 仍未证明 |

## 五、论文表述建议

H2 应表述为："在 Gold-assisted 异常检测下，两阶段控制器在 2 个任务的真实执行中展示了不干预正常任务与恢复异常任务的双行为；金盲替代信号（J 绑定数）在事后一致性检查中产生相同判定，但金盲控制器的前瞻独立验证尚未完成。"
