# 完整 DAG 判别性实验 — GO 操作手册（真实执行授权后使用）

状态：NO-GO（待操作员授权）。本手册在授权后原样执行；金额/上限/顺序均已
冻结，执行者不得临场调整。

## 一、授权与启动

```bash
cd /root/r3_own_pool
python3 -m deadline_reward_v1.full_dag_executor --preflight   # 必须 9/9
DAG_EXPERIMENT_GO=1 python3 -m deadline_reward_v1.full_dag_executor
```

预检不通过 → 停止并报告，不得绕过。执行器内含授权守卫（本仓库代码从不
自行设置 GO）。

## 二、执行序列（已冻结）

- 15 任务 × 3 臂（SS-Tuned → Fixed-Tuned → DD-Online），逐臂逐任务顺序执行；
- 每任务钻石 DAG 按拓扑序（fe, er, tl, xc），tl/xc 提示词动态消费上游当前版本；
- 故障注入按冻结表（seed 20261014）三臂完全一致；DD 种子流可复现：F_TRUNCATED=故障节点首试
  真实 max_tokens=64；F_JSON=首试输出层替换（计划调用照常计费）；
- 恢复：SS 不恢复；Fixed 预冻结规则（low@2048 禁用）；DD-Online v3
  （运行内 PriorStore 学习：Thompson 采样于被决策槽+冻结种子流
  20261014×10^5+task×100+decision、健康槽后验均值、乘性下游传播、
  闭包计价、分节点时延；任务后更新，无同任务泄漏）；
- fail-stop：首个意外错误写 DAG_INCOMPLETE.json 并停止（401 教训已两次验证）。

## 三、硬上限（四项，预检不累积预留）

| 项 | 上限 | 依据 |
|---|---|---|
| 尝试 | 320 | 假传输最坏 216 ×1.5 |
| token | 450,000 | 最坏 311K ×1.45 |
| 现金 | ¥0.80 | 最坏 ¥0.42 ×1.9 |
| 墙钟 | 5,400s | 最坏 4,214s ×1.28 |

预留口径：渲染后提示词保守预留（1 tok/字符+256）+ 全额输出上限；
DS/qwen 按真实费率预留现金；GLM 订阅 ¥0。

## 四、产物与结算（授权后的分析命令）

```bash
python3 -m deadline_reward_v1.full_dag_analyze \
    --run-dir deadline_reward_v1/fe_screening_runs/full_dag_<ts>
```

产出 DAG_ANALYSIS.json：15×3 结算表（分节点契约/语义、q、真实全量
token/现金含失败尝试、顺序任务时延、截止命中、U）+ 三对配对 ΔU
（符号翻转精确置换检验）。分析器已通过等价性测试（45 行零失配，
直接结算=台账重建）。

## 五、GO 决策已知输入（全部零调用量化）

1. **90s 紧层三臂全部任务中位数即迟到**（GO_FEASIBILITY.json）——紧层
   判别力被 λ_f=−2 淹没；接受其为纯压力层或授权前修订分层（冻结项）。
2. **DD 先验敏感性翻转率 0.407**（Wilson-LB 悲观化后，自 0.694 降）——
   配对分析须同时报告逐决策点先验不确定性；DD-vs-Fixed 差异需区分
   先验噪声与机制贡献。
3. 120s 层中位（Fixed 1 迟到 / DD 0）与 p90（DD 4）结论相反——双口径必报。

## 五、失败处理

- HTTP 4xx/5xx、超时、非 JSON 响应 → INCOMPLETE 停止，保留部分台账；
- 预算任一上限触发 → INCOMPLETE 停止（这是保护，不是事故）；
- 凭据：/root/.env.modelpool 优先，绝不入日志/台账。

## 六、完成判据

8/8→三臂全部任务跑完（≤320 尝试）= COMPLETE；任何 INCOMPLETE 都保留
原始记录等裁决，不自动补跑。
