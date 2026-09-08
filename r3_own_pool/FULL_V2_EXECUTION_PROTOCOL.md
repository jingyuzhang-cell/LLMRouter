# R3 全量执行协议 v2（2026-09-08）

本版按用户最新顺序：完成四模型真实采集 → reward supervision → 基线/MA-Router → Pareto 评价。继承 v1.1 的自动指标与开放题 judge 分开报告规则。

## 数据与执行

冻结 query-only cohort：data/cohort_full_v2。5000 个唯一 query，四槽共 20000 个响应单元。去重损失的一个 mmlupro query 用下一个 GSM8K train query 补足；不重复计数。按源分层 3500 train / 750 validation / 750 test；所有候选模型响应随 query 同组。pilot 属于该 cohort，不能用 pilot 中测试题结果选择超参；如已做此类选择，须重新获取未触碰 holdout。

full_collection.py 等待现有 pilot/依赖修复任务后继续全量；API 与本地两条运行队列，本地模型顺序 medium→large→small。已有响应复用，transport failed 再重试一轮，原始历史不覆盖。截断结果单独保留，不按正确性反复重采。每个 runner 本地 GPU/每 API 槽加互斥锁；服务启动失败及时退出。数据完成前不自动训练。

实际 large 是 GPTQ-Int8 权重，必须在报告写明，不能称全池 fp16/FP8。API 模型版本若未返回标为未知。已有 pilot 没记录的元数据不能补造。

## 监督

原始 query.responses 为 listwise，保留所有 tie、自动正确性、judge 分数、失败状态、token 与 timing。训练导出 (query_id, model_id, Q, C, L)；quality predictor 预测 Q，资源 predictor 单独预测 C/L，决策 U=Q−λC−μL。权重在验证集选定，不能用 test 成本/延迟决定选谁。pairwise 可由同一 query 的分项标签派生，tie 保留半胜或零差。20000 行仍只对应 5000 个独立 query，不宣称样本量必然足够。

二元自动正确性是合法监督，连续质量不能凭空编造，也不以 judge 强行覆盖可验证任务。开放题 judge 与自动任务分别报告。difficulty 若由回答质量派生，只能用于事后分层，禁止成为在线输入。固定模型 ID/输出头不支持未见模型的天然泛化。

## 预注册基线

Random（均匀随机期望）、Best Single（仅训练选模型）、KNN utility（训练邻居分项均值）、MLP winner、Reward Regression（线性 Ridge）、MLP Reward、Transformer Router、Oracle（事后上界）。Transformer 具体 encoder 和训练预算在训练前独立冻结；当前不下载/更换模型或提前训练。各方法共用 split、标签、成本尺度和选择规则，记录 Router 自身延迟/计算成本。

## 评价

Quality 和相对 Best Single 的差值、Oracle gap recovery=(Qrouter−Qsingle)/(Qoracle−Qsingle)（分母非正时 null）；成本节省=1−Crouter/Csingle（分母为零时 null），并同时给 quality 差/质量约束；latency 和 routing overhead；质量最大、成本/延迟最小的非支配点与 quality–cost frontier。按 query 配对 bootstrap，分源报告；测试集不选最佳 λ/μ。有限网格不等同完整 Pareto 前沿，AIQ 需按原论文另行核验实现。

## 尚未满足的正式实验门禁

四槽原始响应齐全、评分覆盖、错误/截断显式报告、split/hash 校验后才能冻结训练标签。代码回答执行需受限沙箱；完整回答评分且 judge 可恢复，不能静默截断。完整实现这些门禁前不得宣称全流程就绪。

现有 price_table.json 是旧代理估计，不能当实际成本。中国区 reasoning 官方牌价查得输入 1 CNY/Mtoken、输出 3 CNY/Mtoken（https://help.aliyun.com/zh/model-studio/model-pricing，2026-09-08 查询）；与旧 USD 代理不同，不能直接混算。实际账单/本地 GPU 单价尚未核实，原始 tokens 和 timing 保留，正式成本节省必须在成本口径冻结后重算。混合部署 Phase 1 latency 仅作探索，正式结论需要同部署重测。
