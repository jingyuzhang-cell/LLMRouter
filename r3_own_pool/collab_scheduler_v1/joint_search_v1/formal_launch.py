"""Formal search campaign launcher (envelope B, stage 2).

Launches the 18-session formal search (6 methods x 3 seeds) through the
production runtime (run_session + CampaignQuota, crash-safe) with the six
cross-state selectors from track_b.py (official BoTorch qNEHVI, full-identity
cache predictor) on the frozen SEARCH8 panel.

Admission gates (require_admission):
  selector_review_pass            — six selectors + cross-state loop 15/15 + BoTorch alignment 7/7
  independent_splits_verified     — TASK_PANEL_V1 frozen, zero-exposure verified
  new_semantics_real_validation_pass — FULL/fault billing stage-1 COMPLETE (FULLVAL_STAGE1_REPORT)
  runtime_tests_pass              — test_runtime 10/10
  execution_authorized            — User: 你做完之后继续接着做实验就行 (2026-10-09)

Stage-1 measurements the staged plan required: mechanisms verified (S4 cache
reuse 0-new-requests x4/4, injection/replay billing, recovery restores Q);
real Q low but variable. Launched under frozen SEARCH_BUDGET_V1 ceilings; caps
are ceilings, not completion guarantees; incomplete sessions reported as-is.
"""
import argparse
import hashlib
import json
import random
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'
PROTOCOL = JS / 'SEARCH_BUDGET_V1.json'
PANEL = JS / 'review/TASK_PANEL_V1.json'
LAUNCH = JS / 'FORMAL_LAUNCH_V1.json'
ADMISSION = JS / 'FORMAL_ADMISSION_V1.json'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'

