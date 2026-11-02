# P0: 独立质量验证器设计（三层架构）

**日期**: 2026-11-01 | **状态**: 零调用设计稿 | **目标**: 解决静默质量错误不可观测问题

## 一、设计原则（操作员锁定）

1. **不泄露 Gold 答案**：验证器返回 `VALID / INVALID / UNKNOWN`，不返回正确值
2. **独立于被测模型**：验证器不依赖 flash 或 glm53 的输出来判断正确性
3. **可校准**：验证器自身的准确性须在独立样本上验证
4. **分层递进**：先检查格式（便宜），再检查事实（中等），最后检查语义（昂贵）

## 二、三层验证架构

### 第一层：执行合同验证（已有能力，零成本）

```python
def verify_layer1(output_text, node_contract):
    """检查格式和合同合规性。不消耗模型调用。"""
    result = {
        "parse_ok": False,
        "required_fields_present": False,
        "types_correct": False,
        "verdict": "UNKNOWN"
    }
    
    # 1. JSON 解析
    try:
        parsed = json.loads(output_text)
        result["parse_ok"] = True
    except:
        result["verdict"] = "INVALID"
        result["reason"] = "JSON_PARSE_FAILURE"
        return result
    
    # 2. 必需字段
    for field in node_contract.get("required_fields", []):
        if field not in parsed or parsed[field] is None:
            result["verdict"] = "INVALID"
            result["reason"] = f"MISSING_FIELD:{field}"
            return result
    result["required_fields_present"] = True
    
    # 3. 类型检查
    for field, expected_type in node_contract.get("field_types", {}).items():
        value = parsed.get(field)
        if expected_type == "number" and not isinstance(value, (int, float)):
            result["verdict"] = "INVALID"
            result["reason"] = f"TYPE_ERROR:{field}"
            return result
    result["types_correct"] = True
    result["verdict"] = "VALID"
    return result
```

**能力**：捕获 JSON 解析失败、字段缺失、类型错误
**局限**：无法检测数值正确性或语义正确性

### 第二层：事实与计算验证（需新增，确定性程序化验证）

