# E 类节点兼容性零调用审计报告

**日期**：2026-11-06　**性质**：零 API 调用（网络绊线计数 0）；冻结文件审计前后 SHA 一致；未重启 DAMJS_PILOT_54；未读取或输出任何密钥。
**证据产物**（均在 `e_node_audit/`）：`replay_audit.py` → `REPLAY_AUDIT_RESULTS.json`（实验 X1–X5）；`replay_all_192.py` → `REPLAY_192_RESULTS.json`（X6）；`evidence/` 保存 240 s 探针的执行记录与账本副本（原件在 `/tmp`，易丢失）。

## 结论

审计前提"DeepSeek 的 E 节点响应不符合 D2 合同"**不成立**。240 s 探针里**没有发生任何 DeepSeek 调用**，8 次调用全部是 GLM。E1–E4 失败的真实原因是一处代码缺陷：DAMJS 子进程导入的是基础执行器 `stage_d_executor.py`（64dea819），它的真实调用路径在第一次调用时必然抛出 `AttributeError`，与模型、与响应内容都无关。这个缺陷 2026-11-03 已在 A‴ 执行器 `stage_d_v2_executor.py`（e80fe6a3）中修复。192 次 Stage D 真实执行也正是由 A‴ 执行器连同其配置产生的，并不是身份补记推定的 64dea819。

三个候选方案都不对症。推荐**方案 4：把 DAMJS 子进程改为绑定实际产生基线的 A‴ 执行器及其配置**。这样不改任何冻结文件，零调用重放可逐条复现基线记录。另外，子进程和运行器还有 5 处接线缺陷必须一并修复，其中一处是授权硬上限实际并未执行；预算也需要您裁定。

---

## A. 根因及原始证据

### A.1 前提不成立：探针中没有 DeepSeek 调用

探针执行记录 `evidence/D3_PROBE_RECORD_Current-Proposed__S3__r1.json`（240 s，S3，r1）：

| 字段 | 值 | 含义 |
|---|---|---|
| `slots.max_seen` | glm53flash=2，**deepseek=0** | 8 次调用全部走 GLM |
| `tokens_in / tokens_out` | 4,520 / **16,000 = 8 × 2,000** | 每次调用都恰好停在 E 层上限 `MAXTOK["E"]=2000` |
| `raw.calls` / `exec_log` | **[] / []**，但 tokens 已入账 | 异常发生在"结算之后、写原始记录之前"这个窗口 |
| `anomalies` | E1–E4 均为 `D1=model_suspect`（61.5/97.2/123.2/132.0 s） | 只有两次尝试都抛异常才会生成这一信号 |
| `decisions` | 4 条，`acts=[]` | 见 D.2 的 M2 |

冻结的 D2 规格本来就把 E1–E4 指派给 `glm53flash`（`d2_executor.py:32-35`），基础执行器没有覆盖这一指派。

### A.2 真实根因：基础执行器真实路径上的 AttributeError

- `FinalExec._finish_call` 在第 666 行和第 673 行读取 `h.latency`。真实句柄 `_RealHandle.__init__`（`stage_d_executor.py:312-327`）**从未定义 `latency`**（AST 已核实），只有 Mock 用的 `CallHandle` 有这个属性。
- 抛出位置在 `_settle()` 之后、`raw["calls"].append()` 之前。tokens 已经记账，原始记录却是空的，与 A.1 完全吻合。
- `exec_llm`（:816-861）只有在两次尝试都抛异常时，才把节点置为 Failed 并标 `D1=model_suspect`。JSON 解析失败或缺少 `positions` 只会产生 `D2=structure`，节点仍然记为 Completed。所以"校验失败"不可能产生探针看到的这一特征。
- A‴ 执行器里有现成的修复：`self.latency = None  # bugfix 2026-11-03: _finish_call 读取 h.latency；真实句柄此前缺该属性 -> 真实路径首调即崩（192 Mock 未覆盖）`。

### A.3 零调用复现

