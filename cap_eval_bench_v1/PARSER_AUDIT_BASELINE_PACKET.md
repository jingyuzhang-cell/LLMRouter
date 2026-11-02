# Conservative Parser 独立代码审计——基线身份与支撑材料包

**日期**: 2026-10-31 | **用途**: 操作员作为独立审计主体的 A–E 五项审查输入
**性质**: 零调用、零修改；本包只提供证据与索引，不含裁决。源码 1,155 行已在此前交付，不重复粘贴。
**审计基线**: 以本文第一节的三份文件字节身份为唯一基线，禁止以 651/762 行中间版替代。

## 一、基线身份（服务器侧 2026-10-31 实测）

| 文件 | 行数/字节 | SHA256（完整） | 与授权基线一致 |
|---|---|---|---|
| `integration/conservative_parser.py` | 774 行 | `b740c377263226c35b2b2f8a34af952cde3dc377ca99b1ad5350d3edad710f8a` | ✅ `b740c377…d710f8a` |
| `integration/test_conservative_parser.py` | 381 行 | `9219b9084a9ba25d1ff1a08aafdb7e320dc30959e9ee8c0d7660aca4ff393ef0` | ✅ `9219b908…4ff393ef0` |
| `stage_c_evidence/silver_v2.json` | 基线数据 | `b375eb335cb434cc38f32ce238396b495d04eae911f8115c35e467aa94351e5e` | ✅ `b375eb33…51e5` |

## 二、独立执行复现（服务器侧参考结果，供审计员对端复现比对）

- 命令：`python3 integration/test_conservative_parser.py`（工作目录 `/root/cap_eval_bench_v1`）
- 结果：**20/20 PASS，exit 0**；输出日志 SHA256 `c62c95d35c5675058dd456995dba2f3a0b2858903ef8776eb9082d24264d6ae0`
- 复现产物存于 `stage_c_r3_rescore/PARSER_P1_P20_RERUN_20261031.json`；**历史结果文件已按字节恢复**（前后哈希均为 `b30f99d70e9e7f1b8c2b7237861c314179796d9c5b5f04e4f83274b1e0abd9ce`），无历史覆盖。
- 测试脚本自身写死的输出路径即上述历史文件——审计员本地复现时请同样注意备份。

## 三、修复→代码位置索引（供 B 项核查）

**第二轮五项重点（操作员指定核查点）**：

| # | 核查点 | 实现位置（conservative_parser.py） | 状态 |
|---|---|---|---|
| 1 | 三种负号（`- − –`）保留数值符号 | `_norm_price_multi` L74–83：正则 `[-−–]?`（L76）+ `−/–→-` 归一（L79） | T3 探针已确认负数/符号翻转 |
| 2 | 非法日期真实日历校验 | `_norm_date_multi` L86–103：`date(y,mo,d)` 构造（L95），`ValueError→continue`（L97–98） | T3 探针已确认 2026-02-31 拒绝 |
| 3 | 六条件去重全部严格成立 | `_can_dedup` L309–333：任一条件不可判定即不合并（item L312 / conclusion L315 / scope L318–321 / operands L323–325 / doc roles L327–331） | 静态待审 |
| 4 | 缺失 fact_kind 必然阻止绑定 | `_bind_operand` L387–389：`if not original_kind: continue` → 无候选 → `operand_not_in_ledger` → INSUFFICIENT | 静态待审 |
| 5 | 比例多候选完整检测 | `_norm_ratio` L53–71：双模式（`1:X` + 裸 `0.X`）同收集，>1 个不同值 → `ValueError`（L70） | 静态待审 |

**第一轮六项（T2）**：fact_kind 校验 L384–391；preferred_doc 严格收窄 L399–406；角色唯一性 L482–485 + C2/C3/C4 按角色对应比较 L560–627；全类型多候选 L128–153（`typed_parse`）；fid/版本完整性 L413–421 + L439–446；span 类型化核验 L449–462。

## 四、测试覆盖矩阵与断言强度（供 C/D 项核查——**含三处必须呈报的诚实发现**）

### 发现 1：SPEC §八 P1–P20 矩阵未完整实现（覆盖缺口）

测试文件实有 **20 个断言**（P1,P2,P3,P4,P5,P6,P7×3,P8,P10a,P10b,P12a,P12b,P12c,P14,P15,P17,P19,P20），但 SPEC v2.6 §八 明确列出的以下测试组**完全缺失**：

