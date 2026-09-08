# R3 Router Design (FROZEN 2026-09-08, post-pilot)

决策记录。依据：pilot 500×4（86.3% 顶部并列 → winner 标签无意义；cost-quality 10.6× 差距）。
本文件冻结任务定义、结构、损失、评估口径。后续不再重新讨论，只按此实现与实验。

## 1. 任务定义（论文层面的提升）

- ❌ 旧：Best Model Selection —— 学 winner(x)，86.3% 平局下监督信号是人造边界
- ✅ 新：**Utility-aware Model Routing** —— 学 Q̂(x, m)：给定 query 与模型，预测该模型回答该 query 的质量
- gap 的学习途径：不是分类，而是
  - 回归监督：每 query 4 条 (query, model, Q) 样本 → 5000×4 = **20,000** 质量样本
  - 排序监督：每 query C(4,2)=6 对 → 5000×6 = **30,000** pairwise 样本（监督更强）

论文表述：Instead of learning deterministic winner labels, which suffer from unstable
supervision under close-quality models, we formulate routing as a model-conditioned
utility estimation problem.

## 2. 结构（固定，不再扩展；创新不放在结构上）

```
Query ──Text Encoder(frozen gte)── q_emb ┐
                                         ├─ concat ─ Fusion MLP ─ Q̂(q,m)
Model ──Model Encoder(learnable emb)─ m_emb ┘
                                          + Cost/Latency profile（静态，不学习）
                                          ↓
                              U = Q̂ − λ·Cost − μ·Latency → argmax_m
```

- q_emb: gte-Qwen2-7B-instruct fp16（R2A 同源，已验证一致），3584 维，frozen
- m_emb: nn.Embedding(4, d) 可学习（model-conditioned 的最小实现）
- Fusion MLP: 小型（如 3584+d → 256 → 128 → 1），防止 20k 样本过拟合
- Cost/Latency：部署 profile（Phase-1 用采集实测均值，Phase-2 用全本地重测值）
- 推理：对 4 槽各算 Q̂ → 加 utility → argmax

## 3. 损失（固定）

- L_q = MSE(Q, Q̂)
- L_rank = pairwise hinge: max(0, −(s_i − s_j) + margin)，i 比 j 质量高时
- **L = L_q + α·L_rank**（α 待调，margin 固定后冻结）
- 可选后续（不阻塞主线）：β·L_uncertainty（A3 margin 分析若显示大量 <0.05 再启用）
- 明确不做：RL / GNN / LLM-agent / 复杂神经结构

## 4. 评估口径（固定）

- 数据：frozen split（seed 42, 0.8/0.2, 按 dataset 分层），test 上一次性报告
- 对照组（7 个 + Oracle）：Random / Best Single / KNN / MLP-winner（旧路线对照）/
  RewardReg（每模型独立回归，无 model-conditioning 对照）/ **Hybrid Utility Router（本方法）** / Oracle
- 指标：accuracy（路由后 final quality 均值）、cost、latency、oracle gap recovery
- **λ,μ 行为验证（论文必需）**：沿冻结 (λ,μ) 网格展示 router 行为切换——
  λ=0 → quality 模式偏向 14B/R1；λ 大 → budget 模式偏向 7B/3B。
  不同预算下路由分布变化 + Pareto 曲线（accuracy-cost 平面上 router vs Best Single vs Oracle）
- 论文主图候选：A2 Pareto coverage（各模型非支配区域：3B 低成本区 / 7B balanced 区 /
  14B quality 区 / R1 hard-reasoning 区）

## 5. 顺序（固定）

5000×4 完成 → A1-A3 分析（已预注册 analyze_full.py）→ utility label 冻结 →
7+1 baseline 表 → λ,μ 行为与 Pareto 曲线 → Hybrid Router vs Oracle 结论。
判断标准：unseen query 上 router 是否逼近 Oracle 同时显著降成本。

## 6. 主线约束（用户 2026-09-08 钉死）

论文叙事永远是"旧 Router → 新 Router"（classifier Router 升级为 utility-aware
Router），**不是**"Router → 非 Router"。失败分析只作为 Motivation/分析章节。
任何新想法过三问：是否增强 Router（选择能力/泛化/成本质量权衡）、是否形成 Router
创新点、是否偏离主题。

## 7. 消融梯子（论文必需，train_router.py 已实现）

- A：query-only（共享主干 + 4 头，同框架同损失）= `A:Hybrid-noM`
- B：+model embedding（m_emb 融合）= `Hybrid(lam=0)`
- C：+utility 决策 = (λ,μ) sweep（成本/延迟进决策）
- D：+rank loss = α 从 {0, 0.25, 0.5, 1} 在独立 val split（train 内 1/4 分层）上选
- B−A = model-conditioning 增益；D vs α=0 = rank 损失增益
- 泛化验证：test 上 per-task-type 准确率分解（cross-domain 信号）已入输出

## 8. v2 路线（记录备查，v1 结果出来前不实施）

- Query Encoder 升级：contrastive routing encoder（正：query+best model，负：
  query+bad model）——若 v1 显示 gte 冻结嵌入是瓶颈则启动
- Leave-one-model-out 泛化：需要 model embedding 来自模型特征编码器（能力
  profile → MLP）而非 id-based nn.Embedding（id 版对未见模型结构上无 embedding，
  无法做 LOMO）；与 contrastive encoder 同期评估
- 红线不变：NO RL / GNN / LLM-agent / winner classifier

## 9. 论文包装口径（用户 2026-09-08 钉死）

- m_emb 表述为 **latent model capability representation, learned end-to-end
  through the routing objective**（不是人工能力标签）
- (λ,μ) 不叫"24 组参数扫描"，叫 **Pareto-aware routing**：λ,μ 是策略控制量，
  对应 quality-first / balanced / cost-aware / latency-aware 四种部署策略
- 核心指标 = **Gap Recovery Rate, GRR = (Router − BestSingle)/(Oracle − BestSingle)**，
  目标区间 40-60% 即有论文价值
- 定位一句话：model-conditioned multi-objective ranking Router，在多模型池中
  最大化 Oracle gap recovery 并实现 Pareto-efficient routing
- 数据可靠性门禁（标签噪声风险）：qwen-max 重判 200 条 arenahard 槽位，
  within-0.1 ≥ 0.8 且排序保持率 ≥ 0.9 方可作为论文标签；否则换 judge 重标
- 必做三实验：①8 方法 baseline（含 Ranking-only 独立基线）②消融梯子 A-D
  ③Pareto 曲线（4 单模型锚点 + Router 轨迹 + Oracle 便宜-tie-break 锚点）
