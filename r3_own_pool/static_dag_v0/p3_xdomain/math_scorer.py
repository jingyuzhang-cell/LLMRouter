"""Deterministic math answer normalizer + equivalence scorer for MATH500.

No model calls. Equivalence is decided by sympy after a LaTeX-to-sympy
normalization pass; unsupported forms fall back to canonical string equality,
then to numeric comparison. This module is frozen as the P3 math scorer
candidate; validation results are reported in P3_SCHEMA_AUDIT.json.

Policy notes (deterministic, documented):
  * bare number X is accepted for ground truth "X^\\circ" (degrees are the
    implied unit in angle-answer problems); any other mismatch stays wrong.
  * x=5 is normalized to 5 (single-variable equation answers); "expr = 0" is
    normalized to expr.
  * matrices and intervals are compared exactly; \\pm answers are compared as
    two-element branch sets; \\cup answers as interval sets.
"""
import re

import sympy as sp

_UNITS = re.compile(
    r'\b(inches|meters|metres|feet|units|degrees|centimeters|miles|hours|minutes|seconds'
    r'|people|dollars|square\s*units|cubic\s*units|points|percent)\b\s*(\^\s*\d+)?\s*$',
    re.IGNORECASE)


def _unwrap_boxed(s):
    boxes = re.findall(r'\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}', s)
    if boxes:
        return boxes[-1]
    return s


