# VAL 阶段零调用准入报告（元道退 + *ST卓然）

**日期：2026-11-05。零调用；供操作者与 Codex 审查；不含授权。**

---

## 一、战略转向确认

按操作者裁定：
- **ST 江苏舜天归入开发集**（10 月 pilot 已有 73 次调用记录），不再作为独立测试集
- 下一阶段核心 = **证明联合动态调度优于静态异构分配和固定恢复**（三臂对照）
- 先完成 VAL 阶段零付费准入

## 二、VAL 事件证据核查

### E03 元道退（元道通信 301139）——**证据完整 ✓**

| 文档 | 日期 | 大小 | 内容 |
|---|---|---|---|
| D1 | 2026-05-08 | 6.7KB | 收到《行政处罚事先告知书》 |
| D2 | 2026-08-29 | 4.6KB | 收到《事先告知书》（二次） |
| D3 | 2026-08-29 | 14.5KB | 收到《行政处罚决定书》 |

- **Gold 标注包**：`VAL_GOLD_ANNOTATION_PACKAGE/`（README + 候选原子事实 + 证据清单 + 模板 + 标注协议）
- **候选事实**：`candidates_atomic_facts.json` 已含 E03 事实候选（确定性程序候选，不预设答案）
- **状态**：证据完整、Gold 标注框架就绪，需完成双人标注

### E04 *ST卓然（上海卓然工程技术 688121）——**证据完整 ✓**

| 来源 | 文件数 | 内容 |
|---|---|---|
| pilot benchmark_v1 | 3 PDFs | E04-zhuoran.pdf + sup1 + sup2 |
| cap_eval_bench texts | 3 TXTs | 20260910 / 20261009 / 20261013（已提取） |

- E04 3 份 TXT 已在 `cap_eval_bench_v1/evidence/texts/`，与 pilot PDF 对应
- **注意**：E04 未出现在 `VAL_GOLD_ANNOTATION_PACKAGE/evidence/` 中（该包目前只有 E03 的文本）
- **需补充**：将 E04 的 3 份文本复制到 VAL 标注包，并生成 E04 候选事实

### 结论

- **元道退**：证据+Gold 框架就绪 → 可直接进入双人标注
- ***ST卓然**：证据就绪、Gold 候选需生成 → 补充后进入标注
- 两事件合计 6 份文档、~42KB 文本量

## 三、三臂对照设计（待 VAL 测量后冻结）

| 臂 | 定义 | 目的 |
|---|---|---|
| **A: Static-Hetero** | 按 VAL 能力画像固定分配，无执行中变更 | 强静态基线 |
| **B: Fixed-Recovery** | 同 A 初始分配 + 固定重试/换模型规则 | 分离重试收益 |
| **C: Joint-Dynamic** | 运行时联合 Z/R/π，基于执行反馈决策 | 核心算法 |

**关键比较**：
- C vs A → 动态反馈 vs 静态分配的价值
- C vs B → 联合决策 vs 固定恢复的价值
- A vs B → 单纯重试的收益

HomDS 保留为辅助参考，不作主对照。

## 四、待完成清单（零调用，按操作者顺序）

| # | 任务 | 状态 |
|---|---|---|
| 1 | E03 元道退证据核查 | ✅ 完成（本报告） |
| 2 | E04 卓然证据核查 | ✅ 完成（需补 Gold 候选） |
| 3 | E04 文本复制到 VAL 标注包 + 候选生成 | ⬜ 下一步 |
| 4 | Typed DAG 执行器 + 联合调度器集成检查 | ⬜ |
| 5 | Z/R/π 运行时联合决策路径验证 | ⬜ |
| 6 | 故障注入器零调用完整路径测试 | ⬜ |
| 7 | 节点级 Q/C/L 测量清单 + 精确预算 | ⬜ |

## 五、关键约束

- 元道退、卓然为 **VAL 事件**：用于协议验证/模型选择/预算校准，**不用于最终结论**
- TEST 候选（纳川/欢瑞/ST西王/中铁/祥源族）在 VAL 轮结束前**不得运行**
- 舜天/康得新为 **DEV 事件**：允许迭代，但已有 73 次调用史
- 全程零调用，192 HOLD 不动

---

**文件**：
- E03 证据：`capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D1-D3_E03*.txt`
- E03 Gold 候选：`capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/candidates_atomic_facts.json`
- E04 证据：`cap_eval_bench_v1/evidence/texts/E04-zhuoran_*.txt`（3 份）
- 数据划分：`capital_opinion_pilot/BENCHMARK_SPLIT_AUDIT.md`
