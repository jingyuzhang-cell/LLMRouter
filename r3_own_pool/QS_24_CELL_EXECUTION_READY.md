# QS24：费用信封与受限执行绑定

**技术准备完成，等待本批独立费用授权。0生成请求，未读取真实凭据。**评分冻结仍为`fae5c7bccb052ef0f9ae5a2101caec0fac54b5e59652b6bb00e1b06e06985fa0`，未修改任务、Prompt、Schema、Gold或score.py。新代码仅在[qs_24_cell_execution_binding_v1](qs_24_cell_execution_binding_v1/)；ZCODE、旧实验、V2.1及315个历史身份锚点保持不变。

## 1. 建议批准的唯一费用信封

|项目|提案|
|---|---|
|测量单元|6任务×qwen-flash/qwen-plus/deepseek-flash/glm-5.3=24格|
|请求数|最多24，每格一次；无额外探针、评审、修复、重试|
|输出Token|4096/请求；总98,304|
|请求完整计时|180秒/请求|
|整批客户端|5400秒，同一单调t0，worker5340秒停止并预留收尾|
|任务D|UNKNOWN，不计算按时收益或P90|
|输入代理|冻结messages UTF-8字节合计421,240，不能视为官方Token数量或硬上界|
|请求前估费预留|60,000输入Token+4096输出Token/请求；输入实际超预留时响应后停止|
|建议估费累计阈值|**CNY ¥5.00；USD $0.25，分别核算**|
|真实费用硬上界|**UNBOUNDED_OR_UNVERIFIED**；账户余额/资源包本轮未查询|

阈值明确后可一次批准整批，不需要每1—2格重新授权。费用阈值是客户端估算控制，不是供应商侧现金硬上限，响应后的超额无法撤销。

## 2. 公开价格与条件核算

2026-10-16本轮重新读取官方价目；每百万输入/输出、缓存未命中：Qwen-Flash北京0.15/1.5元、Qwen-Plus北京非思考0.8/2元、GLM-5.3为8/28元，DeepSeek-Flash高峰0.3/1.2美元。各自依据为[Qwen-Flash官方页](https://help.aliyun.com/zh/model-studio/qwen-flash)、[Qwen-Plus官方页](https://help.aliyun.com/zh/model-studio/qwen-plus)、[智谱官方价目](https://docs.bigmodel.cn/cn/guide/start/pricing)、[DeepSeek官方价目](https://api-docs.deepseek.com/quick_start/pricing/)。未查询私有账单，不假设订阅或资源包抵扣。请求仍使用原冻结模型ID与官方普通API端点，不更换供应商或Coding端点。

|模型（各6请求）|输入字节代理|最大输出|代理输入条件估费|60K/请求预留条件估费|
|---|---:|---:|---:|---:|
|qwen-flash|105,310|24,576|¥0.05266050|¥0.090864|
|qwen-plus|105,310|24,576|¥0.1334000|¥0.337152|
|glm-5.3|105,310|24,576|¥1.530608|¥3.568128|
|deepseek-flash|105,310|24,576|$0.0610842|$0.1374912|
|按币种合计|421,240|98,304|¥1.71666850 + $0.0610842|**¥3.996144 + $0.1374912**|

输入代理本身未认证；上述两列都不是“最坏实际账单”。24格逐请求单价、公式、代理、预留和币种见[COST_BY_CELL.csv](qs_24_cell_execution_binding_v1/COST_BY_CELL.csv)。Qwen高输入阶梯价格也已保存，usage超预留时按相应档位估算后停止，不继续用低档美化费用。

仍有账单风险：Tokenizer/消息封装的输入差异、模型别名或价目变化、未返回usage、客户端超时后远端可能继续执行、推理/缓存等账项无法完全核实。余额与资源包覆盖没有被证明，不能写成免费额度。实际cost保留null，直到按请求ID、UTC、usage和对应控制台账单核验。

## 3. 绑定已经完成

[START.py](qs_24_cell_execution_binding_v1/START.py)默认只做零调用检查。执行时逐格复核评分包、绑定包及原始文件SHA256，直接消费原冻结REQUEST_MATRIX_PLANNED.json，不改写消息；只把模型响应交给原冻结score.py。

每次生成之前落独占派发claim、原始请求bytes和请求hash；HTTP输出bytes、JSON、未经修复的模型文本、独立评分、usage、API客户端等待、cell及整批墙钟均保存。HTTP无重定向、无自动重试、不换模型。未知usage、未知费用和未执行状态不记零或成功。

单格JSON/Schema/证据/内容失败及Q=null不停止其他独立格；账户、HTTP、身份、源文件、usage、预算/请求/输出、全局墙钟和系统异常全局停止。父进程最终输出24格状态，只有派发claim而无结算的标IN_FLIGHT_OR_UNKNOWN，未派发标NOT_EXECUTED。启动器独占整批LAUNCH_CLAIM防重复执行。所有结果不得下传真实DAG，不进行Router训练、QS-1000或动态调度。

16项针对性绑定测试通过，包括：模拟24格完整遍历（前两格故意JSON/Schema失败）、原始输出不修复、冻结评分器调用、HTTP账户停止、未知usage停止、身份错误仍核算已知usage、输出/输入预留/估费/请求/墙钟上限、身份核对、异常不重试、独占claim和未批准授权拒绝。测试只使用本地Mock传输及MOCK字符串，不构成真实模型数据或权限凭证。未重复200项评分验收，也未改旧评分。

## 4. 准确命令与授权边界

零调用检查：

```bash
python /root/r3_own_pool/qs_24_cell_execution_binding_v1/START.py
```

仅在用户独立批准后，按实际批准原文新建`USER_AUTHORIZATION.json`，填入本绑定冻结SHA256、完整信封和出站/内存认证许可，然后运行：

```bash
python /root/r3_own_pool/qs_24_cell_execution_binding_v1/START.py --execute --authorization /root/r3_own_pool/qs_24_cell_execution_binding_v1/USER_AUTHORIZATION.json
```

当前仅有[approved=false的模板](qs_24_cell_execution_binding_v1/AUTHORIZATION_TEMPLATE.json)，没有伪造有效批准、余额证明或权限凭据。旧授权不能替代本次费用信封；默认检查不读取Key，也不发送请求。可直接确认的授权文字见[AUTHORIZATION_TEXT.md](qs_24_cell_execution_binding_v1/AUTHORIZATION_TEXT.md)。

**最终状态：BOUND_EXECUTION_READY_AWAITING_NEW_FEE_AUTHORIZATION。**下一步只需独立确认本信封及受限数据发送/认证用途，不需要再修改评分体系。真实24格只验证是否存在可观察的模型×任务Q/C/L差异；6题属于3事件，一格一次，不足以证明稳定交互、Router有效或自动放行QS-1000。本轮到此停止。
