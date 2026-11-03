# DD_V75_AUDIT — 任务—DAG—证据—评分一致性审计（2026-10-30，零调用）

> 按 operator 裁决：追溯 DD-V7.4 实验的真实输入，定位失败位置，建立
> 执行前语义门禁。零模型调用。

## 一、根因确认：**证据绑定错误——加载了错误事件的文档**

### 核心事实

| 项 | 应该 | 实际 |
|---|---|---|
| D_r1 任务事件 | **泽达易盛**（欺诈发行退市） | — |
| 证据文档 | 泽达易盛处罚决定书 | **E04-zhuoran**（*ST卓然退市风险公告） |
| 评分参考 | 泽达易盛事实 | E04-zhuoran 文本 |

**Runner 的证据加载逻辑**：
```python
for f in sorted(B.glob('evidence/texts/*.txt'))[:2]:
    ev[f.stem] = f.read_text()[:3000]
```
`sorted()` 返回按文件名排序的前两个 → E04-zhuoran 开头的文件排序在
最前。**这是一个 fallback 路径的 bug**——D_r1 原始 spec 无 evidence
字段，导致进入了 fallback，而 fallback 没有验证事件身份。

### 证据对比

| 文档 | 事件 | 长度 | 内容类型 | 处罚数据 |
|---|---|---|---|---|
| E04-zhuoran（实际使用） | *ST卓然 | 691+2626 字 | 退市风险提示 | **无** |
| zeda_main（应该使用） | 泽达易盛 | 7,967 字 | **处罚决定书** | 40 个金额锚点 |
| zeda_inter（应该使用） | 泽达易盛 | 9,237 字 | 中介处罚 | 32 个金额锚点 |

### n3/n4 失败的直接证据

- n3(timeline) 输出：`"error": "未提供待整理的事件内容，请提供原始资料"`
- n4(amounts) 输出：`{"amounts": {"总计": 0}}`

**模型在告知输入不足**——退市风险公告中无处罚事实、无时间线事件、
无金额数据。这不是模型能力问题，是证据语义不匹配。

## 二、问题层级

| 层级 | 问题 | 影响 | 状态 |
|---|---|---|---|
| **L1 证据绑定** | 加载了错误事件的文档 | 全链路失败 | **根因** |
| L2 语义门禁 | 无执行前证据-任务身份校验 | 允许不匹配实验启动 | 缺失 |
| L3 评分身份 | 评分参考使用错误事件文本 | ΔQ 无意义 | L1 的下游 |

**单点修复**：正确绑定泽达易盛处罚决定书 → L2/L3 自动解决。

## 三、正确的证据集（已存在于冻结库）

| 文档 | 来源 | 字数 | 关键锚点 | 状态 |
|---|---|---|---|---|
| zeda_csrc_penalty_2023_29 | h1v8_docs/ | 7,967 | 40金额+8日期+9处罚+2主体 | 已冻结(SHA) |
| zeda_csrc_penalty_2024_kangda | h1v8_docs/ | 9,237 | 32金额+5日期+10处罚+2主体 | 已冻结(SHA) |

**不需要新获取任何文档**——正确的证据已在冻结库中。仅需修复
runner 的证据绑定逻辑，并在执行前加入语义身份校验。

## 四、语义门禁设计（执行前必过）

```python
def semantic_gate(task_spec, evidence_docs, scorer_ref):
    # 1. Event identity check
    task_event = extract_event(task_spec['question'])
    doc_events = [extract_event(d['text']) for d in evidence_docs]
    if not all(e == task_event for e in doc_events):
        return FAIL, "EVIDENCE_EVENT_MISMATCH"

    # 2. Fact coverage check (per node type)
    for node in task_spec['nodes']:
        required_facts = get_required_facts(node['role'])
        if not check_coverage(evidence_docs, required_facts):
            return FAIL, f"EVIDENCE_INSUFFICIENT:{node['id']}"

    # 3. Scorer identity check
    if scorer_ref.event != task_event:
        return FAIL, "SCORER_EVENT_MISMATCH"

    return PASS
```

## 五、预算审计

| 项 | 值 |
|---|---|
| 总请求 | 23/23 ✓ |
| glm53 | 8 次 ✓ |
| glm53flash | 15 次 ✓ |
| 总 Token | 9,627（远低于 35,000 上限）|
| 现金 | ¥0 ✓ |
| 违规 | 0 |

**23 次请求消耗的 9,627 Token 在错误证据上——这些调用不可回收。**
下次执行需全新 23 次请求（正确证据 + 语义门禁通过后）。

## 六、修复方案

1. **证据绑定修复**：Runner 从 D_r1 spec 的 evidence 字段或从
   h1v8_docs/zeda_docs.json 加载（而非 fallback glob）
2. **语义门禁**：执行前检查事件身份（泽达易盛）、事实覆盖（≥N 个
   金额+日期锚点）、评分参考一致性
3. **评分器修复**：score_q 使用正确事件的文本作为参考
4. **回归测试**：确保 E04-zhuoran 不再被误用于泽达易盛任务

## 七、是否值得重新执行

**是的**——修复证据绑定后，在正确的泽达易盛处罚决定书上重新执行
23 次配对，才能真正检验 IB vs Alt 的 ΔQ。

**需要重新授权（新 23 次），当前批次的 23 次已消耗且不可复用。**

**付费 HOLD 维持。论文暂停。**
