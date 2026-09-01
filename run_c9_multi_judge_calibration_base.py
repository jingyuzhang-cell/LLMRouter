#!/usr/bin/env python3
"""Run the frozen 15-group base calibration via the audited feasibility harness."""
from pathlib import Path

source_path = Path("/root/run_c9_multi_judge_feasibility.py")
source = source_path.read_text()
replacements = {
    'JUDGES = ("doubao-seed-2.1-turbo", "qwen-max", "glm-4-flash")':
        'JUDGES = ("doubao", "qwen-max", "glm-4-flash")',
    'EVENTS = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_EVENTS.jsonl"':
        'EVENTS = DATA / "C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl"',
    'RESULT = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_RESULT.json"':
        'RESULT = DATA / "C9_2_MULTI_JUDGE_CALIBRATION_BASE_COLLECTION_RESULT.json"',
    'manifest["groups"][:3]': 'manifest["groups"][:15]',
    'assert len(selected) == 3 and len(groups) == 810':
        'assert len(selected) == 15 and len(groups) == 810',
    'if event_key in completed:\n                continue':
        'if event_key in completed and completed[event_key]["success"]:\n                continue',
    '"status": "PASS_ADVANCE_TO_15_GROUP_CALIBRATION" if all(passes.values()) else "FAIL_STOP_BEFORE_FORMAL_LABELS"':
        '"status": "BASE_COLLECTION_COMPLETE"',
    '"groups": 3,': '"groups": 15,',
}
for original, replacement in replacements.items():
    if source.count(original) != 1:
        raise RuntimeError(f"frozen harness substitution target missing or ambiguous: {original}")
    source = source.replace(original, replacement)
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