| 实验 | 设置 | 结果 |
|---|---|---|
| X1 | 基础执行器 + 基础配置，与探针同臂、同场景、同截止期，回放已记录的响应 | 与探针**逐项一致**：INCOMPLETE_NO_RECOVERY、8 次调用、E1–E4 Failed、4 × `D1=model_suspect`、raw 与 exec_log 均为空、deepseek 槽占用 0。仅 GLM 槽并发峰值为 1（探针为 2），原因是回放即时返回 |
| X2 | 对基础真实句柄直接调用 `_finish_call` | `AttributeError: '_RealHandle' object has no attribute 'latency'` @ `stage_d_executor.py:666`。**合法合同 JSON 与空字符串抛出完全相同的异常**；抛出前 tokens 已入账（565/2000） |
| X3 | A‴ 执行器 + V2 配置，回放 Static/Proposed × S3/S4 的 r1 | 4/4 与原记录一致（TP 11/14/8/14，状态、调用数、调用序列均相同） |
| X6 | A‴ 执行器回放**全部 192 条记录**（按记录时延、推断的 stop 原因） | **完全时序记录 170/170 逐字段复现**（TP、状态、调用数、终态、动作、逐节点模型）；全部 192 条中 185 条完全一致，191 条 TP 一致；请求模型与原记录不符的调用为 0 次 |

X6 的 7 处不一致全部落在 22 条"原记录含传输错误、且错误时长未记录"的记录中，例如 J1 在 120 s 时被 urllib 超时打断。这类时长回放无法还原。

### A.4 第二层：E 留在 GLM 上时，即使修好异常也拿不到有效输出

- 探针中 8/8 次 GLM E 调用的输出恰好等于 2,000 的上限。
- Stage 2（2026-11-03，`STAGE_D_V2_STAGE2_REPORT.md`）给出过直接证据：E × GLM-low@8192 成功一次（E1，out 4,681，58.4 s），失败一次（E2，8,192 个 token 全部用于推理，正文 0 字，110.4 s）。当时据此将 E × GLM-low 判为"不可靠（1/2），排除出默认路由"。
- 连成功的那次都需要 4,681 个 token，2,000 的上限下 GLM E 节点必然被截断。

### A.5 为什么此前被误判

1. 异常路径的标签 `D1=model_suspect` 看上去像模型问题。
2. 原始记录为空，无法查看响应内容。
3. 基础执行器的真实模式从未跑过真实批次（192 次全部经由 A‴ 执行器），Mock 路径又有 `latency` 属性，所以缺陷一直潜伏。
4. 此前所说的"子进程挂起、150 s 无输出"其实不是挂起：GLM 调用每次约 30 s（由异常时间戳推算），每次都以该异常结束；没有任何节点完成，自然没有任何进度输出。

### A.6 身份更正：192 次执行由 A‴ 执行器产生

| 判别特征 | 192 条记录实测 | 基础执行器 64dea819 + 配置 11e52032 | A‴ 执行器 e80fe6a3 + 配置 914f3edd |
|---|---|---|---|
| 截止期 | 192/192 为 300 s | 180 s（S5 为 90 s） | 300 s |
| E 节点模型 | deepseek 782/782 | glm53flash | deepseek（`AROUT`） |
| J1 走 GLM 时的最大输出 | 8,192 | J1 上限 3,000，不可能出现 8,192 | 8,192（`AMAX`） |
| 真实句柄的 latency 字段 | 1,409 次调用为数值 | 属性不存在，真实路径首调即崩 | 已于 11-03 修复 |
| git 归档 65fd5abd（11-03 14:05） | — | 64dea819 | e80fe6a3 / 914f3edd |
| 零调用重放 | — | 0/192（没有任何 LLM 节点能完成） | 完全时序记录 170/170 |

时间线：A‴ 执行器 mtime 为 11-03 12:11，记录时间跨度为 11-03 13:03 至 21:56。仍然不存在逐次运行的密码学证明。

---

## B. 三种方案的可行性

| 方案 | 结论 | 依据 |
|---|---|---|
| **1 E 节点改用 GLM** | ✗ 不可行，且有害 | (a) 失败时 E 节点**本来就在 GLM 上**（基础路由为 E → GLM@2000）；(b) 8/8 次调用触顶，Stage 2 直接证据为 1/2，该组合已被排除出默认路由；(c) 时延：GLM E 每次 58–110 s，DS 中位数 2.63 s（n=777）。2 个 GLM 槽跑 4 个 E 节点需要两波，约 117–220 s，**仅 E 层就超过 110 s 截止期，并大概率超过 150 s**；(d) 与 A‴ 路由下的 192 次基线不可比；(e) 不修复 AttributeError，单独实施仍是 TP=0 |
| **2 包装层无损格式适配** | ✗ 不适用 | (a) **不存在格式缺陷**：DS 的 E 输出 775/777 可解析（99.7%），可解析的 775 条全部含 5 个合同字段，E1/E2 的 `positions` 393/393 齐全；仅有的 2 条失败是提前截断（out=1 与 out=47）；(b) 异常发生在 `_finish_call:666`，早于 `extract_json`（:838），文本层适配器拦截不到；(c) GLM@2000 缺的是内容（推理耗尽预算），任何无损适配都补不回来 |
| **3 接受失败** | ✗ 被规则排除，也没有必要 | 这是代码绑定错误，不是模型属性；接受即意味着 54 次全部 TP=0 |

