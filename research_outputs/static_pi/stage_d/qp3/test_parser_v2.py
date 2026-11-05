"""Regression tests for parser_v2: nested string value recovery.

Covers the operator's required cases:
1. Flat facts format (existing behavior preserved)
2. Explicit value format (existing behavior preserved)
3. Nested field-string format (the fix)
4. Multi-entity, multi-period nested format
5. Empty strings, null, non-string values
6. doc/page/quote metadata exclusion
7. Same-name fields, duplicate values, field ambiguity
8. Both explicit value and nested string present
9. Missing evidence: no fabricated citations
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from qp3_primitives import normalize_stage as old_parser
from parser_v2 import normalize_stage_v2_string_values as new_parser

RES = []

def check(name, cond, detail=''):
    RES.append((name, bool(cond), str(detail)))
    print(f"  {name:55s} {'PASS' if cond else 'FAIL'} {'' if cond else detail}")

def entry_values(entries):
    return [e for e in entries if e.get('value') not in (None, '')]

def test():
    # 1. Flat facts format (backward compat)
    flat = {"facts": [
        {"field": "净利润", "value": "亏损12,500万元", "doc": "D1", "page": 1, "quote": "test"},
        {"field": "营收", "value": "24,500万元", "doc": "D2", "page": 1, "quote": "test2"}
    ]}
    old = entry_values(old_parser(flat))
    new = entry_values(new_parser(flat))
    check("1a. flat: old parser finds values", len(old) == 2)
    check("1b. flat: new parser finds values", len(new) == 2)
    check("1c. flat: new preserves doc/page/quote",
          all(e.get('doc') for e in new))

    # 2. Explicit value in nested dict
    nested_explicit = {"bucket1": {"sub1": {"value": "100万元", "doc": "D1", "page": 1, "quote": "q"}}}
    old = entry_values(old_parser(nested_explicit))
    new = entry_values(new_parser(nested_explicit))
    check("2a. nested explicit: old finds value", len(old) == 1)
    check("2b. nested explicit: new finds value", len(new) == 1)

    # 3. THE FIX: nested field-string format
    nested_string = {"欢瑞世纪2026半年度": {"归母净利润": "亏损：12,500.00 万元"}}
    old = entry_values(old_parser(nested_string))
    new = entry_values(new_parser(nested_string))
    check("3a. nested string: old MISSES value", len(old) == 0,
          f"old found {len(old)}")
    check("3b. nested string: new RECOVERS value", len(new) >= 1,
          f"new found {len(new)}")
    if new:
        check("3c. nested string: value correct",
              '12,500' in str(new[0].get('value', '')))

    # 4. Multi-entity nested format
    multi = {
        "公司A": {"罚款": "1000万元", "警告": "警告"},
        "个人B": {"罚款": "150万元"}
    }
    new = entry_values(new_parser(multi))
    check("4a. multi-entity: finds both entities' values", len(new) >= 3)
    buckets = {e.get('bucket') for e in new}
    check("4b. multi-entity: bucket preserved", '公司A' in buckets and '个人B' in buckets)

    # 5. Empty/null/non-string values excluded
    edge = {"data": {"val1": "", "val2": None, "val3": 123, "val4": "real value"}}
    new = entry_values(new_parser(edge))
    check("5a. empty string excluded", all(e['value'] != '' for e in new))
    check("5b. None excluded", all(e['value'] is not None for e in new))
    # numbers may or may not be captured, but empty/None must not be
    check("5c. at least real string captured", any('real' in str(e.get('value','')) for e in new))

    # 6. Metadata keys not treated as values
    meta = {"entry": {"doc": "D1", "page": 1, "quote": "text", "净利润": "100万"}}
    new = entry_values(new_parser(meta))
    check("6a. doc/page/quote not values",
          all(e.get('field') not in ('doc', 'page', 'quote') for e in new))
    check("6b. actual value captured",
          any('100万' in str(e.get('value','')) for e in new))

    # 7. Duplicate/same-name fields
    dup = {"a": {"x": "val1"}, "b": {"x": "val2"}}
    new = entry_values(new_parser(dup))
    check("7a. same-name fields in different buckets",
          len(new) >= 2 and len({e.get('bucket') for e in new}) >= 2)

    # 8. Explicit value takes precedence over nested string
    both = {"entry": {"value": "explicit_val", "other_key": "string_val",
                       "doc": "D1", "page": 1, "quote": "q"}}
    new = new_parser(both)
    vals = [e for e in new if e.get('value')]
    explicit_found = any(e['value'] == 'explicit_val' for e in vals)
    check("8a. explicit value preserved when both exist", explicit_found)

    # 9. No fabricated evidence
    no_ev = {"data": {"field1": "some_value"}}
    new = new_parser(no_ev)
    check("9a. no doc fabricated",
          all(e.get('doc') is None for e in new if 'doc' not in str(e.get('field'))))

    # 10. type/aspects excluded from values
    typed = {"type": "json_object", "aspect": "net_profit",
             "data": {"real": "100万"}}
    new = entry_values(new_parser(typed))
    check("10a. 'type' key not treated as value",
          all(e.get('field') != 'type' for e in new))

    passed = sum(1 for _, ok, _ in RES if ok)
    print(f"\n{passed}/{len(RES)} PASS")
    return 0 if passed == len(RES) else 1

if __name__ == '__main__':
    sys.exit(test())
