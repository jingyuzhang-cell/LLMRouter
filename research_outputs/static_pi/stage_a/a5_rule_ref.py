#!/usr/bin/env python3
"""A5 语义归一规则 v1.0 的参考实现（零调用；不是新规则版本）。

依据：/root/q_foundation/A5_SEMANTIC_RULE_V1.md（sha e25d9bf2…，12/12）
定位：独立辅助指标；不进入旧合同/V3/评分器，不回写 SINK 输出，不改证据引用。

K1 身份 / K2 显式否定职务 / K3 同句且范围一致（不做指代消解；子公司/分公司
不算“公司”）/ K4 无肯定职务表述 / K5 由 K2 保证。
"""
import re

CANON = "均无职务(仅实际控制人)"
_SCOPE_BAD = re.compile(r"(子公司|分公司|下属公司|控股子公司|参股公司)")
_K4_BAD = re.compile(r"(兼任|担任(?!.*任何职务)|出任|董事|监事|总经理|高管)")
_K2 = re.compile(r"未.{0,12}担任(任何)?职务")


def map_a5(value):
    if not isinstance(value, str) or "实际控制人" not in value:
        return False
    if _K4_BAD.search(value):
        return False
    for sent in re.split(r"[。！？；]", value):
        if "实际控制人" not in sent or not _K2.search(sent):
            continue
        if _SCOPE_BAD.search(sent):
            continue
        return True
    return False


def canonical(value):
    return CANON if map_a5(value) else None


POS = ["均为实际控制人，未在公司担任任何职务",
       "实际控制人（除为公司实际控制人外，未在公司担任任何职务）",
       "实际控制人，且未在公司担任任何职务",
       "两家公司均称其为实际控制人，其未在公司担任任何职务"]
NEG = ["实际控制人", "实际控制人，兼任公司董事", "未在公司担任任何职务",
       "实际控制人，未在子公司担任职务", "实际控制人。公司其他人员未担任职务"]
AMB = ["实际控制人。其未在公司担任任何职务",
       "经核查，未发现其担任职务的记载", "实际控制人，据了解未任职"]


def self_test():
    ok = 0
    for v in POS:
        ok += map_a5(v)
    neg_ok = sum(not map_a5(v) for v in NEG)
    amb_ok = sum(not map_a5(v) for v in AMB)
    print(f"positives {ok}/{len(POS)}; negatives rejected {neg_ok}/{len(NEG)}; "
          f"ambiguous rejected {amb_ok}/{len(AMB)}")
    assert ok == 4 and neg_ok == 5 and amb_ok == 3
    print("12/12 PASS")


if __name__ == "__main__":
    self_test()