```python
def verify_layer2_calculate(parsed_output, source_evidence, calc_contract):
    """程序化重算——不使用模型，不消耗调用。
    
    calc_contract 定义:
    - operation: "sum" | "difference_days" | "ratio" | "max" | "count"
    - input_fields: 从 parsed_output 中取哪些字段
    - source_numbers: 从 source_evidence 中取哪些原始数值
    - tolerance: 容差（浮点数比较）
    """
    result = {"verdict": "UNKNOWN", "method": calc_contract["operation"]}
    
    op = calc_contract["operation"]
    
    if op == "sum":
        # 从源证据中提取数字，独立求和
        source_nums = extract_numbers_from_evidence(
            source_evidence, calc_contract["source_numbers"])
        if len(source_nums) != len(calc_contract["source_numbers"]):
            result["verdict"] = "UNKNOWN"
            result["reason"] = "SOURCE_NUMBERS_INCOMPLETE"
            return result
        
        expected = sum(source_nums)
        actual = parsed_output.get(calc_contract["output_field"])
        
        if actual is None:
            result["verdict"] = "INVALID"
            result["reason"] = "OUTPUT_FIELD_MISSING"
            return result
        
        tolerance = calc_contract.get("tolerance", 0.01)
        if abs(float(actual) - expected) <= tolerance:
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "CALCULATION_ERROR"
            # 注意：不返回 expected 值，只返回 INVALID
    
    elif op == "difference_days":
        # 从 parsed_output 取两个日期，程序化计算天数差
        start = parsed_output.get("start_date")
        end = parsed_output.get("end_date")
        claimed_days = parsed_output.get("interval_days")
        
        if not all([start, end, claimed_days]):
            result["verdict"] = "UNKNOWN"
            result["reason"] = "DATE_FIELDS_MISSING"
            return result
        
        try:
            from datetime import date
            d1 = parse_date(start)
            d2 = parse_date(end)
            computed = abs((d2 - d1).days)
            
            if abs(int(float(claimed_days)) - computed) <= 2:  # ±2天容差
                result["verdict"] = "VALID"
            else:
                result["verdict"] = "INVALID"
                result["reason"] = "INTERVAL_CALCULATION_ERROR"
        except:
            result["verdict"] = "UNKNOWN"
            result["reason"] = "DATE_PARSE_FAILURE"
    
    elif op == "ratio":
        # 程序化计算比率
        numerator = float(parsed_output.get(calc_contract["numerator_field"], 0))
        denominator = float(parsed_output.get(calc_contract["denominator_field"], 0))
        claimed_ratio = float(parsed_output.get(calc_contract["ratio_field"], 0))
        
        if denominator == 0:
            result["verdict"] = "UNKNOWN"
            return result
        
        computed = numerator / denominator
        if abs(claimed_ratio - computed) <= calc_contract.get("tolerance", 0.01):
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "RATIO_CALCULATION_ERROR"
    
    elif op == "max":
        # 找最大值
        values = [float(parsed_output.get(f, 0)) 
                  for f in calc_contract["value_fields"]]
        claimed_max = float(parsed_output.get(calc_contract["max_field"], 0))
        
        if abs(max(values) - claimed_max) <= calc_contract.get("tolerance", 0.01):
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "MAX_IDENTIFICATION_ERROR"
    
    return result


def extract_numbers_from_evidence(evidence_text, number_specs):
    """从源文档证据中程序化提取数字（正则匹配，不使用模型）。"""
    import re
    numbers = []
    for spec in number_specs:
        # spec 可以是正则模式或关键词上下文匹配
        pattern = spec.get("pattern", "")
        context = spec.get("context", "")
        
        if pattern:
            match = re.search(pattern, evidence_text)
            if match:
                num_str = match.group(1).replace(',', '').replace('，', '')
                try:
                    numbers.append(float(num_str))
                except:
                    numbers.append(None)
        elif context:
            # 在上下文关键词附近找数字
            idx = evidence_text.find(context)
            if idx >= 0:
                window = evidence_text[idx:idx+100]
                num_match = re.search(r'[\d,]+\.?\d*', window)
                if num_match:
                    num_str = num_match.group().replace(',', '')
                    try:
                        numbers.append(float(num_str))
                    except:
                        numbers.append(None)
        
        if len(numbers) < len(number_specs):
            numbers.append(None)
    
    return numbers
```

**能力**：捕获数值计算错误、日期推算错误、比率计算错误
**关键特性**：
- 全部程序化（正则+算术），不消耗模型调用
- 从**源文档**中提取数字独立重算，不依赖模型输出的数字
- 返回 INVALID 时不告诉引擎正确值——只说"有错"

**适用任务类型**：
| 任务 | operation | 验证方式 |
|---|---|---|
| CALC-1（4数求和） | `sum` | 从文档提取4个虚增利润值，程序化求和 |
| INF-1（日期间隔） | `difference_days` | 从输出取两日期，程序化计算天数差 |
| CALC-2（比率比较） | `max` | 从输出取4个比率，程序化找最大 |
| GAP-INF-3（倍数计算） | `ratio` | 从输出取两比率，程序化相除 |

### 第三层：语义与推理验证（需研究，暂用保守策略）

