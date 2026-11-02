. 
# 【已封账 CLOSED 14:3x】Stage-C-R9B 治理收官：在案 80 次/6 run；补充 6 次永久隔离未追认；R10 与 supp 授权记录已 VOIDED（require 拒绝已验证）；E3-DD-1=DISPUTED 待人工裁定；新调用/算法/论文全部 HOLD。

# LAUNCH_STATUS — stage_c_r9b_v1（12:58 更新；两代理与操作员共读）

## 已结案：80/80 封顶停止，6/8 run，见 STAGE_C_R9B_FINAL.md（合法性待追认）

操作员已三次发送"继续授权"（继续类指令，无批次名/调用上限/Token 上限）——按台账永久规则
三次登记退回。**它不构成授权，也无法映射到下述 A/B/C 任何具体范围。**

## 已就绪（全部零调用验证 PASS @ 12:57）

| 组件 | 状态 |
|---|---|
| chain（delta 合同 + OUT_CAP 2048 截断加固） | sha `09c10bd2`，编译+S2 合成+接缝+截断拒收 4 项 PASS |
| exec（共享前缀去重 12 次/cell + QuotaMeter 重放修复 + SHA 门 + r9b 授权门） | 与 chain 配对一致，接缝测试 6+3+3=12 次/cell |
| 旧批次 | r9_v1 26 次 + r9b/EXEC_124828 46 次均判失效留证；**resume EXEC_124828 可免费重放其共享前缀 #1–3、#22–27** |

## 待操作员裁决（回复合字段整句，二选一；或 C 终止）

- **A（8-run 补足）**："授权 stage_c_r9b_v1 追加 20 次调用（总调用上限 100，Token 上限 150,000 不变）"
- **B（4-run 缩减）**："授权 stage_c_r9b_v1 以 4-run（仅 rep1）继续，上限 34 次调用、80,000 Token"
- **C（终止）**："终止本轮，不再花费"

## 算术依据（EXEC_124828/INVALIDATION.md）

修复版 resume：SC-E1-r1 ≈9 次新调用、SC-E3-r1 ≈6 次、rep2 ×2 ≈24 次 → 8-run 需 ~39 次 > 剩余 34；
4-run 需 ~15 次 ✓。Token：8-run 需 ~58K ≤ 剩余 80K ✓。

## 纪律提醒（两代理）

1. 单一执行者原则：授权落地后由**一个**会话执行发射（建议 ZCode 本会话），另一会话只读。
   EXEC_124828 即因双代理写竞争+提前发射而失效（46 次/70K 作废）。
2. 发射命令（授权落地后）：`cd /root/cap_eval_bench_v1 && nohup python3 integration/stage_c_r9_exec.py stage_c_r9_runs/EXEC_124828 >> stage_c_r9b_launch.log 2>&1 &`
