# DD-V2 最终接线验收 + 微试 GO/NO-GO 报告（基线 eeed184）

零调用、零 GPU。交付：接线代码（`supplementary_runner.py` V2 路由 + `dd_v2.py` 回退识别修正）+ `test_dd_v2_wiring.py`（12/12）+ 开发微试冻结文件。

## 接线 1：run_cell 显式调用 decide_arm_v2（DONE）

`run_cell` 现在对 `DD-Cal / DD-Cal+FB / DD-V2` 臂**直接调用 `dd_v2.decide_arm_v2()`**（软约束/回退按臂配置）；SS 与 DD-V1 继续走 `arm_entry.decide_arm()` **未动一字**。预算预留/释放的门从 `mode=='policy'` 扩展到全部 V2 决策模式（`joint_selection / joint_selection_soft / static_fallback`）；V2 行补 `mu_e2e`/`contention` 别名使 run_cell 的剩余工作记账一致；`degraded` 模式照常走 EARLY_STOP 分支。**假传输验证**：五臂全部产生不同模式（SS=static_recipe、DD-V1=policy、三 V2 臂=joint_selection_soft），物理请求与结算完整。

## 接线 2：静态回退识别修正（DONE）

`v2_score_and_pick` 尾部重写：先同池竞争选出最高 eff_score；**若胜者本身就是静态 LOCAL/计划候选 → `static_fallback`**（此前会被误标 joint_selection）；胜者为其他候选时记录对回退的分数优势。硬预算拒绝测试通过（决策预算 50 tokens 时 `degraded`/物理预算门触发）。

## 接线 3：五臂假传输闭环走真实执行入口（DONE）

`test_dd_v2_wiring.py`：每臂通过 **`run_cell`（真实路由）+ `RealServer` + `Budget` + `RealEngine`** 完整执行（非 StubEngine 直调、非 v2_score_and_pick 直调）。验证：五臂结算完整、模式区分正确、物理预算生效、结算字段可独立复算、硬预算拒绝、服务停止。

## 接线 4：开发微试任务冻结（DONE）

`DD_V2_DEV_MICROTRIAL_FREEZE.json`：5 任务（种子 20261107，池排除 P3-60/微试/frozen200/evaluation 全部历史 uid），2 个 r 故障（可观察恢复场景），档位 medium/wide/tight/medium/wide，sha `3ae7ea8d…`。**用途=开发证据与恢复质量证据积累，永不作最终验证。**

## 12/12 接线检查

| 检查 | 结果 |
|---|---|
| DD-Cal / DD-Cal+FB / DD-V2 路由到 V2 入口 | PASS ×3 |
| DD-V1 模式未动（policy） | PASS |
| SS 保持 static_recipe | PASS |
| 物理预算 ≤100 全臂 | PASS |
| 结算字段完整（Q/C/T/D/R 双口径） | PASS ×3 |
| 回退模式合法集合 | PASS |
| 硬预算拒绝 | PASS |

## 微试 GO/NO-GO

| 项 | 状态 |
|---|---|
| run_cell 显式调用 V2 决策（V1 不动） | **GO** |
| 静态回退正确识别 | **GO** |
| 五臂真实入口假传输闭环 | **GO** |
| 开发微试任务冻结（5 任务、r 故障、非 P3-60） | **GO** |
| 预算预留/释放/台账对新模式生效 | **GO** |

**建议：GO for 3–5 任务真实开发微试**（≤100 请求 / 50K tokens / 3,600s，单次执行、失败即停）。验证目标：V2 联合选择在真实模型上选中动态方案并物理执行异构模型（如 r|large）；静态胜出时正确标记；恢复质量证据开始积累。即便出现正收益也仅为开发证据——正式验证仍需新独立任务集。
