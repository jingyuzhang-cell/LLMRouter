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

v2 表示学习阶梯（按投入递增，全部等 GRR 决策树触发；核心叙事：从 query
representation 升级为 **query-model compatibility representation**）：
- V2a query features concat：embedding + task_type + length + difficulty 预测头
  （多难度维度：math/code/reasoning difficulty scores）
- V2b contrastive routing encoder（正：query+best model；负：query+bad model，
  CLIP 式对齐；直接修 kNN 失败的局部性问题）
- V2c capability-init model encoder：m_emb 用模型能力向量初始化（reasoning/
  coding/math/cost/latency），或直接以能力向量为输入 —— 同时解锁 LOMO
  （id-nn.Embedding 结构上无法对未见模型出嵌入）
- V2d cross-encoder（query + model description 联合 Transformer 交互编码）：
  表达力最强、推理成本最高，v2 末位选项
- 红线不变：NO RL / GNN / LLM-agent / winner classifier

Related Work 对应（论文用）：Query Encoder ↔ LLM routing embedding；difficulty
encoder ↔ IRT-Router；model encoder + FiLM 融合 ↔ EquiRouter；contrastive ↔
router embedding alignment；ranking loss ↔ EquiRouter。
论文表述：针对现有 LLM Router 忽略 query-model 双向匹配关系的问题，设计模型
条件化表示学习模块，通过联合编码任务语义与模型能力特征，学习 query-model
compatibility representation。

## 10. MA-Router 总体架构图（冻结版 + v2 扩展点）

```
                        Query
                          |
                   Query Encoder            [v1: gte-Qwen2 fp16 冻结]
                          |
                        h_q ──────────────┐ (V2a: + task/length/difficulty concat)
                                          │ (V2b: contrastive 对齐后的空间)
   模型槽位 id / (V2c: 能力向量)           │
          |                               │
   Model Encoder [v1: nn.Embedding(4,64)  │
     可学习=latent capability repr]       │
          |                               │
        h_m ──────────────┐               │
                          ↓               ↓
                     Fusion MLP (3584+64 → 256 → 128 → 1)
                          |
                    Q̂(q, m)  ×4 槽       [V2d: cross-encoder 替代]
                          |
              L = L_q(MSE) + α·L_rank(pairwise hinge)
                          |
        ┌──── 决策层（不学习）────┐
        |  Cost/Latency profile  |
        |  U = Q̂ − λC − μL       |   ← Pareto-aware：λ,μ = 策略控制量
        |  ε-tiebreak: |ΔQ̂|<ε → 最便宜 |
        └──────────┬─────────────┘
                   ↓
              select model
```

## 11. 文献支撑映射（Related Work 素材；引用前需核实条目）

| 文献 | 思想 | 对应 MA-Router 组件 |
|---|---|---|
| RouteLLM (ICLR 2025) | preference data 学强弱模型胜负概率 | 我们已在 R2A 复现；binary 偏好对路线被 R2C 证伪（tie 丢弃根因） |
| ICL-Router (AAAI 2026?) | model representation 参与路由 | Model Encoder（m_emb）——需核实条目 |
| IRT-Router | 模型能力画像 × query 需求匹配 | V2c capability-init model encoder——需核实条目 |
| EquiRouter / "When Routing Collapses" | model-conditioned representation；objective-decision mismatch | 消融梯子 A/B 直接验证 conditioning 增益——需核实条目 |
| CLIP 式对比学习 | (query, best/bad model) 正负对齐 | V2b（若 A 消融证明表征瓶颈） |

⚠️ 除 RouteLLM 外的三篇条目在写论文引用前必须逐篇核实真实性与准确出处（顾问转述
可能失真）；设计本身不依赖这些引用成立——它由我们的 R2C/R2D 诊断链独立推导。

优先级（用户定）：model-conditioned ★★★★★ / pairwise ranking ★★★★★ /
difficulty encoder ★★★★ / contrastive ★★★★ / 单纯加数据 ★★。

## 9. 论文包装口径（用户 2026-09-08 钉死）

- **问题表述（一句话）**：现有 Router 将 LLM 视为离散类别标签，而非具有不同
  能力边界与成本属性的决策对象，导致 query→model 匹配关系难以学习。
- **题目候选**：
  1) Learning Model-conditioned Utility Representations for Multi-objective LLM Routing
  2) MA-Router: Model-aware Multi-objective Ranking Router for Efficient LLM Selection
- **三贡献**：① 发现阶段——winner-based routing 的 label compression + model
  ignorance（R2C/R2D 诊断链 + 5000×4 响应池证据）；② model-conditioned
  representation learning（query + model capability 联合编码 → compatibility）；
  ③ Pareto-aware decision mechanism（quality-cost-latency 三目标）。
- difficulty encoder / contrastive 不进主模型，只作 V2 ablation/extension。
- m_emb 表述为 **latent model capability representation, learned end-to-end
  through the routing objective**（不是人工能力标签）

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
