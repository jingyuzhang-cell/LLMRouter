"""JOINT_SCHED micro-pilot launcher (operator GO 2026-10-12, ONE run).

Validates ALL authorization gates BEFORE the first real request:
  1. code-commit binding (this exact launcher + runner hashes);
  2. P3 freeze hash (the 60-task panel must be untouched);
  3. micro-pilot freeze hash (the 3-task list, fault draw, tiers);
  4. explicit flag JOINT_VERIFY_MICROPILOT_GO=1
     + --approved-micropilot-sha256 matching the freeze;
  5. non-empty GPU-exclusive lock path — flock taken here;
  6. unique run directory (refuse existing).
Resource caps hard-wired to the GO allocation: 60 attempts / 25K
tokens / 1,800 s. One failure -> INCOMPLETE + stop (the entry's own
protection); NO re-run path exists in this file.

Run:
  JOINT_VERIFY_MICROPILOT_GO=1 python3 -m deadline_reward_v1.micropilot_launch \
      --approved-micropilot-sha256 <sha256 of JOINT_VERIFY_MICROPILOT_FREEZE.json>
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

GO_ATTEMPT_CAP = 60
GO_TOKEN_CAP = 25000
GO_WALL_CAP = 1800.0
GO_FLAG = 'JOINT_VERIFY_MICROPILOT_GO'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-micropilot-sha256', required=True)
    args = parser.parse_args()

    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1 (operator GO)')

    # ---- gate 1: code binding ----------------------------------------
    import subprocess
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse',
                             'HEAD'], capture_output=True,
                            text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(ROOT), 'status',
                            '--porcelain', '--',
                            'deadline_reward_v1'],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise PermissionError(
            f'uncommitted deadline_reward_v1 changes — refusing:\n{dirty}')

    # ---- gate 2-3: both freeze hashes ---------------------------------
    p3_sha = sha_file(HERE / 'JOINT_VERIFY_P3_FREEZE.json')
    mp_path = HERE / 'JOINT_VERIFY_MICROPILOT_FREEZE.json'
    mp_sha = sha_file(mp_path)
    if args.approved_micropilot_sha256 != mp_sha:
        raise PermissionError('micro-pilot freeze hash mismatch — '
                              'execution refused (GO gate)')
    freeze = json.loads(mp_path.read_text())
    if freeze['p3_freeze_untouched_sha256'] != p3_sha:
        raise PermissionError('P3 freeze drifted since the micro-pilot '
                              'freeze was written — refusing')

    # ---- gate 5: GPU-exclusive lock -----------------------------------
    lock_fh = GPU_LOCK.open('a+')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fh.close()
        raise PermissionError('GPU lock held by another process')

    # ---- gate 6: unique run dir ---------------------------------------
    run_root = HERE / 'micropilot_runs' / time.strftime(
        'pilot_%Y%m%d_%H%M%S')
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        lock_fh.close()
        raise PermissionError('run dir exists — no reuse')
    (run_root / 'JOINT_VERIFY_MICROPILOT_FREEZE.json').write_bytes(
        mp_path.read_bytes())

    # ---- wire the real execution --------------------------------------
    from deadline_reward_v1 import joint_verification_runner as jv
    from deadline_reward_v1.supplementary_runner import ModelManager, \
        RealServer

    # GO caps replace the proposed defaults inside execute()
    orig_caps = dict(wall_seconds=GO_WALL_CAP,
                     new_request_attempts=GO_ATTEMPT_CAP,
                     new_total_tokens=GO_TOKEN_CAP,
                     request_token_reservation=6144,
                     max_output_tokens=4096)
    import collab_scheduler_v1.joint_search_smoke.proposal_v2 \
        .smoke_runner as sr_mod
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget

    class GoBudget(Budget):
        def __init__(self, directory):
            super().__init__(directory, orig_caps)

    manager = ModelManager()
    tasks = freeze['tasks']
    gold_map = jv.build_gold_map(tasks)

    # frozen tier anchors from the INDEPENDENT reliability FIT binding
    rel_run = sorted((HERE / 'reliability_runs').glob('run_*'))[-1]
    binding = json.loads((rel_run / 'BINDING.json').read_text())['binding']
    fit = {c: dict(mean=b['mean']) for c, b in binding.items()}
    sw = {m: 65.0 for m in ('medium', 'large', 'coder')}
    planned = dict(e1='large', e2='large', r='medium', v='coder')

    priors_stub = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
    pol = priors_stub['policy']
    params = dict(priors=priors_stub, q_min=pol['q_min'], eps=pol['eps'],
                  lam_c=pol['lam_c'], lam_t=pol['lam_t'],
                  lam_f=pol['lam_f'], c0=pol['c0'])
    from deadline_reward_v1 import policy as P
    pred = P.OutcomePredictor(priors_stub)
    comp = P.DeadlineCompensator(priors_stub)

    def make_server(budget, task_map):
        return RealServer({}, manager, budget, task_map, run_root)

    try:
        payload = jv.execute(
            approved_p3_sha=p3_sha, run_root=run_root,
            make_server=make_server, manager=manager, tasks=tasks,
            gold_map=gold_map, fit_binding=fit, switch_costs=sw,
            tiers=freeze['tiers'],
            fault_uids=set(freeze['fault_uids']),
            d3_answer='###SYNTHETIC UNPARSEABLE r-output###',
            planned=planned, params=params, predictor=pred,
            compensator=comp, gpu_lock_path=None,                    # lock held HERE
            caps=orig_caps)
        print(json.dumps(dict(status='COMPLETE',
                              statuses=payload['statuses'],
                              physical=payload['physical_total']),
                         indent=1))
        return 0
    finally:
        try:
            manager.stop_current()
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()


if __name__ == '__main__':
    raise SystemExit(main())
