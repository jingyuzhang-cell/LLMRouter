# Local/Full最小接入完成，账户及GO仍待确认

本轮按明确授权修改现有qp5c_runner.py，没有新建执行器。旧实验分支保留；Local/Full新增分支对E执行整节点E-v2生成，禁用原C2补抽循环；t/m/r/p父输出传递及评分段逐字保持不变。修改前源码快照保存在本目录，不覆盖历史数据。

新入口：

```bash
python -B /root/research_outputs/static_pi/stage_d/quality_phase_v1/qp5c_runner.py --local-full --authorization /绝对路径/本批GO.json --output /root/research_outputs/QP5C_RECOVERY_MECHANISMS_20261103/新批次唯一目录
```

该命令本轮未执行。GO文件须包含decision=GO、max_calls=66、estimate_stop_cny=4.5、当前config_sha256和runner_sha256、billing_confirmed=true、output_cap_includes_thinking=true、nonabsolute_cash_cap_accepted=true、rates_cny_per_million={input:0.8,output:2.8}及匹配所确认账户的credential_sha256。不得在未确认时自行填写认证字段；指纹由本地计算，不需在聊天发送密钥。哈希见EXECUTION_CONDITIONS.json。费率变化须重新核算批准，不静默改金额。

输出目录必须全新，账本独立且不加载旧请求缓存；只有Local指定的原始E响应可复用。首次派发前写DISPATCHED；保存完整请求、响应字节及usage；未知usage/系统错误停止，无自动重试。每臂记录从状态绑定、合同加载到终端评分的recovery_wall_s，批次计时单列，未开始臂保留。没有把离线响应时延当真实恢复墙钟。

完成一次限定离线检查：两状态×两臂共4个分支，Local5个、Full6个回调；Local健康E与原响应一致；原下游代码段未变化。使用历史响应仅检查接线，不作为本批模拟收益。无GO在读取凭证/创建批次/网络前阻断。没有启动真实模型调用。

费用：沿用已记录历史公开估费情景，66次输入预留4,325,376、输出计划156,000，合计¥3.8971008；¥4.50阈值、5%储备，对应派发预扣门禁¥4.275。新增输入保护以消息UTF-8字节数加4096不超过65536作保守限制，不改变/裁切请求；它不是服务商Tokenizer认证，实际usage超界会停止且保留已产生费用。输出含思考的账户限制仍必须确认，不能以代码参数存在代替认证。

当前账户读取路径：标准key文件无有效值，现有provider_config中bigmodel-standard-api配置存在。未更换账户，未显示密钥，未发起带凭证探测。账户主体、资源包ID、余额、扣量比例与实际费率无法从该本地配置认证，仍UNKNOWN。账户管理者需对该已配置凭证确认Flash资源包适用、思考输出计量及超包计费；提供脱敏账户说明即可，不需重发密钥。实际结算继续UNKNOWN，不按免费计算。

最终状态：最小恢复接入完成；真实执行HOLD，等待账户计费确认及独立本批GO。无新科学结果，不修改原评分或样本，不补跑、不扩样、不启动其他实验。
