# 建议审核与执行记录（2026-09-08）

方向可行，但不接受“已证明标签是根因”“回归一定恢复局部性”“固定四输出天然支持新模型”“Oracle≈Best Single 就结束项目”等强结论。质量轴没有 gap 仍可能有质量约束下的成本收益。更多数据/模型按 pilot 证据决定，不直接扩到 20k。

已执行：使用既有 C8 419 任务、五模型矩阵，独立新增 kNN utility 与分项 Ridge 的 24 组权重探索；训练折拟合文本表示及成本/延迟尺度，选择使用预测资源，保留所有 tie；保存协议、输入哈希、OOF 决策与结果。原 C8 冻结结果未修改。质量回归增益 0.003250 的任务 bootstrap 区间跨零，不能宣称方法有效。见 REPORT.md。

修复 R3 train_reward_pilot.py：原来 Pareto 扫描读取测试候选的实际 C/T，现在改为训练数据拟合的 Ridge 预测；尺度仅来自训练集。补充 kNN 质量基线，修复 json.dumps(ensure_nan=False) 非法参数。仅语法验证，R3 全流程未运行，因为 data/frozen/pilot_v1.jsonl 不存在。原型仍是固定模型池多输出预测，不声称动态扩池泛化；扫描点不等同完整 Pareto 凸包或 RouterBench AIQ。

R3 现状：其他会话正在采集 reasoning 和下载 3B/7B；审计时 reasoning raw 有 225 行，四模型数据不齐。large 的日志显示 vLLM 导入失败（缺 gguf），多个 runner 仍等待健康检查；为避免与活动会话争用，未另开 GPU 采集或修改其环境。该事项尚未解决。下一步需先恢复本地服务，再完成四槽采集、自动评分/独立 judge、冻结和门禁，才能运行 R3 训练。不能把本次五模型历史开发实验称为新的四模型 pilot 成果。

还需处理：freeze.py 的 difficulty 标签方向反了（低正确率应 hard）；该字段仅用于事后分析，不能作在线输入。冻结工具尚未强制所有门禁，训练入口还需接入验证器。价格代理与混合部署延迟不能直接支持正式成本/延迟结论。更改冻结协议应以新增版本记录。

核对的原始文献：
- RouterBench: https://arxiv.org/abs/2403.12031 （405k inference outcomes，不是 405k queries）。
- RouteLLM: https://arxiv.org/abs/2406.18665 （强弱模型偏好路由，不是连续逐模型 reward 回归的直接验证）。
- kNN: https://arxiv.org/abs/2505.12601 。其结果不证明当前 embedding 必然不可学。

其余引文和“独有创新”尚未逐一核验，不应直接复制进论文。