```python
def verify_layer3_semantic(parsed_output, source_evidence, semantic_contract):
    """语义级验证——当前采用保守策略。
    
    对于因果推理、证据支持等语义问题，当前无法用程序化方法验证。
    保守策略：如果第一、二层都通过，但输出包含以下红旗，返回 UNKNOWN。
    """
    result = {"verdict": "VALID", "layer": 3}
    
    # 红旗检查（保守，不使用模型）
    output_text = json.dumps(parsed_output, ensure_ascii=False)
    
    # 1. 是否包含"不确定"、"无法确定"等表述
    uncertainty_markers = ["不确定", "无法确定", "无法判断", "不清楚", 
                          "insufficient", "unknown", "无法验证"]
    for marker in uncertainty_markers:
        if marker in output_text:
            result["verdict"] = "UNKNOWN"
            result["reason"] = f"UNCERTAINTY_MARKER: {marker}"
            return result
    
    # 2. 是否引用了源文档中不存在的具体数值
    # （检查 output 中的数值是否在 evidence 中出现）
    import re
    output_numbers = set(re.findall(r'\d+\.?\d*', output_text))
    evidence_numbers = set(re.findall(r'\d+\.?\d*', source_evidence))
    fabricated = output_numbers - evidence_numbers - {'0', '1', '2', '100'}
    if fabricated:
        result["verdict"] = "UNKNOWN"
        result["reason"] = f"UNVERIFIED_NUMBERS: {list(fabricated)[:3]}"
    
    return result
```

**能力**：检测不确定性标记、检测来源不明的数值
**局限**：无法真正验证因果推理的正确性——需要后续研究

## 三、验证器与调度引擎的接口

```python
def run_quality_verification(node_output, source_evidence, node_contract):
    """三层递进验证——按成本递增。"""
    
    # Layer 1: 合同验证（零成本）
    l1 = verify_layer1(node_output, node_contract)
    if l1["verdict"] == "INVALID":
        return {"layer": 1, "verdict": "INVALID", 
                "reason": l1["reason"], "failure_type": "contract"}
    
    # Layer 2: 计算验证（零模型调用，程序化）
    if node_contract.get("calc_contract"):
        l2 = verify_layer2_calculate(
            json.loads(node_output), source_evidence,
            node_contract["calc_contract"])
        if l2["verdict"] == "INVALID":
            return {"layer": 2, "verdict": "INVALID",
                    "reason": l2["reason"], "failure_type": "quality_silent"}
        if l2["verdict"] == "UNKNOWN":
            return {"layer": 2, "verdict": "UNKNOWN",
                    "reason": l2.get("reason", ""), "failure_type": "unverifiable"}
    
    # Layer 3: 语义红旗（保守）
    if node_contract.get("semantic_check", True):
        l3 = verify_layer3_semantic(
            json.loads(node_output), source_evidence, node_contract)
        return {"layer": 3, "verdict": l3["verdict"],
                "reason": l3.get("reason", ""), "failure_type": "semantic"}
    
    return {"layer": 1, "verdict": "VALID", "failure_type": None}
```

**引擎消费方式**：
```python
# 在 EngineState 中新增验证结果字段
Node.last_verification = {
    "layer": 2,
    "verdict": "INVALID",  # → 触发 PI_2'-Q 的关键信号
    "reason": "CALCULATION_ERROR",
    "failure_type": "quality_silent"  # → 新的故障类型
}
```

## 四、与 PI_2′ 的关系（不修改原策略）

| 策略 | 触发信号 | 来源 |
|---|---|---|
| **PI_2′（原始）** | systematic failure (contract/parse) + attempt≥2 | 合同层 |
| **PI_2′-Q（新臂G）** | Layer-2 INVALID (quality_silent) + gap≥0.15 + weak model | 验证器 |

PI_2′-Q 是一个**新的独立策略臂**，不替换 PI_2′。两者的差异预注册为 D5。

## 五、验证器自身的校准计划

验证器上线前须在独立样本上验证：
1. **假阳性率**：对已知正确的输出，验证器误报 INVALID 的比例（目标 <5%）
2. **假阴性率**：对已知错误的输出，验证器漏检的比例（目标 <20%）
3. **UNKNOWN 率**：无法判定的比例（可接受，不误触发动机）

## 六、P0 交付物清单

| 文件 | 内容 |
|---|---|
| 本设计文档 | 三层验证架构 + 接口设计 |
| quality_verifier.py（待实现） | 可执行验证器代码 |
| 校准测试用例（待构建） | 已知正确/错误样本的验证器测试 |
