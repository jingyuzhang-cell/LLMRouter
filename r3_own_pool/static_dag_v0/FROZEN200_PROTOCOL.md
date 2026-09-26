# Frozen Evaluation Protocol — 200 New Tasks, One-Shot (FINAL EXPERIMENT)

> 独立确认面板:与全部历史工件零重叠;协议在任何调用前冻结;one-shot,不调参不重跑。
> 目的:防止"optimizer/结论在 120 题上过拟合"的审稿质疑。

## 任务生成

- 来源:TAT-QA train,answer_from=table-text,arithmetic,derivation 含运算符,literals≥2
- 排除:`used_uids()` 的全部历史 UID + 主面板 120 题的 UID
- 选择:sha256("frozen200:"+uid) 升序,前 200 题
- 长度过滤:与主面板相同(tokenizer ≤8192)
- 冻结:任务清单在任何模型调用前写入 FROZEN200_POLICY.json 并提交

## 执行臂

| 臂 | clean | f=30%×3seeds |
|---|---|---|
| Single LLM(large 直答+重试) | ✓ | ✓ |
| Static DAG(固定结构,无反馈,整图同模型重执行) | ✓ | ✓ |
| Dynamic DAG(Dynamic-Real:部署检测+局部恢复) | ✓ | ✓ |

初始分配与主面板相同:e1/e2=large, r=medium, v=coder。
恢复规则与主面板 Dynamic-Real 完全一致(e:记忆规则;r→large;v→large;每节点一次;后继闭包;无门控)。
故障注入:能力型故障绑定(task,node,planned-model);种子 20260923/24/25;率 30%。

## 指标

- 主表:三臂 × (clean + f30%) 正确率(3 种子 mean±std)
- 配对:Dynamic vs Static(每种子 Help/Harm + McNemar);Dynamic vs Single @ f30%
- 退化率:Single vs Dynamic
- Pareto:三臂的 (Q,C,L) 前沿与超体积独占贡献
- 调度器:Pareto-aware selector vs 固定策略
- 预算:Q(B) 曲线(8 档)

## 完整性

- 200 题全部保留在分母;失败/超时/超预算不剔除
- 生成参数 temperature 0, top_p 1, max_tokens 512
- (model,prompt) 缓存复用仅限完全相同提示
- 结果一次性写入 FROZEN200_RESULTS.json
