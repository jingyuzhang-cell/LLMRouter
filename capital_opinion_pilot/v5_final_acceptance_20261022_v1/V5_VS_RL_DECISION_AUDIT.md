# V5 / RL 公平逐决策对照（最终验收版）

**来源：13个冻结合成场景，不是历史真实模型回放或独立真实质量实验。** V5先、RL后是冻结执行顺序，CPU计时没有随机化，不能作算法速度显著性结论。两策略同状态、同检测器、同模型能力/硬约束和同计量口径。

完整初始状态、缓存内容、反馈原文/引用、能力表与冻结参考均见[场景JSON](SCENARIO_MATRIX.json)；矩阵在执行前冻结，SHA256见[MATRIX_FREEZE](MATRIX_FREEZE.json)。[完整决策与执行JSON](V5_VS_RL_DECISIONS.json)记录准备状态哈希、全部候选、拒绝原因、预测Q/C/L、实际回调、输出提交、输入指纹及来源类别；未执行候选实际结果为null。

| 场景／能力维度 | V5 Z、R、π；tools | RL Z、R、π；tools | 候选/可行 V5；RL | 执行状态 V5／RL | 动作不同 |
| --- | --- | --- | --- | --- | --- |
| S00 全部缓存健康／NONE | NONE；R=；π=；tools= | NONE；R=；π=；tools= | 1/1；1/1 | COMPLETE／COMPLETE | 否 |
| S01 上游输出合同失效 | LOCAL；R=a,out；π=a→fast,out→fast；tools=join | LOCAL；R=a,out；π=a→cheap,out→cheap；tools=join | 6/4；6/4 | COMPLETE／COMPLETE | 是 |
| S02 汇合节点自身失效 | LOCAL；R=out；π=out→fast；tools=join | LOCAL；R=out；π=out→cheap；tools=join | 4/2；4/2 | COMPLETE／COMPLETE | 是 |
| S03 独立分支缓存指纹异常 | LOCAL；R=b,out；π=b→fast,out→fast；tools=join | LOCAL；R=b,out；π=b→cheap,out→cheap；tools=join | 6/4；6/4 | COMPLETE／COMPLETE | 是 |
| S04 模型不可用 | LOCAL；R=a,out；π=a→cheap,out→cheap；tools=join | LOCAL；R=a,out；π=a→cheap,out→cheap；tools=join | 3/1；3/1 | COMPLETE／COMPLETE | 否 |
| S05 Token预算紧张但可行 | LOCAL；R=a,out；π=a→cheap,out→cheap；tools=join | LOCAL；R=a,out；π=a→cheap,out→cheap；tools=join | 6/1；6/1 | COMPLETE／COMPLETE | 否 |
| S06 Token预算不足／拒绝 | REFUSE | REFUSE | 6/0；6/0 | REFUSED／REFUSED | 否 |
| S07 截止期紧张但可行 | LOCAL；R=a,out；π=a→fast,out→fast；tools=join | LOCAL；R=a,out；π=a→fast,out→fast；tools=join | 6/1；6/1 | COMPLETE／COMPLETE | 否 |
| S08 截止期不足／拒绝 | REFUSE | REFUSE | 6/0；6/0 | REFUSED／REFUSED | 否 |
| S09 质量未知且要求终端质量下限 | REFUSE | REFUSE | 6/0；6/0 | REFUSED／REFUSED | 否 |
| S10 有依据的缓存怀疑／扩大范围候选 | LOCAL；R=a,out；π=a→fast,out→fast；tools=join | EXPAND；R=a,b,out；π=a→cheap,b→cheap,out→cheap；tools=join | 21/20；21/20 | COMPLETE／COMPLETE | 是 |
| S11 有证据VERIFY，不改变健康缓存 | VERIFY；R=；π=verify_b→fast；tools= | VERIFY；R=；π=verify_b→cheap；tools= | 3/2；3/2 | VERIFIED_ANNOTATION／VERIFIED_ANNOTATION | 是 |
| S12 无冲突依据的VERIFY请求／拒绝 | REFUSE | REFUSE | 3/0；3/0 | REFUSED／REFUSED | 否 |

所有可行候选的终端质量预测均为未知，不用0代替；没有可行候选时预测对象为null。下表中Q为**执行后、有效终端输出的合成算术精确匹配**；无合法交付时为null，不能读成内容错误率0。C与L的数值均为合成回调计量，不是真实账单或网络墙钟。

