# VAL Gold 标注试点包（元道退）——Gold 状态：PENDING（无人工标注者参与前不得宣布 Gold）
流程：标注员 A/B 背靠背 → annotate_agreement.py（κ 参考 ≥0.75，同时人工复核分歧/定位/裁决）
→ 第三标注员裁决 → 资深者抽 20% → 冻结 gold/。
可见：task.md + evidence/ + candidates（提效）；不可见：被评模型输出、评分器结果。
AI 交叉核验未授权；授权后仅 Silver 辅助层。模板见 templates.json。
