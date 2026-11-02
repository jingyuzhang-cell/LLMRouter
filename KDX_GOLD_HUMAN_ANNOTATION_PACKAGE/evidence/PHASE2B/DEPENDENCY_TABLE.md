# PHASE2B 逐项依赖表 + 消融重算（零调用；取代此前的 D_* 汇总表达）

> 拓扑（v2.1，SINK 无原始 E 旁路）：E1←D1、E2←D2、E3←D3、E4←D4；**J1←E1+E2**；**J2←J1+E3+E4**；**SINK←J1+J2**。
> J1/J2 输出契约强制携带证据锚点五元组（doc_id/page/quote/来源哈希/判断项）——SINK 无法读原始文档，全部引用经 J 层透传。

## 一、23 项事实 + U2 的逐项依赖

| fact | 语义 | 生产节点 | 直接消费的上游 | 信息来源文档 |
|---|---|---|---|---|
| A1 | D1 立案对象=俞发祥个人 | SINK | J2.subject_binding[D1] | D1（经 E1→J1→J2） |
| A2 | D2 立案对象=俞发祥个人 | SINK | J2.subject_binding[D2] | D2（经 E2→J1→J2） |
| A3 | D3 立案对象=公司+王勇 | SINK | J2.subject_binding[D3] | D3（经 E3→J2） |
| A4 | D4 立案对象=公司 | SINK | J2.subject_binding[D4] | D4（经 E4→J2） |
| A5 | 俞发祥两公司均无职务 | SINK | J1.judgments（职务字段）+J2 | D1+D2（经 E1/E2→J1） |
| B1 | D1 编号 01120260037 | SINK | J2.notice_binding[D1] | D1（经 E1→J1→J2） |
| B2 | D2 编号同号 | SINK | J2.notice_binding[D2] | D2（经 E2→J1→J2） |
| B3 | D3 两编号存在、两主体均立案 | SINK | J2.notice_binding[D3].numbers | D3（经 E3→J2） |
| **B3b** | D3 逐号绑定（顺序对应规则） | SINK | J2.notice_binding[D3].per_number_binding+rule_applied | D3（经 E3→J2） |
| C1 | D4 事由=SPECIFIC(2023年报) | SINK | J2.cause_specificity[D4] | D4（经 E4→J2） |
| C2 | D1/D2/D3 事由=GENERIC | SINK | J2.cause_specificity[D1,D2,D3] | D1/D2（经J1）+D3（经E3） |
| D_1 | 自然人身份 SAME_PERSON | SINK | J1.judgments[kind=person_identity] | D1+D2（E1+E2） |
| D_2 | 文书实例 SAME_NOTICE_INSTANCE | SINK | J1.judgments[kind=notice_instance] | D1+D2（E1+E2） |
| D_3 | 收到事件 SAME_RECEIPT_EVENT | SINK | J1.judgments[kind=receipt_event] | D1+D2（E1+E2） |
| D_4 | 公告主体 DIFFERENT_COMPANY | SINK | J1.judgments[kind=announcing_companies] | D1+D2（E1+E2） |
| E1 | 个人立案文书实例数=1 | SINK | J2.counts.personal_filing_instances（依赖 J1.notice_instance） | D1+D2 |
| E2 | 公告主体数=2 | SINK | J2.counts.announcing_company_count | D1+D2 |
| E3 | D3 立案对象主体数=2 | SINK | J2.counts.d3_subject_count | D3（经 E3） |
| F1 | D1 落款日 2026-10-09 | SINK | J2（日期透传，源自 J1/E1） | D1 |
| F2 | D2 落款日 2026-10-10 | SINK | J2（日期透传，源自 J1/E2） | D2 |
| F3 | 收到日 2026-10-09（双源） | SINK | J1（receipt_event 证据锚点）+J2 | D1+D2 |
| F4 | 落款日差≠收到事件差 | SINK | J1（两级日期锚点）+J2 | D1+D2 |
| **U2** | D3 收到日 UNKNOWN（"近日"） | SINK.abstentions | **J2.unresolvable[field=D3收到日期]** | D3（经 E3→J2） |

## 二、消融重算（逐项口径）

- **移除 J1**（E1/E2 与下游断开）：不可产出 = A1, A2, A5, B1, B2, C2(部分,D1/D2), D_1, D_2, D_3, D_4, E1, E2, F1, F2, F3, F4 —— **16 槽位**（此前报告 11 为汇总漏计，已按逐项更正）；
- **移除 J2**（J1 与 E3/E4 均断开于 SINK 前最后一层）：不可产出 = 全部 23 + U2（SINK 只剩 J1 输出，D3/D4 簇与绑定计数全失）——但该消融的实际含义是"最后一层判断缺失"；更有分辨力的表述：**仅切断 J2 对 E3/E4 的边** → A3, A4, B3, B3b, C1, C2(D3 部分), E3, U2 共 **8 槽位**不可产出；
- U2 的依赖链：E3(D3 文本"近日") → J2.unresolvable → SINK.abstentions ✓（已列入上表与 J2 消融）。

## 三、证据锚点传递链（SINK 无旁路的补偿）

E 层抽取 quote+page → J1/J2 判断项强制携带 {doc_id, page, quote, source_raw_sha256, 判断项} 五元组（输出契约已固化于 phase2b_prompts.py 的 J1/J2 system）→ SINK 引用取自 J 层锚点 → 评价器按合同锚点哈希核验。任何一环缺失即引用无效（evidence_support 降分），结构性防止"判断对但溯源断"。
