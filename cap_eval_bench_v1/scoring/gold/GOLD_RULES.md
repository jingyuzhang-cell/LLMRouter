# Gold 标注规则（评测模块内部 + 人工裁决流程）

1. 本工作包全部机器构建参考一律标注 **SILVER**（silver/*.json，逐字引文+程序接地）。
2. **GOLD 宣称条件**（缺一不可）：
   a. 独立人工裁决员（非本系统开发者、非任务作者）逐条阅读证据原文；
   b. 对每条 silver 事实裁定 correct / incorrect / ambiguous，并可直接修正答案；
   c. 裁决记录写入 human_adjudication.csv（模板见同目录）；
   d. 裁决后由评测模块程序复核修正答案的引文接地，复核通过才升级为 GOLD；
   e. GOLD 文件命名 gold/*.gold.json，与 silver 并存；评分器可切换参考集并在报告中注明。
3. 在任何报告/论文中：未经上述流程的事实集只能称 silver/auto-verified，不得称 gold 或
   "人工确认"。
4. 冲突处理：裁决员之间不一致的条目标 AMBIGUOUS 并从主评分剔除（不计入分母，需在报告中
   披露剔除数量）。
