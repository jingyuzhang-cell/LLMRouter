# Qwen-Flash V3 受限执行入口与技术准入

结论：**启动器技术接线完成；真实采集 HOLD：Qwen-Flash 当前 Key 权限未确认，且本轮无真实付费授权。** 不派发任何请求。

## 冻结与调用链

独立目录：`/root/r3_own_pool/qwen_flash_v3_execution_v1/`。

基线方案冻结 SHA256：`24c96e1253f32ab314cb48c3dacc04383b758445822d89570ab70d88cfa1eec9`，保留不动。本轮建立新的执行冻结清单，绑定该清单及原预算 V2 的全部50份冻结依赖；不覆盖方案包。

调用链：START.py → 核验新清单、V3方案与旧依赖哈希 → 原评价器零调用输入检查 → 独立授权/权限回执 → 永久排他 LAUNCH_CLAIM → 自有子进程 watchdog → 每格持久化完整请求、输出预算及估算占额 → 固定 Qwen HTTP 请求 → 原始响应保存 → 原冻结 measurement.evaluate → 原生Schema/顶层适配/适配后Schema/证据与L1检查 → 每格记录及最终全部单元状态。

新增文件：START.py、runtime.py、PROTOCOL.json、两种未批准的授权模板、未确认权限回执模板、TEST.py、OFFLINE_TEST_RESULT.json、IMMUTABLE_BASELINE.json、FREEZE_MANIFEST.json。本目录没有付费授权、真实派发记录或生成结果。

模型池仍为 qwen-plus / deepseek-flash / glm-5.3 / qwen-flash；本启动器仅能执行第四列六格，不支持切换至其他模型、MiniMax、旧本地模型或24格全批。

## 请求与评价完全一致

请求模型 `qwen-flash`，北京普通API：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，`DASHSCOPE_API_KEY`，`enable_thinking=false`，`response_format={"type":"json_object"}`，每请求 `max_tokens=16384`。温度等其余参数来自冻结模板，不另设默认覆盖。允许响应身份 qwen-flash 或官方对应快照 qwen-flash-2025-07-28，实际返回身份、request ID、fingerprint原样记录，未知权重版本保持UNKNOWN。未知身份或意外思考输出停止整批。

六格模板与旧Qwen-Plus同节点请求体逐项比较，除 model 外完全相同。Schema、消息内容、来源、时间截止、实体身份、quote、L1参考与质量规则不变。没有把评价参考额外加入Prompt。

评价器直接复用旧冻结 measurement.py，不复制或重写评分逻辑：extract_current 使用同一 quote V2 及允许的裸数组顶层封装，其余五节点使用同一 Contract V2。每格新建原守卫与固定前置上下文，不传播本批其他模型输出。

保留 raw_schema_pass、adapted_schema_pass、evidence_guard_pass、transport_format_violation、adaptation_type、完整原始输出、独立L1、verified_metrics、proxy_metrics、unknown_metrics、合同首次失败与登记数量。完整 QUALITY_AND_CONTRACT.json 单独保存。API往返时延与单元/批次墙钟分别记录；无法独立观测的服务端纯推理时延为空，不能把HTTP往返全称为服务计算时延。

已知 ISO 日期语法与跨页单位窗口拒绝仍保留。这些是评价边界，不能自动解释成模型事实错误；本轮未修改合同或影子复评规则。事实引用通过不等于完整事实精确率；风险主观结论及全任务质量UNKNOWN。

## 权限检查结果

**未确认。** 本地只有未确认模板，没有同一Key、北京地域/业务空间的Qwen-Flash权限及普通API付费资源回执。未读取任何密钥，未发认证账户或模型列表请求。

