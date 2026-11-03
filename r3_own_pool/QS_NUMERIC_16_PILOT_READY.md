# 条件化数值能力区分度 Pilot：受限执行准备

**TECHNICAL READY / CASH UPPER BOUND UNVERIFIED / EXECUTION AUTHORIZATION PENDING。本轮0真实API、0GPU，未读取凭据。**

固定4任务×4模型16请求，范围6/9/3/6，共24必要数值目标、96目标观测。模型ID为qwen-flash、qwen-plus、deepseek-flash、glm-5.3；实际端点和请求不改。题目、Gold、守卫、旧实验和ZCODE不改。F2人工Gold与P0-3继续独立HOLD；QS-1000/Router不启动。

## 费用信封

|限制|拟冻结值|
|---|---:|
|请求|16，各格一次，无重试|
|输出|4096/请求，65536/批|
|输入监控预留|32768/请求，524288/批，**非认证Token上界**|
|客户端墙钟|180秒/请求，3600秒/批；串行，worker3590秒停止，父进程负责收尾|
|估费准入/停止阈值|CNY3.00、USD0.10，分别核算，**待授权**|
|实际现金硬上限|UNBOUNDED_OR_UNVERIFIED|

实际冻结消息UTF8长度代理总计225980字节；不能据此声称真实Token总数。每格及按模型/任务汇总详见COST_BY_CELL.csv、BUDGET_SUMMARY.json。条件估算使用每格32768输入预留＋最大4096输出，不假设缓存折扣：

|模型|请求|输入预留|最大输出|条件费用|
|---|---:|---:|---:|---:|
|qwen-flash|4|131072|16384|¥0.0442368|
|qwen-plus|4|131072|16384|¥0.1376256|
|glm-5.3|4|131072|16384|¥1.507328|
|deepseek-flash|4|131072|16384|$0.0589824|
|合计|16|524288|65536|¥1.6891904＋$0.0589824|

公开计价口径每百万输入/输出Token：Qwen-Flash北京非思考128K内¥0.15/1.5，Qwen-Plus同口径¥0.8/2（[Flash官方表](https://help.aliyun.com/zh/model-studio/qwen-flash)、[Plus官方表](https://help.aliyun.com/zh/model-studio/qwen-plus)）；GLM-5.3标准¥8/28（[智谱官方表](https://docs.bigmodel.cn/cn/guide/start/pricing)）。这些是公开价格，不证明账号权益或余额。DeepSeek沿用已存公开快照峰值cache-miss $0.3/1.2；本次[官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)全文访问失败，仅检索摘要可见输入价，输出价未重新认证。因此全批只提供条件估算，不认证最坏账单上界。

启动器在每格前按预留最大用量预估准入，响应后按实际usage重新核算；输入超预留、输出超限、usage未知或估费超阈值立即停止后续。输入超额/价格变化的本次调用可能已计费；客户端超时不代表服务端取消。GLM推理Token和供应商usage口径、隐式缓存、账户实际折扣/资源包、远端执行等都可能造成估算与账单不同。没有严格现金硬上限证明；若必须硬现金上限，则仍HOLD，不能用3600秒替代费用约束。

## 任务与分析边界

TASK_FEATURE_AUDIT.md给出逐题需求。主体、角色、年度、请求单位已给定；测量Q_value_given_slot，不是自由语义或最终报告Q。宏景两题定位后是直接算术，天花板风险高；全满也是有效负面发现。

PREREGISTRATION.md固定覆盖、天花板、跨事件差异门槛和Q/C/L分析；ANALYZE.py输出逐任务四模型满分情况、极差、未知分母、同币种估费支配关系。逐格明细保留原子判定，不能仅凭数值错推断角色错，不能把UNKNOWN记0。每格一次、3个已曝光开发事件，不得宣称稳定排名、P90、完整语义能力、Router有效性。历史旧24格不混入本次配对。

## 启动器

START.py在独立目录接入冻结score_numeric.py；不改原冻结任务包。默认仅校验文件、16格一致性与费用配置，不读密钥、不联网。执行必须提供**新用户独立批准**、精确绑定SHA、相同信封及费用/出站/内存认证许可。单次排他LAUNCH_CLAIM防止重复执行；HTTP自动重试为0，拒绝重定向。不得伪造授权。

每格使用自己的冻结前置输入，任何本格结果均不下传。Schema/内容/证据失败和UNKNOWN继续其他独立格；账户、身份、冻结来源变化、请求/预算/时间、usage未知、系统故障全局停止。客户端超时保留远端完成UNKNOWN并停止整批，不能自动重试。停止时全部16格均有执行或NOT_EXECUTED状态。

零调用检查：

```bash
python /root/r3_own_pool/qs_numeric_16_execution_binding_v1/START.py
```

**只有独立付费批准并如实填写授权文件后**使用：

```bash
python /root/r3_own_pool/qs_numeric_16_execution_binding_v1/START.py --execute --authorization /root/r3_own_pool/qs_numeric_16_execution_binding_v1/USER_AUTHORIZATION.json
```

这条命令本轮未执行。授权字段和建议全文见AUTHORIZATION_TEMPLATE.json、AUTHORIZATION_TEXT.md。绑定身份见FREEZE_SHA256.txt。

10/10直接相关假传输测试通过，包括同输入、出站Gold隔离、未授权拒绝、16格质量失败继续、429停批无重试、错误模型停止、费用准入、Token超额、超时UNKNOWN、UNKNOWN不记0。不重新运行历史200项测试或F2检查。此处测试只证明执行机制，不证明真实模型区分度。完成准备后停止，等待授权。
