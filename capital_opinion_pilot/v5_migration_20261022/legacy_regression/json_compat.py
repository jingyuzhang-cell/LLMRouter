"""Layered JSON contract parsing (protocol fix, 2026-10-14, zero-pay).

Problem (F7 round): models emit RAW control characters (newlines) inside JSON
string values; strict json.loads correctly rejects them, but the content is
otherwise well-formed. Truncation-induced incompleteness must NOT be repaired.

Layers — each recorded SEPARATELY, never conflated:
  L0 strict      : json.loads(fenced(text)) with default strict=True.
  L1 control-char: same extraction, json.loads(..., strict=False) — accepts raw
                   control chars inside strings. Provable-safe: it changes NO
                   field values or structure, only tolerates formatting bytes
                   that JSON forbids in strings.
  L2 (reserved)  : NO further repair. Unescaped inner quotes, truncation, missing
                   brackets are all left as failures — repairing those can change
                   string boundaries or invent structure (not provably safe).

Raw responses are never modified. Callers must report strict_ok and
compat_ok independently; a compat pass is NEVER presented as a strict
contract pass.
"""
import json
import re


def _fenced_slice(text):
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
    if m:
        t = m.group(1).strip()
    i = min([j for j in (t.find('['), t.find('{')) if j >= 0], default=-1)
    if i > 0:
        t = t[i:]
    return t


def parse_layers(text):
    """Returns {strict_ok, compat_ok, value, compat_layer, error}.

    value is the parsed object at the highest layer that succeeded
    (L1 preferred when both pass — they are equal objects when both pass).
    """
    t = _fenced_slice(text)
    out = {'strict_ok': False, 'compat_ok': False, 'value': None, 'error': None}
    try:
        out['value'] = json.loads(t)  # L0: strict JSON
        out['strict_ok'] = True
        out['compat_ok'] = True
        out['compat_layer'] = 'L0_strict'
        return out
    except json.JSONDecodeError as e0:
        try:
            out['value'] = json.loads(t, strict=False)  # L1: control chars only
            out['compat_ok'] = True
            out['compat_layer'] = 'L1_control_char'
            out['error'] = f'L0: {e0}'
            return out
        except json.JSONDecodeError as e1:
            out['error'] = f'L0: {e0} | L1: {e1}'
            return out


def node_contract(node, parse_result, key_map=None, min_report_chars=100):
    """Apply the node contract on top of layered parsing.

    Returns (strict_contract_ok, compat_contract_ok, value, note):
      strict_contract_ok = L0 passed AND required key/type checks hold on L0.
      compat_contract_ok = strict OR (L1 passed AND same checks hold on L1).
      L2/truncation failures keep both False.
    """
    key_map = key_map or {'t1': 'facts', 't2': 'facts', 't3': 'timeline',
                          't4': 'entity_facts', 't5': 'verdicts', 't6': 'report'}
    key = key_map[node]
    v = parse_result['value']
    if v is None:
        return False, False, None, parse_result['error']
    if not isinstance(v, dict) or key not in v:
        return False, False, None, f'missing key {key}'
    val = v[key]
    if node == 't6':
        ok = isinstance(val, str) and len(val) > min_report_chars
    else:
        ok = isinstance(val, list) and len(val) > 0
    if not ok:
        return False, False, None, f'bad type/len for {key}'
    strict_ok = parse_result['strict_ok'] and ok
    compat_ok = ok  # value came from the highest passing layer
    return strict_ok, compat_ok, val, parse_result.get('compat_layer')
