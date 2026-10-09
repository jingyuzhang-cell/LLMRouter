"""Continuation of FULL_VALIDATION_PROTOCOL_V2 minimum-completion scope.

fullval_authorized_1h_01 exhausted its 30-request envelope after 11/16 cells
(t1, t2 complete; t3 S1+S4+S2; t4 NOTHING). The v2 protocol's must-complete
scope (S1+S4 for all 4 tasks) is therefore not yet met. This module runs ONLY
task 09aaae63 (t4) under a tight continuation envelope authorized by the user's
instruction to continue the experiments (2026-10-09).

Same discipline as fullval_runner.py: manifest-frozen, hash-bound, no retry or
resume, GPU-locked, global budget, S4 provenance and S3 traversal checks.
L-scale is NOT re-frozen (first-S1-only rule; run 01 already recorded it).
"""
import argparse
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
import signal

from .evaluator import JointEvaluator, MeteredExecutor, NODES
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    Budget, StopRun, append)

ROOT = Path('/root/r3_own_pool')
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'FULLVAL_CONTINUATION_1.json'
RUN01 = HERE / 'fullval_runs/fullval_authorized_1h_01/STATUS.jsonl'
UID = '09aaae63-03dd-4173-ba29-1a4a60946982'
X = ('large', 'large', 'medium', 'coder')
FAULT = '###SYNTHETIC UNPARSEABLE r-output [directed syntax corruption]###'
SCENES = ('S1', 'S4', 'S2', 'S3')  # S1+S4 must, S2 should, S3 optional


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def task():
    from static_dag_v0.multidag_dynamic import hybrid_pool, ctx_table, ctx_text
    t = dict(next(t for t in hybrid_pool() if t['uid'] == UID))
    t['ctx_table'] = ctx_table(t['para'])
    t['ctx_text'] = ctx_text(t['para'])
    return t


def freeze():
    if MANIFEST.exists():
        raise FileExistsError('Manifest exists; no silent rebinding')
    paths = [Path(__file__), HERE / 'evaluator.py',
             ROOT / 'collab_scheduler_v1/fault30_run.py',
             ROOT / 'collab_scheduler_v1/fault30_protocol.py',
             ROOT / 'static_dag_v0/run.py',
             ROOT / 'static_dag_v0/multidag_dynamic.py',
             ROOT / 'static_dag_v0/tool_aware_v1.py',
             ROOT / 'collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py',
             RUN01]
    models = {}
    for slot in ('medium', 'large', 'coder'):
        provenance = ROOT / 'router_v2/label_repair_experiment/raw' / f'{slot}_MODEL_PROVENANCE.json'
        paths.append(provenance)
        models[slot] = sha(provenance)
    m = dict(
        version='fullval_continuation_1_v1',
        authorization='User: 你做完之后继续接着做实验就行 (2026-10-09); completes the '
                      'v2 minimum scope left unmet by fullval_authorized_1h_01 '
                      '(request budget 30/30 after 11/16 cells; t4 unexecuted)',
        prior_run=dict(status=json.loads(RUN01.read_text().splitlines()[-1])['status'],
                       requests_consumed=30, tokens_consumed=11713, cells=11),
        caps=dict(new_request_attempts=15, new_total_tokens=12000, wall_seconds=1500,
                  request_token_reservation=8192, max_output_tokens=512,
                  logical_calls_per_task_config_state=12, automatic_retries=0),
        tasks=[task()], bindings={str(p): sha(p) for p in paths}, models=models,
        scope='t4 only; S1+S4 must complete, S2 should, S3 optional; fresh '
              'validation-local cache (no reuse from run 01); corruption never cached; '
              'L-scale NOT re-frozen (first-S1-only rule honored from run 01)',
        limits='Calibration/mechanism only; no algorithm or quality claim')
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(manifest=str(MANIFEST), sha256=sha(MANIFEST), model_calls=0)))


class ValidationExecutor(MeteredExecutor):
    def begin_cell(self, state, cid):
        super().begin_cell('fullval_cont1', self.scenario + ':' + cid)


