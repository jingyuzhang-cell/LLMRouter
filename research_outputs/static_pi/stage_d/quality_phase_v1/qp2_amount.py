"""QP2 amount module (zero calls): prompt contract + deterministic parser.

Design against the measured failure mode (QP1 attribution: 213/254 value errors
were amounts): unit mismatch (元/万元/亿元), thousands separators, number picking
among several figures, and amount/unit split across lines.

The prompt block requires each amount fact to carry BOTH the verbatim raw form
AND a normalized yuan value, so the scorer never has to guess a unit. The parser
is deterministic and unit-normalizing; tolerant comparison (default 0.1%) is a
preregistered, arm-uniform choice reported alongside strict equality.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

UNITS = {'元': Decimal(1), '万元': Decimal(10_000), '亿元': Decimal(100_000_000),
         '万': Decimal(10_000), '亿': Decimal(100_000_000), '%': Decimal(1)}

AMOUNT_PROMPT_BLOCK = (
    '金额专项要求（本臂强制执行）：\n'
    '1) 涉及金额/比例的事实，必须输出五个字段：field、raw（原文逐字形式，含千分位逗号与单位，'
    '如 "43,497,313.43 元" 或 "89.99 亿元"）、unit（只能是 元/万元/亿元/万/亿/%）、'
    'normalized_yuan（换算成元后的纯数字；百分比填原数值，unit 填 %）、quote（含该金额的连续逐字原文）。\n'
    '2) 一句话里有多个数字时，只取该事实对应的那个；金额与单位跨行时，quote 必须覆盖到单位所在行。\n'
    '3) normalized_yuan 由 raw 数值乘以单位换算得到，禁止四舍五入到不同数量级；'
    '原文本身有约数的，保留原精度。\n'
    '4) 输出 JSON 数组挂在 facts 条目下，逐金额一条。')


def _clean(s):
    s = unicodedata.normalize('NFKC', str(s if s is not None else ''))
    return s.replace('，', ',').replace(' ', '').replace('\u3000', '')


def parse_amount(text):
    """Parse '<number>[unit]' → (Decimal_value_in_unit, unit_str) or None.

    Returns the value in the STATED unit (not normalized to yuan); use
    to_yuan() for normalization. Percentages return the raw number with unit '%'.
    """
    t = _clean(text)
    m = re.match(r'^(?:人民币)?(-?\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|亿|万|元|%|)(?:人民币)?$', t)
    if not m:
        return None
    try:
        num = Decimal(m.group(1).replace(',', ''))
    except InvalidOperation:
        return None
    return num, (m.group(2) or '元')


def to_yuan(num, unit):
    return num * UNITS.get(unit, Decimal(1))


def is_percent(unit):
    return unit == '%'


def amount_equal(got, gold, rel_tol=Decimal('0.001'), abs_tol_yuan=Decimal('1')):
    """Unit-aware amount equality. Both sides may carry different units.
    Percentages compare numerically (unit must be % on both)."""
    a, b = parse_amount(got), parse_amount(gold)
    if not a or not b:
        return False
    if is_percent(a[1]) != is_percent(b[1]):
        return False
    if is_percent(a[1]):
        return abs(a[0] - b[0]) <= rel_tol * abs(b[0])
    ya, yb = to_yuan(a[0], a[1]), to_yuan(b[0], b[1])
    return abs(ya - yb) <= max(rel_tol * abs(yb), abs_tol_yuan)
