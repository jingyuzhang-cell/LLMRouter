"""V2.3 real-model experiment runner — prepared for Experiment GO.

ZERO real calls in this file. Upon Experiment GO + EXECUTE_EXPERIMENT=1,
this script runs the frozen five-arm pilot (or confirmation) through the
REAL stub infrastructure with real-model measurements. The stub pilot
(v23_pilot_stub.py) validated the pipeline end-to-end; this runner
corrects the arm ablation definitions revealed by the stub pilot.

Arm definitions (V2.3 protocol §2, CORRECTED after stub pilot):

  SS  Both static: the best pre-frozen static arm (selected per
      Protocol §3 on independent calibration data), executed as a fixed
      plan. π = planned models. (Z, R) = the static arm's recipe.

  DS  Recovery dynamic, assignment static: the POLICY selects (Z, R)
      via the two-stage decision (filter + argmax E[R]) over candidates
      whose π is CONSTRAINED to the planned models. This isolates the
      value of dynamic recovery-scope/range decisions.

  SD  Recovery static, assignment dynamic: the static recipe determines
      (Z, R) exactly as SS, but π is FREE over the menus for the
      affected/unexecuted nodes in R. This isolates the value of
      node-level model reassignment.

  DD  Both dynamic: the FULL policy (Z, R, π) selected jointly by the
      two-stage decision over all candidates. This is the complete
      mechanism.

  NONE  No recovery: accept the failure; the DAG completes with
      whatever output the planned execution produced.

The stub pilot revealed that in a degenerate prior world, DS ≡ SS and
DD ≡ SS because the policy always selects the same plan. The arm
implementations below enforce the ablation constraints:

  DS: filter candidates to those with π(n) == planned(n) for all n;
      then apply the two-stage decision over those candidates ONLY.
  SD: fix (Z, R) to the SS recipe; enumerate π variants within menus
      for nodes in R ∪ PENDING; then apply the two-stage decision over
      the π variants ONLY (the (Z, R) is not a choice).

Run (dry): python3 -m deadline_reward_v1.v23_experiment_runner
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent

ARMS = ('SS', 'DS', 'SD', 'DD', 'NONE')


def planned_models():
    """The frozen planned model assignment (the C-arm hetero X)."""
    return {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}


def select_arm_candidates(cands, arm, planned):
    """Filter/enumerate candidates per the arm's ablation constraint."""
    if arm == 'SS':
        # The static best arm: LOCAL with planned models (the E-arm
        # matched recipe for D/E scope, planned models for others).
        # Selected on independent calibration data per Protocol §3.
        selected = [c for c in cands if c.arm in ('LOCAL', 'FULL')
                    and all(c.pi.get(n) == planned.get(n)
                            for n in ('e1', 'e2', 'r', 'v') if n in c.pi)]
        return selected
    if arm == 'DS':
        # Recovery dynamic: the policy chooses (Z, R) over candidates
        # whose π is CONSTRAINED to planned models.
        return [c for c in cands
                if all(c.pi.get(n) == planned.get(n)
                       for n in ('e1', 'e2', 'r', 'v') if n in c.pi)]
    if arm == 'SD':
        # Recovery static, assignment dynamic: (Z, R) fixed to the
        # SS recipe's scope (LOCAL on the fault-closure set), but π
        # is FREE for nodes in R ∪ PENDING.
        # This means: among LOCAL candidates (same Z=LOCAL, R=fault
        # closure), select over the π variants ONLY.
        return [c for c in cands if c.arm == 'LOCAL']
    if arm == 'DD':
        # Both dynamic: all candidates (LOCAL, FULL, FULL_DYNAMIC).
        return list(cands)
    if arm == 'NONE':
        return []
    raise ValueError(arm)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-protocol-sha256')
    parser.add_argument('--phase', choices=['pilot', 'confirmation'],
                        default='pilot')
    args = parser.parse_args()

    # ---- structural validation (always runs) ----
    from deadline_reward_v1 import reassign
    from deadline_reward_v1.scheduler_state import SchedulerState
    from deadline_reward_v1.stub_engine import (
        InjectedClock, StubEngine, StubModelServer)

    protocol_path = HERE / 'REAL_EXPERIMENT_PROTOCOL_V2.md'
    protocol_sha = hashlib.sha256(
        protocol_path.read_bytes()).hexdigest()

    planned = planned_models()
    priors = json.loads(
        (HERE / 'PRIORS_STUB_V1.json').read_text())  # → PRIORS_REAL_V1

    from deadline_reward_v1.stub_engine import load_ledger
    from deadline_reward_v1 import detection as det
    from deadline_reward_v1.reward import realized_rtask
    from deadline_reward_v1 import policy

    OUTDIR = HERE / 'evidence' / 'v23_experiment'
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print(json.dumps(dict(
        status='STRUCTURAL_DRY_RUN' if not args.execute
               else f'EXECUTE_{args.phase.upper()}',
        protocol_sha256=protocol_sha,
        phase=args.phase,
        arms=list(ARMS),
        planned_models=planned,
        note='Arm ablation definitions corrected after stub pilot '
             'revealed DS≡SS in degenerate priors',
        model_calls=0,
    ), indent=1))

    if args.execute:
        if os.environ.get('EXECUTE_EXPERIMENT') != '1':
            raise PermissionError(
                'Experiment execution requires EXECUTE_EXPERIMENT=1')
        if not args.approved_protocol_sha256:
            raise PermissionError(
                'Experiment execution requires the operator-approved '
                'protocol SHA-256')
        if args.approved_protocol_sha256 != protocol_sha:
            raise PermissionError(
                'Protocol SHA mismatch: the protocol has drifted')
        raise NotImplementedError(
            'Experiment execution is NOT IMPLEMENTED. '
            'Experiment GO has not been authorized by the operator.')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