def run(m, directory, backend):
    from collab_scheduler_v1.fault30_protocol import Ledger
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    append(directory / 'MANIFEST.jsonl', m)
    budget = Budget(directory, m['caps'])
    start = time.monotonic()
    proc = log = None
    current = None
    lock = None
    old_out = backend.OUT
    backend.OUT = directory
    status = 'VALIDATION_INCOMPLETE'
    reason = 'interrupted'
    completed = []
    full_completed = []
    previous = {s: signal.getsignal(s) for s in (signal.SIGALRM, signal.SIGTERM)}

    def deadline(*_):
        raise StopRun('wall deadline or termination')

    try:
        lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for s in previous:
            signal.signal(s, deadline)
        signal.setitimer(signal.ITIMER_REAL, m['caps']['wall_seconds'])

        def prepare(model):
            nonlocal proc, log, current
            budget.check()
            if model == current:
                return
            began = time.monotonic()
            if proc is not None:
                backend.stop_model(proc, log)
                proc = log = None
                current = None
            proc, log, _ = backend.start_model(model)
            current = model
            append(directory / 'MODEL_SWITCH.jsonl',
                   dict(model=model, wall_s=time.monotonic() - began))
            budget.check()

        ex = ValidationExecutor(directory, budget, backend.call_model, prepare, m['models'])
        led = Ledger()
        t = m['tasks'][0]
        for scene in SCENES:
            budget.check()
            ex.scenario = scene
            z = {'S1': 'NONE', 'S4': 'NONE', 'S2': 'LOCAL', 'S3': 'FULL'}[scene]
            cid = '__'.join((*X, z))
            fault = {} if scene in ('S1', 'S4') else {t['uid']: ('r', FAULT)}
            before = budget.attempts
            evaluator = JointEvaluator(ex, led, [t])
            result = evaluator.evaluate(cid, 'clean' if not fault else 'fault30', fault)
            if scene == 'S4':
                if budget.attempts != before or len(ex.events) != 4 or not all(
                        e.get('alias_of') and ':S1:' in e['alias_of'] for e in ex.events):
                    raise StopRun('S4 provenance/new-request mismatch')
            if scene == 'S3':
                replay = [e for e in ex.workflow if ':replay:' in e['key']]
                if len(replay) != 4 or {e['key'].split(':')[3] for e in replay} != set(NODES) \
                        or len(ex.workflow) != 8:
                    raise StopRun('FULL four-node traversal incomplete')
                full_completed.append(t['uid'])
            append(directory / 'SCENARIOS.jsonl',
                   dict(scenario=scene, uid=t['uid'], result=result,
                        injected_logical_calls=sum(bool(e['response'].get('injected_fault'))
                                                   for e in ex.workflow),
                        replay_nodes=[e['key'] for e in ex.workflow if ':replay:' in e['key']]))
            completed.append([scene, t['uid']])
        status = 'COMPLETE'
        reason = 'all four t4 scenario cells completed'
    except BaseException as exc:
        reason = repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for s, h in previous.items():
            signal.signal(s, h)
        try:
            if proc is not None:
                backend.stop_model(proc, log)
        except BaseException as exc:
            status = 'VALIDATION_INCOMPLETE'
            reason += '; cleanup failure ' + repr(exc)
        finally:
            backend.OUT = old_out
            if lock is not None:
                lock.close()
            report = dict(status=status, reason=reason,
                          full_status='FULL_PATH_VERIFIED' if full_completed else 'FULL_UNVERIFIED',
                          completed=completed, requests=budget.attempts,
                          tokens_known=budget.actual_tokens,
                          tokens_charged_with_pending=budget.charged,
                          pending=budget.pending,
                          observed_wall_s=time.monotonic() - start,
                          note='Continuation of run 01 minimum scope; no retry')
            append(directory / 'STATUS.jsonl', report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--freeze', action='store_true')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--manifest-sha256')
    p.add_argument('--run-id', default='fullval_cont1_01')
    a = p.parse_args()
    if a.freeze:
        freeze()
        return
    m = json.loads(MANIFEST.read_text())
    for path, digest in m['bindings'].items():
        if sha(path) != digest:
            raise ValueError('Binding mismatch ' + path)
    if canonical([task()]) != canonical(m['tasks']):
        raise ValueError('Task content mismatch')
    if not a.execute:
        print(json.dumps(dict(status='PREFLIGHT_PASS', manifest_sha256=sha(MANIFEST),
                              caps=m['caps'], model_calls=0)))
        return
    if os.environ.get('FULLVAL_CONT_EXECUTE') != '1' or a.manifest_sha256 != sha(MANIFEST):
        raise PermissionError('Approved manifest hash and environment required')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.run_id):
        raise ValueError('Unsafe run id')
    from static_dag_v0 import run as engine
    report = run(m, HERE / 'fullval_runs' / a.run_id, engine)
    raise SystemExit(0 if report['status'] == 'COMPLETE' else 2)


if __name__ == '__main__':
    main()
