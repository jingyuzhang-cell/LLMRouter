# SCREENING_80_QUALITY_AUDIT — 80 次筛选质量指标审计（零付费）

## 1. 组合数与复用对应（全过）

- 预期 80 次（冻结矩阵）：pilot 12（fact_extraction）+ full80 68（timeline/entity/crosssource）= 80 ✓
- 类型无重叠（pilot 仅 fact_extraction，full80 无 fact_extraction）✓
- 12 次复用输入与 pilot_v1 冻结包一致（同一 screening_pilot_v1_frozen.json）✓

## 2. 样本数偏差（如实报告）

| 类型 | 协议目标 | 实际 | 差异原因 |
|---|---|---|---|
| fact_extraction | 5 | **3** | 元道退仅 3 份文档各取 1 片段；舜天/康得新未加入事实提取类 |
| timeline | 5 | **6** | 冻结包生成时 6 个证据段（元道退3+舜天2+康得新1）——超出协议 |
| entity_relations | 5 | **6** | 同上 |
| crosssource_check | 5 | 5 | 一致 |

**偏差影响**：n=3 的事实提取类样本量最小（每模型仅 3 次测量）；n=6 的类型比协议多 1 个样本。
能力表 V2 已标注各格 n_samples。

## 3. Q 计算公式审计（关键澄清）

原 Q 计算为 `avg_output_count / max_avg_count_per_type`——这是**相对产出数量比**，
不是事实质量或准确率。Q=1.0 表示"该类型产出条目最多"，不表示"100% 正确"。

**V2 修正**：Q 更名为 `Q_output_ratio`，含义为产出数量比；Gold=PENDING 期间不作为质量指标使用。
未来 Gold 完成后，Q 将改为 Gold 对齐的 Precision/Recall/F1。

## 4. 零输出审计

### 主体关系零输出（Qwen 全部 6 样本 + 其他 3 次）
- **Qwen 6/6 零输出**：原始响应有内容（raw_len 110-521 字符）但解析后 relations 数组为空——
  模型输出了合法 JSON 但内容为空数组。**可能是提示词不适配**（Qwen 对 relation 抽出的
  JSON Schema 理解不同）而非模型无能力。
- GLM-5.3 ER1 零输出：raw_len=626 有内容但 count=0——同类型偶发。
- DeepSeek ER2 零输出：raw_len=502——单次。

### 跨源核查零输出（除 GLM-5.3 外全部 20 次中 19 次）
- **19/20 零输出**：全部有 raw content（120-2014 字符）但 verdicts 数组为空。
- **例外**：GLM-5.3 XC1 有 6 条判定（唯一非零）。
- **最可能原因**：跨源核查任务的提示词要求"判断一致性/矛盾/互补/证据不足"，但输入的
  两个来源来自不同事件（元道退 vs 舜天/康得新），**没有可比较的事实对**——模型正确地
  输出"无相关判定"。这不是模型能力缺陷，而是**样本设计问题**。

## 5. 能力表 V2（capability_table_v2_audited.json）

修正内容：
1. Q 更名为 Q_output_ratio（产出数量比，非质量）
2. 各格标注 n_samples
3. 零输出标注 zero_output + 说明（可能是提示词适配或证据不足）
4. gold_status=PENDING
5. 跨源核查类标注"样本设计可能不适配"（跨事件对比无意义）

## 6. 支持与不支持的结论

**支持（有数据基础）**：
- DeepSeek 在全部四类型上时延最快（2.0-5.0s，n=3-6/格）
- GLM-5.3 在时间线/主体关系/跨源核查上产出最多（n=5-6/格）
- 事实提取上 DeepSeek 产出最多（n=3/格）
- Qwen 主体关系持续零产出（n=6，但可能是提示词问题）
- JSON 契约率：GLM-5.3 100%，DeepSeek 100%，Flash 95%，Qwen 95%

**不支持（数据不足或方法缺陷）**：
- 任何模型的事实"质量"（Q 是数量比，非 Gold 校验的准确率）
- 跨源核查能力（样本设计问题，跨事件对比大多无意义）
- Qwen 主体关系能力（可能是提示词适配，需修提示词后重测）