FAULT_SEED = 20261009
CORRUPT = {
    'e1': '{"facts": []}',
    'e2': '{"facts": []}',
    'r': '###SYNTHETIC UNPARSEABLE r-output [directed syntax corruption]###',
    'v': '{"value": null}',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def frozen_inputs():
    return [JS / 'evaluator.py', JS / 'runtime.py',
            ROOT / 'collab_scheduler_v1/fault30_run.py',
            ROOT / 'collab_scheduler_v1/fault30_protocol.py',
            ROOT / 'static_dag_v0/run.py',
            ROOT / 'static_dag_v0/multidag_dynamic.py',
            ROOT / 'static_dag_v0/tool_aware_v1.py',
            ROOT / 'collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py',
            JS / 'review/track_a.py', JS / 'review/track_b.py', PANEL]


def build_fault_panel(search_tasks):
    """Deterministic 30% corrupted-node panel, frozen at build time.
    Hidden from selectors by construction (run_session never passes faults)."""
    rng = random.Random(FAULT_SEED)
    n_fault = max(1, round(0.3 * len(search_tasks)))
    chosen = rng.sample([t['uid'] for t in search_tasks], n_fault)
    panel = {}
    for uid in chosen:
        node = rng.choice(['e1', 'e2', 'r', 'v'])
        panel[uid] = (node, CORRUPT[node])
    return panel


def make_launch():
    if LAUNCH.exists():
        raise FileExistsError('Launch config exists; no silent rebinding')
    protocol = json.loads(PROTOCOL.read_text())
    panel = json.loads(PANEL.read_text())
    tasks = [{k: t[k] for k in ('uid', 'question', 'derivation', 'answer',
                                'ctx_table', 'ctx_text')}
             for t in panel['tasks_search']]
    faults = build_fault_panel(tasks)
    m = dict(
        version='formal_launch_v1',
        authorization='User: 你做完之后继续接着做实验就行 (2026-10-09); staged plan '
                      'stage-2 launch following stage-1 completion',
        protocol_sha256=sha(PROTOCOL),
        tasks=tasks, n_tasks=len(tasks),
        fault30_panel={u: list(f) for u, f in faults.items()},
        fault30_rule=f'Random({FAULT_SEED}): 30% of SEARCH8 uids, node uniform e1/e2/r/v, '
                     'typed corruption; frozen BEFORE launch; corruption replaces the '
                     'metered answer and is never cached',
        session_order=[f'{method}_{seed}' for seed in protocol['search_seeds']
                       for method in protocol['methods']],
        models={slot: sha(ROOT / 'router_v2/label_repair_experiment/raw'
                          / f'{slot}_MODEL_PROVENANCE.json')
                for slot in ('medium', 'large', 'coder')},
        caps=protocol['campaign_caps'],
        reporting='incomplete sessions reported as-is; curves compared on common '
                  'budget support; no extension')
    LAUNCH.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    print(json.dumps(dict(launch=str(LAUNCH), sha256=sha(LAUNCH), model_calls=0,
                          sessions=len(m['session_order']))))


def make_admission():
    if ADMISSION.exists():
        raise FileExistsError('Admission exists; no silent rebinding')
    a = dict(
        version='formal_admission_v1',
        status='READY',
        protocol_sha256=sha(PROTOCOL),
        execution_authorized=True,
        authorization='User: 你做完之后继续接着做实验就行 (2026-10-09)',
        selector_review_pass=True,
        selector_review_evidence='TRACK_B_EVIDENCE.json cross-state 15/15; '
                                 'TRACK_A_EVIDENCE.json BoTorch alignment 7/7',
        independent_splits_verified=True,
        independent_splits_evidence='TASK_PANEL_V1.json frozen; '
                                    'TRACK_C_EVIDENCE.json 14/14 zero-exposure',
        new_semantics_real_validation_pass=True,
        new_semantics_evidence='FULLVAL_STAGE1_REPORT.json — minimum scope exceeded; '
                               'S4 cache reuse 0-new-requests x4/4; recovery restores Q',
        runtime_tests_pass=True,
        runtime_tests_evidence='test_runtime.py 10/10',
        blockers=[],
        bindings={str(p): sha(p) for p in frozen_inputs() + [LAUNCH]})
    ADMISSION.write_text(json.dumps(a, ensure_ascii=False, indent=1))
    print(json.dumps(dict(admission=str(ADMISSION), sha256=sha(ADMISSION))))


class SyncedSelector:
    """Bridges run_session's selector contract (candidates, observations) to
    ProductionSearcher: ingests any evaluator observations not yet seen (the
    legal channel — run_session passes session.observations), then selects."""

    def __init__(self, searcher):
        self.searcher = searcher
        self._seen = set()

    def __call__(self, candidates, observations):
        for o in observations:
            key = (o['config_id'], o.get('state', 'clean'))
            if key not in self._seen:
                self._seen.add(key)
                self.searcher.observe_evaluator_result(o)
        return self.searcher.select(candidates)


def run_campaign(launch, only=None):
    import sys
    sys.path.insert(0, str(ROOT))
    from collab_scheduler_v1.joint_search_v1.runtime import run_session, require_admission
    from collab_scheduler_v1.joint_search_v1.review.track_b import ProductionSearcher
    from collab_scheduler_v1.joint_search_v1.evaluator import space
    from collab_scheduler_v1.fault30_protocol import Ledger

    protocol = require_admission(PROTOCOL, ADMISSION, launch['protocol_sha256'])
    tasks = launch['tasks']
    faults = {u: tuple(f) for u, f in launch['fault30_panel'].items()}
    states = [('clean', {}), ('fault30', faults)]
    task_uids = [t['uid'] for t in tasks]
    sp = space()
    bindings = {slot: launch['models'][slot] for slot in ('medium', 'large', 'coder')}

    from static_dag_v0 import run as engine
    campaign = JS / 'formal_campaign'
    results = []
    for sid in launch['session_order']:
        if only and sid not in only:
            continue
        method, seed = sid.rsplit('_', 1)
        seed = int(seed)
        # deterministic per-session searcher seed
        searcher = ProductionSearcher(method, sp, task_uids, rng_seed=seed)
        selector = SyncedSelector(searcher)
        t0 = time.time()
        report = run_session(campaign=campaign, protocol_sha=launch['protocol_sha256'],
                             protocol=protocol, method=method, seed=seed,
                             tasks=tasks, states=states, selector=selector,
                             ledger=Ledger(), backend=engine, bindings=bindings,
                             gpu_lock_path=GPU_LOCK)
        report['session_id'] = sid
        results.append(report)
        print(json.dumps(dict(session=sid, status=report['status'],
                              wall_s=round(time.time() - t0),
                              requests=report.get('new_requests'))))
        (JS / 'formal_campaign' / 'CAMPAIGN_LOG.jsonl').parent.mkdir(exist_ok=True)
        with open(JS / 'formal_campaign' / 'CAMPAIGN_LOG.jsonl', 'a') as fh:
            fh.write(json.dumps(report, default=str) + '\n')
    done = sum(1 for r in results if r['status'] == 'COMPLETE')
    print(json.dumps(dict(sessions_run=len(results), complete=done)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--build', action='store_true')
    p.add_argument('--admit', action='store_true')
    p.add_argument('--preflight', action='store_true')
    p.add_argument('--run', action='store_true')
    p.add_argument('--only', help='comma-separated session ids')
    a = p.parse_args()
    if a.build:
        make_launch()
        return
    if a.admit:
        make_admission()
        return
    launch = json.loads(LAUNCH.read_text())
    for path, digest in json.loads(ADMISSION.read_text())['bindings'].items():
        if sha(path) != digest:
            raise ValueError('Binding mismatch: ' + path)
    if launch['protocol_sha256'] != sha(PROTOCOL):
        raise ValueError('Protocol drifted')
    if a.preflight:
        print(json.dumps(dict(status='PREFLIGHT_PASS', sessions=len(launch['session_order']),
                              tasks=launch['n_tasks'],
                              faulted=len(launch['fault30_panel']), model_calls=0)))
        return
    import os
    if a.run:
        if os.environ.get('JOINT_SEARCH_EXECUTE') != '1':
            raise PermissionError('Execution environment required')
        run_campaign(launch, only=set(a.only.split(',')) if a.only else None)


if __name__ == '__main__':
    main()
