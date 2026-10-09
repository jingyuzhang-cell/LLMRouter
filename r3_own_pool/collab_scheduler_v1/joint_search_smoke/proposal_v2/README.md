# 8 题真实成本 Smoke：待执行审批

已补齐独立入口 `smoke_runner.py`。本次准备未启动模型，未提交或推送 Git。

范围：8 个已暴露的诊断任务 × clean/fault30 两状态 × 四个现有配置，共 64 个任务单元。四配置为 HETEROGENEOUS/QUALITY × NONE/LOCAL_REROUTE。fault30 按冻结种子抽取 floor(8×0.3)=2 个故障任务。它验证计量与执行准入，不验证六组搜索算法优劣；48 配置搜索仍仅是设计。

## 冻结的待审批上限

- 新模型请求尝试最多 200 次（失败请求也计数）。
- 总 Token 上限 1,638,400；派发前每次预留 8192，输出最多 512。
- 工作时限 3600 秒，包含模型加载；到时中断工作，清理服务可能使总墙钟略超时。
- 每任务/配置/状态逻辑调用最多 12；自动重试 0。
- 任何上限或异常触发即停止，保存 INCOMPLETE；不自动续跑、加预算或扩大搜索。

这些是运行上限，不是费用预测，也不保证跑完 64 单元。未知 usage 保留完整预留，已知有效 usage 才释放余量。DISPATCH.jsonl 在派发前 fsync；已有目录不可覆盖，有未结算预留的运行不能自动恢复。

## 缓存与时延口径

采用冷启动，不导入历史答案缓存。只复用本轮新生成的成功响应，缓存身份绑定模型来源、生成代码、完整序列化 Prompt、任务、节点和状态。Prompt 包含节点实际消费的依赖值；没有另行绑定上游原始响应全文。故障注入、失败和 dry 响应不能成为缓存源。

别名不增加物理请求、Token 或服务时延。顺序真实请求的服务时延求和；面板墙钟和模型切换墙钟另报。legacy used/lat 不作本轮物理费用或部署端到端延迟。不同配置按固定顺序共享本轮缓存，因此本 Smoke 的配置费用不能用来宣称算法优越性。

## 零调用验证

18 项 unittest（5 项原有计量测试 + 13 项新预算/执行器/整流程测试）通过。新测试含 64 单元 Stub 流程、缺失 usage 停止、异常清理及禁止覆盖目录。三个已有 eval_config 缓存回归通过，结果另存 CACHE_REGRESSION.json，没有重写历史回归文件。默认预检通过，模型调用为 0。

上述检查不是正式算法实验，也尚未验证真实服务的 usage 和真实缓存命中。若实际没有命中缓存，该验收项仍未完成，不能仅凭 Stub 声称真实验证通过。

## 默认预检（零调用）

```bash
cd /root/r3_own_pool
python -m collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner
python -m unittest collab_scheduler_v1.test_physical_accounting collab_scheduler_v1.joint_search_smoke.proposal_v2.test_smoke_runner -v
```

## 审批后才能运行

必须由用户明确批准上面的上限，再由唯一执行窗口运行以下命令。协议或绑定代码变化即需要重新检查；不使用原 fault30_run --execute 入口。

```bash
cd /root/r3_own_pool
JOINT_SMOKE_EXECUTE=1 python -m collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
  --execute --run-id smoke8_metering_01 \
  --approved-protocol-sha256 fb58b83a73fad280b9d55ec398c7cb51747b303aa8ad94ff30e3e5ae0f8bef15
```

输出：本目录 `runs/smoke8_metering_01/`，含协议快照、DISPATCH.jsonl、TRAJECTORY.jsonl、FAULT_DRAWS.jsonl、MODEL_SWITCH.jsonl、COMPLETED_PANELS.jsonl 和 STATUS.jsonl；异常可有 ERRORS.jsonl。不写回 Reference Cube、旧 LR 结果或旧请求账本。

验收时核对尝试账本、响应 usage、轨迹和已完成行：完成行的计量必须一致；失败/中断请求只在尝试账本保留，不混入已完成任务 Q/C/L。检查真实 cache hit 的新增费用为零，修复后新 Prompt 确实产生独立请求，记录未完成单元与预算停止原因。完成该验收后才能讨论正式搜索预算。
