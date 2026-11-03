# V2.1真实Pilot已完成

本轮实际16请求，HTTP200和内容Q可计算均16/16；原生Schema13/16，严格Pilot不通过。没有重试或追加。

|节点样本|Qwen-Flash|Qwen-Plus|DeepSeek-Flash|GLM-5.3|
|---|---:|---:|---:|---:|
|ofg_current|1.0000|1.0000|1.0000|1.0000|
|ofg_media|0.6667|0.6667|1.0000|0.0000|
|ssf_current|1.0000|1.0000|1.0000|1.0000|
|ssf_media|1.0000|1.0000|1.0000|1.0000|

输入45243、输出6007，合计51250 Token；执行客户端墙钟86.894秒。条件费用估算CNY 0.1401953 + USD 0.0047214，实际账单待核验，不合并币种。

[完整报告](qcl_measurement_v2_1_pilot/REAL_RUN_20261016_074921/RESULT_REPORT.md)，[真实逐格矩阵](qcl_measurement_v2_1_pilot/REAL_RUN_20261016_074921/REAL_CAPABILITY_MATRIX.csv)。

上述Q是预定义闭集槽位响应质量；新闻短语粒度差异也会扣分，不能等同完整语义事实错误。三个Qwen-Plus裸数组的原Schema失败保持不变。此批两个已见开发事件不支持泛化或显著模型排名。

本轮到此停止：不自动修订、不再调用、不扩到1000题、无GPU、无ZCODE修改或Git提交。
