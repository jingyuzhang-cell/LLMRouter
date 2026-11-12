# 统一执行底座零调用核验（2026-11-07）——UB-1 规格（DA-JS v3 实验底座）

**依据**：操作者 DA-JS v3 路线第 1 步。核验对象：STRUCTURED_TRANSFER_V1.2（已执行，96/105 调用）与 MERGE_VIS（已执行，18/18 调用）的机制一致性、成本与质量可迁移性。

---

## 一、ST V1.2 机制精读（代码 `st_v1_exec.py` + `b_arm_budget.py`）

省 token 的三个来源（可移植的机制核心，与其 GLM/zeda 任务解耦）：
1. **代码侧事实库**（`build_store`）：解析结构化抽取 → 逐事实在源文档中**确定性定位**（`locate_all`）→ provenance_status（VERIFIED_UNIQUE/MULTI_SPAN / UNVERIFIABLE_ABSENT）+ quote 由代码附加；fact_id = 类型+文档位置（跨节点唯一）；(类型,归一值,角色) 去重；代码侧冲突预筛。
2. **按类型分片消费**：下游节点只收所需类型切片（slim 投影，quote 仅在需要处出现）。
3. **按 fid 标注而非再生**：下游输出=标注（状态/阶段/核验），终端在标注库上生成。

## 二、六项对照核验（操作者清单）

| 检查项 | ST V1.2（zeda/GLM/TP 评分） | MERGE_VIS（E04/qwen/11 槽 Gold） | UB-1（移植后，本管线） |
|---|---|---|---|
| 事实完整性 | B 臂 5/5 块正向，无静默截断 | Retention **1.000**（6/6；63→63 全量传递） | **构造性保证**：确定性合并零调用验证 6/6 全保留（Q=0.712=extract 覆盖） |
| fid 唯一性 | 代码生成 span 位 id（唯一） | 命名空间 branch::fid（唯一） | 命名空间 + 代码侧 provenance |
| 引用完整性 | quote 代码附加 | ES 0.978 | ES = 代码核验的 provenance（构造性 ≥0.978 量级） |
| Token | **−26% vs 其 A 臂** | **×3.4**（10.2K/调用；全量回显） | 下游估算 ~8K tok/执行（去 merge 调用 + slim 输入 + quote 不经模型回显）≈ **冻结管线水平** |
| 时延 | — | 单元 ~300s（×3） | 估算 ~70–85s/执行（少一次 merge 调用），D=240s 充裕 |
| 终端质量 | TP 11→14，Precision 100% | **Q_report 0.712**（=Q_merge） | **0.712 构造性成立**（=extract 覆盖；剩余缺口=extract 覆盖+逐字伪影，改写口径 ~0.82） |

**关键洞察（MERGE_VIS × ST 交叉）**：MERGE_VIS 证明本管线 LLM merge 在完全可见时是纯传递（零语义增值）→ **UB-1 将 merge 替换为零调用确定性合并**（去重(norm(value),doc)+排序+冲突保留），保留率由构造保证 1.000。这是"完整传递 ≠ 塞满上下文"原则的直接实现：信息以结构化事实包流动，quote/引用由代码附加，模型只做 extract、标注、终端组织。

**一致性边界（如实声明）**：ST V1.2 的数值产自 zeda 任务/TP 评分/GLM-5.3，**不假定跨管线等同**；UB-1 在 E04 上的全部数字来自 MERGE_VIS 实测 + 本审计零调用构造，机制是移植、结果不外推。

## 三、UB-1 规格（冻结，作为 v3 三策略实验的公共底座）

```
Extract（DS×3 文档，与既有缓存复用）→ 命名空间 fid
  ↓ 代码侧 Store 构建（零调用）：源文档定位→provenance；去重；冲突保留
Merge = 确定性合并（零调用；保留率 1.000 构造保证）
  ↓ slim（fid+value+doc，2.8–5.2K 字符）
Verify（1 次 qwen）：按 fid 标注状态（不回显 quote）
  ↓ 标注库 + 组织合同
Report（1 次 qwen）：fid+value+summary；quote 由代码按 fid 确定性附加
```
- 每执行 **5 调用**（冻结管线 6、MERGE_VIS 6）；token ≈ 冻结管线水平；L ≈ 70–85s
- 质量基准：Q_report 0.712 / ES ~0.978（构造性）；extract 覆盖成为唯一上游质量变量 → **正是调度器需要观测与作用的对象**

## 四、对 DA-JS v3 步骤 2–4 的直接含义

1. **估计表重建**目标改为终端口径：Q̂(a|s) 以 Q_terminal 计（UB-1 下 = store 覆盖传导）；s 含**上游质量可观测信号**（store 规模、provenance 率、跨分支重叠）——"extract 没提的，恢复 merge 无用"这一上游约束首次可在线判定。
2. **决策算法**：ε-支配 + VoI 探针策略保留（v2 已验证），动作空间 (Z,R,π) 加第 4 类：**E=extract 级重执行**（上游质量不足时唯一有效动作——损失账本显示 extract 是剩余唯一真实质量源）。
3. **三策略配对**（Static/Proposed/DA-JS-v3）全部跑在 UB-1 上：共享缓存 extract、同注入位置与条件、恢复调用计入各臂成本、同预算同截止、按任务配对；8–12 个真实多文档事件任务。

## 五、零调用核验产物

`UNIFIED_BASE_AUDIT_UB1.md`（本文件）；确定性合并验证（6/6 全保留）与 slim 尺寸实测见上表；数据源 `merge_vis_runs/`、`st_v1_LEDGER.jsonl`、`b_arm_budget.py`。未发起任何真实调用；192 HOLD 未动。