| 场景 | 预测Token V5/RL | 预测串行完成时长秒 V5/RL | 回调Token V5/RL | 合成现金CNY V5/RL | 合成执行秒 V5/RL | 合成终端Q V5/RL | 拒绝原因（两策略相同） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S00 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 1 | 无 |
| S01 | 40 / 20 | 2.1 / 8.1 | 40 / 20 | 0.04 / 0.02 | 2.1 / 8.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion |
| S02 | 20 / 10 | 1.1 / 4.1 | 20 / 10 | 0.02 / 0.01 | 1.1 / 4.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion |
| S03 | 40 / 20 | 2.1 / 8.1 | 40 / 20 | 0.04 / 0.02 | 2.1 / 8.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion |
| S04 | 20 / 20 | 8.1 / 8.1 | 20 / 20 | 0.02 / 0.02 | 8.1 / 8.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion |
| S05 | 20 / 20 | 8.1 / 8.1 | 20 / 20 | 0.02 / 0.02 | 8.1 / 8.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion, token_budget |
| S06 | null / null | null / null | 0 / 0 | 0 / 0 | 0 / 0 | null / null | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion, token_budget |
| S07 | 40 / 40 | 2.1 / 2.1 | 40 / 40 | 0.04 / 0.04 | 2.1 / 2.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion, deadline |
| S08 | null / null | null / null | 0 / 0 | 0 / 0 | 0 / 0 | null / null | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion, deadline |
| S09 | null / null | null / null | 0 / 0 | 0 / 0 | 0 / 0 | null / null | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_unsupported_full_expansion, terminal_quality_unidentified |
| S10 | 40 / 30 | 2.1 / 12.1 | 40 / 30 | 0.04 / 0.03 | 2.1 / 12.1 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification |
| S11 | 20 / 10 | 1 / 4 | 20 / 10 | 0.02 / 0.01 | 1 / 4 | 1 / 1 | ILLEGAL_missing_invalid_or_pending_verification |
| S12 | null / null | null / null | 0 / 0 | 0 / 0 | 0 / 0 | null / null | ILLEGAL_missing_invalid_or_pending_verification, ILLEGAL_verify_without_supported_conflict_or_repair |

拒绝原因列是候选审计统计，可能包含未选候选的拒绝，并非该行最终选中动作失败；所有逐候选理由和数量均在JSON。没有模型回调的NONE/REFUSED在明确无执行的情况下现金为0，不代表未知供应商费用被记成0。

## 公平性与可复制性

13/13场景两臂准备状态哈希相同，候选数、硬约束和逐候选拒绝原因一致。26/26重复求解得到同一Z/R/π/tools；不重复执行模型回调来制造样本量。实际执行的模型逐节点与选定π核对，工具重算与R分别记录。重复性指决策，不包括随机器负载变化的本地墙钟。

- S00证明健康完整缓存可直接NONE，两策略均零回调，不无故重执行。
- S01/S02/S03分别覆盖上游、join自身与指纹失效，均按合法依赖更新结果；join自身异常无需重跑健康a/b分支。
- S04/S05/S07展示可用性、预算和截止期改变π；S06/S08/S09拒绝不足预算、截止期及未知质量下限，没有非法调用。
- S10中V5不对未知扩大收益加分；RL严重异常规则选择EXPAND。最终合成数值都正确，但成本与时延出现取舍，不能直接认定V5更优，也不能将保留数值正确缓存等同于证据质量已得到验证。
- S11有依据VERIFY只产注解，S12没有冲突依据时不执行。注解不是确认性Gold。

5/13动作不同，均未产生独立真实收益证据。有效合成终端交付的数值检查满分，不能证明模型质量异质性。规划CPU秒、实际本地函数墙钟、合成回调执行秒均分别存储，不能相加后冒充真实网络性能；本轮也不做显著性或跨任务普遍收益声明。

## 剩余限制及冻结

全部能力表、价格和时延是明确的合成单元，不是新采集模型表现。没有新真实模型响应，没有拿历史未执行的反事实动作填充结果。RL共享候选枚举/Pareto设施的原型开销不代表高效纯规则实现的最优CPU开销；本轮只验收公平信息、合法动作与计量口径，不宣称规划速度优势。

复现须在新目录使用冻结矩阵与对应源码，并保留失败日志；现有运行器独占锁且拒绝覆盖旧沙箱/输出。不能重跑后筛选有利结果。执行器、规则与矩阵冻结后，本轮停止，不启动付费或GPU实验。
