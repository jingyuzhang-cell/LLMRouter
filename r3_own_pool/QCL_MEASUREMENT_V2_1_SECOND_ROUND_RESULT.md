# V2.1第二轮真实Pilot完成：测量接口封存

**严格Pilot通过**：16/16真实请求、HTTP200、原生Schema及Q可计算；必要字段完整100%，无重试、无追加。

|任务|Qwen-Flash|Qwen-Plus|DeepSeek-Flash|GLM-5.3|
|---|---:|---:|---:|---:|
|ofg_current|1.0000|1.0000|1.0000|1.0000|
|ofg_media|0.6667|0.6667|0.6667|0.0000|
|ssf_current|1.0000|1.0000|0.6667|0.6667|
|ssf_media|1.0000|1.0000|0.6667|0.6667|

输入46379、输出5721，合计52100 Token；执行客户端墙钟81.126秒。费用估算CNY 0.1392853 + USD 0.0048162，实际账单待核验。

**Q是格式敏感的固定槽位响应分，不是纯语义事实正确率。**本轮扣分包含短语边界、单位别名或value重复携带单位，不能据此宣布事实能力排名。未改分或修改规则。

[完整报告](qcl_measurement_v2_1_pilot/REAL_RUN_20261016_080118/RESULT_REPORT.md)，[真实矩阵](qcl_measurement_v2_1_pilot/REAL_RUN_20261016_080118/REAL_CAPABILITY_MATRIX.csv)，[逐项扣分归因](qcl_measurement_v2_1_pilot/REAL_RUN_20261016_080118/FAILURE_ATTRIBUTION.json)。

已完成唯一局部修正和第二轮复验，接口封存。下一阶段须独立设计QS采集与Router目标，不能未经授权直接扩到1000题或把本批小样本当成功概率先验。当前无第三轮、无GPU、无ZCODE修改或Git提交。
