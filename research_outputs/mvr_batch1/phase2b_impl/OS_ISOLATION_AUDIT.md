# AutoDL OS 级网络隔离补验——环境能力审计报告

> 操作者 2026-10-31 批准的补验范围：环境能力检查、unshare -n 隔离验证、T1–T10 干跑复核、OS 级出口证据采集。零真实模型调用。

## 一、环境身份确认

- **主机**：`autodl-container-024b4f8aa7-7660f85b`
- **特征**：`/root/autodl-tmp` 存在、overlay 文件系统 30G——**这就是 AutoDL 容器**

## 二、OS 级 namespace 隔离——穷举全部已知方法，全部失败

| 方法 | 结果 |
|---|---|
| `unshare(CLONE_NEWNET)` | **Operation not permitted** |
| `unshare(CLONE_NEWUSER \| CLONE_NEWNET)` | **Operation not permitted** |
| `unshare(CLONE_NEWUSER \| CLONE_NEWNET \| CLONE_NEWNS)` | **Operation not permitted** |
| `nft` / `nftables` | 不存在 |
| `iptables` | 不存在 |
| `firejail` | 不存在 |
| `bubblewrap (bwrap)` | 不存在 |

**根因**：容器 seccomp 过滤器（mode=2）阻止了 `unshare` 系统调用，即使 `/proc/sys/kernel/unprivileged_userns_clone = 1`（宿主机允许）也被容器层 seccomp 覆盖。**这不是权限不足，是容器安全策略的系统性限制。**

## 三、当前网络状态

- 网络接口：`eth0`（活跃）+ `lo`——**可出网**（DNS 解析 open.bigmodel.cn 成功）
- 无任何现成防火墙规则

## 四、诚实结论

**本 AutoDL 容器在 Docker/seccomp 配置下，无法产生 OS 级 namespace 隔离证据。**这是容器环境的系统性限制，不是临时状态。

## 五、可行的替代方案（供操作者裁定）

| 方案 | 可行性 | 证据级别 |
|---|---|---|
| A：要求 AutoDL 平台调整容器 seccomp 白名单（加入 unshare） | 需平台操作，本会话无法执行 | 可产生真 OS 级证据 |
| B：在 AutoDL 宿主机（容器外）执行 dryrun + `unshare -n` | 需 SSH 到宿主机，本容器无该权限 | 可产生真 OS 级证据 |
| C：接受程序级证据（SocketGuard + 双重解除武装）作为当前环境下的最高可达证据级别 | 本会话可执行 | 程序级（非 OS 级） |
| D：推迟 OS 级验证到真实调用前的最后一次检查，当前以程序级+环境审计放行干跑 | 本会话可执行 | 程序级 + 诚实环境声明 |

## 六、当前已有证据（程序级，非 OS 级）

- SocketGuard 拦截日志：`dryrun/*/socket_guard.log`（全部测试中零出网尝试记录）
- RealTransport 双重解除武装：环境标志 `PHASE2B_REAL` 未设置 + `REAL_CALLS_ALLOWED` 文件不存在
- 全部 T1–T10 + 篡改回归 11/11 PASS
- Token 公式已更新至 1.0×UTF-8 + 协议开销
- 本环境审计报告（穷举方法+结果全量在案）

**操作者裁定后方可继续。**
