"""Detection-predicate mirrors for M2 (deadline_reward_v1) — stdlib only.

Mirrors EXACTLY the audited production predicates (AUDIT II §2), for the
subset that can fire during planned-only execution (M2 scope — no recovery
stages yet): D1 (e-node empty facts), D3 (r unparseable/unevaluable),
D5 (v missing or v-vs-r mismatch), D6 (task-level terminal failure).
D2/D4 (changed-output families) are recovery-cascade triggers and cannot
fire before recovery exists (M4); their enum slots are reserved.

Production semantics are mirrored, never imported (L5 import rule); parity
against the production functions (fault30_protocol.Ledger.parse_facts_safe,
static_dag_v0.multidag_dynamic.value_of/json_value/close) is asserted by
the test suite on a probe grid. Any divergence is a bug, not a tuning knob.
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

D1 = 'D1_e_empty'          # e-node: facts list empty / unparseable
D3 = 'D3_r_unparseable'    # r-node: expression missing / unparseable / unevaluable
D5 = 'D5_v_fail'           # v-node: value missing/unparseable or v != r value
D6 = 'D6_task_fail'        # task-level terminal failure over final outputs


def _decode(text) -> str:
    """Mirror of tool_aware_v1.decode (2026-10-11 parity fix): strip a
    leading ``` fence line and a trailing ``` marker, then trim. Unfenced
    text passes through unchanged. Real model answers are fenced; the
    original mirror's bare json.loads misfired D1/D3/D5 on all of them."""
    text = (text or '').strip()
    if text.startswith('```'):
        parts = text.split('\n', 1)
        if len(parts) == 2:
            text = parts[1].rsplit('```', 1)[0].strip()
    return text


def parse_facts(answer: str) -> List[dict]:
    """Mirror of the D1 predicate input: the facts list, [] on any failure.
    Facts VALIDATION stays looser than production (no 1..12 length /
    finite-value / evidence checks) — documented divergence biased toward
    under-detecting D1; empirically counted in the supplementary preflight."""
    try:
        obj = json.loads(_decode(answer))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(obj, dict):
        return []
    facts = obj.get('facts')
    return facts if isinstance(facts, list) else []


def facts_empty(answer: str) -> bool:
    return not parse_facts(answer)


def _evaluate(expression: str, facts: List[dict]) -> Tuple[Optional[float],
                                                           bool]:
    """Evaluate an r-expression against positional fact values, mirroring
    production exec_calc EXACTLY (2026-10-11 parity fix): AST whitelist of
    + - * / with rational constants, unary +/-, and vN fact references;
    exact Fraction arithmetic, float() at the end; anything outside the
    whitelist (functions, names, comparisons) is an error. The earlier
    split-on-'+' mirror misfired D3 on naturally-occurring legitimate
    expressions ('v1 - v0', '(v0 + v1) / 2') — observed in the real
    trajectory records. NOTE the convention difference: production exec_calc
    receives merged facts as {'facts': [...]}; this mirror's public
    value_of keeps the M2 list convention and wraps here."""
    import ast
    import operator
    import re as _re
    from fractions import Fraction

    funcs = {ast.Add: operator.add, ast.Sub: operator.sub,
             ast.Mult: operator.mul, ast.Div: operator.truediv}
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError):
        return None, True

    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return Fraction(str(n.value))
        if isinstance(n, ast.Name) and _re.fullmatch(r'v[0-9]+', n.id):
            idx = int(n.id[1:])
            if idx >= len(facts):
                raise ValueError('fact index out of range')
            f = facts[idx]
            v = f.get('value') if isinstance(f, dict) else None
            # exactly production: Fraction(str(v)) — numeric strings also
            # evaluate; non-numeric values raise -> error
            return Fraction(str(v))
        if isinstance(n, ast.UnaryOp) and isinstance(
                n.op, (ast.USub, ast.UAdd)):
            return walk(n.operand) * (-1 if isinstance(n.op, ast.USub)
                                      else 1)
        if isinstance(n, ast.BinOp) and type(n.op) in funcs:
            return funcs[type(n.op)](walk(n.left), walk(n.right))
        raise ValueError('not allowed')

    try:
        return float(walk(tree)), False
    except Exception:
        return None, True


def value_of(expression_answer: str, facts: List[dict]) -> Tuple[
        Optional[float], bool]:
    """Mirror of value_of(r_answer, merged_facts) error semantics. The M2
    convention passes the merged facts LIST (production wraps them in a
    dict); fence-aware decode included in the 2026-10-11 parity fix."""
    try:
        obj = json.loads(_decode(expression_answer))
    except (json.JSONDecodeError, TypeError):
        return None, True
    if not isinstance(obj, dict) or not isinstance(obj.get('expression'),
                                                   str):
        return None, True
    return _evaluate(obj['expression'], facts)


def json_value(answer: str) -> Optional[float]:
    """Mirror of json_value(v_answer) (multidag_dynamic.py): strict loads
    FIRST, then the decode (fence-stripping) fallback — the production dual
    path, mirrored 2026-10-11. float() coercion — numeric strings and
    booleans convert; anything else falls to None."""
    try:
        return float(json.loads(answer)['value'])
    except Exception:
        try:
            return float(json.loads(_decode(answer))['value'])
        except Exception:
            return None


def close(a: Optional[float], b: float) -> bool:
    """Mirror of production close() (multidag_dynamic.py:66-67): requires a
    non-None and tolerates max(1e-4, 1e-4·|b|)."""
    return a is not None and abs(float(a) - float(b)) <= max(
        1e-4, 1e-4 * abs(float(b)))


def detect_e(answer: str) -> bool:
    """D1."""
    return facts_empty(answer)


def detect_r(r_answer: str, facts: List[dict]) -> bool:
    """D3."""
    _, err = value_of(r_answer, facts)
    return err


def detect_v(v_answer: str, r_answer: str, facts: List[dict]) -> bool:
    """D5: v missing/unparseable, or disagrees with the r value. When r
    itself errored (D3 territory) the comparison is skipped — mirroring
    production V3 (fault30_run.py:403-409)."""
    vv = json_value(v_answer)
    if vv is None:
        return True
    rv, rerr = value_of(r_answer, facts)
    if rerr:
        return False
    return not close(vv, rv)


def detect_task(facts_e1: List[dict], facts_e2: List[dict],
                r_answer: str, v_answer: str) -> bool:
    """D6 mirror of evaluator.detected_failure (evaluator.py:74-84):
    observable outputs only — no gold, no fault registry."""
    if not facts_e1 or not facts_e2:
        return True
    vv = json_value(v_answer)
    if vv is None:
        return True
    rv, rerr = value_of(r_answer, merged_facts(facts_e1, facts_e2))
    if rerr:
        return True
    return not close(vv, rv)


def merged_facts(f1: List[dict], f2: List[dict]) -> List[dict]:
    return list(f1) + list(f2)
