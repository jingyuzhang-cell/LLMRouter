# R3 Multi-objective Router Dataset Schema v1.1

状态: FROZEN（2026-09-08）。取代 v1.0 中与之冲突的段落；采集器（含 validator）在本文件确认后实施。

v1.0 → v1.1 变更:
1. quality 改为**按任务分流**: math/code/knowledge 只用自动指标（exact-match / pass@1 / 选项匹配），
   **不用 judge**；仅 arenahard 用 LLM judge（论文可信度优先）。
2. latency 细化: `{total_ms, ttft_ms, decode_ms, tokens_per_second, source}`；Phase 1 为辅助口径，
   **论文核心结果只用 Phase 2 本地 vLLM**。
3. 新增 `utility_scores` 预留字段: 冻结 (λ, μ) 网格上的 Reward = Q − λC − μT 预计算值，
   raw 字段保留可整库重算。
4. 模型池维持 4 槽不变（scaling 梯度 + reasoning 维度，分析简单，创新在 router 不在池）。
5. 规模计划: 第一轮 5000 → 门禁验证（loss 下降 + oracle gap recovery > 0）→ 扩到 20k。

已知张力（显式声明）: GT 任务二元标签会把 accuracy 轴 headroom 封顶在少数独赢比例（R2C 教训）。
补偿: (a) arenahard 750 条提供分级质量维; (b) cost/latency 是连续轴，多目标 Pareto 的主要收益来源
（R2D 已证）; (c) 若 v1 验证后需要分级标签，judge prompt 已冻结，可对存量 raw answer 补判——
schema 无需变更。

## 1. 记录 schema（JSONL，每行一个 query，canonical 存储）

```json
{
  "query_id": "gsm8k_test_0001",
  "task_type": "math",
  "difficulty": "easy",
  "query": "原始完整 prompt",
  "ground_truth": "32",
  "responses": [
    {
      "model": "Qwen/Qwen2.5-7B-Instruct",
      "answer": "最终答案文本",
      "thinking": null,
      "quality": {
        "auto_score": 1.0,
        "auto_correct": true,
        "judge_score": null,
        "judge": null,
        "final": 1.0,
        "quality_source": "exact_match"
      },
      "cost": {
        "tokens_input": 512,
        "tokens_output": 230,
        "tokens_estimated": false,
        "price_input_per_mtok": 0.0,
        "price_output_per_mtok": 0.0,
        "usd": 0.00021
      },
      "latency": {
        "total_ms": 1830.4,
        "ttft_ms": 412.7,
        "decode_ms": 1417.7,
        "tokens_per_second": 162.1,
        "source": "local_4090_vllm | dashscope_api | phase2_local_vllm"
      },
      "utility_scores": {
        "lam0.5_mu0": 0.71,
        "lam1_mu0.5": 0.62
      },
      "status": "ok"
    }
  ]
}
```

- 每行固定 4 个 response 槽位全齐（listwise；失败槽位 status=failed，字段填 null，不删行）。
- `quality_source` ∈ {exact_match, pass@1, option_match, judge_qwen-max}，按任务固定:
  gsm8k→exact_match; mbpp/humaneval→pass@1; mmlupro→option_match; arenahard→judge_qwen-max。
- `final` 规则: GT 任务 = auto_score；arenahard = judge_score。
- `difficulty`: 采集后按 task_type 内 pool 平均 final 三分位派生冻结。
- `utility_scores`: freeze 阶段计算; `utility = final − λ·Ĉ − μ·T̂`，其中 Ĉ = usd / (该 query 4 槽
  usd 最大值)，T̂ = total_ms / (该 query 4 槽最大 total_ms)（per-query 归一，消除量纲与题间差异）;
  λ ∈ {0, 0.1, 0.5, 1, 2, 5} × μ ∈ {0, 0.1, 0.5, 1} 共 24 组。键名 `lam{λ}_mu{μ}`。
  raw cost/latency 始终保留 → 任何新 (λ, μ) 可离线重算。
- tie（多槽 final 相同）永不丢弃——这是训练数据，不是偏好对。

## 2. JSON Schema（机器校验用）

见 `schema/r3_record.schema.json`（draft-07）。validator 依据此文件 + 第 6 节门禁实现。

## 3. MySQL 镜像表（可选，接已有系统；JSONL 为唯一 canonical 源）

见 `schema/mysql_ddl.sql`。三表: `r3_queries`（query 级 + split + hash）、
`r3_responses`（槽位级，utility 以 JSON 列冗余存）、`r3_collections`（批次/manifest 级）。
同步方向单向: JSONL → MySQL（`storage.py` 负责），禁止回写。

## 4. collector 目录结构

```
r3_own_pool/collect/
  validate_dataset.py     # 先写、先跑（见第 6 节）；schema 校验 + 训练可用性门禁
  datasets/sources.py     # 5 源统一加载: -> {query_id, task_type, query, ground_truth}
  models/qwen_client.py   # 本地 vLLM（3B/7B fp16、14B FP8），流式取 TTFT
  models/deepseek_client.py  # DashScope deepseek-r1-distill-qwen-14b，流式取 TTFT
  runner.py               # for dataset -> for query(index 升序) -> for model; 断点续采
  metrics.py              # quality evaluators（第 7 节分派表）
  storage.py              # JSONL 追加写 + manifest + MySQL 单向镜像
  freeze.py               # difficulty 回填 + split 冻结(seed42 0.8/0.2 分层) + utility 计算 + sha256
  price_table.json        # 采集日冻结牌价（USD/Mtok in/out × 4 模型）
  judge_prompts/v1.md     # 仅 arenahard 使用
```

