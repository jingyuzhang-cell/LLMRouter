# STAGE_D 预启动阻断：S5 竞速等待败者（2026-11-02，零调用）

**状态**：BLOCKED — 操作员 GO 已收到，但**未执行**；真实调用 0，费用 0，资源包未消耗。  
**触发**：GO `STAGE_D_CONFIRM_V1`（2,688 调用 / 9.5M token / ¥34.56 核算）后的启动前源码复核。

## 一、证据

预注册：
- V1.1 §1.2：“首个可解析结果胜出，**迟到者作废**但其调用成本与资源槽占用全额计入”。
- V1.2 FULL：S5 时间模型 **J2=15.8s（9.5+6.3）**、DAG **89.9s**。

冻结执行器 `stage_d_executor.py`（`ef50527e…`）第 678–681 行：
```python
rh = ds if winner == "deepseek" else glm
lh = glm if winner == "deepseek" else ds
r = self._finish_call("J2", rh)
rl = self._finish_call("J2", lh)   # 等待败者 h.done
...
self._after_j2(r)                   # 之后才允许 SINK
```
`_finish_call` 首行 `h.done.wait()`（第 596–597 行）。真实 `RealProvider.cancel()` 仅逻辑取消（urllib 无传输级终止），败者 GLM 仍跑完 29.4s，因此 **J2 等败者结束才完成**。

## 二、影响

- 竞速臂 J2 ≈ 29.4s（等于静态 GLM），而非 15.8s；DAG ≈ 103.5s，而非 89.9s。
- S5 按时率/时延收益被系统性抹掉，Joint vs R-only/π-only 的 S5 时延结论失真。
- Mock 未暴露：`cancel_effective=True` 时 Mock 立即返回取消；真实场景恒为 `late_completed`。
- 冻结 11/11 仅机械哈希通过；S5 执行路径的 PASS 撤回为 BLOCKED；预注册（V1.3.2 A、R1、统计）不受影响。

## 三、最小修复（不改设计、不加模块）

1. 胜者结果立即 `_after_j2`，SINK 继续；
2. 败者进入后台结算线程：`_finish_call` 等待其真实结束，结算迟到成本/槽/token；`finish` 在 makespan 记录后 join；
3. `race_log.loser_cancel_state` 保留 `late_completed`；`s5.late_cost` 由后台线程写回；
4. 测试：J2/SINK makespan 只按胜者；败者成本入账；槽占用到真实结束；全局 token == 记录；无重复计账；重跑 19 主 + 14 P0 + 6 保护 + 192 Mock；重新冻结；重做 S5 路径审计。

## 四、待决定

- **A（推荐）**：批准最小修复 → 重跑测试/192 Mock → 重新冻结 → 按同批次/同额度重新确认 GO。
- **B**：维持当前冻结，接受 S5 时延结论无效（不推荐）。

在答复前：真实调用 **0**；192 执行 **HOLD**；资源包未使用；冻结文件原样保留。
