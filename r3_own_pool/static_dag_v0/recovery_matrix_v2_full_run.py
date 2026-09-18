"""Full 148-node recovery actions. Frozen method code imported unchanged from commit 4983983.
Action-level checkpoint: each finished action is appended and fsynced immediately; resume skips
completed (node_id, action) pairs. Interrupted actions replay cached responses deterministically."""
import fcntl
import json
import os
import time
from . import core, run as engine
from .recovery_matrix_v2_snapshot import digest
from .recovery_matrix_v2_pilot import ACTIONS, execute_action
from .recovery_matrix_v2_full_prep import OUT

def run():
    snaps = [json.loads(p.read_text()) for p in sorted((OUT / 'runtime').glob('*.json'))]
    assert len(snaps) == 148 and all(s['valid'] for s in snaps)
    engine.OUT = OUT
    results_path = OUT / 'FULL_ACTION_RESULTS.jsonl'
    done = set()
    if results_path.exists():
        for l in results_path.read_text().splitlines():
            r = json.loads(l); done.add((r['node_id'], r['action']))
    cache = {}
    if (OUT / 'RESPONSES.jsonl').exists():
        for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); cache[r['key']] = r['response']
    def append(path, obj):
        with path.open('a') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
    proc = log = None; current = None; completed = len(done)
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Same model batching as the passed pilot: medium group first, then large.
            for action_group in [['no_recovery', 'retry_same', 'evidence_retrieval', 'local_decompose'], ['switch_model']]:
                for snap in snaps:
                    for action in action_group:
                        if (snap['node_id'], action) in done: continue
                        def call(model, prompt, stage, sh):
                            nonlocal proc, log, current
                            key = digest([snap['node_id'], action, stage, sh, model, prompt])
                            if key in cache: return cache[key]
                            if model != current:
                                if proc is not None: engine.stop_model(proc, log); proc = log = None
                                proc, log, _ = engine.start_model(model); current = model
                            append(OUT / 'REQUESTS.jsonl', dict(key=key, node_id=snap['node_id'], action=action, stage=stage, model=model, snapshot_hash=sh, prompt=prompt))
                            r = engine.call_model(model, prompt)
                            append(OUT / 'RESPONSES.jsonl', dict(key=key, node_id=snap['node_id'], action=action, stage=stage, model=model, response=r)); cache[key] = r
                            if r.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
                            return r
                        rec = execute_action(snap, action, call)
                        append(results_path, dict(node_id=snap['node_id'], **rec))
                        done.add((snap['node_id'], action)); completed += 1
                        core.write(OUT / 'STATUS.json', dict(phase='FULL_RUNNING', completed_actions=completed, total_actions=740, calls=len(cache), node_id=snap['node_id'], action=action))
                        print(json.dumps(dict(node_id=snap['node_id'], action=action, completed=completed, calls=len(cache))), flush=True)
        finally:
            if proc is not None: engine.stop_model(proc, log)
    core.write(OUT / 'FULL_ACTIONS_DONE.json', dict(nodes=148, actions=len(done), calls=len(cache), unix_time=time.time()))
    core.write(OUT / 'STATUS.json', dict(phase='FULL_ACTIONS_COMPLETE_PENDING_AUDIT', nodes=148, calls=len(cache)))

if __name__ == '__main__':
    run()
