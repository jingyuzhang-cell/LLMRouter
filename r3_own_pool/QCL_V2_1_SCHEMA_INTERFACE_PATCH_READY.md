# V2.1唯一Schema接口修正：第二轮准备

本次只完成局部Schema接口修正准备，0真实请求。首轮16/16内容Q可计算、13/16原生Schema通过及原始分数全部保留。

## 选择的修正

选择**格式提示强化**，不增加适配器，不改Schema、Gold、评分器或槽位问题。实际顶层结构为`{"answers":[...]}`，不是facts/evidence对象。

在原system消息前加一个明确的容器要求：整个响应必须是JSON对象；唯一顶层键answers；其值是答案数组；禁止裸数组和代码围栏。原system正文、完整user问题、来源目录、所有槽位、输出Schema、模型参数及输出上限保持字节内容一致。

这不会把裸数组重新统计为原生Schema成功。若模型仍输出裸数组，原生Schema继续失败；内容Q沿用冻结评分器独立计算。没有添加事实、补单位、换引用或修改任何答案。

## 可复核的限制

- 16个请求均仅有相同的容器前缀变化；同任务四模型获得相同messages。
- 评分器及Gold等7项基础输入哈希锁定，首轮全部文件哈希锁定。
- 复用已经实际执行过的零重试受限传输，只替换请求矩阵、增加补丁哈希和round=2授权门禁。
- 新system前缀会改变prompt_hash。第二轮数据必须标记独立轮次，不能与首轮合并为完全同Prompt的严格重复样本。
- 没有真实调用，因此不能说提示强化一定能提高原生Schema通过率。

## 第二轮预算和退出门

仍为2事件×2节点×4模型=16格；单格最多一次请求、2048输出Token；总请求输出配额32768；120秒单请求、2400秒完整客户端。费用估算停止阈值草案仍CNY10/USD1；不是实际现金硬上限，价格快照/输入Token及实际账单上界仍未认证，单独授权必须明确接受。

严格门槛不变：Q可计算16/16、必要字段完整100%且UNKNOWN0、原生Schema>=95%（16格需16/16）。不设最低内容Q，不改短语匹配规则；首轮短语粒度扣分、GLM单位错误不在本次修复范围。

单格质量失败继续测量其他独立单元；账户/权限、身份、未知usage、预算、系统安全及全局截止停止整批。超时远端状态UNKNOWN保留，不重试、不修复、不换模型。

这是首轮真实Pilot后唯一接口修正。第二轮结束后不再自动进行第三轮或新增修订；通过则封存测量接口，未通过则结束这一修补路线。QS规模采集、Router、DAG实验及端到端评价均需独立任务和预算，不自动启动。

## 入口与授权

目录：`qcl_measurement_v2_1_pilot/schema_interface_patch_v1/`。

零调用验证：

`python /root/r3_own_pool/qcl_measurement_v2_1_pilot/schema_interface_patch_v1/START.py`

**真实执行需另外授权并写入可审计AUTHORIZATION.json**；启动器要求round=2和本补丁冻结哈希，首轮授权文件不能复用。AUTHORIZATION_TEMPLATE.json默认approved=false，不是已获批文件。

获得授权后的准确执行命令：

`python /root/r3_own_pool/qcl_measurement_v2_1_pilot/schema_interface_patch_v1/START.py --execute`

本轮没有执行该命令，也没有创建第二轮LAUNCH_CLAIM或读取密钥。

建议授权文本：

> 批准执行唯一Schema接口补丁冻结版本的第二轮16格Pilot。允许相同公开来源和槽位问题发送至既有阿里云、DeepSeek、智谱官方端点，现有Key仅用于内存认证。最多16请求、2048输出Token/次、总32768输出配额、120秒/次、客户端2400秒；批准CNY10/USD1估算停止阈值并接受未认证输入Token与实际费用风险。不重试、不追加、不改Gold或评分。第二轮结束即停止，无论通过与否均不得自动再修订、扩采或启动调度实验。

状态：**FORMAT_PATCH_PREPARED，SECOND_ROUND_NOT_AUTHORIZED**。不修改ZCODE、无GPU、无Git提交。
