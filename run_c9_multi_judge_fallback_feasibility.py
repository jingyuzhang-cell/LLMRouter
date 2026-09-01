#!/usr/bin/env python3
"""Re-run the frozen feasibility harness with the configured Doubao fallback."""
from pathlib import Path

source_path = Path("/root/run_c9_multi_judge_feasibility.py")
source = source_path.read_text()
replacements = {
    'JUDGES = ("doubao-seed-2.1-turbo", "qwen-max", "glm-4-flash")':
        'JUDGES = ("doubao", "qwen-max", "glm-4-flash")',
    'EVENTS = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_EVENTS.jsonl"':
        'EVENTS = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_EVENTS_DOUBAO_FALLBACK.jsonl"',
    'RESULT = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_RESULT.json"':
        'RESULT = DATA / "C9_2_MULTI_JUDGE_FEASIBILITY_RESULT_DOUBAO_FALLBACK.json"',
}
for original, replacement in replacements.items():
    if source.count(original) != 1:
        raise RuntimeError(f"frozen harness substitution target missing or ambiguous: {original}")
    source = source.replace(original, replacement)
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
