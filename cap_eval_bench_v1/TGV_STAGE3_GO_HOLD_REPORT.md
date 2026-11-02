# TGV 阶段三 GO/HOLD 报告（五项零调用合成验证，2026-10-30）

**结论：GO（零调用机制验收通过）**。全部用例、断言与证据见
TGV_STAGE3_VERIFICATION.json（24 用例，逐条含 evidence 字段）与执行日志（本报告附摘）。
驱动器 stage_c_tgv_exec.py（sha `e16e4aab`）授权门未注册 stage_c_tgv_v1——
**已验证 fail-closed**：真实实验维持 HOLD，须操作员单独授权。

## 五项汇总

| 包 | 用例 | 结果 | 覆盖 |
|---|---|---|---|
| S3-1 Real-MCF 规则冻结 | 4/4 | ✅ | 真实路径源码级零模型条件化注入；合法 flash 响应原样放行（行为级）；结构规则目标=reasoning 节点（π0=flash，能力表 0.58/0.80）；三态分类器单元测试 |
| S3-2 四臂分化矩阵+动作约束 | 8/8 | ✅ | 两任务 × 四臂：Static=INCOMPLETE_NO_RECOVERY（单次尝试、无 z）；R-only=INCOMPLETE_RECOVERY_EXHAUSTED（目标节点全程 flash，禁换模型）；π-only=COMPLETE（目标 [flash✗→glm53✓]，禁 z）；Joint=COMPLETE（动作合法性交 S3-5） |
| S3-3 缓存保证 | 4/4 | ✅ | 同键同模型免费重放；同 prompt 异模型独立真实调用（模型后缀进缓存键）；purpose 后缀=实际模型；版本变化新键 |
| S3-4 配额与身份保证 | 4/4 | ✅ | flash 配额独立触顶即拒；去重重放不消耗配额；结算模型=请求模型（身份不串扰）；全局硬顶=分模型之和（95 次/130K，无幻余量） |
| S3-5 Z 候选合法性 | 4/4 | ✅ | chk 失败态产生 SPLIT_VERIFY 候选（异类双亲）；apply_z 后依赖无环、report 仍在；MERGE 依冻结规则合法不适用（见披露二） |

## 披露一：初次运行为 21/24（3 FAIL），未掩盖，逐例处置如下

1. **S3-4 replay-does-not-consume-quota FAIL**（glm53 counted=2）：**测试构造缺陷**——脚本含一行
   杂散真实调用（新鲜 meter 上未计入预期）。机制本身经 R1 对（两次同键调用仅计 1）验证正确。
   处置：删除杂散行后复测 PASS。预期值未修改——原预期（+1）即正确，缺陷在构造。
2/3. **S3-5 两任务 candidates-legal FAIL**（z_ops=[]）：**测试构造缺陷**——测试搭了全健康态；
   冻结语义为决策时合法性（SPLIT_VERIFY 仅对**失败态**节点枚举）。改为 chk 失败+双亲健康后
   PASS。**连带发现真实问题一件（披露二）。**

## 披露二：阶段二文档一处夸大，现予更正（原冻结交付物未修改）

TGV_STAGE2_DEPENDENCY_PROOFS.md 曾称"两 extracts 同父同 kind → MERGE 候选存在"。按冻结
z_candidates 规则，MERGE 还需**证据焦点非不相交**（subtask 首段文档集交集非空）；TGV 两任务的
extracts 分别面向不同文书 → 焦点不相交 → **MERGE 合法不适用**（冻结调度器注释原文即预期
"expected EMPTY on the current task set"）。对 ΔU(Joint−π) 有意义的 Z 空间是 SPLIT_VERIFY，
其合法性已在两任务上验证成立；本更正不改变 Z 空间结论，仅收窄候选类型表述。

## 授权边界（重申）

- 本 GO = **零调用机制验收通过**，不构成真实实验授权，更非 Z 已获性能贡献证明。
- 真实模型调用 / GPU / 付费实验维持 HOLD；启动须操作员对 stage_c_tgv_v1 的单独授权语句
  （建议字段：批次名 / 20 runs / 95 次 / 130K / GLM≤75 次·110K / Flash≤20 次·20K / ¥0）。
- 全程零模型调用、零费用；冻结算法与 Stage-2 交付物零修改。
