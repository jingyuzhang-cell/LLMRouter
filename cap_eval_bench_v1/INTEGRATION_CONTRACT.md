# INTEGRATION_CONTRACT — 面向 Planner/静态分配线（Codex）与动态联合调度线（ZCodex）的集成要求

评测模块不参与 Planner、结构优化器、Router、动态恢复算法的开发。两条开发线按下述契约接入，
即可在不接触任何评分参考的前提下被同一裁判评测。

## 1. 你方可以访问（且仅可以）
- `tasks/tasks_frozen.jsonl`：任务问题、证据 doc_id 集、信息截止日、交付 schema、UNKNOWN 边界、deadline；
- `evidence/retrieval_api.py`：唯一证据访问通道（按任务作用域、按预算、审计日志）；
- `evidence/index.json` 的文档元数据（标题/日期/哈希/字符数——不含正文）；
- `traces_schema/trace_schema.json`：输出轨迹格式。
**禁止**：`tasks/tasks_private*`、`scoring/**`、直接读取 `evidence/texts/*` 原文、任何 silver
答案/标准 DAG/分支描述符（隔离门会扫描你方输入目录）。

## 2. 你方必须产出（每任务每 run）
1. **轨迹** `trace.jsonl`（单行一个 JSON 对象，符合 trace_schema）：含 planning（规划调用计量）、
   retrieval（调用数与注入字符数，与 retrieval_log 对账）、nodes[]（每 attempt 计量、parse_status、
   repair_of）、program_ms、wall_s（单调钟实测：规划前→交付落盘）、status、config_hash；
2. **交付** `deliverable.json`：按任务 deliverable_schema 填字段；report 为带 doc_id 引用的文本；
   UNKNOWN 边界逐项显式标注（评分器确定性探测）；
3. `system_id` 固定取值：`planner_static`（Codex 静态分配线）/ `structure_opt`（结构优化线）/
   `dynamic_joint`（ZCodex 动态联合线）/ `single_model` / `fixed_homogeneous`；config_hash 锁定
   你方超参与模型映射版本。

## 3. 成本记账义务（E 的数据来源全部由你方 trace 提供，评测侧仅核验）
- 规划、检索、模型首试、修复、程序开销全记；失败调用照记；跨请求复用须标 `reused: true`
  （0 新增 token，但重复利用历史输出必须在 notes 声明场景）；
- 检索侧对账：你方 trace 的 retrieval.calls/chars_injected 必须与 evidence/retrieval_log.jsonl
  中 run_id 匹配的记录一致，不一致即该 run 判 INVALID；
- 输出预算：所有系统对同任务同节点类型使用相同 max_tokens（由评测方在赛前后统一发布每类节点
  上限表；你方不得单方面调高）。

## 4. 动态调度线（ZCodex）附加字段
- 异常检测/重分配/局部恢复的每个决策事件写入 nodes[] 的 `repair_of` + notes（含触发信号类型）；
  RQ2 的恢复收益判定完全基于这些字段与 K 指标，缺失即无法主张收益；
- 预算/截止控制器动作（提前停止、降级）须记录于 trace.notes，墙钟以实际 wall_s 为准。

## 5. 运行批次与交付方式
- 每批次：8 任务 × k 重复（k 由协调方定，默认 3），同批次内三系统同会话或声明负载条件；
- 交付目录：`<system_id>/<batch_id>/T-*/run_*/{trace.jsonl, deliverable.json}`；
- 评测模块只读该目录 + retrieval_log 对账，出具 Q/E/K 与跨系统对比（PROTOCOL_EVAL_V1 §5/7）。

## 6. 版本与变更
本契约与 PROTOCOL_EVAL_V1、评分器、silver 集、任务集的任何变更都换版本号并重冻结
（BENCH_FREEZE_MANIFEST.json）；进行中的批次以开跑时冻结版本为准。
