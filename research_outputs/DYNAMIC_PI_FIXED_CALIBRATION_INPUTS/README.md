# 下游独立校准输入

已提取时间线、关系、核验、报告四类真实历史输入，来源为已结案中控开发校准的DeepSeek提交记录。每项逐字段等于保存的真实请求及DAG上游端口，保留父节点commit_id、模型、原始文件SHA-256。没有读取ZCode数据，没有改历史记录，没有发送请求。

解决范围：后续校准不必为了获得这些输入重新运行整条上游链，单个模型抽取失败不再必然剥夺其他节点的测量机会。这里只提供材料，未修改冻结执行器的实际控制流。

使用：同一节点的所有待测模型必须取得同一份input和输出合同；独立派发并分别记录Q/E/K、usage、费用、耗时及失败。不可把某模型失败输出用作其他节点的新输入，也不可在评测后更换固定输入。

边界：上游内容由DeepSeek生成，合同提交不等于语义正确；可能存在生成模型风格偏差。测得的是给定固定输入的条件性能力，不是上游鲁棒性或端到端独立收益。目标节点历史答案没有写入对应输入夹具。报告节点需要的其他节点历史输出属于其输入，不是该报告节点答案。所有新模型测量为空，质量PENDING，不补造Q或可靠性。

未提供付费命令，不沿用旧额度。后续采用本材料属于新批次校准设计，需要在批次中事前声明，而非补跑旧实验。重复样本、画像迁移与质量评分限制必须保留。

验证：四项针对性检查通过：四节点真实输入一致、未提交上游拒绝、输入变更拒绝、合同错配拒绝。命令 `python -B -m unittest -v test_inputs`。`build.py`只读历史数据并写本目录，完全无网络。

## 独立单元处理入口

`replay_cells.py` 将四类节点×两个模型分为8个独立单元。当前是**历史记录导入/回放入口，不是已接入真实HTTP的校准器**。`CELL_REPLAY.json` 包含4条原始DeepSeek观测和4条Qwen缺测；缺测不再阻断其他单元导入，失败不抹除实际消耗，未测不填零。逐条核对请求模型、完整输入、源哈希及响应Token与执行轨迹的一致性。一次历史响应仍仅计1个样本，回放不增加样本量。

`execute_cells` 正常失败继续独立单元，系统异常停止；上限为本地处理单元数和派发前墙钟检查，不是API请求、现金或可中断的HTTP超时守卫。没有付费入口，不能用它宣称实时预算控制已接通。测试中的失败/异常由内存夹具触发，只证明分流行为，不是模型实测。

复算：`python -B replay_cells.py --output NEW_CELL_REPLAY.json`（输出文件须不存在）。验证：`python -B -m unittest -v test_cells`。真实HTTP适配、完整预算及新批次授权仍未接入；本轮不修改冻结运行器或重启旧批次。

## 输出外包装歧义处理

`REQUEST_DRAFTS/` 保存8份未发送请求草案（四节点×两个模型）。`build_requests.py`把返回结构约束放入system、输入材料放入user；明确只返回findings或report顶层，不回显node_id/contract/schema/input包装。原始输入未修改，两个模型的messages及其他通用参数相同，仅model不同。离线核对见OFFLINE_CHECK.json。

这不是已授权的新批次：没有HTTP入口、计费账户绑定、输入Token认证、现金预算或真实执行。3072是每请求计划输出限制，8请求合计24576仅为输出Token计划上限，不是总Token或账单上限。服务商特定参数兼容性未验证。模型标识沿用历史候选，不声称版本已重新认证。

提示已发生变更，因此历史DeepSeek观测不能假装是同一新提示下的对照。未来若使用此方案进行配对校准，两模型都需相同新提示的真实观测；不能只测Qwen再把新旧提示混合宣称模型优劣。旧Qwen失败不改判，所有参考Q保持UNKNOWN。此修改只消除已知歧义，不保证真实模型不再违反合同。

## 已接通的独立真实执行入口（当前未授权）

`run_calibration.py` 现在提供默认只读预检和显式`--execute`入口。使用新目录内的`bounded_transport.py`（基于旧传输器隔离复制，改为发送双角色messages）；复用既有SQLite预算Guard与原始结构验证函数，不改冻结源码。每个单元使用固定历史输入，模型正常合同失败记账后继续其他单元；HTTP/usage/预算/超时异常停止，不重试。新请求、完整响应、输出、usage、耗时、估费及UNKNOWN结算均保存在新输出目录。既有run_calibration测试是OFFLINE_CONTROL_TEST，不是新模型能力数据。

预检：`python -B run_calibration.py`。

仅在本新批次获批、生成对应授权回执、提供本地环境密钥后运行一次：

```bash
python -B /root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_INPUTS/run_calibration.py --execute --authorization /root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_INPUTS/AUTHORIZATION.json --output /root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_RUN
```

不读取或打印密钥；环境变量为DYNAMIC_PI_QWEN_KEY和DYNAMIC_PI_DEEPSEEK_KEY。当前没有AUTHORIZATION.json，模板approved=false。一次运行锁固定在本目录，换输出目录也不能补跑。

本候选范围8请求（每模型4），输入预留131072 Token（非认证上界），输出最多24576 Token，单请求180秒、整批1800秒。2026-10-31核对官方公开报价：Qwen北京非思考、输入<=128k按0.8/2元每百万输入/输出Token；DeepSeek按高峰未命中0.3/1.2美元。按每请求16384输入预留+3072输出计算并向上取整，合计条件估费¥0.077008及$0.034408；候选程序停止阈值¥0.20/$0.10，非现金封顶，实际结算UNKNOWN。价格来源在CALIBRATION_CONFIG.json。这不是把8请求授权从旧40请求继承过来。

BATCH_LOCK.json绑定代码、请求、输入、原始来源及预算依赖。默认预检通过，未批准模板的执行命令被拒绝且未创建运行锁或输出目录。真实网络兼容性仍未在本版本验证。新提示下两模型各需新测量，不能与旧提示混合主张性能差异；合同通过只代表结构及引用链检查，语义Q仍待评价。本批只采集条件性节点画像，不包含Static/Dynamic配对，也不自动启动后续实验。
