# 方案B双模型核验与规则检查结果

**真实核验批次结束；机器辅助候选参考已生成，未认证独立Gold。**

- 请求：20/20；批次状态：COMPLETED；停止原因：None。
- 原生JSON：19；规定核验容器：19；自动重试0。
- 输入Token：107471；输出Token：66147。
- 保守估费（分币种）：CNY 0.1076832；USD 0.0571011。实际账单仍待核验，不把估费写成现金扣款。
- 观测批次墙钟：834.113秒；来源与算法身份保持：True。

## 原文规则核对

共核查262条两模型事实主张（非去重真值数）；其中237条引文可定位到指定源文档，195条未在已执行字面规则中发现反例。后者仍不是独立正确率。
两模型严格字段对齐0对事实，其中0对同时通过来源追溯并给出SUPPORTED，列为机器共识候选。表达不同而未对齐者保留UNALIGNED，不能直接判为分歧或错误。

16个待核冲突项逐项结果：

|编号|状态|双模型共识（若有）|
|---|---|---|
|CT02_C01|UNRESOLVED_SOURCE_TRACEABILITY|—|
|CT02_C02|UNRESOLVED_SOURCE_TRACEABILITY|—|
|CT02_C03|SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE|NO_CONFLICT|
|CT02_C04|SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE|NO_CONFLICT|
|CT02_C05|SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE|NO_CONFLICT|
|CT02_C06|SOURCE_TRACEABLE_MACHINE_CONSENSUS_CANDIDATE|NO_CONFLICT|
|CT04_C01|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C02|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C03|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C04|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C05|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C06|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C07|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C08|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C09|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|
|CT04_C10|UNRESOLVED_MISSING_OR_DUPLICATE_REVIEW|—|

完整逐事实、逐引文的页码、文本区间、原始判断和字段核对见SOURCE_CONSTRAINED_REFERENCE.json。仅对空白/Unicode作定位规范化；未重写模型事实、替换证据或补数值答案。跨文档重复日期不自动算矛盾，TRUE_CONFLICT共识也仅为机器语义候选。

## 六维参考的实际边界

来源事实和引文可形成候选参考；必要完整性和问题相关性仍UNKNOWN，因为原CT任务没有最终问题字段及已确认的必要事实全集。模型不能猜题补全。未进行人类双盲评审，所有7事件保留开发曝光。

## 稳健性与停止

16项中有12项仍未决；不能将它们强判为支持/反对。保留不同合理处理下的标签范围，但没有与这10任务和本批参考匹配的策略终端输出，策略排序敏感性目前不可识别。本轮不读取调度器答案来构造参考，不捏造稳健结论。

批次结束后停止；无追加、无重试、无QS/Router/GPU或调度收益实验。实际账单及终端任务定义的缺口保留，不自动进入确认性实验。