您给出的两条裁决规则（可无损修复则选方案 2，缺语义则选方案 1），都以"DS 响应格式不合合同"为前提，而这个前提已被证伪。DS 路径既没有格式问题，也没有语义缺失。唯一的语义缺失出现在 GLM@2000 路径上，而规则 2 指向的方案 1 恰恰就是这条路径。因此两条规则都不触发。

## C. 推荐方案及理由

**方案 4：DAMJS 子进程改为绑定 `stage_d_v2_executor.py`（e80fe6a3）和 `stage_d_v2_executor_config.json`（914f3edd）。**

1. **对症**：A‴ 执行器带有 2026-11-03 的 `latency` 修复。
2. **恢复本批次的原意**：批次清单冻结 64dea819，是因为身份补记推定它产生了 192 次基线；该推定已被 A.6 推翻。改为绑定基线的真实执行器，DAMJS 与基线才共享同一路由、检测器、修复库和提示词。
3. **E 节点保持 DS@4000**：这是经您批准的 A‴ 路由，有直接与间接证据支持；DS E 节点中位 2.63 s，与 110/150/240 s 的截止期网格相容。基线 S3/S4 的 makespan 中位数为 Static 58.5/103.2 s、Proposed 141.6/125.4 s。
4. **零冻结改动、可直接替换**：子进程用到的入口在 A‴ 执行器中同名同签名（5 个调用路径签名逐一比对一致）；`glm_low_call` 与 `stage_d_real_transport` 的源码逐字节相同；重放 170/170 复现。
5. 就性质而言，这是"包装层、无损、不改冻结合同"的修复，但修的是**绑定**，不是格式。

## D. 最小修改范围

### D.1 冻结文件：零改动

`stage_d_executor.py` 64dea819、`stage_d_v2_executor.py` e80fe6a3、`d2_executor.py` df8a2de6、两份执行器配置、`stage_a/executor.py` 5f1de3c7、`transport.py` 7a423eb3、评分器、Gold、`damsj_engine.py` 7eec919b，均保持不变。

### D.2 必改项（只涉及非冻结的 `_damsj_real_child.py` 与 `damsj_pilot_runner.py`）

| # | 缺陷 | 证据 | 修改 |
|---|---|---|---|
| M1 | 子进程绑定了基础执行器与基础配置（D3 根因） | A.2、A.3 | `import stage_d_v2_executor as SDE`；配置改为 `stage_d_v2_executor_config.json`，截止期仍按块覆盖 |
| M2 | 臂标签 `Current-Proposed` 原样传入执行器，任何策略分支都不匹配，`acts` 恒为空，**实际上是第二个 Static 臂** | 探针中 4 条 model_suspect 决策均为 `acts=[]`；X4：检出 J1 结构故障却不修复（7 次调用，对照为 8 次） | 显式映射 `{'Static':'Static','Current-Proposed':'Proposed-Dynamic','DAMJS':'Proposed-Dynamic'}`，遇到未知标签直接报错 |
| M3 | **授权硬上限没有执行**：运行器构造了 `BudgetGuard(400 次/1.4M token/¥2.5)`，但从未扣账（`damsj_pilot_runner.py:53` 只构造，`:129` 只打印快照）。子进程只受执行器配置的全局上限约束（2,688 次，¥34.56–40）；单次执行上限 14 次 × 54 次 = 756 次 | grep 结果 | 子进程把 `cfg['global']` 设为剩余授权额度，并使用新的状态目录。冻结的 `GlobalBudget` 跨进程持久化，并在预留时拦截。运行器遇到 `INCOMPLETE_BUDGET` 立即停批 |
| M4 | L4 部分结果从未接线：真实子进程不写 `node_end` 事件，而 `completed_outputs()` 只读这一事件 | 只有 Mock 子进程和包装器自身的节点执行器会写 `node_end` | 子进程增加轮询线程，节点转为 Completed 时写入 `node_end(ok, output)` |
| M5 | DAMJS 的截止期锚点错误：`t_rem` 从首次策略调用（第一个节点完成时）起算，而不是从执行开始起算 | `wrapped_policy` 中的 `started[0]` | 改为使用 `ex.t0` |

