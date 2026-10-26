# 任务B：执行绑定验收报告

**结论：零调用FakeMeter绑定PASS；真实执行准入HOLD。**

仅两臂：A=GLM-5.3固定整图，B=采购Qwen-Plus/余额DeepSeek。A是已有开发样本上预先选定的强单模型，不声称已知总体最优。预算未认证，不提供真实模型发送通道。

|检查项|状态|证据|
|---|---|---|
|same_dag_prompt_evidence_deadline|PASS_FAKE|A/B共享节点、边、逐字节分支消息、冻结目录与240秒共同臂截止期。|
|allocation_only|PASS_FAKE|只改模型分配；结构与恢复关闭，固定两轮AB/BA。|
|frozen_terminal_scorer_binding|PASS_FAKE|原始分支文本经过冻结限定合同，均提交后才汇合评分；合法但错误数值会降低分数。|
|complete_metering|PASS_FAKE|逐请求usage/币种/模拟费用/本地服务墙钟/重试0；实际账单null，语义引用正确率null。|
|cache_dedup_budget_stop|PASS_FAKE|无跨臂复用；重复运行拒绝，指纹异常阻止汇合；任一错误后不追加臂。|
|fake_meter_zero_real_calls|PASS_FAKE|主干干跑8次FakeMeter，真实发送入口显式拒绝；所有结果为合成夹具。|
|version_and_hashes|PASS_FAKE|源文件、配置、评分依赖、合同和当前代码版本纳入MANIFEST；旧文件身份不变。|

13项集成/反例测试通过，退出码0。涵盖正确链路、合法错误内容、非法输出、调用失败、Token越界、预算不足、缓存指纹失效、配置/源身份漂移、重复执行拒绝和真实发送拒绝。有效在途兄弟会完成并记账，失败输出不提交，汇合不运行，后续臂不派发。

主干干跑FAKE_RUN_02完整执行4个臂轮次、8次假调用，每轮确定性汇合后接原评分入口。FakeMeter响应是明确标记的参考夹具，数字正确只是测试输入，不是模型响应，不用于证明收益。FAKE_RUN_01在增加臂级独立预算预留前生成，保留原记录，不冒充最终版本。

## 可重复入口

```bash
cd /root/r3_own_pool/static_allocation_numeric_pilot_v1/ab_execution_binding_v2
python -m unittest -v test_execution
python executor.py --fake-out /tmp/unique-new-fake-run-directory
```

干跑目录已有RUN_CLAIM时拒绝复用。没有真实发送命令，不读取密钥。

## 未验收范围

- Token完整上界、实际账单、HTTP发送/usage绑定与真正的请求取消未由FakeMeter证明。
- 完整舆情Q、完整语义执行合同、语义引用正确率没有独立参考，保持不可评分。
- 单事件两轮只能检查链路和方向，不能做独立任务总体的显著性、非劣或稳定收益声明。
- 所以第1步仍待验收，不启动结构优化实验。
