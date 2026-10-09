"""Isolated metering smoke. Default: read-only preflight; no model imports/startup."""
import argparse
import collections
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

ROOT = Path('/root/r3_own_pool')
PACKET = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append(path, value):
    with Path(path).open('a') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


class StopRun(BaseException):
    """Bypass transport exception handlers; always unwind GPU cleanup."""


class Budget:
    def __init__(self, directory, caps, clock=time.monotonic):
        self.path = Path(directory) / 'DISPATCH.jsonl'
        self.caps, self.clock = caps, clock
        self.start = clock()
        self.attempts = 0
        self.charged = 0
        self.actual_tokens = 0
        self.pending = {}
        # Never silently resume/reset a partially spent budget.
        if self.path.exists():
            raise ValueError('Existing dispatch ledger: explicit reconciliation required')

    def check(self):
        if self.clock() - self.start >= self.caps['wall_seconds']:
            raise StopRun('wall budget')

    def reserve(self, key):
        self.check()
        amount = self.caps['request_token_reservation']
        if self.attempts >= self.caps['new_request_attempts']:
            raise StopRun('request budget')
        if self.charged + amount > self.caps['new_total_tokens']:
            raise StopRun('token budget')
        idx = self.attempts + 1
        append(self.path, dict(event='reserved', id=idx, key=key,
                               tokens=amount, unix=time.time()))
        self.attempts = idx
        self.charged += amount
        self.pending[idx] = amount
        return idx

    def settle(self, idx, response):
        usage = response.get('usage') or {}
        tokens = usage.get('total_tokens')
        valid = (type(tokens) is int and 0 <= tokens <= self.pending[idx]
                 and type(usage.get('prompt_tokens')) is int
                 and type(usage.get('completion_tokens')) is int
                 and usage['prompt_tokens'] >= 0
                 and 0 <= usage['completion_tokens'] <= self.caps['max_output_tokens']
                 and tokens == usage['prompt_tokens'] + usage['completion_tokens'])
        append(self.path, dict(event='response', id=idx, usage_valid=valid,
                               response=response, unix=time.time()))
        if not valid:
            raise StopRun('Missing/invalid usage; full reservation retained')
        self.charged += tokens - self.pending.pop(idx)
        self.actual_tokens += tokens
        if response.get('status') != 'delivered':
            raise StopRun('Infrastructure failure (known usage charged)')
        self.check()


def make_executor_class():
    from collab_scheduler_v1.fault30_run import Executor

    class SmokeExecutor(Executor):
        def __init__(self, directory, budget, dispatch, prepare, bindings):
            # Deliberately bypass historical cache loading in Executor.__init__.
            self.directory, self.budget = Path(directory), budget
            self.dispatch, self.prepare, self.bindings = dispatch, prepare, bindings
            self.by_key, self.cache, self.faults = {}, {}, {}
            self.scope = ''
            self.counts = collections.Counter()
            self.events = []

        def begin_cell(self, state, cid):
            self.scope = state
            self.cid = cid
            self.by_key = {}
            self.counts.clear()
            self.events = []
            self.clear_faults()

        def call(self, key, model, prompt, uid=None, node=None):
            self.budget.check()
            task = key.split(':')[-1]
            self.counts[task] += 1
            if self.counts[task] > self.budget.caps['logical_calls_per_task_config_state']:
                raise StopRun('logical per-cell budget')
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            # Full serialized node input includes dependency values. Conservative
            # task/node/state scope prevents unsafe cross-state/role reuse.
            identity = (self.bindings[model], digest, task, key.split(':')[3], self.scope)
            fault = self.faults.get((uid, node, model)) if uid is not None else None
            event_id = f'{self.scope}:{self.cid}:{key}'
            if fault:
                response = dict(status='delivered', answer=fault[0],
                                usage=fault[1], latency_s=fault[2], injected_fault=True)
                rec = dict(key=key, model=model, response=response)
            elif identity in self.cache:
                source = self.cache[identity]
                rec = dict(key=key, model=model, alias_of=source['event_id'],
                           response=source['response'])
            else:
                self.prepare(model)
                idx = self.budget.reserve(event_id)
                started = time.monotonic()
                try:
                    response = self.dispatch(model, prompt)
                except BaseException as exc:
                    append(self.directory / 'ERRORS.jsonl', dict(id=idx, error=repr(exc), observed_failed_service_s=time.monotonic()-started))
                    raise
                response['latency_s'] = time.monotonic() - started
                self.budget.settle(idx, response)
                if not isinstance(response.get('answer'), str) or not response['answer']:
                    raise StopRun('Empty/malformed answer')
                rec = dict(key=key, model=model, response=response)
                self.cache[identity] = dict(event_id=event_id, response=response)
            self.by_key[key] = rec
            self.events.append(rec)
            append(self.directory / 'TRAJECTORY.jsonl', dict(event_id=event_id,
                   prompt_sha256=digest, cache_identity=identity, **rec))
            return rec
    return SmokeExecutor


