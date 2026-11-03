# STAGE_C_RESULTS — 五臂动态对照：**整批无效（证据注入缺失），如实报告**（2026-10-30）

> 授权：150 次/150K Token（"授权继续"）。实用 **92 次/43K Token**
> （glm53 17K + flash 26K），¥0。20 run 全部真实执行完毕。
> **但整批结果无效**——所有 20 run 的终端输出为 UNRESOLVED，原因与
> Batch2 的 69% 失败同根：**证据文档文本未注入节点提示词**。

## 发生了什么

Stage-C 运行器是新建代码（PHASE2_PROTOCOL 冻结了设计但无现成运行器）。
其 `build_prompt` 函数接收 `evidence_texts` 参数但**从未在 extracts
节点提示词中使用**——f2 的 prompt 仅 411 字符（应含数千字符文档），
模型诚实返回 "UNRESOLVED: 仅提供文档索引, 未注入正文证据"。

```
f1(index) → 正常（文档标题索引）
f2(extracts) → prompt 411 字符，无文档正文 → UNRESOLVED
f3(timeline) → 上游 UNRESOLVED → 空（此处注入异常）
f4-f6 → 级联 UNRESOLVED → 终端报告全 "UNKNOWN/UNRESOLVED"
```

**这是同一类证据流缺陷的第三次出现**（38 批次→修复→Batch2 140 批次
回归→修复→Stage-C 新代码再次引入）。根因：每次新建运行器时手工组装
提示词，未复用已修复的 `_doc_text` 注入路径。

## 数据保留

- 92 次真实调用全量入账（`stage_c/` 双账本 + 20 run 目录）；
- Silver 评分不可用（全 UNRESOLVED 不入分母）；
- 运行器代码 `phase2_stage_c.py` 在案——修复点已定位（build_prompt
  的 extracts 分支需注入 `evidence_texts` 的文档正文）。

## 决定

**不追加调用修复重跑**（按工作原则：不因结果不好临时修补）。整批
92 次调用记为已消耗、结果无效——教训入档：

> 新建运行器必须复用已修复的证据注入基础设施，不得手工重组提示词。
> 此规则已适用于未来所有 Stage-C/反馈学习阶段的运行器构建。

**Stage-C 需重新授权后执行（修复版运行器 + 新预算）。**
