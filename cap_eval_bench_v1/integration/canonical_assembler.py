"""Canonical deliverable assembler — IDENTICAL terminal-deliverable conditions for
every arm (single_model / fixed_graph / auto_graph / optimized_graph / alloc_* /
dyn_*). Phase-1 fairness post-mortem: the single-model arm emitted prose only and
was mechanically down-scored on K.schema_conformance while DAG arms assembled
structured fields; this module removes that asymmetry.

Rules (frozen):
 1. The arm's final-synthesis call MUST receive the task deliverable_schema and
    emit JSON keyed by schema field names (fair-prompt clause, PHASE2_PROTOCOL).
 2. This assembler only VALIDATES and NORMALIZES the arm's own output: fields
    present are copied verbatim (stringified); missing fields become ''.
 3. It NEVER reads silver/gold/branch references (Silver-blind by construction;
    the isolation gate additionally scans its outputs) and NEVER rewrites,
    completes, or augments facts.
 4. Identical behaviour for every arm: output depends only on (task, raw_output).
"""
import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent


def load_task(task_id):
    for l in (BENCH / 'tasks' / 'tasks_frozen.jsonl').read_text().splitlines():
        t = json.loads(l)
        if t['task_id'] == task_id:
            return t
    raise KeyError(task_id)


def assemble(task, raw_output):
    fields = [f['field'] for f in task['deliverable_schema']]
    if isinstance(raw_output, str):
        try:
            raw = json.loads(raw_output.strip().removeprefix('```json').removeprefix('```')
                             .removesuffix('```').strip())
        except Exception:
            raw = {'report': raw_output}
    else:
        raw = raw_output
    if not isinstance(raw, dict):
        raw = {'report': json.dumps(raw, ensure_ascii=False)}
    deliverable = {'task_id': task['task_id']}
    for f in fields:
        v = raw.get(f, '')
        deliverable[f] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    marks = raw.get('unknown_marks', [])
    deliverable['unknown_marks'] = [str(m) for m in marks] if isinstance(marks, list) else []
    deliverable['_assembly'] = {'assembler': 'canonical_v1', 'arm_agnostic': True,
                                'silver_blind': True, 'fields_filled_by_arm': sorted(
                                    [f for f in fields if deliverable[f] != ''])}
    return deliverable


FAIR_PROMPT_CLAUSE = (
    '\n【终端交付合同（与所有对照臂完全一致）】最终输出必须是一个JSON对象，键名恰为：'
    '{fields}；各字段值为字符串（时间线/结构化内容可为JSON字符串）；另有 unknown_marks 数组，'
    '对任务声明的不可确认边界逐项给出标注文本。不得输出JSON以外的内容。')


def fair_final_prompt_suffix(task_id):
    task = load_task(task_id)
    return FAIR_PROMPT_CLAUSE.format(
        fields=', '.join(f['field'] for f in task['deliverable_schema']))


# ---------------- uniform contract normalizer (L1 fix; applies to ALL arms/nodes) ----------------
def normalize_contract_output(txt, required_ports):
    """Deterministic, Silver-blind, arm-agnostic contract normalization.

    Returns (port_subset_dict, meta) where meta records the normalization applied:
      - extra_keys_dropped: model added informative keys beyond the contract
        (kept OUT of the output; logged for transparency, never scored as content)
      - salvaged_syntax: minor JSON syntax slip repaired by trimming to the last
        balanced object/array
    Raises ValueError when any required port is missing after normalization.
    """
    import json as _json
    import re as _re

    def parse(t):
        s = t.strip()
        m = _re.search(r'```(?:json)?\s*(.+?)```', s, _re.S)
        if m:
            s = m.group(1).strip()
        start = min([i for i in (s.find('['), s.find('{')) if i >= 0], default=-1)
        if start > 0:
            s = s[start:]
        return _json.loads(s)

    meta = {'extra_keys_dropped': [], 'salvaged_syntax': False}
    try:
        obj = parse(txt)
    except Exception:
        # balanced-brace salvage: trim trailing malformed tail
        s = txt.strip()
        m = _re.search(r'```(?:json)?\s*(.+?)```', s, _re.S)
        if m:
            s = m.group(1).strip()
        start = min([i for i in (s.find('['), s.find('{')) if i >= 0], default=-1)
        if start < 0:
            raise ValueError('no JSON object found')
        best = None
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(s[start:], start):
            if esc:
                esc = False
                continue
            if ch == '\\':
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in '{[':
                depth += 1
            elif ch in '}]':
                depth -= 1
                if depth == 0:
                    best = i + 1
        if best is None:
            raise ValueError('unbalanced JSON')
        obj = _json.loads(s[start:best])
        meta['salvaged_syntax'] = True
    if not isinstance(obj, dict):
        raise ValueError(f'top-level {type(obj).__name__}, need object')
    missing = [p for p in required_ports if p not in obj]
    if missing:
        raise ValueError(f'missing required ports: {missing}')
    meta['extra_keys_dropped'] = sorted(set(obj) - set(required_ports))
    # PRINCIPLE (advisor ruling): stripping non-contract keys must NEVER erase
    # model-declared uncertainty. Salvage uncertainty-bearing strings from the
    # dropped keys so the runner can carry them to the final synthesis node.
    import re as _re2
    _unc = _re2.compile(r'UNRESOLVED|无法确认|未能确认|未确认|证据不足|无证据|不确定|缺失|UNKNOWN', _re2.I)
    carried = []
    for k in meta['extra_keys_dropped']:
        v = obj[k]
        txt = v if isinstance(v, str) else _json.dumps(v, ensure_ascii=False)
        if _unc.search(txt):
            carried.append(f"{k}:{txt[:60]}")
        if len(carried) >= 3:
            break
    meta['uncertainty_carried'] = carried
    return {p: obj[p] for p in required_ports}, meta
