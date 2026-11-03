"""auth_gate — mandatory structured-authorization gate for ALL real
model-call entrypoints (operator directive 2026-10-29: bare '授权'
must never again suffice; the execution ENTRY enforces the scope).

An authorization is valid only if a record in AUTHORIZATIONS.json
contains ALL of: batch_name, max_calls, max_tokens, models, tasks,
issued_by='operator', created (timestamp), and the entrypoint's
batch_name matches. Caps in code become the MIN(code, record).
Writing a record requires an operator ruling that itself states the
full scope — the assistant may transcribe it verbatim, never invent.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
AUTH_FILE = HERE / 'AUTHORIZATIONS.json'

REQUIRED = ('batch_name', 'max_calls', 'max_tokens', 'models',
            'tasks', 'issued_by', 'created')


def _load():
    if not AUTH_FILE.exists():
        return {}
    return json.loads(AUTH_FILE.read_text())


def transcribe(record: dict) -> dict:
    """Transcribe an operator ruling's full scope verbatim into the
    registry. Only callable with the ruling's own fields; asserts
    completeness. The assistant never fills missing numbers."""
    missing = [k for k in REQUIRED if k not in record]
    if missing:
        raise ValueError(f'authorization incomplete, missing {missing}; '
                         'refuse to transcribe (operator must state all)')
    if record['issued_by'] != 'operator':
        raise ValueError("issued_by must be 'operator'")
    all_ = _load()
    all_[record['batch_name']] = record
    AUTH_FILE.write_text(json.dumps(all_, ensure_ascii=False, indent=1))
    return record


def require(batch_name: str) -> dict:
    """Entrypoint gate: returns the record or raises with the exact
    missing items. A bare '授权' without a transcribed record can
    never pass this."""
    all_ = _load()
    rec = all_.get(batch_name)
    if rec is None:
        raise PermissionError(
            f'NO VALID AUTHORIZATION for batch "{batch_name}". '
            f'Known: {sorted(all_) or "(none)"}. An operator ruling '
            f'must state batch_name/max_calls/max_tokens/models/tasks '
            f'and be transcribed into {AUTH_FILE.name} before launch.')
    missing = [k for k in REQUIRED if k not in rec]
    if missing:
        raise PermissionError(f'authorization record incomplete: '
                              f'{missing}')
    return rec


def effective_caps(batch_name: str, code_calls: int,
                   code_tokens: int) -> dict:
    rec = require(batch_name)
    return dict(batch_name=batch_name,
                max_calls=min(code_calls, int(rec['max_calls'])),
                max_tokens=min(code_tokens, int(rec['max_tokens'])),
                models=list(rec['models']), tasks=list(rec['tasks']))


if __name__ == '__main__':
    # self-test: gate refuses without record
    try:
        require('nonexistent_batch')
        print('FAIL: gate did not refuse')
    except PermissionError as e:
        print('gate self-test PASS:', str(e)[:80])
