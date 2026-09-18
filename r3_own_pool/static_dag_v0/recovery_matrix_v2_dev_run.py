"""Dev replan pilot runner: 40 frozen dev failure nodes x 5 actions
(retry_same, switch_model, evidence_retrieval, local_decompose, local_replan).
Frozen action code reused unchanged; local_replan is the new dev arm.
Action-level checkpoint: append+fsync per finished action; resume skips (node_id, action)."""
import fcntl
import json
import os
import time
from . import core, run as engine
from .recovery_matrix_v2_pilot import ACTIONS, execute_action
from .recovery_matrix_v2_replan import execute_replan
from .recovery_matrix_v2_snapshot import digest
from .recovery_matrix_v2_devset import DEV

DEV_ACTIONS = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose', 'local_replan']

def run():
    snaps = [json.loads(p.read_text()) for p in sorted((DEV / 'runtime').glob('*.json'))]
    assert len(snaps) == 40 and all(s['valid'] for s in snaps)
    engine.OUT = DEV
    results_path = DEV / 'ACTION_RESULTS.jsonl'
    done = set()
    if results_path.exists():
        for l in results_path.read_text().splitlines():
            r = json.loads(l); done.add((r['node_id'], r['action']))
    cache = {}
    if (DEV / 'RESPONSES.jsonl').exists():
        for l in (DEV / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); cache[r['key']] = r['response']
    def append(path, obj):
        with path.open('a') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
    proc = log = None; current = None; completed = len(done)
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for action_group in [['retry_same', 'evidence_retrieval', 'local_decompose', 'local_replan'], ['switch_model']]:
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
                            append(DEV / 'REQUESTS.jsonl', dict(key=key, node_id=snap['node_id'], action=action, stage=stage, model=model, snapshot_hash=sh, prompt=prompt))
                            r = engine.call_model(model, prompt)
                            append(DEV / 'RESPONSES.jsonl', dict(key=key, node_id=snap['node_id'], action=action, stage=stage, model=model, response=r)); cache[key] = r
                            if r.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
                            return r
                        rec = execute_action(snap, action, call) if action != 'local_replan' else execute_replan(snap, call)
                        append(results_path, dict(node_id=snap['node_id'], **rec))
                        done.add((snap['node_id'], action)); completed += 1
                        core.write(DEV / 'STATUS.json', dict(phase='DEV_RUNNING', completed_actions=completed, total_actions=200, calls=len(cache), node_id=snap['node_id'], action=action))
                        print(json.dumps(dict(node_id=snap['node_id'], action=action, completed=completed, calls=len(cache))), flush=True)
        finally:
            if proc is not None: engine.stop_model(proc, log)
    core.write(DEV / 'ACTIONS_DONE.json', dict(nodes=40, actions=len(done), calls=len(cache), unix_time=time.time()))
    core.write(DEV / 'STATUS.json', dict(phase='DEV_ACTIONS_COMPLETE', nodes=40, calls=len(cache)))

if __name__ == '__main__':
    run()