| 缺失测试 | SPEC 预期 | 职责 |
|---|---|---|
| P9a–e（C1–C5 各一项 MISMATCH） | 各→FALSE | 逐条件排除 |
| P11（多 fid 同值） | INSUFFICIENT | 唯一绑定 |
| P13a–f（C1–C5+R1 各一字段缺失） | UNKNOWN，主张 held | F2/F26 |
| P16（TRUE+UNKNOWN 并存） | TRUE 双方 REFUSED；其余 held | 传播 |
| P18（多条 UNKNOWN 关联） | 该主张不 CREDITED | 多关联 |

"20/20 PASS" 是对**实有 20 断言**的通过，不等于 SPEC 测试计划全覆盖。

### 发现 2：三处断言比 SPEC 放宽 / 绕行

- **P3**（L96–98）：SPEC 预期 REFUSED（内部不一致）；断言接受 `REFUSED 或 INSUFFICIENT_EVIDENCE`。
- **P19**（L270–292）：SPEC 的验证点是"C2 必须按角色对应比较，否则误判 TRUE"。但构造中第二条主张**无 doc_a/doc_b**（L275–278），其 0.1339 操作数因 f2/f3 双候选在绑定阶段即失败（ambiguous_binding→INSUFFICIENT），矛盾检查走 C2=UNKNOWN 而非 MISMATCH 路径——断言 `result != TRUE` 经**绑定失败**而非**角色对应比较**通过。F27 的验证点实际未被行使。文件内注释（L284–288）亦承认此构造局限。
- **P20**（L298–312）：SPEC 预期 REFUSED（span_value_mismatch）；断言仅要求 `!= CREDITED`。本次复现实际值 = `INSUFFICIENT_EVIDENCE` + `span_ambiguous_parse`（宽 span 内含 0.1335/0.1339 双候选）。这与 T3 已登记的规范-实现偏差同源：SPEC 要求 parse 失败→REFUSED(`span_type_mismatch`)、多候选→INSUFFICIENT；实现两者并入 INSUFFICIENT。

### 发现 3：P1 历史回放实测值与 SPEC §七预期不一致

SPEC §七对 r3 的预期为 `A=SCORED, B=NOT_SCORED_VERIFIED, f17=REFUSED`；本次复现 P1 实际输出：**4 条主张全部 INSUFFICIENT_EVIDENCE**（2×UNKNOWN_SCOPE + 2×RELEVANT）。断言本身只要求 claims>0，故通过；但回放路径与 SPEC 预期行为存在实质差距（回放 ledger 转换中 `source_doc_version=''`（L325）会强制 version_missing→INSUFFICIENT——构造差异还是实现差距，请审计员裁定）。

## 五、E 项数据保护预检（BENCH_FREEZE_MANIFEST.json，328 条）

- **310 条完整一致**（含全部 `scoring/silver/T-*.silver.json`、`scoring/qe_k_scorer.py`、GOLD_RULES.md、phase1/stage_a 账本等）。
- **6 条变更**（去重后 5 个文件）：

| 文件 | 定性建议 |
|---|---|
| `tasks/tasks_frozen.jsonl`（清单中重复列 2 次） | **已文档化损坏**：STAGE_C_AUDIT 发现3（清理脚本清空，0 条有效），恢复待办在案 |
| `integration/six_arm_scheduler.py` | **已文档化多版本**：STAGE_C_AUDIT"代码版本 ⚠ 多版本 v1→v2→v4" |
| `AUTHORIZATION_LEDGER.md` | 追加式增长预期 + R10 VOID 争议待 append-only 澄清；无原始字节可证"仅追加"，请审计员裁定 |
| `stage_c_r6_runs/ledger.jsonl` | 账本运行期追加预期；同上无法证明仅追加 |
| `evidence/index.json` | **未定性**：本轮首次发现，无在案文档解释，需审计员裁定 |

- **12 条缺失**：全部为 `stage_a/SA-auto-T-M1-r1/r2、SA-auto-T-P2-r1/r2` 四个 run 目录的 `deliverable/scores/trace.json`（清单冻结后该四组 auto 臂产物不在盘上）。

## 六、既有证据引用（不重复开展）

- T3 规则对齐 18 项执行探针：见 `T3_PARSER_EVAL_ALIGNMENT_REPORT.md`（2026-10-31，含规范-实现偏差登记）。
- 两轮缺陷审计（6+5 项）的修复落实：以第三节位置索引对照源码静态核查为准。

## 七、边界声明

本包不构成审计结论。PASS / NEEDS FIX / BLOCK 三态判定权在审计主体。若审计员需要对端执行，基线即第一节三文件；若无法取得字节级一致副本，按授权规则标 BLOCK。
