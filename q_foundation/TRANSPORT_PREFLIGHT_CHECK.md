# Static-π 真实执行前置检查报告（零调用，只读）

> 操作者 2026-11-01 指令：只检查已冻结的 transport.py 五项安全边界；不修改 Runner3、不新增工程模块、不发起模型请求。**本报告是只读边界确认，不是 OS 安全认证；OS 级隔离维持 BLOCKED_BY_ENVIRONMENT。**

**总判定：PASS（带 3 个执行期门禁 + 2 项残余风险如实记录）**

---

## ① 实验模型请求是否只有一个出网入口

**判定： sanctioned 路径唯一出口 = `transport.py :: call_model`。**

- `transport.py`（/root/capital_opinion_pilot/transport.py，73 行）为纯函数实现：`glm_call`（GLM 订阅端点）/ `openai_call`（DeepSeek/Qwen，仅未来对照臂使用），无实例状态。
- **`/root/q_foundation/` 与 `/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/`（合同、评分器、设计、传播审计所在目录）网络代码文件数 = 0**——评价侧完全不触网。
- 范围内其余含网络代码的文件全部为历史阶段产物，不在 Static-π 执行路径上：
  - capital_opinion_pilot 根目录 18 个（probe_*/gather_*/v3_*/pilot_common.py 等早期试点与采集脚本）；
  - `v5_migration_20261022/`、`legacy/scheduler_v4_20261022/` 迁移/回归快照（同批文件的副本）；
  - `research_outputs/mvr_batch1/phase2b_impl/runner3.py` RealTransport（工程线，v4.1 审计 FAIL，BLOCKED，不经其执行）。
- **Stage A/B 执行器尚未编写** → 预登记 3 个执行期硬门禁（执行器审查时逐条验证，缺一不跑）：
  1. **import 审计**：执行器出网模块唯一 = transport.py（无第二 urlopen/requests/httpx 引入）；
  2. **别名白名单**：Stage A/B 仅允许 `glm53flash`（openai_call 路径在本两阶段不可达）；
  3. **端点回显**：每次调用的请求日志回显实际 URL 常量，进 run 记录。

## ② 实验脚本是否存在 subprocess / os.system 旁路出网

**判定：零旁路出网。**

- 网络工具调用（curl/wget/ssh/scp/rsync/nc/telnet）= **0**；
- `os.system(` / `os.popen(` 直接调用 = **0**；
- subprocess 实际命令清单（全量去重）：`nvidia-smi`（本地 GPU 查询）、`python3`/`sys.executable`（本地测试运行器）、`pdftotext`（本地 PDF 抽取）、`git rev-parse`（本地仓库）——**全部本地，无一出网**。

## ③ GLM 请求端点是否严格限制为 open.bigmodel.cn

**判定：是（代码层固定常量，调用方不可参数化）。**

- `GLM_ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'`——模块级常量，函数签名不含端点参数；
- API key 从本地 `/root/.zcode/v2/provider_config.json` 读取，不硬编码、不外传；
- 范围内其余 bigmodel.cn 出现：`docs.bigmodel.cn`（注释中的文档链接，非 API 调用）与各历史快照中的同一常量副本；
- 历史佐证：`test_kdx_local_single.py:25` 含对非法端点 `'https://remote'` 的 `assertRaises(ValueError)` 测试——端点白名单纪律在早期调度器测试中即存在。

## ④ 是否存在未经允许的重定向或备用网络出口

**判定：无备用编码出口；两项残余风险如实记录（不修复——修复=工程开发，违反本轮约束）。**

- 代码层无任何备用端点、fallback URL、代理配置；
- 运行时行为事实（Python 3.12.3，本机实测）：
  - `urlopen` 默认启用 `HTTPRedirectHandler` → **会跟随 3xx 重定向**（可至任意 http/https 主机，无主机钉扎）；
  - TLS 证书校验默认开启（`verify_mode = CERT_REQUIRED`）；
  - DNS 解析未钉扎（常规明文解析）。
- **残余风险 = 重定向跟随无钉扎 + DNS 未钉扎。这正是 OS 级隔离必须维持 BLOCKED 的原因：本检查不阻止主机上其他进程出网，不能替代命名空间/seccomp 级隔离。**

## ⑤ Gateway 串行化是否被准确记录

**判定：记录口径修正为分层表述。**

- `transport.py` 本身**无锁、无 Gateway**（纯函数）→ 直连路径不存在人为串行化，逐调用时延为独立测量；
- 串行化约束（全局锁内执行 send）**仅存在于 Runner3 EgressGateway 路径**——工程线产物，Stage A/B 不经其执行；
- 记录规定：Stage A/B DAG 按依赖顺序执行，逐调用墙钟可报告，**不做任何并行 Makespan 主张**（无论直连还是 Gateway 路径）；Runner3 串行化注记仅适用于未来经 Gateway 的执行。

---

## 附：本轮同步完成（操作者指示的回归断言）

`state_scorer.py` 篡改测试新增 **K_FD_S1_out_of_gold**（操作者四项断言：FD_S1 不计入分母 / 不算重复 / 不抵消缺失 / 不影响 17 项评分；另验证 FD_S1 描述性输出遵循枚举规则且 quote 用 S1 真实条件句原文）。**12/12 全 PASS**。评分逻辑零变更，仅测试扩充；版本 sha256 `3c6030d0…` → **`82b8945b…`**，如实升版记录。

**状态：39 次调用维持待授权。本报告不构成执行授权。**
