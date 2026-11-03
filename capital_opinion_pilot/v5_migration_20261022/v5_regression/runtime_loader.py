"""Runtime loader whitelist: planner/retriever/scheduler/executor may ONLY read
task.md and evidence_index.json from an event directory. Any gold/ access raises."""
from pathlib import Path

ALLOWED = ('task.md', 'evidence_index.json')

def load_runtime_input(event_dir, name):
    if name not in ALLOWED:
        raise PermissionError(f'runtime components may not read {name}')
    p = Path(event_dir) / name
    if not p.exists():
        raise FileNotFoundError(name)
    return p.read_text()
