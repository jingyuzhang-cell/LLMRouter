# TFJS 批次申请：Terminal-Fidelity Joint Scheduling（零调用构建完成，待授权）

**回应操作者 2026-11-06 裁定**：先解决 Report 信息保真，再用相同上游输入做配对实验，直接检验调度是否改善终端 Q/C/L；不扩大策略复杂度、不加模型池、不重测已验证机制、不改 Gold/评分口径。

---

## 一、设计（两组配对，因果分离）

### 组一：Report 保真对照（配对单位：同一 merge 事实集 + 同一 verify 标注）
- **A_original**：V1 冻结 report 提示词（模型重新生成证据）
- **B_fidelity**：组织表达合同（逐条原样保留 fid/value/doc/quote/verify_status，仅可新增 summary；禁止改写/新增/删除事实）+ runner 按 fid **确定性回填**引用
- 6 个上游事实集 = V1 DA-JS persistent r1–r3（Q_merge 0.545×3）+ V2 DA-JS-v2 persistent r1–r3（0.273/0.455/0.273），覆盖两批质量区间；每集 verify 重算 1 次（共享），两变体 × 2 rep
- **归因**：输入逐位相同 → Δ(报告变体) 是纯报告效应

### 组二：调度策略对照（配对单位：同一 extract 输出 + 同一注入异常）
- 每 rep：3 次真实 DS extract（**缓存共享**）→ 1 次真实 qwen base merge（**同一次调用、同一截断**，两臂共享）
- **Proposed 臂**：R(注入→失败)→π(DS)→verify→B_fidelity report（4 调用）
- **DA-JS-v2 臂**：decide_v2→Z2（3 DS 分片）→verify→B_fidelity report（5 调用）
- 两臂统一用 B_fidelity 报告（传递机制是被检验对象；报告变体效应由组一单独量化）
- **归因**：extract 抽样混杂从构造上消除（V1↔V2 跨批混杂的根源被拆除）

## 二、预注册预期（含诚实上限，防事后口径争议）

1. Q_report(B) 上限 = Q_merge（value 按 fid 回填传递）；B−A 的 ΔQ_report 即"报告段损失的可回收部分"
2. **ES(B) 上限 = 上游 quote 有效性（实测 0.16–0.44）**：回填只能传递不能修复引用——若上游 split/merge 的 quote 本身被改写，引用准确性的根本约束在上游。此预检已零调用完成并存档
3. B 臂若仍低于上限，差额 = 模型在组织阶段丢 fid 的比率（可测）
4. 组二预期：Z2 臂 Q_merge ≥ π 臂（ pooled 0.454 vs 0.349）；终端差值 = 组二直接检验对象
5. **若组一显示保真报告不能提高 Q_report/Support，接受该结果**并据此重新判断调度收益边界（操作者预注册要求）

## 三、指标（操作者表）

Q_merge / Q_report / ES / **Support**（新增，代理定义：命中 Gold 槽位的事实中，其 quote 逐字包含该槽位 Gold 引用跨度的比例）/ C（调用+¥）/ L（臂时延：恢复+verify+report）/ JointSuccess（Q_report≥0.5 ∧ 按期）。Gold 与命中规则与 V1/V2 完全一致，未修改。

## 四、预算

- Mock 全量演练：**69 调用 / ¥1.23 / 管线 18+18 执行单元全部通过**（G2 39 + G1 30）
- 真实 tokens 预计 ≈21 万
- 申请上限：**100 调用 / 500,000 tokens / ¥2.2**
- 停止规则：任一上限触顶即停（仅执行边界）；正负结果全部报告；192 HOLD 不动

## 五、文件

`tfjs_runner.py`、`tfjs_score.py`、`tfjs_config.json`、`tfjs_runs/`（mock 演练）、预检（回填上限）见本申请第二节

---

## 授权请求（明文；未收到前不发起任何真实调用）

> **批次 `TFJS_V1`：调用 ≤100 次；Token ≤500,000；费用 ≤¥2.2。授权执行终端保真联合调度配对实验（组一 30 + 组二 39 调用）。**
