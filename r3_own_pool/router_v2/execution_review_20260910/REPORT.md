# 实验执行核查

结论：尚未形成论文实验闭环；本轮完成本地可执行部分，外部请求待明确授权。

| 阶段 | 核查与本轮执行结果 | 是否完成 |
|---|---|---|
| P0 clean matrix | train/val/test 已重新导出并校验，仍有 650 个开放题单元缺标签；原 750 题 test 全部退役 | 部分 |
| P1 stable pair | 折内独立选题 113 道；large 565/565，reasoning 0/565 | 未完成 |
| P2 MA 标签对照 | 原 winner、原 pair 三 seeds 已实跑；repeat 均值、stable pair、同样本原 pair 对照入口已完成，等待双模型重复标签 | 部分 |
| P3 多目标 | 无事后成本泄漏的 tie-aware 已重新实跑；成本/延迟统一口径与独立确认仍缺失 | 仅探索完成 |

## 可复现结果

- 重建基线：Ridge 87.193%，DatasetBest 87.126%；Ridge 差值区间覆盖 0。
- 新的同架构锚定 MA 控制：原 winner 三 seeds 平均 83.574%，原 pair 平均 87.317%。每个原 pair seed 的增益区间均覆盖 0；不能挑最佳 seed 宣称超过基线。
- 该原 winner/原 pair 比较同时改变标签与训练样本，不能单独归因为标签。待执行的 stable pair 与同样本原 pair 对照才用于隔离标签方向的效果。
- 固定 epsilon=.005：平均质量 87.126%，成本代理降低 1.92%，记录延迟降低 11.97 秒。质量差95%区间为 [-0.403,+0.404] pp，不能认定严格质量非劣。

## 本轮修复与边界

- 修复旧清洗报告只隔离81题的遗漏：已纳入真实测试开封证据，隔离全部750题。没有重算测试质量。
- 发现历史报告所引用 clean train 快照当前缺失；保留历史报告，新生成矩阵并重跑分组OOF，数值复现成功。
- 已完成的旧 large 480条回答未丢弃；按来源与采样设置核验并复评，113题面板中复用22题/110条，标签无变化；新采集455条。
- 每个外层训练折独立选择41题，包含严格分歧、近并列、高regret和按数据集随机采样；去重并集113题。该折评估题的重复标签不能进入该折训练。
- 5×5比较是相关观测，不能当25次独立试验；.8是经验阈值。temperature=.7标签用于temperature=0原结果的迁移实验，不能宣称同部署分布噪声已估计。
- 新增失败恢复、外部HTTP接口、标准答案不外发、稳定标签完整性及同样本对照测试；本轮19项相关测试通过。
- 原始test已开封，正式确认需要新增去重测试题；当前不能通过重排原split恢复独立性。

## 下一步执行入口

外部数据范围、请求次数与重试上限见 EXTERNAL_SCOPE.json；审批仍拒绝数据外发，未启动reasoning重复生成或开放题补评分。
双模型采集齐全后依次运行：

```bash
python -m router_v2.run_repeat_stability --panel router_v2/repeat_fold_panel_20260910/PANEL.jsonl --output data/repeat_fold_stability_20260910 --mode aggregate
python -m router_v2.train_repeat_pair_ma --panel-dir router_v2/repeat_fold_panel_20260910 --groups router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json --repeat-dir data/repeat_fold_stability_20260910 --mode stable --output router_v2/ma_stable_pair_20260910
```

当前stable训练入口会因标签不完整而拒绝运行；尚无stable-pair超越DatasetBest的实验结论。
