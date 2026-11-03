# cap_eval_bench_v1 — 复杂资本市场任务评测集与独立终端评价模块

角色边界（与两条开发线并行）：本目录只做**评测**——任务集、冻结证据、Q/E/K 独立评分、隔离与
公平比较；不含 Planner/Router/静态优化器/动态恢复算法的任何实现。零付费交付（无模型调用、
无 GPU）；既有冻结实验（capital_opinion_pilot 等）零改动、只读复用。

## 一次性交付清单
| 组件 | 位置 | 说明 |
|---|---|---|
| 任务集（公开面） | tasks/tasks_frozen.jsonl | 8 任务/4 类：P 监管处罚×3、D 披露变化×2、M 并购重组×1、R 事件市场反应×2；含截止日/交付 schema/UNKNOWN 边界/deadline |
| 评分参考（私有面） | tasks/tasks_private.jsonl、scoring/silver/*.json | 52 条 SILVER 事实（100% 引文接地）+ 分支描述符（预期多分支证据汇合点）；**永不向被评系统暴露** |
| 证据库 | evidence/（index.json + texts/ + raw/） | 23 份官方文档（17 冻结复用+6 新采：舜天差错更正×2、美的吸收合并×4）；URL/日期/SHA256 全记录 |
| 证据访问 API | evidence/retrieval_api.py | 确定性分段检索：按任务作用域、按预算、出处保留（chunk 偏移+哈希）、逐调用审计日志；retrieval_coverage.json 为默认词下限基线 |
| Q/E/K 评分器 | scoring/qe_k_scorer.py | 独立离线终端评分（定义冻结于协议 §3） |
| Gold 规则 | scoring/gold/ | 机器参考一律 Silver；人工裁决流程与模板；未裁决不得称 Gold |
| 隔离门 | isolation/gate.py | 私有内容（silver 问题/答案/引文、分支描述符）泄漏扫描 + 公开面自检 |
| 轨迹契约 | traces_schema/ | trace_schema.json + 合成样例（明确标注 SYNTHETIC，禁入评分） |
| 评测协议 | PROTOCOL_EVAL_V1.md | Q/E/K 冻结定义、成本/墙钟/可靠性/按期统计口径、三系统公平比较与判定门槛、防泄漏防伪 |
| 集成契约 | INTEGRATION_CONTRACT.md | Codex（planner_static/structure_opt）与 ZCodex（dynamic_joint）接入要求 |
| 冻结清单 | BENCH_FREEZE_MANIFEST.json | 全部冻结工件哈希（tests B7 校验） |
| 测试 | tests/test_bench.py | 零调用验收：接地/评分器/检索确定性/隔离/完整性/冻结校验 |

## 快速使用
```bash
cd /root/cap_eval_bench_v1
python3 tests/test_bench.py                       # 验收（零调用）
python3 isolation/gate.py selftest                # 公开面隔离自检
python3 isolation/gate.py check <你的输入目录>     # 泄漏扫描（被评系统输入）
# 被评系统侧（唯一证据通道）：
python3 -c "import sys; sys.path.insert(0,'/root/cap_eval_bench_v1/evidence'); import retrieval_api as R; \
chunks, used = R.retrieve('T-M1','my_run_001',['换股比例','核准','问询'],3300)"
# 评分（评测侧）：
python3 -c "import sys; sys.path.insert(0,'/root/cap_eval_bench_v1/scoring'); import qe_k_scorer as S, json; \
trace=json.load(open('<trace.json>')); dv=json.load(open('<deliverable.json>')); print(json.dumps(S.score_run(trace,dv),ensure_ascii=False))"
```

## 关键设计决定（一句话版）
- 检索查询词由被评系统自选：检索策略是被评能力的一部分，评测侧只审计不干预；
- E 是向量永不坍缩；K 含 deadline 与 verdict；Q 对幻觉日期罚分、对 UNKNOWN 边界合规给分；
- 一切参考为 Silver，Gold 须走 scoring/gold/ 的人工裁决流程；
- 三条系统线（静态异构/结构优化/动态联合）+ 单模型/同构基线在同一任务、同一 API、同一预算与
  deadline 下由本模块统一出具 Q/E/K 与 Pareto 关系。
