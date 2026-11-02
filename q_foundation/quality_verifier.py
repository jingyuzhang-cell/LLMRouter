"""Independent Quality Verifier — three-layer architecture (zero model calls).

Layer 1: Contract verification (parse, fields, types) — existing capability
Layer 2: Factual/calculation verification (programmatic recalculation from source evidence)
Layer 3: Semantic red-flags (conservative, uncertainty markers + unverified numbers)

Key design principle: returns VALID/INVALID/UNKNOWN without exposing Gold answers.
"""
import json
import re
from datetime import date


# ============ Layer 1: Contract Verification ============

def verify_layer1(output_text, node_contract):
    """Check format and contract compliance. Zero cost, no model calls."""
    result = {"layer": 1, "parse_ok": False, "verdict": "UNKNOWN", "reason": ""}

    # 1. JSON parse
    try:
        parsed = json.loads(output_text)
        result["parse_ok"] = True
    except (json.JSONDecodeError, TypeError):
        # Try fenced JSON
        m = re.search(r'```(?:json)?\s*(.+?)```', output_text, re.S)
        if m:
            try:
                parsed = json.loads(m.group(1).strip())
                result["parse_ok"] = True
            except:
                result["verdict"] = "INVALID"
                result["reason"] = "JSON_PARSE_FAILURE"
                result["failure_type"] = "contract"
                return result
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "JSON_PARSE_FAILURE"
            result["failure_type"] = "contract"
            return result

    # 2. Required fields
    for field in node_contract.get("required_fields", []):
        if field not in parsed or parsed[field] is None:
            result["verdict"] = "INVALID"
            result["reason"] = f"MISSING_FIELD:{field}"
            result["failure_type"] = "contract"
            return result

    # 3. Type checks
    for field, expected_type in node_contract.get("field_types", {}).items():
        value = parsed.get(field)
        if value is None:
            continue
        if expected_type == "number" and not isinstance(value, (int, float)):
            # Try converting string to number
            try:
                float(str(value).replace(',', ''))
            except:
                result["verdict"] = "INVALID"
                result["reason"] = f"TYPE_ERROR:{field}"
                result["failure_type"] = "contract"
                return result

    result["verdict"] = "VALID"
    return result


# ============ Layer 2: Calculation Verification ============

