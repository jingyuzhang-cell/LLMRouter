# Recovery Matrix v2 — Full (148 nodes) 统计报告

统计单位：failure node；cluster bootstrap 按 task_uid，B=10000，seed=20260918。

## 主表：R(φ, a) 恢复率 [95% CI]

| Failure Type | retry_same | switch_model | evidence_retrieval | local_decompose | no_recovery |
|---|---|---|---|---|---|
| **evidence** (n=61) | 0.262 [0.152,0.383] | 0.197 [0.098,0.305] | 0.246 [0.143,0.367] | 0.230 [0.127,0.339] | 0.000 (基线) |
| **reasoning** (n=61) | 0.213 [0.115,0.311] | 0.197 [0.098,0.295] | 0.131 [0.049,0.213] | 0.164 [0.082,0.262] | 0.000 (基线) |
| **structural** (n=26) | 0.192 [0.038,0.346] | 0.115 [0.000,0.231] | 0.154 [0.038,0.308] | 0.077 [0.000,0.192] | 0.000 (基线) |

## 同节点配对差 ΔR(a1,a2)

| Failure Type | 配对 | ΔR [95% CI] | 不一致对数 |
|---|---|---|---|
| evidence | evidence_retrieval vs switch_model ★ | +0.049 [-0.033,+0.138] | 7/61 |
| evidence | evidence_retrieval vs local_decompose ★ | +0.016 [-0.067,+0.102] | 7/61 |
| reasoning | switch_model vs retry_same ★ | -0.016 [-0.066,+0.033] | 3/61 |
| structural | local_decompose vs switch_model ★ | -0.038 [-0.115,+0.000] | 1/26 |

## 成本与延迟（ΔC=增量 tokens，ΔT=额外服务时延 s）

| Failure Type | 动作 | ΔC mean/median | ΔT mean/median |
|---|---|---|---|
| evidence | retry_same | 266.4/242 | 0.307/0.306 |
| evidence | switch_model | 266.6/242 | 0.359/0.358 |
| evidence | evidence_retrieval | 2727.0/3250 | 3.198/2.549 |
| evidence | local_decompose | 2807.1/3393 | 3.471/3.402 |
| reasoning | retry_same | 266.6/239 | 0.317/0.334 |
| reasoning | switch_model | 265.7/239 | 0.353/0.375 |
| reasoning | evidence_retrieval | 2056.2/1146 | 2.712/1.979 |
| reasoning | local_decompose | 2181.1/1289 | 3.585/3.197 |
| structural | retry_same | 292.7/234.5 | 0.332/0.319 |
| structural | switch_model | 293.6/237.0 | 0.397/0.364 |
| structural | evidence_retrieval | 3600.3/3720.0 | 4.373/3.467 |
| structural | local_decompose | 3695.3/3832.0 | 4.849/4.502 |

## 机制分析

- Evidence (retrieval, n=61): P(recover|ΔER>0)=0.1818 (n=11) vs P(recover|ΔER≤0)=0.26 (n=50)；ΔER>0/11，=0/50，<0/0。
- Structural (decompose, n=26): P(recover|ΔD>0)=0.25 (n=8) vs P(recover|ΔD≤0)=0.0 (n=18)。

## 每类最高动作（不作显著性声明）

- evidence: retry_same（no significant best: CIs overlap）
- reasoning: retry_same（no significant best: CIs overlap）
- structural: retry_same（no significant best: CIs overlap）