def _brace_body(s, i):
    """s[i] == '{'; return (body, index_of_closing_brace) with nesting handled."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == '{':
            depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j
    return None, None


def _skip_ws(s, j):
    while j < len(s) and s[j].isspace():
        j += 1
    return j


def _convert_fracs(s):
    out = []
    i = 0
    while i < len(s):
        m = re.match(r'\\(?:frac|dfrac|tfrac)', s[i:])
        if not m:
            out.append(s[i])
            i += 1
            continue
        j = _skip_ws(s, i + m.end())
        num = den = None
        if j < len(s) and s[j] == '{':
            num, j = _brace_body(s, j)
            if num is None:
                out.append(s[i]); i += 1; continue
            j = _skip_ws(s, j + 1)
            if j < len(s) and s[j] == '{':
                den, j = _brace_body(s, j)
                if den is not None:
                    j += 1
            elif j < len(s) and s[j].isalnum():
                den, j = s[j], j + 1
        elif j < len(s) and s[j].isalnum():
            num, j = s[j], j + 1
            j = _skip_ws(s, j)
            if j < len(s) and s[j] == '{':
                den, j = _brace_body(s, j)
                if den is not None:
                    j += 1
            elif j < len(s) and s[j].isalnum():
                den, j = s[j], j + 1
        if num is None or den is None:
            out.append(s[i])
            i += 1
            continue
        out.append(f'(({num})/({den}))')
        i = j
    return ''.join(out)


def _convert_sqrts(s):
    out = []
    i = 0
    while i < len(s):
        m = re.match(r'\\sqrt', s[i:])
        if not m:
            out.append(s[i])
            i += 1
            continue
        j = _skip_ws(s, i + m.end())
        body = None
        if j < len(s) and s[j] == '{':
            body, j = _brace_body(s, j)
            if body is not None:
                j += 1
        elif j < len(s) and s[j].isalnum():
            body, j = s[j], j + 1
        if body is None:
            out.append(s[i])
            i += 1
            continue
        out.append(f'sqrt({body})')
        i = j
    return ''.join(out)


def _convert_texts(s):
    out = []
    i = 0
    while i < len(s):
        m = re.match(r'\\(?:text|mbox)', s[i:])
        if not m:
            out.append(s[i])
            i += 1
            continue
        j = _skip_ws(s, i + m.end())
        if j < len(s) and s[j] == '{':
            body, j = _brace_body(s, j)
            if body is not None:
                out.append(body)
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return ''.join(out)


def _deg_marker(s):
    return re.sub(r'(\d+(?:\.\d+)?)\s*\^\s*\\circ', r'DEG:\1', s)


def _plain(s):
    s = s.replace('\\$', '$').replace('$', '').replace('\\,', '').replace('\\!', '').replace('\\ ', ' ')
    s = s.replace('\\left', '').replace('\\right', '').replace('\\infty', 'oo').replace('\\cup', ' U ')
    s = s.replace('∪', ' U ')
    s = _convert_texts(s)
    s = _UNITS.sub('', s).strip()
    s = _convert_fracs(s)
    s = _convert_sqrts(s)
    s = re.sub(r'(\d+)\s*\(\((\d+)\)/\((\d+)\)\)', lambda m: f'(({m.group(1)}*{m.group(3)}+{m.group(2)})/{m.group(3)})', s)
    s = re.sub(r'(\d+)_\{(\d+)\}', lambda m: str(int(m.group(1), int(m.group(2)))), s)
    s = s.replace('\\pi', 'pi').replace('\\cdot', '*').replace('\\times', '*')
    s = s.replace('\\{', '{').replace('\\}', '}')
    s = re.sub(r'(\d),(\d{3})', r'\1\2', s)
    s = re.sub(r'(\d)\s+([a-zA-Z(])', r'\1*\2', s)
    s = re.sub(r'\)\s*\(', ')*(', s)
    s = re.sub(r'(\d)\s*([a-zA-Z])', r'\1*\2', s)
    s = re.sub(r'^[a-zA-Z]\s*\\in\s*', '', s)
    m = re.match(r'^\s*([a-zA-Z])\s*=\s*(.+)\s*$', s)
    if m:
        s = m.group(2)
    m = re.match(r'^\s*(.+?)\s*=\s*0\s*$', s)
    if m:
        s = m.group(1)
    s = re.sub(r'(\d)i\b', r'\1*I', s)
    s = re.sub(r'(?<![a-zA-Z])i(?![a-zA-Z])', 'I', s)
    s = re.sub(r'\\([a-zA-Z]+)', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = _UNITS.sub('', s).strip()
    return s


def _matrix_from(s):
    m = re.search(r'\\begin\{pmatrix\}(.*?)\\end\{pmatrix\}', s, re.S)
    if not m:
        return None
    rows = []
    for row in re.split(r'\\\\', m.group(1)):
        rows.append([_plain(c) for c in row.split('&')])
    try:
        return 'MATRIX:' + str(sp.Matrix([[sp.sympify(c) for c in r] for r in rows]).tolist())
    except Exception:
        return None


def _interval_from(s):
    m = re.match(r'^\s*([\[\(])\s*(.+?)\s*,\s*(.+?)\s*([\]\)])\s*$', s)
    if not m:
        return None
    try:
        a, b = sp.sympify(_plain(m.group(2))), sp.sympify(_plain(m.group(3)))
        return str(sp.Interval(a, b, m.group(1) == '(', m.group(4) == ')'))
    except Exception:
        return None


def canonical(s):
    """LaTeX/plain answer -> canonical comparable string."""
    s = (s or '').strip()
    s = _unwrap_boxed(s)
    s = _deg_marker(s)
    if '\\pm' in s:
        parts = [canonical(p) for p in s.split('\\pm')]
        return '±'.join(sorted(parts))
    s = s.replace('\\cup', ' U ').replace('∪', ' U ')
    if ' U ' in s:
        parts = [canonical(p) for p in s.split(' U ')]
        return 'U:'.join(sorted(parts))
    mat = _matrix_from(s)
    if mat is not None:
        return mat
    s = _plain(s)
    if 'DEG:' in s or 'U:' in s:
        return s
    iv = _interval_from(s)
    if iv is not None:
        return iv
    return s


def _sym(s):
    try:
        return sp.sympify(s, evaluate=False)
    except Exception:
        return None


def equivalent(answer, gold):
    a, b = canonical(answer), canonical(gold)
    if a == b:
        return True
    if '±' in a or '±' in b:
        return set(a.split('±')) == set(b.split('±'))
    if 'U:' in a or 'U:' in b:
        return set(a.split('U:')) == set(b.split('U:'))
    m = re.match(r'^DEG:(.+)$', a or '')
    n = re.match(r'^DEG:(.+)$', b or '')
    if m and not n:
        ea = _sym(m.group(1)); eb = _sym(b)
        if ea is not None and eb is not None:
            try:
                return bool(sp.simplify(ea - eb) == 0)
            except Exception:
                pass
    if n and not m:
        ea = _sym(a); eb = _sym(n.group(1))
        if ea is not None and eb is not None:
            try:
                return bool(sp.simplify(ea - eb) == 0)
            except Exception:
                pass
    if a.startswith('MATRIX:') or b.startswith('MATRIX:') or 'DEG:' in a or 'DEG:' in b:
        return False
    ea, eb = _sym(a), _sym(b)
    if ea is not None and eb is not None:
        try:
            d = sp.simplify(ea - eb)
            if d == 0:
                return True
        except Exception:
            pass
        try:
            if isinstance(ea, (tuple, sp.Tuple)) and isinstance(eb, (tuple, sp.Tuple)) and len(ea) == len(eb):
                return all(equivalent(str(x), str(y)) for x, y in zip(ea, eb))
        except Exception:
            pass
        try:
            import math as _math
            fa, fb = complex(ea.evalf()), complex(eb.evalf())
            if (_math.isfinite(fa.real) and _math.isfinite(fb.real)
                    and abs(fa - fb) <= 1e-6 * max(1.0, abs(fa), abs(fb))):
                return True
        except Exception:
            pass
    return False


def parseable(s):
    s = canonical(s)
    if '±' in s or s.startswith('MATRIX:') or 'DEG:' in s or 'U:' in s:
        return True
    return _sym(s) is not None