### D.3 需您裁定的保真度问题（不阻断运行，但影响论文能声明什么）

| # | 问题 | 选项 |
|---|---|---|
| F1 | DAMJS 臂是子进程里手写的规则闭包，没有实例化 `damsj_engine.Scheduler`；29 项不变量测试覆盖的是 Scheduler，不是这个闭包 | 冻结闭包作为本批次策略并补测试，或改为接入 Scheduler |
| F2 | `History.record()` 从未被调用，重复抑制（C3-a/C3-b）永远不会触发，而子进程文档声称已覆盖 | 接线，或删除该声明 |
| F3 | 闭包里没有 Π（swap）分支；DAMJS 的决策不写入 `ex.decisions`，记录中 decisions 恒为 0 | 本批次 DAMJS 臂的实际动作空间只有 Z_format、Z_structure、R，论文表述需相应限定 |

## E. 新批次配置和 MANIFEST 需要更新的内容

### E.1 批次配置

- **新 batch_id**（例如 `DAMJS_PILOT_54_R2`）配新状态目录；旧批次的状态保留作为诊断记录，不复用、不覆盖。
- **设计不变**：3 臂 × 截止期 {110, 150, 240} s × S3/S4 × 3 次重复 = 54 次，块内随机顺序。
- **路由继承 A‴**：E1–E4 走 DS@4000；J1 走 GLM-5.3-Flash（low）@8192；J2/SINK 走 DS@4000；FMT 本地。并发槽 GLM 2、DS 1；单次执行上限 14 次调用、¥0.18。
- **凭据**：`STAGE_D_GLM_KEY`（J1 用）与 `DEEPSEEK_API_KEY`（E/J2/SINK 用）都必须提供，只注入子进程环境，不打印。在 A‴ 路由下，每次执行 7 个 LLM 节点中有 6 个依赖 DS 密钥。

### E.2 预算（需您裁定）

**账本更正**：探针实际消耗 8 次调用、20,520 token、核算 ¥0.0484（全部为 GLM，现金 ¥0）。`D3_ROOT_CAUSE_V2.md` 中的"¥0.0304 / 12,948 token"与执行记录及持久化账本不符。

累计消耗为 23 次调用、51,472 token、核算 ¥0.1212，**剩余 377 次调用、1,348,528 token、核算 ¥2.3788**。

**需求估算**：取 32 条同场景基线记录（S3/S4 × Static/Proposed，截止期 300 s），每次执行 Static 为 7.00 次调用、20,372 token、核算 ¥0.0353；Proposed 为 7.69 次、24,883 token、核算 ¥0.0455。DAMJS 臂按 Proposed 估计。54 次合计：

| 估计口径 | 调用 | token | 核算 ¥ | 对照剩余额度 |
|---|---|---|---|---|
| 均值 | **≈403** | ≈1.26M | ≈2.27 | **调用超出剩余 377 次** |
| 最大值 | ≈450 | ≈1.70M | ≈3.32 | 三项均超出 |

结论是**调用上限构成硬约束**，按现有额度批次很可能在第 50 次左右停在 INCOMPLETE。短截止期会截断部分执行，实际消耗会略低，但不能保证低于 377 次。我不会自行提高预算。可选的做法有三种：

1. 您提高调用上限：按最大值估计，还需剩余额度 ≥450 次；
2. 缩减规模：例如改为 2 次重复，即 36 次执行，均值约 269 次调用，最大值约 300 次；
3. 按原规模运行，接受以 INCOMPLETE 结束。

原计划的真实冒烟测试（3 臂 × 1 次，240 s）约需 22 次调用、约 7 万 token、约 ¥0.13。建议代码路径部分改用 E.4 的零调用重放冒烟，真实冒烟只保留 1 次执行，用于验证连通性。

### E.3 MANIFEST 更新内容（只新建文件，不覆盖原文件）

新批次清单相对 `DAMJS_BATCH_MANIFEST.json` 的变化：

