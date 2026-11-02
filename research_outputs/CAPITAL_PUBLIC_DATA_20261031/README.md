# 新增资本市场公开材料

本次实际下载7份文档：5份PDF（27页）及2份HTML。原文件、逐页文本、来源URL、抓取时间及SHA-256见 SOURCE_MANIFEST.json；一个原PDF入口HTTP405失败记录保留，使用公开披露报刊的公司公告HTML替代。

## 任务索引（问题草案，不是参考答案或实验结果）

### 佳缘科技处罚与会计差错更正
信息截止：2026-10-23。
对照处罚决定与差错更正公告，重建披露时间线，区分违法事实涉及期间、更正覆盖期间、责任主体与处罚结论；不能对应的事项标为 UNKNOWN。

- [CSRC_PENALTY](JIAYUAN_202610/CSRC_PENALTY/source.html)；[原始来源](https://www.csrc.gov.cn/csrc/c101928/c7666388/content.shtml)
- [ACCOUNTING_CORRECTION](JIAYUAN_202610/ACCOUNTING_CORRECTION/source.pdf)；[原始来源](https://static.cninfo.com.cn/finalpage/2026-10-17/1225609797.PDF)

### 容百科技合同问询与回复
信息截止：2026-01-19。
截至2026年1月19日，区分合同约定、公司估算、采购预测和仍待落实的条件；逐项核对问询及回复是否回答同一问题。

- [INQUIRY](RONBAY_202601/INQUIRY/source.pdf)；[原始来源](https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-01-14/688005_20260114_OG2A.pdf)
- [REPLY](RONBAY_202601/REPLY/source.pdf)；[原始来源](https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-01-19/688005_20260119_MV08.pdf)

### 金橙子收购方案调整问询与回复
信息截止：2026-05-26。
对照问询与回复，核对交易支付方式、估值及调整原因、关联关系和审批状态；区分公司解释、预测与已发生事实。

- [INQUIRY](JCZ_202605/INQUIRY/source.pdf)；[原始来源](https://static.cninfo.com.cn/finalpage/2026-05-19/1225313541.PDF)
- [REPLY_CNSTOCK](JCZ_202605/REPLY_CNSTOCK/source.html)；[原始来源](https://paper.cnstock.com/html/2026-05/26/content_2222058.htm)

## 使用边界

- 所有参考均未独立裁决，不宣称 Gold；新增收集不等于事件从未参与历史开发。
- 容百科技2月7日处罚事先告知材料单独保存，禁止进入1月19日任务输入；它是事先告知，不是最终处罚决定。
- PDF文本按页提取，尚未完成逐表格视觉复核；网页文本保留导航等内容，未当作人工清洗金标准。
- 当前材料提供监管事件与披露证据，不代表已收集社交媒体情绪、传播量或市场反应数据。若研究这些指标，须另有对应数据，不能由公告替代。
- 未调用模型、未生成替代响应、未改动冻结算法或历史结果；没有测量模型—节点Q/C/L。
- 这三组材料可用于定义多来源问题，但未证明必须具有复杂DAG，也未据此承诺动态重分配收益。

## 可用数据入口

- `TASK_INPUTS.json`：3个任务的截止时间、资料白名单、六项交付问题与输出合同草案。
- `REFERENCE_CANDIDATES.json`：18项待审问题的原文窗口、页码（PDF）、提取文本字符跨度、源文件及文本哈希。重复命中全部保留，没有自动选择正确证据。answer保持null，独立裁决保持PENDING。
- `DATA_CHECK.json`：18项均定位到文字，全部保存跨度可精确回取。这只证明定位，不证明事实支持或评分合格。
- `build_task_data.py`：纯本地可复算入口，不调用模型，不导入历史执行器。

发现的实际边界：金橙子回复原文出现“2025年5月14日”董事会日期；与2026年材料的时间关系待核，不自行更正。容百的采购金额估算与预测需求不可写成确定履约结果。

现有runner/score.py按每臂完整输出、冻结REFERENCE_SCOPE及六项审阅决定评分；本数据包不是可直接替换旧批次的配置。没有导入旧运行器或更改其授权/锁文件。新的事件、输入合同和参考状态需要在后续整批配置中绑定。双模型在这些节点上的真实测量仍为空，公开文档不提供模型Q/C/L。

## 来源输入包（本次新增）

`MODEL_INPUTS/INDEX.json` 索引三个可直接读取的 source-only JSON，包含任务问题、截止日期及两份白名单原文。doc_id由事件、来源ID和完整原始文件SHA-256组成，保留PDF页码、文本哈希及原文。不复制待审参考、答案或证据检索窗口。网页为完整提取文本，可能包含导航，不声称已完成语义清洗。

复算命令（必须使用不存在的新输出目录，不覆盖旧产物）：

```bash
cd /root/research_outputs/CAPITAL_PUBLIC_DATA_20261031
python -B materialize.py --output MODEL_INPUTS_NEW
```

已用 `python -B -m unittest -v test_materialize` 验证五类边界：真实材料保真及未来来源排除、误加未来来源拒绝、参考元数据隔离、缺失/失败/重复来源及缺失日期拒绝、文本篡改拒绝。全程无网络与模型调用。

限制：日期判定依据现有来源清单日期，不是独立日期裁决；输入包只固定材料边界，不代表已接入模型运行器或完成任务独立性认证，也不提供模型Q/C/L。此次没有修改ZCode或冻结实验文件。
