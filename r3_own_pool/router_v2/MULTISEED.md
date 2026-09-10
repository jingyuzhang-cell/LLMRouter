# 多 seed 共同封存与汇总

实现：multiseed.py。默认seed为42、43、44，全部使用同一输入、实现、质量容忍度和训练预算。每个seed可独立在validation选参数，但所有选择在任何测试评估之前完成。该工具不替代评分、资源及历史暴露审计，真实gate必须有证据。

在 /root/r3_own_pool 使用既有Python环境运行。以下是真实数据门禁完成后的命令模板，文件路径不表示相应材料已经齐备：

```bash
/root/autodl-tmp/llmrouterbench_r2_venv/bin/python -m router_v2.multiseed fit \
  --cohort data/cohort_full_v2 \
  --outcomes data/frozen/full_v2/outcomes.jsonl \
  --gate data/frozen/full_v2/GATE.json \
  --embeddings data/embeddings_full_v2_recovery1/EMBEDDINGS.npz \
  --seeds 42 43 44 --quality-delta 0 --epochs 60 \
  --output router_v2/batch_quality_strict
```

fit不执行测试评分。每个seed写入独立目录；BATCH_PROTOCOL.json先记录seed名单，BATCH_FROZEN.json在所有训练成功后绑定各seed封存文件。输入与实现hash沿用单run检查。

确认预定方法、端点、独立确认资格和所有策略封存后，运行：

```bash
/root/autodl-tmp/llmrouterbench_r2_venv/bin/python -m router_v2.multiseed evaluate \
  --output router_v2/batch_quality_strict
```

evaluate先校验所有seed，再以独占写入BATCH_TEST_OPENED.json登记评估尝试，然后执行各seed评估。中途失败保留登记，不自动重跑或删除。出现中断需审查现场，当前未实现恢复命令。

SUMMARY.json保留所有seed的逐项结果、均值与样本标准差、各约束通过次数、原有逐seed区间及结果文件hash。不按测试选择seed，不平均置信区间，不把跨seed重复评估当作扩大测试样本量。通过次数是描述性结果，不是新的显著性检验。gap recovery任一seed无定义时不通过删除该seed求均值。

限制：这是批次内保护，不能阻止直接调用单run evaluate或新建另一个batch。尚未实现全项目中央开封登记或多个质量容忍度批次共同封存。因此不得根据本批测试结果再挑其他端点、seed或改方法。现有独立测试资格问题仍需先解决。

验证：5项多seed测试通过，覆盖合成端到端、重复seed拒绝、后续seed损坏提前拦截、中断保留登记及汇总语义。全部为合成数据验证，未执行真实训练或测试。
