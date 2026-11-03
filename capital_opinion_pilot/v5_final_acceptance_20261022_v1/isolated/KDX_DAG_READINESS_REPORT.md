# KDX_DAG_READINESS_REPORT — 冻结分化 DAG 逐节点就绪审计（零调用）

审计对象：`v3_frozen/kdx_frontier/initial_dag_v3_kdx_frontier.json`（冻结快照，SHA 见 FREEZE_MANIFEST）。
归因纪律：任务集合/goal/依赖语义=LLM 自主（含截断后确定性格式打捞，仅剥离未闭合 rationale）；
extracts_f 类型升级、m_auto_facts_merge 节点、消费者改接=程序类型适配（全部记录于 type_adaptation）；
两次规划调用截断失败保留在账本。**编译恢复不记作 LLM 直接生成成功。**

## 逐节点检查

| 节点 | 契约 | 输入合法 | 证据获取 | 就绪判定 |
|---|---|---|---|---|
| t0 index | evidence_registry.v1 ✓ | question+ctx_table ✓ | 文档元数据 | ✅ |
| t1 extracts_f（监管线） | doc_retrieval_facts.v1 ✓ | question+evidence_index ✓ | 作用域 3 文档；19K 字分配下覆盖其线内全部 6 条 seed | ✅（@≥9.5K 部分、@19K 全） |
| t2 extracts_f（问询线） | ✓ | ✓ | 作用域 2 文档；19K 下覆盖 A7 | ✅（@19K） |
| m_auto_facts_merge | facts_merge.v1 ✓ | facts 多绑定 ✓ | 程序执行零调用 | ✅（见下实测） |
| t3 timeline / t4 entity_facts | ✓ | 消费汇合输出 doc_extracts ✓ | — | ✅ |
| t5 factcheck_full | ✓ | extracts+timeline+entity ✓ | — | ✅ |
| t6 report | report.v1 ✓ | verified_facts ✓ | — | ✅ |

- **分支独立性**：两线文档作用域不相交（{penalty, notice_2019, notice_2020} vs {inquiry_2018, inquiry_2019}），可独立检索执行；
- **facts_merge 实测**（kdx_facts_merge_live_test.json）：82 个真实检索块双线汇合，5/5 文档、逐项
  保留来源节点/块 SHA256/公开日期；冲突标记 0（块级唯一键下无同键碰撞——**注意**：冲突检测的
  设计粒度是"事实级"，将在 extracts 节点输出结构化事实时生效，块级实测只能验证出处保留）；
- **冗余分支**：t3/t4 为并行分析分支，V2 经验显示可能覆盖重叠——属执行后冗余度量项，非结构冗余；
  无不可执行节点；
- **无人工增节点**：编译器仅插入 1 个机械汇合节点（已标注）。

## 就绪结论

**结构就绪、合法、分支独立、汇合语义经真实数据验证；执行就绪取决于预算参数**：
- 3,300 字/线：不可运行（覆盖 2/7）；
- 9,500 字/线：可运行但降质（5/7，约 6.2K token/线注入）；
- **19,000 字/线：完整可运行（7/7，约 12.4K token/线注入，总注入约 25K token）**。
