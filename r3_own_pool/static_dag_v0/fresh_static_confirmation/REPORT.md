# Fresh Static DAG Confirmation

使用经审计未参与开发的MultiHiertt train独立holdout，100题；不称为官方test。原dev模型、特征、GTE、节点定义、评分与utility固定。

主评估 493 个节点，Transformation 4 个仅探索性报告。所有三个候选模型各节点均有真实响应。

| 方法 | 主节点质量 Q | 去重总 tokens | 去重调用 | 每任务服务时长 s |
|---|---:|---:|---:|---:|
| AlwaysLarge | 0.4483 | 499102 | 400 | 11.710 |
| QueryRouter | 0.4442 | 498533 | 400 | 10.185 |
| StaticCapability | 0.4483 | 499102 | 400 | 11.710 |
| FrozenNodeRouter | 0.5132 | 485643 | 400 | 7.787 |
| NodeOracle | 0.5781 | 521767 | 410 | 6.432 |

## 配对比较（task-cluster bootstrap，10000次）

Node Router − QueryRouter：ΔQ=+6.90pp，95% CI [3.43, 10.48]pp；每题tokens差=-128.9，CI [-175.42049999999998, -84.49800000000003]。
Node Router − AlwaysLarge：ΔQ=+6.49pp，95% CI [3.86, 9.13]pp；每题tokens差=-134.6，CI [-187.97299999999998, -84.59875000000001]。
Node Router − StaticCapability：ΔQ=+6.49pp，95% CI [3.86, 9.13]pp；每题tokens差=-134.6，CI [-187.97299999999998, -84.59875000000001]。

## F1–F3

F1（至少一个主要类型Node GAP>0）：True。
F2（泛化方向）：True；统计支持：True。
F3（quality recovery>0）：True；Recovery=0.5，CI [0.3281250000000002, 0.6527777777777773]。BestFixed=large，quality oracle gap=0.129817。
Static阶段最终确认：True。

| Node Type | 节点 | BestFixed Q | Oracle Q | GAP | NodeRouter Q | Recovery |
|---|---:|---:|---:|---:|---:|---|
| extraction | 193 | 0.5959 | 0.6943 | 0.0984 | 0.5959 | 0.0 |
| transformation (exploratory) | 4 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | None |
| reasoning | 100 | 0.1900 | 0.2700 | 0.0800 | 0.2200 | 0.3749999999999999 |
| verification | 200 | 0.5900 | 0.6200 | 0.0300 | 0.5800 | -0.3333333333333333 |

## 冻结与边界

- This is a conditional node-table benchmark: gold facts for reasoning and gold/perturbed verification inputs; not deployed end-to-end DAG quality.
- Fresh holdout is audited unused labelled train, not official test; audit covers two workspace roots, not pretraining or unknown external use.
- Full-dev heads refit/exported with original alpha/features before fresh inference; original CV reproduced.
- StaticCapability follows implemented global profile, not a per-node-type profile.
- Question-length feature and quality scoring unchanged, including their limitations.
- Primary transformation excluded; old46.2% was utility recovery, fresh number is quality recovery.
- Per-call latency/service sum and deduplicated tokens are measured; end-to-end latency and dollar billing not established.

本轮完成后停止。不依据fresh结果修改参数或阈值，不重选模型，不启动Feedback、Dynamic DAG或Graph Forest，不推GitHub。
