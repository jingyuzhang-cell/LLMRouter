# Runner3 剩余三项验收报告（2026-10-31）

> 操作者三项验收：①OS 级网络隔离 ②输入 Token 保守上界证明 ③T9 许可失效窗口。零模型调用。

## 项①：OS 级网络隔离——**本容器不可达，如实报告**

**环境事实**（已入档 `/proc/self/status` 解码）：

| 能力 | 状态 |
|---|---|
| CAP_SYS_ADMIN（unshare 需要） | **NO** |
| CAP_NET_ADMIN（iptables 需要） | **NO** |
| CAP_SYS_PTRACE（strace 需要） | **NO** |
| CAP_NET_RAW | YES |
| CAP_SYS_CHROOT | YES |
| seccomp | mode 2（过滤中） |

**结论**：本容器**无法产生 OS 级 namespace 隔离证据**。`unshare -n` 返回 `Operation not permitted`；`iptables` 不存在；`strace` 不存在。

**现有替代证据级别**：SocketGuard（程序级 socket 拦截+日志）+ RealTransport 双重解除武装（环境标志 + 不存在文件双条件）——**程序级禁止发送 ≠ OS 级禁止外联**，操作者裁定正确。

**解除路径**：OS 级验证须在具备 CAP_SYS_ADMIN 的主机上执行——具体为 AutoDL 服务器上运行 dryrun_tests.py 前，以 `unshare -n` 或等效 namespace 隔离包裹，保留系统级日志。**本项不在本容器完成，不伪造、不替代。**

## 项②：输入 Token 保守上界——**0.75 系数不够保守，需升级至 1.0**

### 实测发现

| 验证方法 | 最坏 ratio(actual_tokens / utf8_bytes) | 0.75 保守？ |
|---|---|---|
| **Phase2 真实数据**（27 调用） | GLM: 0.666；DS: 0.526 | ✓ |
| **tiktoken 离线**（10 类边界输入） | 0.493（数字密集） | ✓ |
| **穷举最坏情况**（15 类极端） | **1.000（"1.1.1." 交替模式）** | **✗ FAIL** |

**关键发现**：交替数字+小数点模式（如 `"1.1.1.1."×50`）每个字节恰好产生一个 token——ratio=1.0，超过 0.75。这在真实金融文档中不会出现，但操作者要求"不能为了通过测试降低预算安全要求"，**数学上 0.75 不是上界**。

### 裁定建议

| 方案 | 系数 | 安全性 | 成本影响 |
|---|---|---|---|
| A：升级至 **1.0 × utf8_bytes** | 1.0 | **数学严格上界**（每字节最多 1 token） | 预留放宽 ~33%，但真实场景仍极保守（实际 ratio 0.1-0.5） |
| B：冻结 tokenizer 精确计数 | tiktoken 精确 | 最准确 | 需引入 tiktoken 为运行时依赖，且 GLM tokenizer 不同于 tiktoken |
| C：维持 0.75 + 类型白名单 | 0.75 | 仅限已验证输入类型 | 需要输入分类器，增加复杂度 |

**推荐 A（1.0）**：数学上无懈可击、无新增依赖、对真实场景成本影响极小。

### 已完成的验证数据

- Phase2 Step3 真实数据：GLM 21 条 + DS 6 条，全部通过（ratio ≤ 0.666）
- tiktoken 10 类：纯中/纯英/数字/JSON/混合/特殊符号/空格/单字符/中文单字——全部通过（ratio ≤ 0.493）
- 穷举 15 类极端：**发现 "1." 交替模式 ratio=1.000（0.75 失败）**

## 项③：T9 许可失效窗口——**4/4 全 PASS**

| 测试 | 并发顺序 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| T9-A | A.acquire=ISSUED → B 触发闭锁 → A 尝试 handoff | A REVOKED，零出网 | handoff=REVOKED | **PASS** |
| T9-B | B handoff=HANDED_OFF → 闭锁 → mark_in_flight | B IN_FLIGHT，保留未知态 | permit=IN_FLIGHT | **PASS** |
| T9-C | 闭锁已存在 → A 申请新许可 | A 被拒绝 | acquire=REVOKED | **PASS** |
| T9-D | 5×ISSUED → 闭锁 → 全部检查 | 全部 REVOKED | 5/5 REVOKED | **PASS** |

证据文件：`dryrun/T9_PERMIT_WINDOW.json`。

## 总结

| 验收项 | 状态 | 说明 |
|---|---|---|
| OS 级隔离 | **不可达（本容器）** | 须在 AutoDL 服务器补做；程序级替代已在案 |
| Token 上界 | **0.75 不保守 → 建议升级 1.0** | 数学证明+穷举发现反例；操作者裁定系数 |
| T9 许可窗口 | **4/4 PASS** | 确定性调度测试完成 |