核心流程:
```
for query in dataset:
    for model in pool:                       # 本地模型逐个常驻全量后再换下一个
        answer, usage, lat = client.generate(query)   # 流式: ttft/decode/total
        save partial(response 槽位)
    # 采集全部完成后:
    quality = metrics.evaluate(task_type, query, responses)   # 只依赖该任务对应层
    cost    = storage.cost_of(usage, price_table)
```

## 5. quality evaluator 设计（按任务分派，不做全局 judge）

| task_type | evaluator | 实现 | 产出 |
|---|---|---|---|
| math (gsm8k) | exact_match | 提取 `####`/末行数字，去千分位/单位/分数等价归一后比对 | auto ∈ {0,1} |
| code (mbpp, humaneval) | pass@1 | 沙箱执行（复用 LLMRouterBench evaluation/ 执行器），超时 10s，提取代码块 | auto ∈ {0,1} |
| knowledge (mmlupro) | option_match | 提取选项字母（末行 `Answer: X` 类模式）与 GT 字母比对 | auto ∈ {0,1} |
| general (arenahard) | judge_qwen-max | 冻结 rubric 0-10 锚定（正确性 6/完整性 2/清晰性 2）/10 归一 | judge ∈ [0,1] |

- 所有提取器正则/解析规则随 schema 冻结（`metrics.py` 内常量），解析失败 → status=parse_failed
  并保留 raw answer（不猜）。
- 人工抽检 5%（~250 条分层）只做校准报告，不改标签。

## 6. validate_dataset.py（先于任何模型调用实现并运行）

输入: 一个或多个 JSONL（+可选 MySQL 连接）。两级检查:

A. **schema 级**（逐行对 JSON Schema）: 必填字段齐全; 4 槽位齐且 model 集合 == 冻结池;
   quality/cost/latency 子字段类型与取值域; status 枚举; query_id 全局唯一; prompt 去重。

B. **训练可用性级**（整库）: status=ok 比例 ≥ 99%（分母 = 5000×4）; latency 覆盖 100%;
   每任务 final 标签覆盖 100%; utility_scores 24 组齐; split 冻结件存在且 train/test 无交集;
   全库 sha256 与 manifest 一致; （arenahard）judge 非空率 100%。

输出: `validation_report.json`（逐项 PASS/FAIL + 计数）——训练脚本以 B 级全 PASS 为放行条件。

## 7. cost calculator 设计

- `price_table.json`: 采集日冻结 4 模型 in/out USD per Mtok（来源: Qwen 官方 opensource 牌价 ×3 +
  DashScope deepseek-r1-distill-qwen-14b 牌价），含冻结日期与出处 URL。
- `usd = in/1e6·p_in + out/1e6·p_out`; tokens 以服务端 usage 为准（vLLM usage / API usage），
  缺失时 tiktoken 估算并置 `tokens_estimated=true`。
- raw tokens 双列永久保留 → 牌价修订可整库重算（freeze.py 提供 `--recompute-cost`）。

## 8. latency recorder 设计

- 统一流式调用: `ttft_ms` = 首 token 到达墙钟; `decode_ms` = total − ttft;
  `tokens_per_second` = out_tok / (decode_ms/1000)。
- `source` 字段区分 `local_4090_vllm`（Qwen 3 槽，Phase 1）/ `dashscope_api`（R1-Distill 槽，
  Phase 1）/ `phase2_local_vllm`（Phase 2 全池重测，覆盖写新批次，不覆盖 Phase 1 原值）。
- **论文口径 = Phase 2**: 全池本地 vLLM FP8、batch=1、同卡顺序、TTFT/TPOT/total 三指标。
  Phase 1 latency 只进附录作 sanity（混布不可比，协议已声明）。

## 9. 训练目标（数据契约，供 reward router 开发对照）

- 模型 1 Reward Predictor: input = query embedding（gte-Qwen2 3584d，R2A 同源可复用）,
  output = 4 槽 reward（每槽一个 head: quality/cost/latency 或 utility）;
  建议 MLP 3584→1024→512→4，MSE / pairwise ranking 复合损失。
- 模型 2 Pareto Selector: 输入预测 reward 向量 + 用户 (λ, μ)，输出槽位（argmax
  `Q̂ − λĈ − μT̂`）；评估沿冻结 (λ, μ) 网格出 Pareto 前沿，对比 Random / Best Single /
  KNN / MLP-classifier / Oracle（R2B 同口径）。
- 扩池零改动: reward head 数 = 池大小，listwise schema 天然支持。

## 10. 规模计划与扩容路径

- v1 = 5000（本协议配额）。放行门禁: reward predictor val loss 收敛 + 任一 (λ, μ) 下
  oracle gap recovery > 0 + cost 轴 Pareto 占优 Best Single（R2D 已示范可行性）。
- v2 = 20k: 扩容源已探明——gsm8k train 余量 ~6.7k、mmlupro test_3000 余 2k、bench 内
  mathbench / livecodebench / livemathbench / bbh / gpqa / simpleqa 等冻结件可加 task_type，
  schema 不变，仅 datasets 表增行。