def preflight():
    protocol = json.loads((PACKET / 'SMOKE_PROTOCOL.json').read_text())
    manifest = json.loads((PACKET / 'TASK_MANIFEST.json').read_text())
    for path, expected in protocol['code_sha256'].items():
        if sha(ROOT / path) != expected:
            raise ValueError('Code binding changed: ' + path)
    if sha(manifest['source']) != manifest['source_sha256']:
        raise ValueError('Task source changed')
    tasks = json.loads(Path(manifest['source']).read_text())['tasks']
    task_map = {t['uid']: t for t in tasks}
    selected = [task_map[u] for u in manifest['task_uids']]
    if len(selected) != 8 or len(set(manifest['task_uids'])) != 8:
        raise ValueError('Expected eight distinct tasks')
    return protocol, selected


def execute(protocol, tasks, run_id):
    from collab_scheduler_v1 import fault30_protocol as fp, fault30_run as fr
    from static_dag_v0 import run as engine
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in run_id):
        raise ValueError('Unsafe run id')
    directory = PACKET / 'runs' / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('SMOKE_PROTOCOL.json', 'TASK_MANIFEST.json'):
        (directory / name).write_bytes((PACKET / name).read_bytes())
    budget = Budget(directory, protocol['proposed_hard_budget'])
    engine.OUT = directory
    state = dict(proc=None, log=None, model=None)
    bindings = {}
    for model in ('medium', 'large', 'coder'):
        provenance = ROOT / 'router_v2/label_repair_experiment/raw' / f'{model}_MODEL_PROVENANCE.json'
        bindings[model] = sha(provenance) + ':' + sha(ROOT / 'static_dag_v0/run.py')
    append(directory / 'BINDINGS.jsonl', bindings)

    def prepare(model):
        if state['model'] != model:
            started = time.monotonic()
            if state['proc'] is not None:
                engine.stop_model(state['proc'], state['log'])
                state.update(proc=None, log=None, model=None)
            budget.check()
            proc, log, _ = engine.start_model(model)
            state.update(proc=proc, log=log, model=model)
            append(directory / 'MODEL_SWITCH.jsonl', dict(model=model,
                   wall_s=time.monotonic() - started))
            budget.check()

    ex = make_executor_class()(directory, budget, engine.call_model, prepare, bindings)
    status, reason, completed = 'INCOMPLETE', 'interrupted', 0
    lock = None
    previous = signal.getsignal(signal.SIGALRM)
    def deadline(*_):
        raise StopRun('wall deadline')
    try:
        lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, max(.001, budget.caps['wall_seconds'] - (time.monotonic() - budget.start)))
        led = fp.Ledger()  # prompt builders only; its historical answers never seed cache
        pools = json.loads((fp.BENCH / 'FAULT_POOLS.json').read_text())
        for panel in protocol['states']:
            faults = fp.build_faults(panel.get('seed', 20260923), panel['rate'], tasks, pools)
            append(directory / 'FAULT_DRAWS.jsonl', dict(state=panel['name'], faults=faults))
            for cid in protocol['configs']:
                ex.begin_cell(panel['name'], cid)
                _, _, _, nodes = fp.planned_models(cid)
                for uid, (node, failing) in faults.items():
                    ex.set_fault(uid, node, nodes[node], failing, dict(total_tokens=0), 0)
                started = time.monotonic()
                rows = fr.eval_config(cid, ex, led, tasks, faults, {t['uid']: t for t in tasks})
                accounting = fr.physical_accounting(ex.events)
                for field in ('logical_calls', 'cache_hits', 'injected_calls', 'new_requests', 'new_tokens', 'new_latency_s'):
                    if not math.isclose(sum(r[field] for r in rows.values()), accounting[field], abs_tol=1e-8):
                        raise StopRun('Row/event accounting mismatch: ' + field)
                budget.check()
                append(directory / 'COMPLETED_PANELS.jsonl', dict(state=panel['name'], cid=cid,
                       rows=rows, observed_panel_wall_s=time.monotonic()-started))
                completed += len(rows)
        status, reason = 'COMPLETE', 'all 64 diagnostic cells completed'
    except BaseException as exc:
        reason = repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        try:
            if state['proc'] is not None:
                engine.stop_model(state['proc'], state['log'])
        finally:
            if lock is not None:
                lock.close()
            append(directory / 'STATUS.jsonl', dict(status=status, reason=reason,
                   completed_cells=completed, attempts=budget.attempts,
                   charged_tokens_including_reservations=budget.charged,
                   known_actual_tokens=budget.actual_tokens, pending=budget.pending,
                   observed_wall_s=time.monotonic()-budget.start,
                   note='Wall deadline interrupts work; server cleanup may extend elapsed wall. No automatic resume.'))
    print(json.dumps(dict(status=status, reason=reason, output=str(directory))))
    return 0 if status == 'COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--approved-protocol-sha256')
    args = parser.parse_args()
    protocol, tasks = preflight()
    if not args.execute:
        print(json.dumps(dict(status='PREFLIGHT_PASS', tasks=len(tasks), cells=64,
            protocol_sha256=sha(PACKET / 'SMOKE_PROTOCOL.json'), model_calls=0,
            budget=protocol['proposed_hard_budget']), ensure_ascii=False))
        return 0
    if os.environ.get('JOINT_SMOKE_EXECUTE') != '1' or args.approved_protocol_sha256 != sha(PACKET / 'SMOKE_PROTOCOL.json'):
        parser.error('Requires explicit approval, JOINT_SMOKE_EXECUTE=1 and exact approved protocol hash')
    return execute(protocol, tasks, args.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
