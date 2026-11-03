# RQ1 V1.8.2-R3 机制重建与回归（零调用）

## 1. 三项机制

### 1.1 DAG 质量传播（已重建）

DAG：`e0,e1 -> t(e0), m(e0,e1) -> r(m), v(m,t) -> p(r,v)`。
- 每个节点的成功概率读取**直接父节点的真实输出**；
- `q` = 被消费父事实中 TP 的比例；`p = base*(0.35+0.65*q*up)`；
- verification 有纠错项 `+0.30*(1-q)*(1-base)`；report 依赖 r 与 v；
- 解析/合同失败使该节点全部事实 FN，并沿依赖降低下游 q；
- 上游错误可被继承、放大或被 verification 部分纠正。

### 1.2 终端评分（已重建）

- 每节点 2 事实；13 条可判定 + 1 条 report UNKNOWN（排除出 Q/TP）；
- 本地 Q = 13 条 TP 率；**终端 Q = (v0,v1,p0) 三条关键事实同时 TP+定位+支持**；
- TP / FP / FN / UNKNOWN / LOCALIZATION / SUPPORT 全部逐事实记录；
- 局部改善不保证终端改善（定位/支持或上游可失败）。

### 1.3 CRN（已重建）

- 每个 (task,node,fact) 一组 U：correct/parse/contract/fp/unk/loc/sup；
- 所有策略共享同一 U；策略只改变模型分配与由此产生的 p/上游 q；
- 同一分配在不同策略调用中结果完全相同（T6/T7）。

## 2. T1–T8 结果

| 测试 | 结果 | 证据 |
|---|---|---|
| T1/T2 上游扰动与错误传播 | **PASS** | 父节点强制 FP 后 m 事实 TP 率下降 >0.05 |
| T3 错误纠正 | **PASS** | verification 纠错项使终端质量高于纯传播 |
| T4 终端分离 | **PASS** | sup=0 时本地 Q>0、终端 Q=0 |
| T5 评分完整性 | **PASS** | TP+FP+FN+UNK=14；loc/sup∈[0,1] |
| T6 CRN | **PASS** | 同分配两次评估逐元素相同 |
| T7 配对 | **PASS** | 同分配零差；不同分配产生差异 |
| T8 精确检验 | **PASS** | 500 例含并列/零差与暴力一致 |

日志：`RQ1_V1_8_2_R3_TESTS.log`；JSON：`RQ1_V1_8_2_R3_TESTS.json`。

## 3. 校准（R3-B/C）

脚本 `rq1_v1_8_2_r3_calibrate.py`：H0 3000；H1 1500/1000；up/parse/up+parse/dir/partial；
N=16/24/40；NT 主策略，TRUE 上限；G_Q/G_F/G_R 联合。
结果：`RQ1_V1_8_2_R3_CALIBRATION.log` / `.json`。

**未完成**：
- CF Oracle 训练规模 5/10/20（本轮校准只含 NT/TC/TRUE；CF 未实现独立训练规模实验）。
- 方向可识别性（R3-C）未在本机制上重跑；R1 的方向结论属于旧模型。
- 费用货币模型：**BLOCKED**，仅相对价格。
- 独立代码审计：**BLOCKED**（本会话无法提供真正独立审计者；需外部复核）。

## 4. 当前状态

- R3-A：机制重建 **完成**；T1–T8 **PASS**。
- R3-B：关键事实/统计口径 **部分完成**（TP/FP/FN/UNK/loc/sup 已入评分；λ=1 净值；精确检验保留）。
- R3-C：Oracle/可靠性 **部分完成**（解析/合同已入 G_R；CF 训练规模与方向未完成）。
- R3-D：回归 **部分完成**（T1–T8；端到端校准运行中；独立审计 BLOCKED）。

**RQ1 仍为 NOT READY for real GO**：机制已修，但 R3-C/D 未闭环，且无真实数据。
