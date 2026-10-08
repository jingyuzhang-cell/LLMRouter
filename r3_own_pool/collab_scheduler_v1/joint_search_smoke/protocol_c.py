"""C: 8-task Joint Search Smoke Protocol (frozen pre-execution design).

Fixed 4-node DAG (e1,e2→r→v). Joint search over X (node-model assignment)
and Z (feedback recovery strategy). This is a NEW protocol — does NOT reuse
P1-C dynamic topology patch or the 6-task P2 draft.
"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_smoke'
OUT.mkdir(exist_ok=True)

PROTOCOL = dict(
    role='joint_search_smoke_8task',
    created_unix=int(time.time()),

    # === Task Selection ===
    task_selection=dict(
        n_tasks=8,
        source='frozen200 panel (FROZEN200_POLICY.json), deterministic SHA order',
        seed='joint_smoke_v1',
        selection_rule='sort by SHA256("joint_smoke_v1:" + uid), take first 8',
        exclusion='no overlap with P1-B directed task (3117a2bf)',
    ),

    # === DAG Structure (FIXED — no topology search) ===
    dag=dict(
        nodes=['e1', 'e2', 'r', 'v'],
        edges=[['e1', 'r'], ['e2', 'r'], ['r', 'v']],
        topology='ParallelER + verifier (fixed, no Y search)',
    ),

    # === Search Space ===
    search_space=dict(
        X=dict(
            description='node-model assignment for (e1,e2,r,v)',
            families={
                'cheap': ['medium', 'medium', 'medium', 'medium'],
                'quality': ['large', 'large', 'large', 'large'],
                'heterogeneous': ['large', 'large', 'medium', 'coder'],
                'balanced': ['medium', 'medium', 'large', 'medium'],
                'type_prior': ['large', 'medium', 'coder', 'large'],
            },
        ),
        Z=dict(
            description='feedback recovery strategy',
            options=['none', 'reroute'],
        ),
        total_configs='len(X_families) * len(Z) = 5 * 2 = 10 base configs',
        note='10 configs × 8 tasks × 1 state (fault30) = 80 task-evaluations',
    ),

    # === Fault Model ===
    fault=dict(
        state='s_fault30 (30% injection, seed 20260923)',
        rate=0.3,
        seeds=[20260923],
        n_faulted_tasks='int(8 * 0.3) = 2 tasks',
        node_choice='random from {e1,e2,r,v}',
        pool='FAULT_POOLS.json',
    ),

    # === Budget ===
    budget=dict(
        logical_call_cap_per_task=12,
        total_logical_cap=8 * 12 * 10,  # 960 (upper bound if all 10 configs run)
        smoke_real_cap=200,  # actual LLM calls cap for smoke
        smoke_real_note='200 real calls = ~25% of theoretical max; sufficient '
                        'for smoke validation',
        cost_estimate='avg 4 nodes/task * ~300 tok/node * 80 evaluations ≈ '
                      '~96k tokens (with cache reuse much less)',
    ),

    # === Search Algorithms (6 methods) ===
    algorithms=[
        dict(name='random', type='baseline',
             description='uniform random over unevaluated configs'),
        dict(name='greedy_q', type='single-objective',
             description='argmax surrogate Q̂ only'),
        dict(name='scalarized', type='multi-objective',
             description='rotating frozen weight bank, argmax w·F̂'),
        dict(name='ehvi', type='MOBO',
             description='MC expected hypervolume improvement'),
        dict(name='sa_pgfs', type='proposed',
             description='cost-aware EHVI with state-conditioned surrogate'),
        dict(name='qnehvi', type='strongest baseline',
             description='noisy expected HV improvement'),
    ],

    # === Initial Design ===
    initial_design=dict(
        n_init=2,
        shared_across_algorithms=True,
        selection='random (seed 42) from the 10-config space',
    ),

    # === Budget for Search ===
    search_budget=dict(
        t_min=2, t_max=10,  # full curve on 10 configs
        per_step='one config revealed per step',
        replay_seeds=100,
    ),

    # === Objectives ===
    objectives=dict(
        Q='fraction of 8 tasks with final answer within tolerance of gold',
        C='real model tokens per task (excluding cache hits and injected)',
        C_logical='logical calls per task (including cache and injected)',
        L_serial='sum of per-call service latency (serial execution)',
        L_wall='end-to-end wall-clock per task',
        note='C uses only real model calls (not cache); L_serial is sum of '
             'service latencies; L_wall is wall-clock including model switching',
    ),

    # === Termination ===
    termination=dict(
        mode='fixed-budget (all 10 configs revealed)',
        no_early_stopping=True,
        no_interim_analysis=True,
    ),

    # === Artifact Isolation ===
    artifact_isolation=dict(
        run_dir='joint_search_smoke/runs/<run_id>/',
        separate_from='P1-B (frozen), Reference Cube (frozen), fault30 results (frozen)',
        no_modification_of_historical_results=True,
    ),

    # === Information Boundary ===
    information_boundary=dict(
        surrogate_features='structural encoding of (X,Z) config only; no gold info',
        may_use='previously revealed configs\' (Q,C,L) from THIS run',
        may_not_use='unrevealed configs\' true values; historical fault30 results '
                    'as labels (execution defect versions); Reference Cube as labels',
    ),
)

code_files = [
    'collab_scheduler_v1/fault30_run.py',
    'collab_scheduler_v1/p2_executor_audit/final_targeted.py',
]
PROTOCOL['code_sha'] = {
    f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()[:16] for f in code_files
}

(OUT / 'SMOKE_PROTOCOL_C.json').write_text(json.dumps(PROTOCOL, indent=1))
print(json.dumps(dict(
    n_tasks=8, n_configs=10, n_algorithms=6,
    smoke_real_cap=200, search_budget='t=2..10, 100 replay seeds'), indent=1))