def _parse_date(date_str):
    """Parse various date formats to datetime.date."""
    date_str = str(date_str).strip()
    patterns = [
        r'(\d{4})-(\d{2})-(\d{2})',
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        r'(\d{4})[/.](\d{1,2})[/.](\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, date_str)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def extract_numbers_from_evidence(evidence_text, number_specs):
    """Extract numbers from source evidence using context/pattern matching.
    Programmatic only — no model calls."""
    numbers = []
    for spec in number_specs:
        pattern = spec.get("pattern", "")
        context = spec.get("context", "")
        found = None

        if pattern:
            m = re.search(pattern, evidence_text)
            if m:
                try:
                    found = float(m.group(1).replace(',', '').replace('，', ''))
                except:
                    pass
        elif context:
            # context can be "prefix::skip_n" to skip first n numbers after context
            parts = context.split('::skip_')
            ctx = parts[0]
            skip = int(parts[1]) if len(parts) > 1 else 0
            idx = evidence_text.find(ctx)
            if idx >= 0:
                window = evidence_text[idx:idx + 200]
                all_nums = re.findall(r'([\d,]+\.?\d*)', window)
                # Skip year numbers and first `skip` numbers
                filtered = [n for n in all_nums if not (len(n) == 4 and n.startswith('20'))]
                if len(filtered) > skip:
                    try:
                        found = float(filtered[skip].replace(',', ''))
                    except:
                        pass

        numbers.append(found)
    return numbers


def verify_layer2(parsed_output, source_evidence, calc_contract):
    """Programmatic recalculation from source evidence. No model calls.
    Returns VALID/INVALID/UNKNOWN without exposing the correct value."""
    result = {"layer": 2, "verdict": "UNKNOWN", "reason": "",
              "failure_type": None}
    op = calc_contract.get("operation", "")

    if op == "sum":
        source_nums = extract_numbers_from_evidence(
            source_evidence, calc_contract.get("source_numbers", []))
        if any(n is None for n in source_nums):
            result["reason"] = "SOURCE_NUMBERS_INCOMPLETE"
            return result

        expected = sum(source_nums)
        actual = parsed_output.get(calc_contract.get("output_field", "total"))
        if actual is None:
            result["reason"] = "OUTPUT_FIELD_MISSING"
            return result
        try:
            actual = float(str(actual).replace(',', ''))
        except:
            result["verdict"] = "INVALID"
            result["reason"] = "OUTPUT_NOT_NUMERIC"
            result["failure_type"] = "quality_silent"
            return result

        tol = calc_contract.get("tolerance", 0.01)
        if abs(actual - expected) <= tol:
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "CALCULATION_ERROR"
            result["failure_type"] = "quality_silent"

    elif op == "difference_days":
        start = parsed_output.get("start_date", "")
        end = parsed_output.get("end_date", "")
        claimed = parsed_output.get("interval_days")

        d1, d2 = _parse_date(start), _parse_date(end)
        if d1 is None or d2 is None:
            result["reason"] = "DATE_PARSE_FAILURE"
            return result
        if claimed is None:
            result["reason"] = "INTERVAL_FIELD_MISSING"
            return result

        try:
            claimed = int(float(str(claimed).replace('天', '')))
        except:
            result["verdict"] = "INVALID"
            result["reason"] = "INTERVAL_NOT_NUMERIC"
            result["failure_type"] = "quality_silent"
            return result

        computed = abs((d2 - d1).days)
        tol = calc_contract.get("tolerance_days", 2)
        if abs(claimed - computed) <= tol:
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "INTERVAL_CALCULATION_ERROR"
            result["failure_type"] = "quality_silent"

    elif op == "max":
        value_fields = calc_contract.get("value_fields", [])
        values = []
        for vf in value_fields:
            v = parsed_output.get(vf)
            if v is None:
                result["reason"] = f"VALUE_FIELD_MISSING:{vf}"
                return result
            try:
                values.append(float(str(v).replace(',', '')))
            except:
                result["verdict"] = "INVALID"
                result["reason"] = f"VALUE_NOT_NUMERIC:{vf}"
                result["failure_type"] = "quality_silent"
                return result

        claimed_max = parsed_output.get(calc_contract.get("max_field", ""))
        try:
            claimed_max = float(str(claimed_max).replace(',', '').replace('%', ''))
        except:
            # Check if max_field contains a year identifier
            max_idx = calc_contract.get("max_index_field")
            if max_idx:
                idx_val = parsed_output.get(max_idx, "")
                expected_idx = value_fields[int(values.index(max(values)))]
                if expected_idx.split('_')[0] in str(idx_val):
                    result["verdict"] = "VALID"
                else:
                    result["verdict"] = "INVALID"
                    result["reason"] = "MAX_IDENTIFICATION_ERROR"
                    result["failure_type"] = "quality_silent"
            return result

        tol = calc_contract.get("tolerance", 0.01)
        if abs(max(values) - claimed_max) <= tol:
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "MAX_IDENTIFICATION_ERROR"
            result["failure_type"] = "quality_silent"

    elif op == "ratio":
        num = parsed_output.get(calc_contract.get("numerator_field", ""))
        den = parsed_output.get(calc_contract.get("denominator_field", ""))
        claimed = parsed_output.get(calc_contract.get("ratio_field", ""))

        try:
            num = float(str(num).replace(',', '').replace('%', ''))
            den = float(str(den).replace(',', '').replace('%', ''))
            claimed = float(str(claimed).replace(',', ''))
        except:
            result["reason"] = "RATIO_FIELDS_NOT_NUMERIC"
            return result

        if den == 0:
            result["reason"] = "DIVISION_BY_ZERO"
            return result

        computed = num / den
        tol = calc_contract.get("tolerance", 0.05)
        if abs(claimed - computed) <= tol:
            result["verdict"] = "VALID"
        else:
            result["verdict"] = "INVALID"
            result["reason"] = "RATIO_CALCULATION_ERROR"
            result["failure_type"] = "quality_silent"

    return result


# ============ Layer 3: Semantic Red-Flags (Conservative) ============

UNCERTAINTY_MARKERS = [
    "不确定", "无法确定", "无法判断", "不清楚", "无法验证",
    "insufficient", "unknown", "无法核验", "证据不足"
]


def verify_layer3(parsed_output, source_evidence, node_contract):
    """Conservative semantic checks. No model calls.
    Returns UNKNOWN for uncertain outputs, VALID otherwise."""
    result = {"layer": 3, "verdict": "VALID", "reason": "",
              "failure_type": None}
    output_text = json.dumps(parsed_output, ensure_ascii=False)

    # 1. Uncertainty markers
    for marker in UNCERTAINTY_MARKERS:
        if marker.lower() in output_text.lower():
            result["verdict"] = "UNKNOWN"
            result["reason"] = f"UNCERTAINTY_MARKER: {marker}"
            return result

    # 2. Numbers in output not present in evidence (potential fabrication)
    if node_contract.get("check_number_provenance", True):
        output_nums = set(re.findall(r'\d+\.?\d*', output_text))
        evidence_nums = set(re.findall(r'\d+\.?\d*', source_evidence))
        # Allow common non-evidence numbers
        allowlist = {'0', '1', '2', '3', '100', '10', '20', '50', '200'}
        unverified = output_nums - evidence_nums - allowlist
        # Dates decompose into numbers (2025, 12, 19 etc) that may not appear as-is
        # Increase threshold to 8 to reduce false positives on date-containing outputs
        if len(unverified) > 8:
            result["verdict"] = "UNKNOWN"
            result["reason"] = f"UNVERIFIED_NUMBERS: {len(unverified)} found"
            return result

    return result


# ============ Main Entry Point ============

def run_quality_verification(node_output_text, source_evidence, node_contract):
    """Three-layer progressive verification. Cheapest first.
    
    Returns: {
        "layer": int (1/2/3),
        "verdict": "VALID" | "INVALID" | "UNKNOWN",
        "reason": str,
        "failure_type": "contract" | "quality_silent" | "semantic" | None,
        "parsed": dict (if parseable)
    }
    """
    # Layer 1
    l1 = verify_layer1(node_output_text, node_contract)
    parsed = None
    if l1["parse_ok"]:
        try:
            t = node_output_text.strip()
            m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
            if m:
                t = m.group(1).strip()
            parsed = json.loads(t)
        except:
            pass

    if l1["verdict"] == "INVALID":
        return {**l1, "parsed": parsed}

    # Layer 2 (if calc contract defined)
    if parsed and node_contract.get("calc_contract"):
        l2 = verify_layer2(parsed, source_evidence,
                           node_contract["calc_contract"])
        if l2["verdict"] != "VALID":
            return {**l2, "parsed": parsed}

    # Layer 3
    if parsed and node_contract.get("semantic_check", True):
        l3 = verify_layer3(parsed, source_evidence, node_contract)
        return {**l3, "parsed": parsed}

    return {"layer": 1, "verdict": "VALID", "reason": "",
            "failure_type": None, "parsed": parsed}
