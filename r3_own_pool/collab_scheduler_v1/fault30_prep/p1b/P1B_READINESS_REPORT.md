# P1-B 真实执行前准入报告（2026-10-09，零 LLM 调用，未启动 GPU）

依据 d501386 审计意见逐项准入。全部通过后仅授权**单任务真实冒烟**，不授权批量。

| 准入项 | 状态 | 证据 |
|---|---|---|
| 真实 Prompt/解析/故障注入适配（非假任务语义） | PASS | dag_patch_p1b.py：e/r/v 用 fault30_protocol 真实构造器；r1/r2 新节点带真实分解/合并 prompt 与 JSON 解析协议；故障注入走 (task,node,planned_model) 注册表 |
| 已执行/运行中/已消费下游保护补全，非法操作原子拒绝 | PASS | insert/rewire 增加受影响后继 pending 守卫（T6：对 done 后继的依赖变更被拒）；全部 draft-validate-commit |
| 持久化 append-only 台账 + 失败调用记账 | PASS | p1b/LEDGER.jsonl 逐调用落盘（key/node/model/prompt_sha/strategy/响应含失败）；T4 重放验证 |
| 端到端 wall-clock 与调度开销分离 | PASS | 每轨迹 end_to_end_wall_s（任务级）与 node_wall_s、scheduler_overhead_s 分列 |
| 全局预算守卫（非仅单任务 12 次） | PASS | GLOBAL_BUDGET=480 硬顶 + 每任务 12；超限干净中止 |
| 任务/种子配对 | PASS | T3：同一 fault 种子 20260923 的注册表在各策略间逐一相同 |
| gold 数据权限 | PASS | gold 仅进入事后评分函数；检测器/策略签名无 gold 通路（T1 结构验证） |
| 不可执行图不误记完成 | PASS | T5：infra 失败轨迹 status=aborted，绝非 completed |
| 基础设施异常不引发无限重试 | PASS | retry=0；T2：失败调用计费一次后干净中止 |
| 协议冻结 | PASS | P1B_PROTOCOL.json：5 任务（seed 20261009、sha256 排序、UID 哈希）、2 状态、4 策略、同初始 DYN-HET、缓存禁用、串行、重试 0、代码 SHA |

**预计真实调用量**：40 条轨迹硬顶 480；现实估计 ~210–270（single~10 / static~40 / reroute~70–90 / dynpatch~90–130）。
**两级启动**：第 1 级 = 1 任务冒烟（真实服务输出格式→检测→patch 提交→新节点执行→持久日志核查）；若自然故障未触发 patch，可用预固定定向故障场景单独验证机制并分开报告。第 2 级 = 其余 4 任务配对试运行。
**边界**：P1-B 验证 Dynamic-DAG-Patch 在线机制，不是 Outer+SA-PGFS 在线优化系统。
**本轮产出为桩服务集成证据（LEDGER_SELFTEST_STUB.jsonl 为桩记录，正式运行前清空 LEDGER.jsonl）。**
