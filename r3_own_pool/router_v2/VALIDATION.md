# 本轮验证记录

2026-09-08。执行环境：`/root/autodl-tmp/llmrouterbench_r2_venv/bin/python`，CPU，OPENBLAS_NUM_THREADS=1 / OMP_NUM_THREADS=1。

执行：`python -m unittest discover -s r3_own_pool/tests`（从/root）。20 tests，全部通过。另通过改动文件语法编译与 `git diff --check`。

关键证据：

- 合成端到端训练→validation冻结→test评估，覆盖24组偏好和分项/约束结果。
- 仅翻转合成test质量、将test成本与延迟乘1000，重新训练的所有预测和验证选择完全相同（计时字段除外）。
- 封存后修改选择文件，在读取测试质量前拒绝评估；同run重复评估被独占开封标记拒绝。
- 全tie排序损失为零且可反传；不同有效pair数不改变同等违反程度的每题权重。
- Oracle gap为零返回null，零资源尺度不产生NaN/Inf；未通过质量/延迟门槛时回退固定模型。
- 缺失质量、不完整/重叠split、未验证成本门禁均拒绝；JSONL内Unicode分隔符正确保留。
- 新冻结入口逐字保留split和outcomes，拒绝覆盖；旧full_v1冻结入口在读取数据前拒绝。
- 机会分析在读取候选结果前过滤开发query；测试记录响应结构即使无效，也不影响训练分区分析。
- 既有采集完整性与旧Router修复测试继续通过。

没有调用新模型API、使用采集GPU、运行真实全量训练或评估真实test质量。合成数据的结果只证明软件流程运行与隔离性质，不证明模型有效性、统计显著性、全局最优性或部署节省。

当前真实数据门禁快照见 PREFLIGHT.json：5000 query、3500/750/750划分核验通过；四槽完整query仍只有500。成本、评分、代码执行隔离和holdout历史尚未认证，不能自动生成PASS gate。采集任务继续运行，快照计数会过时。