[官方Key文档](https://help.aliyun.com/zh/model-studio/get-api-key)说明地域、业务空间和自定义模型范围会影响访问权限。因此 Qwen-Plus 历史成功不能替代 Qwen-Flash 权限。当前没有经确认免费、可用且已授权认证的只读账户查询路径，不假设存在，也不以生成请求探测。

六格运行需要控制台或官方支持回执：模型、端点、地域、实际Key安全SHA256绑定、普通API付费资源、确认人、证据引用及有效期。授权还绑定回执的规范JSON哈希。运行时仅在已授权子进程内读取 DASHSCOPE_API_KEY（环境→.env.modelpool→.env），计算指纹核对，不输出/落盘密钥。

若无法取得权限回执，已准备 **permission-probe** 模式：只用第一个完整冻结 extract_current 请求，最多1请求；它仅免于要求事先证明模型访问权限，不免除独立付费授权、费用风险、凭据使用授权及模型身份检查。响应HTTP成功与模型身份可证明当次访问，合同失败另计；不能证明余额足够或其余节点成功。**本轮不执行。**

## 请求与费用停止机制

|模式|最多请求|每次输出上限|客户端完整墙钟|请求截止|收尾预留|
|---|---:|---:|---:|---:|---:|
|six|6|16,384|900秒|120秒|60秒|
|permission-probe|1|16,384|240秒|120秒|60秒|

单请求探针留出额外启动校验余量，不是将所有时间都用于API。父进程自入口开始计时，在总截止前60秒终止自有worker；请求另有SIGALRM硬客户端截止与connect/read timeout。父进程只终止自己创建的子进程；不调用GPU、不管理其他实验进程。远端是否取消与最终费用保持未知。

六格输入代理73,377 Token，总最大输出98,304；≤128K输入档、按输出全用完的条件估算¥0.15846255，**不是现金硬上限**。单探针输入代理5,549，条件估算¥0.02540835。实际输入仍无认证硬上界。

为避免把最低价格档当停止保证，启动器的保守费用监控统一使用公开最高输入/输出阶梯单价1.2/12元每百万Token：派发前按该格输入代理和最大输出占额；收到usage后按实际Token重算；超过用户在独立授权中指定的 `conditional_estimate_stop_cny` 则停止。六格监控预留之和约¥1.2677004、第一格约¥0.2032668，均只是**条件估算**。模板阈值留空，未经批准不会自行设置。

这项监控不能阻止当前请求已经发生的未知账单，也不是账户余额限制。无usage时保留整个估算占额，标记未知债务并停止；实际cost始终待账单核验，不把估算写成实际费用。若要求真正现金硬上限，仍需账户侧可执行限额或供应商保证；本入口不声称已实现。

永久原子排他启动标记覆盖两种模式，崩溃后不自动清除；每格在HTTP前保存请求及派发占额。不重试、不修复、不切模型。HTTP/账户/身份/未知usage/接口异常立即停止；格式、Schema、证据失败计入该格，其他独立格沿用同一冻结输入，不修复重跑。所有剩余格明确NOT_EXECUTED，超时中断格IN_FLIGHT_OR_UNKNOWN。

单探针与六格不是自动串联流程；执行任一模式后该包启动标记保留。若先跑探针，后续续采必须另行授权、明确排除已派发单元并冻结续采协议，不能直接用六格命令重复第一格。

## 验证与可比性

仅10项针对性零调用测试：授权/权限/有效期/Key绑定、单请求范围、模板等价与原评价器、六格Mock字段保留、HTTP/身份/未知usage停止、费用/墙钟派发前拒绝、永久声明与重复拒绝、超时不重试、历史响应同评分影子回放。Mock仅证明执行接线，不提供新质量/能力结果。

旧四格、原24格矩阵、原始输出和历史判定不变；原V3方案也未变。历史三模型与新Qwen-Flash列只能做标注时间和版本的条件性比较，不能称同批严格配对或完整四模型矩阵。其余五节点没有历史真实结果不能补齐。没有运行完整DAG、恢复、路由或ZCODE调度器。

## 准确命令（本轮仅运行第一条dry-run）

零调用核验：

```bash
PYTHONDONTWRITEBYTECODE=1 python /root/r3_own_pool/qwen_flash_v3_execution_v1/START.py
```

取得独立六请求授权与有效权限回执后：

```bash
python /root/r3_own_pool/qwen_flash_v3_execution_v1/START.py --execute --mode six --authorization /absolute/path/approved_six.json --permission-evidence /absolute/path/confirmed_qwen_flash_permission.json
```

仅在另行批准单请求权限探针后（不同时批准六请求）：

```bash
python /root/r3_own_pool/qwen_flash_v3_execution_v1/START.py --execute --mode permission-probe --authorization /absolute/path/approved_one_probe.json
```

授权的freeze_sha256必须是新执行目录FREEZE_MANIFEST.json的SHA256，不能填旧方案包哈希。权限回执哈希采用 `sha256(json.dumps(receipt,sort_keys=True,separators=(',',':')).encode())`。两份模板 approved 均为false，不能直接用作批准文件。

最终状态：**TECHNICAL_ENTRY_READY / REAL_EXECUTION_HOLD**。下一步仅为确认当前Key权限并获得指定模式的独立付费授权；不需要再开发路由器或寻找第五个模型。停止等待，不发送请求。
