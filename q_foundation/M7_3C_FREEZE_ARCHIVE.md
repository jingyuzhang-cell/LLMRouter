# M7-3C 最终冻结归档（Final Freeze Archive）

**日期**: 2026-11-01 | **状态**: 冻结归档完成，等待 M7-3D GO

## 冻结清单（SHA-256）

| 文件 | SHA-256 | 角色 |
|---|---|---|
| M7_3C_FREEZE_MANIFEST.md | 9b365041… | 冻结主清单（已审批） |
| M7_3D_REFERENCE_FACTS.json | db267157… | E04+E06 参考事实（AI_ADJUDICATED） |
| m7_3d_analysis.py | 42cc3681… | 预注册分析脚本（含 D4 排除） |
| m7_decision_engine.py | a10612fb… | 决策引擎（F 策略） |
| m7_policy_v10.py | f31fb487… | V1.0 策略（F′ 对照，含 D4 登记） |
| pilot_common.py (Meter v2.2) | [见 /root/capital_opinion_pilot/] | M7-3D 执行基础设施（6 轮实证） |

## 冻结纪律

- 以上文件在 M7-3D GO 后**零修改**
- 任何变更 = 协议违规 → 弃批 → 重预注册
- 执行器 = Meter v2.2（Guard v3.3 本轮不接入）
- 评分器 = terminal_quality v1.2.3

## 超时风险处置（操作员指令 #61）

- 超时不视为零消耗
- 不释放原有预算预留
- 超时后不无条件立即重试
- 无法确认实际消耗时按未知消耗保守处理
- 预算状态连续性无法保证时停止当前批次
