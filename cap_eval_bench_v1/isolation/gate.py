"""Isolation gate: verify that NOTHING PRIVATE leaks into system-facing inputs.

PRIVATE = silver quotes/answers/questions (scoring/silver/*), branch descriptors and
any tasks_private content. The gate scans given files/directories (prompts, configs,
public bench surfaces) for normalised substrings of every private element.

Usage:
  python3 isolation/gate.py check <paths...>      # exit 0 = clean, 2 = leak
  python3 isolation/gate.py selftest             # public bench surfaces must be clean
"""
import json
import re
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from bench_common import norm  # noqa: E402

MIN_LEN = 12          # skip trivially short strings (would false-positive)
IGNORE_FILES = {'retrieval_log.jsonl', 'gate_selftest.json'}


def private_elements():
    els = []
    for p in sorted((BENCH / 'scoring' / 'silver').glob('T-*.silver.json')):
        d = json.loads(p.read_text())
        els.append((f'{p.name}:branch_descriptor', json.dumps(d['branch_descriptor'], ensure_ascii=False)))
        for f in d['silver']:
            els.append((f"{p.name}:{f['fact_id']}:quote", f['quote']))
            els.append((f"{p.name}:{f['fact_id']}:answer", f['answer']))
            els.append((f"{p.name}:{f['fact_id']}:question", f['question']))
    for line in (BENCH / 'tasks' / 'tasks_private.jsonl').read_text().splitlines():
        d = json.loads(line)
        els.append((f"tasks_private:{d['task_id']}:branches", json.dumps(d['branch_descriptor'], ensure_ascii=False)))
    return [(k, v) for k, v in els if len(norm(v)) >= MIN_LEN]


def iter_files(paths):
    for p in map(Path, paths):
        if p.is_file() and p.name not in IGNORE_FILES:
            yield p
        elif p.is_dir():
            for q in sorted(p.rglob('*')):
                if q.is_file() and q.name not in IGNORE_FILES and 'scoring' not in str(q.relative_to(BENCH)) \
                        and 'tasks_private' not in q.name:
                    yield q


def check(paths):
    leaks = []
    priv = private_elements()
    for f in iter_files(paths):
        try:
            content = norm(f.read_text(errors='ignore'))
        except Exception:
            continue
        for key, val in priv:
            nv = norm(val)
            if len(nv) >= MIN_LEN and nv in content:
                leaks.append({'file': str(f), 'private_key': key, 'snippet': val[:50]})
                if len(leaks) > 20:
                    return leaks
    return leaks


def selftest():
    """Public surfaces (tasks, evidence texts are BY DESIGN the sanctioned inputs;
    texts may legitimately contain quote substrings — they are the SOURCE documents,
    so only tasks/public/scoring-interface surfaces are checked here)."""
    leaks = check([BENCH / 'tasks' / 'tasks_frozen.jsonl', BENCH / 'PROTOCOL_EVAL_V1.md',
                   BENCH / 'INTEGRATION_CONTRACT.md', BENCH / 'evidence' / 'retrieval_api.py'])
    report = {'checked_public_surfaces': ['tasks/tasks_frozen.jsonl', 'PROTOCOL_EVAL_V1.md',
                                          'INTEGRATION_CONTRACT.md', 'evidence/retrieval_api.py'],
              'private_elements': len(private_elements()), 'leaks': leaks,
              'note': 'evidence texts are the sanctioned SOURCE and are intentionally not gated; '
                      'silver QUESTION/ANSWER/QUOTE strings and branch descriptors must never appear '
                      'in prompts, planner inputs, selector configs or controller state'}
    (BENCH / 'isolation' / 'gate_selftest.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return leaks


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        l = selftest()
        print(json.dumps({'selftest': 'CLEAN' if not l else 'LEAK', 'n_leaks': len(l)}, ensure_ascii=False))
        sys.exit(0 if not l else 2)
    l = check(sys.argv[2:]) if len(sys.argv) > 2 else []
    print(json.dumps({'check': 'CLEAN' if not l else 'LEAK', 'leaks': l[:10]}, ensure_ascii=False))
    sys.exit(0 if not l else 2)
