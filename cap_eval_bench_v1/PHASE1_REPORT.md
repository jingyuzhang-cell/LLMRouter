# PHASE1_REPORT — 真实端到端批次（授权执行：22 次/33,000 上限；实际 11 次/13,632）

三线链路上的第一批**真实**运行（真实 Planner + 真实执行 + 基准检索 + 独立评分）。全程零超限；
去重机制经真实批次验证（补跑 T-P1 时 planner 两次调用零成本复用）。结果为可行性证据，
**不构成任何算法优势主张**（Phase-2 归因对照尚未运行）。

## 运行结果

| run | 状态 | Q | coverage | C_total(tok) | L_service(s) | E_evidence 支持 | 检索自给 |
|---|---|---|---|---|---|---|---|
| T-P1 auto_graph | **INVALID（规划信封用尽）** | — | — | 规划 2 次计入 2,532 | — | — | — |
| T-P1 single_model | COMPLETE | 0.5938 | 5/8 | 2,566 | 9.3 | 1.0 | 5/8 |
| T-R1 auto_graph | **COMPLETE** | 0.4917 | 3/6 | 7,058 | 36.9 | 1.0 | 6/6 |
| T-R1 single_model | COMPLETE | 0.6667 | 4/6 | 1,676 | 9.6 | 1.0 | 6/6 |

## 三个真实发现（如实）

1. **小语料任务上单模型再次同时赢质量与成本**（T-R1：Q 0.667 vs 0.492，token 1,676 vs 7,058）。
   与舜天 V2.2 结论同向，这是第三个独立真实复现：语料可整体注入时，DAG 的分解开销无净收益。
   T-R1 auto_graph 的完整 6 节点真实轨迹与逐节点评分见 phase1/PH1-auto_graph-T-R1/。
2. **T-P1 规划真实失效**：信封内两个样本（首试+修复）均死于同一模式——SP 级检查通过但
   装配级"死分支"（终局不可达）。运行器已把装配错误纳入修复反馈（代码修复+补跑验证），
   但去重正确复用了旧修复输出，信封已尽。处置：按协议记 INVALID，不人工救图、不加调用。
   工程含义（窗口2改进项）：终局可达性检查应前置到 SP 级，使修复提示在信封内携带该信号。
3. **single_model 臂的 verdict=INCOMPLETE 是臂设计造成的**：该臂只产出报告文本、结构化字段
   留空，schema_conformance 被机械扣分。Q（内容）可比，K.schema 不可比——Phase-2 协议须先
   裁定该臂的交付装配方式（解析填字段或豁免结构分），已在附录留档。

## 预算与纪律
- 实际 11/22 次、13,632/33,000（保证线口径）；单模型两 run 均 stop=max_tokens（512 上限，
  截断如实入账；T-P1 5/8 覆盖在 512 截断下取得，为该臂下限而非上限——Phase-2 需输出预算配平）。
- 检索全部经基准 API（对账一致）；评分全部离线独立完成；无评测指标回流。

## 交付物
phase1/{PH1-auto_graph-T-P1, PH1-single_model-T-P1, PH1-auto_graph-T-R1, PH1-single_model-T-R1}/
{trace.json, deliverable.json, scores.json} + model_call_ledger_phase1.jsonl（逐调用双口径+去重标记）。
