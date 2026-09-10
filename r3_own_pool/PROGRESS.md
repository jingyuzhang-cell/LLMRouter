=== R3 5000x4 collection status  (15:40:51) ===
large (local):      4993/4999  [0.0/min]
medium (local):      4981/4999  [0.0/min]
small (local):      4948/4999  [0.0/min]
reasoning (R1 API): 4082/4999  [0.0/min]  ETA -
local driver: full driver done Wed Sep  9 12:56:56 CST 2026
gpu: 0 MiB, 0 %
pipeline: [18:59:33] pipeline watcher started
local line ETA: ~0h01m for all 3 slots

next after reasoning completes: v2 scoring/freeze/fit path (router_v2; legacy auto-pipeline retired)


## 2026-09-10 数据污染审计与修复

发现旧train矩阵633个服务故障零分（其中175个在客观任务）、tie-aware使用当前请求实际成本、repeat panel缺失标准答案绑定，以及真实750题test已开封。已修复训练标签门禁、折内成本决策与repeat评分协议，生成新的客观训练快照、相似题分组、97题repeat panel，完成Ridge同折/分组/排除pilot对照与3-seed MA排序消融。29项相关测试通过。原test全部作为开发历史，不再认证独立；没有在此次审计汇总validation/test质量。详细结果及后续输入见router_v2/contamination_audit_20260910b/REPORT.md与REMEDIATION.json。


2026-09-10 错误切换定位与锚定MA：在修复标签的相似题分组OOF上，完成3-seed嵌套选参，MA从旧固定60轮平均81.759%提升至87.014%，但仍未超过DatasetBest 87.126%，RidgeGuard消融为87.160%。新增3项隔离/决策测试通过。详细结果见router_v2/anchored_ma_clean_20260910/REPORT.md；不宣称MA独立增益或正式测试闭环。
