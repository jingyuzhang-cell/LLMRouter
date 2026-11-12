# 检测器 V4 冻结记录（零调用）

**日期**：2026-11-06
**依据**：操作员要求核验 V3 是否覆盖 T1 暴露的 not_found 标签变体，未覆盖则建新版本、保留旧版本。
**核验结论**：V3 不覆盖。V3 只改了“是否”类槽位，非“是否”槽的压制判定仍用 V2 的同义词表，表中没有 not_found。T1 A1 第 3 次重复中，J2 用 not_found 扣住 5 个槽，V2 与 V3 都报 NONE。
**离线回归**：10/10（`V4_REGRESSION.json`），重放了全部 9 份真实 J2 输出（Stage A' 3 份、T1 6 份）。

| 文件 | sha256 |
|---|---|
| `detectors_v4.py` | `aebba8bba5277c6f05e07ae86fc1c41703818514db7d08a80e088d446bd4b77d` |
| `detectors_v3.py`（保留） | `6f39b9af9f0405376b8bad71a8d685814fb34e05a4029b920f1da0256401cd30` |
| `detectors_v2.py`（保留） | `c2c3384265b39aee6783eff407402c4c775d7eb0b18aea005442f80ec1548c24` |

## 唯一改动：J2 状态标签三分类

| 类别 | 标签 | 来源 |
|---|---|---|
| 确认 | 已核验、correct、verified、supported、computed | 冻结时全部真实台账中出现过的确认类标签（共 147 次） |
| 压制 | V2 的 10 个同义词 + not_found | not_found 来自 T1 A1 第 3 次重复（5 次） |
| 未知 | 其他任何非空标签 | 新增状态 UNKNOWN_LABEL，**绝不静默当作 NONE** |

- **M1 状态**：NONE（已确认或无候选证据）、EXPLICIT_SUPPRESSION、OMISSION（未提及）、UNKNOWN_LABEL。
- **其余不变**：“是否”槽沿用 V3 的候选规则，M2 与 M3 原样调用 V3。

## 重放结果

- 9 份 J2 输出中，V4 与 V3 只在一处不同：T1 A1 第 3 次重复的 5 个 not_found 槽，从 NONE 变为 EXPLICIT_SUPPRESSION（回归 L4、L7）。
- unverifiable 与“已核验”的判定与 V3 完全一致（L5、L6）。
- 未见过的标签（如“部分核验”）有候选证据时报 UNKNOWN_LABEL（L8）。

## 冻结承诺

- 千山药机确认实验使用 V4；V2 与 V3 的结果并列报告。
- 独立任务上出现新标签时，按 UNKNOWN_LABEL 如实报告，不在实验中途修改标签表。
