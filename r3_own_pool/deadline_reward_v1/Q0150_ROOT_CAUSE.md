# Q0150_ROOT_CAUSE — 终端质量 0.150 的根因定位（2026-10-27，零调用）

## 根因确认：sink prompt 构造的两个实现缺陷

### 缺陷 1：facts_json 传入的是原始抽取 JSON 字符串的前 50 字符，不是解析后的独立事实

**错误代码**：
```python
facts_json = json.dumps([{'fact_id':f'F{i}','fact':v[:50],'doc_id':k}
  for i,(k,v) in enumerate(outputs.items()) if k.startswith('n_')])[:3000]
```

**实际效果**：sink 收到 3 个被截断的 JSON 包装片段（283 字符 / 265 token），
而非 31 条结构化事实。**所有关键金额（12,500.00 万元等）和日期在截断中丢失。**

**对比**：正常工作的 NEW_CONTRACT_SINK_VALIDATION 传入 2294 token 的完整事实集。

### 缺陷 2：verdicts_json 硬编码为 `'[]'`——verify 输出被完全丢弃

DS verify 节点正常运行（in=1538, out=1087），但其输出**从未传给 sink**。
sink 收到的核验判定为空数组。

## 影响范围

**所有策略的 sink 都使用了同样的错误构造**——因此所有策略质量均为 0.150。
这不是模型或调度问题，是**实现缺陷**。

## 修复方案

使用 NEW_CONTRACT_SINK_VALIDATION 中的正确构造：

```python
# 正确：解析抽取 JSON 为独立事实
all_facts = []
for doc_id, ext_text in [('main', main_out), ('sup1', sup1_out), ...]:
    items = json.loads(ext_text)  # parse the extraction JSON
    for j, item in enumerate(items):
        all_facts.append({'fact_id': f'{doc_id}_f{j}',
                          'fact': str(item.get('fact','')),
                          'doc_id': doc_id,
                          'date': str(item.get('date','')),
                          'quote': str(item.get('quote',''))[:60]})

facts_json = json.dumps(all_facts, ensure_ascii=False)  # FULL facts, no truncation
verdicts_json = verify_output  # ACTUAL verify output, not '[]'
```

## 下一步

修复 sink prompt 构造后重跑现金约束配对——预期质量将从 0.150 显著提升
（参照正确实现的 Flash=0.750 / DS=0.850）。

**付费 HOLD 保持。**