| 组件 | 原清单 | 新清单 |
|---|---|---|
| executor | `stage_d_executor.py` 64dea819 | `stage_d_v2_executor.py` **e80fe6a3** |
| config | `stage_d_executor_config.json` 11e52032 | `stage_d_v2_executor_config.json` **914f3edd** |
| child | `_damsj_child.py` bbfc527d（Mock 子进程，真实运行不使用） | `_damsj_real_child.py`（修复后实测 SHA） |
| wrapper | `damsj_executor.py` 04964d72（**已过期**：修复 PIPE 死锁后磁盘为 107db96a） | 107db96a，重新冻结 |
| runner | 未登记 | `damsj_pilot_runner.py`（修复后实测 SHA） |
| 真实路径依赖 | 未登记 | `stage_a/executor.py` 5f1de3c7（提示词）、`transport.py` 7a423eb3（DS 传输） |
| d2、engine、tests、scorer、stats、analysis、prereg | 已核对一致 | 不变 |
| governance | `EXECUTOR_IDENTITY_SUPPLEMENT.md` | 追加本报告与身份勘误 |

注意：按原清单，wrapper 的 SHA 已经不匹配，依批次自身的完整性规则，**每次执行都会被判为 INTEGRITY_FAIL**。

**身份勘误**（新建文件）：取代 `EXECUTOR_IDENTITY_SUPPLEMENT.md` 第一、二节以及 `MANIFEST_STAGE_D_V2.json` 中 `executor_version_registration` 的"64dea819 推定"，改为登记 e80fe6a3 + 914f3edd，依据为 A.6 与 X6；原文件保持不变。

另需注意命名冲突：补记里的"V2"标签指 4ab0c47d（S5 修复候选），**不是** `stage_d_v2_executor.py`。

建议的论文措辞："192 次 Stage D 真实执行由 A‴ 执行器 `stage_d_v2_executor.py`（e80fe6a3…）与配置 914f3edd… 产生，依据为记录内五项判别特征与零调用逐记录重放（完全时序记录 170/170 复现）；不存在逐次密码学证明。"

论文方法部分对 192 次执行配置的描述，应为 A‴ 路由与 300 s 截止期，而不是基础 D2 规格中"E 节点在 GLM 上"的描述。

### E.4 发射前门禁（全部零调用）

1. **G1 重放冒烟**：修复后的子进程加 A‴ 执行器，用记录回放跑 3 臂。Static 与 Proposed 必须逐字段复现基线记录；DAMJS 必须跑完；臂标签断言必须通过。
2. **G2 身份校验**：批次前后各对新清单做一次组件 SHA 校验。
3. **G3 预算强制测试**：把上限设为 1 次调用，第二次预留必须得到 `INCOMPLETE_BUDGET`，且运行器必须停批。
4. **G4**：前三项通过后，等待您对真实冒烟和正式批次的 GO。

---

## 对既有报告的更正（原文件不修改）

| 文件 | 原表述 | 更正 |
|---|---|---|
| `D3_ROOT_CAUSE_V2.md` 层 2 | DS 的 E 响应未通过 D2 合同校验 | 证伪。探针中没有 DS 调用，失败原因是 `stage_d_executor.py:666` 的 AttributeError |
| `D3_ROOT_CAUSE_V2.md` 层 1 | 缺 `DEEPSEEK_API_KEY` 是原因之一 | 探针的 E 节点走 GLM，缺密钥不是失败原因；但在 A‴ 路由下该密钥是必需的 |
| `D3_ROOT_CAUSE_V2.md` 账本 | 探针消耗 ¥0.0304 / 12,948 token | 实际为核算 ¥0.0484 / 20,520 token（现金 ¥0） |
| `DAMJS_PILOT_STATUS.md` 的 D3 | 疑似在初始化路径上阻塞 | 不是阻塞，见 A.5 第 4 点 |
| D2 缺陷"L4 部分结果未捕获" | — | 两个原因：节点从未完成（AttributeError），以及真实子进程不写 `node_end`（M4） |
| `EXECUTOR_IDENTITY_SUPPLEMENT.md`、`MANIFEST_STAGE_D_V2.json` | 192 次执行推定由 64dea819 产生 | 改为 e80fe6a3 + 914f3edd（A.6） |

## 待您裁决

1. 是否批准方案 4（重绑 A‴ 执行器）以及 D.2 中的 M1–M5 修改。
2. 预算：提高调用上限、缩减规模，或接受以 INCOMPLETE 结束（E.2）。
3. 保真度问题 F1–F3 如何处理。
4. 身份勘误文件与新批次 MANIFEST 是否落盘。
