# 全项目资源同步最终报告（2026-11-06）
> 本报告由 zcode 窗口生成，与 08:00Z 的 RESOURCE_SYNC 盘点（另一窗口）衔接：该轮完成资源盘点与索引（阶段一至四），本轮补齐跨窗口上下文层、环境清单与本报告（阶段五之可达部分+阶段六）。

## 第六阶段指标
| 指标 | 值 |
|---|---|
| 已发现资源总数 | **70,538**（另有前置快照 47,229 资产/4,187 记录，已并入） |
| 已成功同步资源数（建立副本/投递） | **0** —— 按只读纪律本轮仅索引不复制；跨环境投递待权限 |
| 仅建立索引资源数 | 70,538（全部 INDEXED_ONLY，含 SHA256） |
| 未同步资源数 | 70,538（同上）；外部不可见环境数量 **UNKNOWN** |
| 冲突资源数 | **2,647** 组同名不同内容（VERSION_CANDIDATES 待裁决）；确认冲突 0（未裁决）；同内容重复 10,296 组（可建引用） |
| 不可访问环境 | 3 类：其他 ChatGPT 窗口 / 本地 Windows 科研目录 / 其他科研软件（Overleaf/Zotero 等，存在性未证实）→ 见 ENVIRONMENTS.json |
| 凭据排除 | 198 个敏感名文件已排除；抽检 0 泄漏 |

## 各环境最后同步时间
| 环境 | 可见性 | 最后同步 |
|---|---|---|
| AutoDL 容器 /root | LOCAL_VISIBLE | 2026-11-06T08:00:09Z |
| 数据盘 autodl-tmp | 部分（模型权重除外） | 2026-11-06T08:00:09Z |
| 本地 git 分支+worktree（14 分支/6 worktree） | LOCAL_VISIBLE | 2026-11-06T08:00:09Z |
| GitHub origin（15 分支，main=c91afd43） | API_VISIBLE | 2026-11-06T08:41Z（PR#11） |
| 服务器 AI 会话存档（.claude/.codex/.copilot/.zcode，412 条） | LOCAL_VISIBLE | 2026-11-06T08:00:09Z |
| ChatGPT 其他窗口 | **NOT_VISIBLE** | 从未 |
| 本地 Windows 目录 | **NOT_VISIBLE** | 从未 |

## 分类计数
EXPERIMENTS 43,304 / CODE 15,819 / REPORTS 3,263 / EVIDENCE 3,937 / ARCHIVE 1,390 / DECISIONS 502 / PAPERS 745 / RUNNING 555 / DATASETS 675 / SCORERS 348（仓库 9 个）

## 完整性检查结果
- 抽样 30 条：存在 30/30，SHA256 一致 30/30（≤2MB 全量复核），缺失 0，错配 0
- 索引中凭据模式命中 0
- 正在运行：search_cases.py（independent_case_search，P2 前置资料搜索；非模型实验）；08:00Z 快照中的 plan_a_prime.py 当前采样未见（状态未知）
- 已知不一致登记：旧 EXPERIMENT_LEDGER 的 E2.1-A MD/JSON 状态不一致（MD"待分析"vs JSON"CONFIRMATORY_FAIL"，执行以 JSON 为准——RESOURCE_SYNC READ_ME 已登记）
- 未推分支 3 个（feature/joint-algorithm、feature/planner-execution、zcode/deadline-feasibility-audit）与 295 个未提交工作区删除——**均未动，待操作者裁决**

## 后续增量同步方式
1. 服务器侧：重跑盘点脚本生成新时间戳目录 + 追加 INDEX_EVENTS.jsonl（不覆盖）
2. 跨窗口：新窗口开工前读本包 7 文件；产生新结论→用户拷回本目录追加
3. 本地 Windows / ChatGPT：用户导入本包或将文件上传服务器/GitHub 后由下轮收录
4. 冲突裁决：VERSION_CANDIDATES.json 2,647 组按"保留双版本+标记差异"待逐组裁决

## 纪律执行确认
模型调用 0、GPU 0、费用 0；原始资产未修改；未推送 GitHub；未覆盖任何服务器文件；未触碰其他窗口资产；索引仅追加。
