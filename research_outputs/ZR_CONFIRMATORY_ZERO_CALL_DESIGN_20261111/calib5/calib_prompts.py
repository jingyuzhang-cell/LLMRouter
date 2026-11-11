"""CAL5 通用双文书提示词（问询函/回复公告域；零模型调用）。

与 full_dag_tasks.py 的处罚文书专用提示词不同，本模块面向"问询函 × 回复"
与"更正公告 × 监管文书"两类通用双文书任务，不预设处罚/听证语义。
输出合同保持与冻结执行器一致：entity_facts.v2 / timeline.v2 /
entity_relations.v2 / fact_check.v2 / xc_locate.v1。
五条冻结约束：两臂同 D1/D2 原文窗口；两臂同父输出；同注入位置/值/次数；
Gold 不入任何输入；端到端按实际 token 记账。
"""


def fe_generic(doc_id, text):
    return (
        '你是一个资本市场文书事实抽取助手。\n\n'
        '## 任务类型：fact_extraction\n'
        f'## 证据文档 doc_id：{doc_id}（每条事实的 evidence_doc_id 必须使用此 id）\n'
        '## 任务描述\n从证据文书中抽取原子事实：涉及主体、事项/谓词（交易对价、'
        '持股比例、财务指标、评估值、日期、条件等）、数值或结论、时间范围与口径。'
        '每条含事实陈述、数值/日期、主体列表、evidence_doc_id。\n\n'
        f'## 证据文档 [{doc_id}]\n{text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每个元素包含 fact, date, entities, '
        'evidence_doc_id 字段\n- 输出契约：entity_facts.v2\n'
        '- 只抽取有原文证据支持的事实，不得虚构；数值保留原文口径与单位\n\n'
        '请严格按照输出要求完成任务。')


def tl_generic(doc_id, facts_json, text_head):
    return (
        '你是一个资本市场文书事实抽取助手。\n\n'
        '## 任务类型：timeline\n'
        f'## 证据文档 doc_id：{doc_id}（时间线每项的 evidence 引用此 id）\n'
        '## 任务描述\n基于抽取事实构建该文书披露事项的时间线与关键数值节点'
        '（交易/事项的披露、受理、问询、回复、评估、承诺等），每项含日期、'
        '描述、关键数值与证据。\n\n'
        f'## 上游抽取事实 [{doc_id}]\n{facts_json}\n\n'
        f'## 证据文档片段 [{doc_id}]\n{text_head}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每项包含 date, event, value, '
        'evidence 字段\n- 输出契约：timeline.v2\n\n'
        '请严格按照输出要求完成任务。')


def er_generic(doc_id, text):
    return (
        '你是一个资本市场文书事实抽取助手。\n\n'
        '## 任务类型：entity_relations\n'
        f'## 证据文档 doc_id：{doc_id}（每条关系的 evidence_doc_id 使用此 id）\n'
        '## 任务描述\n识别文书中的主体（上市公司、标的公司、交易对方、中介机构）'
        '及其关系与关键数值（交易对价、持股比例、评估值、业绩承诺、财务指标），'
        '每条含主体名称、角色、关系/数值、证据。\n\n'
        f'## 证据文档 [{doc_id}]\n{text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每条包含 entity, role, relation, '
        'value, evidence_doc_id 字段\n- 输出契约：entity_relations.v2\n\n'
        '请严格按照输出要求完成任务。')


def xc_dual_generic(d1_id, d2_id, facts_tl, facts_er, d1_text, d2_text):
    """Z=0：双文书汇合，单次完成冲突定位与裁决（fact_check.v2）。"""
    return (
        '你是一个资本市场文书事实核查助手。\n\n'
        '## 任务类型：cross_verification\n'
        f'## 来源A doc_id：{d1_id}\n## 来源B doc_id：{d2_id}\n'
        '## 任务描述\n将来源A与来源B两路输出逐条对照，定位相互冲突的字段'
        '（同主体、同谓词、同阶段/时间、同口径且不能同时成立者），依据两份原始'
        '文书正文裁决正确值；正常阶段变化（如草案→修订稿、预案→正式稿）不是冲突，'
        '按阶段分别记录。\n\n'
        f'## 来源A事实 [{d1_id}]\n{facts_tl}\n\n'
        f'## 来源B事实 [{d2_id}]\n{facts_er}\n\n'
        f'## 原始文书A [{d1_id}]\n{d1_text}\n\n'
        f'## 原始文书B [{d2_id}]\n{d2_text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每条含 claim, source_a, source_b, '
        'verdict(SUPPORTED/UNSUPPORTED/CONFLICT), resolved_value, evidence_doc_id\n'
        '- 输出契约：fact_check.v2\n\n请严格按照输出要求完成任务。')


def loc_dual_generic(d1_id, d2_id, facts_tl, facts_er, d1_text, d2_text):
    """Z=1 第一步：仅定位冲突字段与原始证据（与 Z=0 相同输入信息）。"""
    return (
        '你是一个资本市场文书事实核查助手。\n\n'
        '## 任务类型：cross_verification_locate\n'
        f'## 来源A doc_id：{d1_id}\n## 来源B doc_id：{d2_id}\n'
        '## 任务描述\n对照两路输出，逐字段列出需要裁决的冲突（同主体、同谓词、'
        '同阶段/时间、同口径且不能同时成立），并为每个冲突在原始文书中定位证据'
        '位置。正常阶段变化（草案→修订稿、预案→正式稿）不是冲突。只使用两路输出'
        '与两份原始文书，不引入外部信息。\n\n'
        f'## 来源A事实 [{d1_id}]\n{facts_tl}\n\n'
        f'## 来源B事实 [{d2_id}]\n{facts_er}\n\n'
        f'## 原始文书A [{d1_id}]\n{d1_text}\n\n'
        f'## 原始文书B [{d2_id}]\n{d2_text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，元素含 field, tl_item, er_item, '
        'evidence_doc_id, evidence_span\n- 输出契约：xc_locate.v1\n\n'
        '请严格按照输出要求完成任务。')


def ver_dual_generic(d1_id, d2_id, located, facts_tl, facts_er, d1_text, d2_text):
    """Z=1 第二步：逐字段验证与裁决（输出合同仍 fact_check.v2）。"""
    return (
        '你是一个资本市场文书事实核查助手。\n\n'
        '## 任务类型：cross_verification\n'
        f'## 来源A doc_id：{d1_id}\n## 来源B doc_id：{d2_id}\n'
        '## 任务描述\n基于已定位的冲突字段，逐条核验并依据原始文书裁决正确值。'
        '不得引入定位证据之外的来源。\n\n'
        f'## 已定位字段证据\n{located}\n\n'
        f'## 来源A事实 [{d1_id}]\n{facts_tl}\n\n'
        f'## 来源B事实 [{d2_id}]\n{facts_er}\n\n'
        f'## 原始文书A [{d1_id}]\n{d1_text}\n\n'
        f'## 原始文书B [{d2_id}]\n{d2_text}\n\n'
        '## 输出要求\n- 输出格式：JSON数组，每条含 claim, source_a, source_b, '
        'verdict(SUPPORTED/UNSUPPORTED/CONFLICT), resolved_value, evidence_doc_id\n'
        '- 输出契约：fact_check.v2\n\n请严格按照输出要求完成任务。')
