"""JOINT_SCHED confirmatory launcher (60-task P3 panel; execution
requires the operator's explicit written GO — see
JOINT_VERIFY_CONFIRMATORY_READINESS.md §4).

Gate pattern mirrors micropilot_launch.py; adds a --rehearse mode that
runs EVERY gate and stops before any model server start (zero calls):

  1. JOINT_VERIFY_CONFIRMATORY_GO=1 + --approved-p3-sha256 (the P3
     freeze hash) + --approved-caps-sha256 (the approved caps text);
  2. code-cleanliness binding (no uncommitted deadline_reward_v1
     changes);
  3. P3 freeze integrity (hash + deterministic panel re-derivation);
  4. GPU-exclusive flock (non-blocking);
  5. unique run directory;
  6. confirmatory caps fixed to the approved values — hard refusals on
     mismatch, no overrides.

Real run (only after the written GO):
  JOINT_VERIFY_CONFIRMATORY_GO=1 python3 -m \
      deadline_reward_v1.confirmatory_launch \
      --approved-p3-sha256 <sha> --approved-caps-sha256 <sha>
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

GO_FLAG = 'JOINT_VERIFY_CONFIRMATORY_GO'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
# Confirmed with the readiness package §3 (PROPOSAL until the operator
# approves; the caps-sha gate binds the run to the APPROVED text):
CONFIRMATORY_CAPS = dict(wall_seconds=11000.0, new_request_attempts=800,
                         new_total_tokens=300000,
                         request_token_reservation=6144,
                         max_output_tokens=4096)
CAPS_TEXT = ('800 requests / 300000 tokens / 11000 s '
             '(JOINT_VERIFY_CONFIRMATORY_READINESS.md §3)')


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _gates(args):
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1 (operator GO)')
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse',
                             'HEAD'], capture_output=True,
                            text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(ROOT), 'status',
                            '--porcelain', '--',
                            'deadline_reward_v1'],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise PermissionError(f'uncommitted changes — refusing:\n{dirty}')
    p3_path = HERE / 'JOINT_VERIFY_P3_FREEZE.json'
    p3_sha = sha_file(p3_path)
    if args.approved_p3_sha256 != p3_sha:
        raise PermissionError('P3 freeze hash mismatch')
    if args.approved_caps_sha256 != hashlib.sha256(
            CAPS_TEXT.encode()).hexdigest():
        raise PermissionError('caps approval hash mismatch — the '
                              'approved allocation text differs')
    # panel re-derivation (deterministic seeds)
    from deadline_reward_v1.joint_verification_runner import build_p3_panel
    freeze = json.loads(p3_path.read_text())
    rebuilt = build_p3_panel()
    if (rebuilt['uids'] != freeze['uids']
            or rebuilt['fault_uids'] != freeze['fault_uids']):
        raise PermissionError('P3 panel re-derivation mismatch')
    return commit, p3_sha, freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-p3-sha256', required=True)
    parser.add_argument('--approved-caps-sha256', required=True)
    parser.add_argument('--rehearse', action='store_true',
                        help='run every gate, print REHEARSAL_PASS, '
                             'stop BEFORE any server/model call')
    args = parser.parse_args()

    commit, p3_sha, freeze = _gates(args)
    lock_fh = GPU_LOCK.open('a+')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fh.close()
        raise PermissionError('GPU lock held by another process')

    if args.rehearse:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()
        print(json.dumps(dict(status='REHEARSAL_PASS', model_calls=0,
                              git_commit=commit, p3_sha256=p3_sha,
                              n_tasks=freeze['n_tasks'],
                              n_faults=len(freeze['fault_uids']),
                              caps=CONFIRMATORY_CAPS)))
        return 0

    run_root = HERE / 'confirmatory_runs' / time.strftime(
        'conf_%Y%m%d_%H%M%S')
    if run_root.exists():
        lock_fh.close()
        raise PermissionError('run dir exists — no reuse')

    from deadline_reward_v1 import joint_verification_runner as jv
    from deadline_reward_v1.supplementary_runner import ModelManager, \
        RealServer
    from deadline_reward_v1 import policy as P

    manager = ModelManager()
    tasks = freeze['tasks']
    gold_map = jv.build_gold_map(tasks)
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

    def make_server(budget, task_map):
        return RealServer({}, manager, budget, task_map, run_root)

    try:
        payload = jv.execute(
            approved_p3_sha=p3_sha, run_root=run_root,
            make_server=make_server, manager=manager, tasks=tasks,
            gold_map=gold_map, fit_binding=fit, switch_costs=sw,
            tiers=freeze['tiers'],
            fault_uids=set(freeze['fault_uids']),
            d3_answer=freeze['fault_answer'], planned=planned,
            params=params, predictor=P.OutcomePredictor(priors_stub),
            compensator=P.DeadlineCompensator(priors_stub),
            gpu_lock_path=None, caps=CONFIRMATORY_CAPS)
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
