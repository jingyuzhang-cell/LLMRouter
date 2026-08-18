#!/usr/bin/env python3
"""Show exact progress for the resumable Fin-RoME-300 response matrix."""
import json
from collections import Counter
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data/finance_router/finrome_300/responses.jsonl"
latest = {}
raw = 0
if path.exists():
    for line in path.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw += 1
        latest[(row.get("task_id"), row.get("model"), row.get("repeat"))] = row
successful = {key: row for key, row in latest.items() if row.get("success")}
failed = len(latest) - len(successful)
per_task = Counter(key[0] for key in successful)
per_model = Counter(key[1] for key in successful)
complete_tasks = sum(count == 12 for count in per_task.values())
print(f"成功作业: {len(successful)}/3600 ({len(successful)/36:.2f}%)")
print(f"待补成功作业: {3600-len(successful)}")
print(f"当前最新失败: {failed}")
print(f"完整任务: {complete_tasks}/300 ({complete_tasks/3:.2f}%)")
print(f"原始检查点行数: {raw}")
for model in ("deepseek-chat", "qwen-plus", "qwen-turbo", "glm-5.2"):
    print(f"  {model}: {per_model[model]}/900")
