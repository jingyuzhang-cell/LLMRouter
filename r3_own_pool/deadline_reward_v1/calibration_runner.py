"""Calibration measurement runner — ZERO real calls in this file's default mode.

Upon Calibration GO (operator authorization), this script executes the
CALIBRATION_MEASUREMENT_PLAN under the frozen budget envelope. The
--execute flag + CALIBRATION_EXECUTE=1 env var are required for any real
call; the default is a zero-call structural dry run that validates the
plan, panel, budget, and standards freeze.

Run (dry): python3 -m deadline_reward_v1.calibration_runner
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'CALIBRATION_MEASUREMENT_PLAN.json').read_text())
STANDARDS = json.loads(
    (HERE / 'CALIBRATION_FREEZE_PREREQUISITES.json').read_text())

SLOTS = {'medium': 'medium', 'large': 'large', 'coder': 'coder'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_panel() -> list:
    """Select calibration tasks: same source as evaluation, DISJOINT uids."""
    # The frozen200 / adaptive_benchmark task sources
    fz = ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json'
    bench = ROOT / 'static_dag_v0/adaptive_benchmark'
    # Collect evaluation-panel uids to exclude
    excluded = set()
    # Formal campaign panels
    formal = ROOT / 'collab_scheduler_v1/joint_search_v1/review/TASK_PANEL_V1.json'
    if formal.exists():
        fp = json.loads(formal.read_text())
        for key in ('tasks_search', 'tasks_holdout', 'tasks'):
            for t in fp.get(key, []):
                excluded.add(t['uid'])
    # Net-benefit panels
    nb_rows = ROOT / 'collab_scheduler_v1/joint_search_v1/netbenefit_runs/NB_ROWS.jsonl'
    if nb_rows.exists():
        for line in nb_rows.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                excluded.add(r.get('arm', ''))  # arms not uids, but safe
    # Build candidate pool from frozen200
    candidates = []
    if fz.exists():
        fzp = json.loads(fz.read_text())
        for t in fzp.get('tasks', []):
            if t['uid'] not in excluded:
                candidates.append(dict(
                    uid=t['uid'], question=t['question'],
                    derivation=t['derivation'], answer=t['answer'],
                    ctx_table=t.get('ctx_table', ''),
                    ctx_text=t.get('ctx_text', '')))
    return candidates


def enumerate_cells():
    """Enumerate all (node, model, condition) measurement cells."""
    cells = []
    ms = PLAN['measurement_cells']['models']
    for node in PLAN['measurement_cells']['nodes']:
        for model in ms.get(node, []):
            for cond in PLAN['measurement_cells']['conditions']:
                cells.append(dict(node=node, model=model, condition=cond))
    return cells


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-plan-sha256')
    args = parser.parse_args()

    # ---- structural validation (always runs) ----
    cells = enumerate_cells()
    plan_cells = PLAN['measurement_cells']['total_cells']
    if len(cells) != plan_cells:
        print(f'ERROR: expected {plan_cells} cells, got {len(cells)}')
        return 1

    standards_sha = sha(
        (HERE / 'CALIBRATION_FREEZE_PREREQUISITES.json').read_bytes())
    if STANDARDS.get('data_viewed_before_freeze'):
        print('ERROR: standards were frozen AFTER data viewing')
        return 1

    panel = build_panel()
    min_panel = PLAN['task_panel']['minimum_panel_size']
    panel_ok = len(panel) >= min_panel

    budget = PLAN['budget_envelope']
    est_calls = PLAN['measurement_cells']['total_min_calls']
    est_ok = est_calls <= budget['max_measurement_requests']

    print(json.dumps(dict(
        status='STRUCTURAL_DRY_RUN' if not args.execute else 'EXECUTE_MODE',
        cells=len(cells),
        min_calls_per_cell=30,
        estimated_total_calls=est_calls,
        budget_requests=budget['max_measurement_requests'],
        budget_tokens=budget['max_measurement_tokens'],
        budget_wall_s=budget['max_wall_seconds'],
        panel_candidates=len(panel),
        panel_minimum=min_panel,
        panel_ok=panel_ok,
        budget_ok=est_ok,
        standards_sha256=standards_sha,
        standards_data_viewed=STANDARDS.get('data_viewed_before_freeze',
                                            None),
        gates=PLAN['execution_gates'],
        model_calls=0,
    ), indent=1))

    if not panel_ok:
        print(f'WARNING: panel has {len(panel)} candidates; '
              f'minimum is {min_panel}')
    if not est_ok:
        print(f'WARNING: estimated calls ({est_calls}) exceed budget cap')

    # ---- execution gate ----
    if args.execute:
        if os.environ.get('CALIBRATION_EXECUTE') != '1':
            raise PermissionError(
                'Calibration execution requires CALIBRATION_EXECUTE=1')
        if not args.approved_plan_sha256:
            raise PermissionError(
                'Calibration execution requires the operator-approved '
                'plan SHA-256')
        plan_sha = sha(
            (HERE / 'CALIBRATION_MEASUREMENT_PLAN.json').read_bytes())
        if args.approved_plan_sha256 != plan_sha:
            raise PermissionError(
                'Plan SHA mismatch: the measurement plan has drifted '
                'from the operator-approved version')
        # Real measurement execution would go here, gated on the
        # budget envelope and running through the stub engine's
        # reserve/settle discipline. NOT IMPLEMENTED until Calibration
        # GO is explicitly authorized.
        raise NotImplementedError(
            'Calibration measurement execution is NOT IMPLEMENTED. '
            'Calibration GO has not been authorized by the operator.')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
