# Multi-objective Adaptive Router 数据采集协议 v1.0

状态: FROZEN（2026-09-08）。本协议取代 r3_own_pool/R3_DATA_PROTOCOL.json 的草稿。
目的: 为 Multi-objective Adaptive Router（预测 per-model reward = quality − λ·cost − μ·latency，
Pareto 选择）构造自有 routing dataset。Phase 1 = 快速验证 query→模型选择规律是否存在；
Phase 2 = 全本地 vLLM 重测 latency/cost 正式实验。

编码自 R2A/R2B/R2C/R2D 失效分析的教训:
- 永不丢 tie（R2D 根因 1: 训练集丢 tie → 路由器退化为常数预测）
- 质量必须分级（R2C: 二元分数把 oracle headroom 封死在少数独赢比例）
- latency 是一等公民（R2C: 所有官方数据均无 latency）
- 保存原始 answer（可重评，judge 协议会演进）
- listwise 存储（无 pairwise 阶段）

## 1. 数据集选择（5 源，配额冻结，合计 5000）

| task_type | dataset | 配额 | 来源（本地冻结件） | ground truth | Level-1 自动指标 |
|---|---|---|---|---|---|
| math | gsm8k | 2112（test 1319 全部 + train 前 793） | HF openai/gsm8k 经 hf-mirror 下载，下载即 sha256 冻结 | `#### 数字` | exact_match（数字等价） |
| code | mbpp | 974（全部） | llmrouterbench_r2/data/bench/mbpp（974 题） | 测试用例 | pass@1（沙箱执行，复用 LLMRouterBench evaluation/ 执行器） |
| code | humaneval | 164（全部） | llmrouterbench_r2/data/bench/humaneval（164 题） | 规范解+测试 | pass@1（同上） |
| knowledge | mmlu-pro | 1000 | llmrouterbench_r2/data/bench/mmlupro/test_1000 | 选项字母 | 选项 exact match |
| general | arenahard | 750（全部） | llmrouterbench_r2/data/bench/arenahard | 无 | 无（仅 Level-2 judge） |

- 选取规则: 各源内按 index 升序取前 n（确定性、无随机抽样、无 seed 依赖）。
- 题目去重: 按 prompt 精确文本去重（mmlupro 已知 1 处重复，16==338，保留先出现者）。
- difficulty 字段: 采集完成后按 task_type 内 pool 平均 final quality 三分位（easy/medium/hard）
  派生并冻结——派生量，不人工标。

## 2. 模型池（4 槽位，2026-09-08 API 探测事实驱动）

| slot | model | 服务方式（Phase 1） | 依据 |
|---|---|---|---|
| small | Qwen/Qwen2.5-3B-Instruct | 本地 vLLM（权重已在 HF cache） | DashScope 已下架 qwen2.5 主体系列（仅剩 0.5b/1.5b） |
| medium | Qwen/Qwen2.5-7B-Instruct | 本地 vLLM fp16（~15G VRAM ✓） | 同上；hf-mirror 可下 |
| large | Qwen/Qwen2.5-14B-Instruct | 本地 vLLM，on-the-fly FP8（~14G VRAM ✓） | fp16 28G 不进 24G 卡；FP8 是全池统一无 4bit 权重污染的方案 |
| reasoning | deepseek-ai/DeepSeek-R1-Distill-Qwen-14B | DashScope API `deepseek-r1-distill-qwen-14b`（已验证 200） | 官方 distill 权重服务，Phase 2 转本地 FP8 |

- vLLM 不可用时的降级: 系统 python torch 2.8.0+cu128 + transformers 生成（慢 10-20×，仅应急）。
- Phase 2: 四模型全本地 vLLM FP8 顺序重测 latency（协议另立 v2，数据 schema 不变）。
- 论文期扩池（5-8 模型）: schema 为 listwise，加槽位零改动。

## 3. 调用方式

- 统一 OpenAI-compatible 接口；本地 vLLM `--served-model-name` 与 HF repo id 一致。
- 参数: temperature=0, top_p=1.0；max_tokens: math 4096 / code 2048 / knowledge 2048 /
  general 4096；reasoning 模型 think 段单独存（`thinking` 字段），观察到截断则升 8192 重跑该题。
- 顺序: for dataset → for query（index 升序）→ for model（槽位序）。本地模型逐一常驻
  （一个模型跑完全量再换下一个，避免争用）；API 模型穿插于同一 query 环内。
- 并发: 本地 vLLM batch 由服务端自排；API 并发 ≤ 4；速率/5xx 退避重试 ≤ 3 次，
  仍失败记 status=failed（不静默丢弃）。
- 采样确定性: temperature=0 + 记录 vLLM/HF 与 DashScope 的 model version/revision。
- 断点续采: 按 (query_id, model) 已完成即跳过，manifest 记录进度。

## 4. quality 评价（三层）

- **Level-1 自动指标（主标签，全有 GT 源免费）**: gsm8k exact-match / mbpp+humaneval
  pass@1 沙箱执行 / mmlu-pro 选项匹配。产出 auto_score ∈ {0,1} 与 auto_correct。
- **Level-2 LLM judge（分级 partial credit → [0,1]）**:
  - 主判: DashScope `qwen-max`（本机探测 200 ✓；E 系列已验证稳定）。
    ⚠️ 用户草案的 GPT-4o-mini 经探测 **端点不可达**（超时），本协议替换为 qwen-max。
  - 副判（可选，做一致性统计）: DeepSeek API `deepseek-v4-flash`（探测可达）。
  - judge 必须池外（自偏好规避）; qwen-max / deepseek-v4 均池外 ✓。
  - rubric: 0-10 锚定量表（正确性 0-6 / 完整性 0-2 / 清晰度 0-2），归一化 /10。
    judge prompt 模板随协议冻结（`judge_prompts/v1.md`），输入含题目+参考答案+模型回答。
  - arenahard 仅靠此层。
- **Level-3 人工抽检**: 每源分层抽 5%（共 ~250 条）人工核对，报告 judge 一致率。
- **final 标签规则（训练前冻结）**: final = judge_score（Level-2 完成）；
  Level-2 失败的记录回退 auto_score。tie 永不丢弃。

## 5. cost 计算

- 统一按官方牌价表（采集日冻结进 `price_table.json`，USD per Mtok，in/out 分列）:
  - Qwen2.5-3B/7B/14B-Instruct: 按 Qwen 官方 open-source 牌价（本地推理以牌价计,
    保证与 API 模型可比；Phase 2 另记硬件成本）。
  - DeepSeek-R1-Distill-Qwen-14B: 按 DashScope 该模型牌价。
- 公式: `usd = in_tok/1e6·p_in + out_tok/1e6·p_out`；tokens 取服务端 usage（本地 vLLM
  usage / API usage 字段），无则 tiktoken 估算并标记 `tokens_estimated: true`。
- raw tokens 双列存（tokens_input / tokens_output），价格表变更可整库重算。

## 6. latency 测量

- Phase 1（本协议）: 客户端墙钟 ms（请求发出→完整响应），记录
  `measurement_context` = "local_4090_vllm" 或 "dashscope_api"；latency 仅作参考轴，
  不做结论（混合部署不可比——用户已确认 Phase 1 不追求 latency）。
- 同时记录 tokens_output / time → tokens_per_second（归一化吞吐，跨部署部分可比）。
- Phase 2（正式）: 四模型全本地、batch=1、同卡顺序，TTFT 与 total_ms 双指标。

## 7. 数据库 schema（JSONL，每行一个 query）

```json
{
  "query_id": "gsm8k_test_0001",
  "task_type": "math",
  "difficulty": "easy",               // 派生冻结字段，采集后回填
  "query": "原始完整 prompt",
  "ground_truth": "32",               // arenahard 为 null
  "responses": [
    {
      "model": "Qwen/Qwen2.5-7B-Instruct",
      "answer": "最终答案文本",
      "thinking": "<think>... 或 null",
      "quality": {
        "auto_score": 1.0, "auto_correct": true,
        "judge_score": 0.9, "judge": "qwen-max",
        "final": 0.9
      },
      "cost": {
        "tokens_input": 512, "tokens_output": 230,
        "price_input_per_mtok": 0.0, "price_output_per_mtok": 0.0,
        "usd": 0.00021, "tokens_estimated": false
      },
      "latency": {
        "time_ms": 1830.4, "tokens_per_second": 125.6,
        "measurement_context": "local_4090_vllm"
      },
      "status": "ok"                  // ok|failed|truncated
    }
    // ... 每行固定 4 个槽位全齐（listwise，无 pairwise）
  ]
}
```

- 存储: `r3_own_pool/data/raw/{dataset}.jsonl`（采集）→ `judged/`（评分后）→
  `frozen/`（difficulty 回填 + split 冻结 + sha256）。任何阶段不可变追加，不覆盖。
- split: prompt 级、train 0.8 / test 0.2、seed 42、按 dataset 分层；冻结件含
  train/test query_id 清单与全库 sha256。

## 8. 采集脚本结构（协议冻结后实施，Step 2）

```
r3_own_pool/
  collect/
    sources.py      # 5 源加载器: 统一产出 {query_id, task_type, query, ground_truth}
    clients.py      # 本地 vLLM client / DashScope client, 统一返回 (text, usage, wall_ms)
    runner.py       # for dataset → for query → for model; 断点续采; manifest
    judge.py        # Level-1 指标执行器(exact-match/沙箱) + Level-2 judge 调用
    price_table.json# 采集日冻结牌价
    judge_prompts/v1.md
    freeze.py       # difficulty 回填 + split 冻结 + sha256 清单
```

- 采集 manifest: 每 (dataset, model) 一个进度文件（已完成 query_id 列表 + 计数 + 用量）。
- 门禁（训练放行前全查）: 4 槽 × 5000 题 status=ok ≥ 99%；latency 字段 100%；
  judge_score 覆盖 100% 且主/副判一致率报告；无 train/test 泄漏; 牌价表已冻结。

## 与用户草案的两处事实性偏离（探测驱动）

1. judge 的 GPT-4o-mini → qwen-max（OpenAI 端点本机不可达；qwen-max E 系列已验证）。
2. 模型池 3 个 Qwen 槽位无法走 API（DashScope 已下架 qwen2.5-7b/14b）→ 本地 vLLM
   （3B 权重已在缓存），仅 DeepSeek-R1-Distill-14B 走 DashScope——恰好构成草案的
   "API + 小规模本地" 混合，且 Phase 1 不以 latency 下结论的设定使其无害。
