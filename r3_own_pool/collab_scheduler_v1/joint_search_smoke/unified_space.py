"""Unified config space definition + 6-method search interface (zero calls).

Resolves the 30 vs 48 discrepancy:
- proposal_v2 has 16 X × 3 Z (NONE/LOCAL/FULL) = 48
- design_d has 15 X × 2 Z (none/reroute) = 30

UNIFIED: 16 X × 2 Z = 32 configs.
- Z=FULL excluded: the current executor does NOT implement full-graph re-execution
  as a recovery strategy (only NONE and LOCAL_REROUTE are supported)
- X: the 16 unique assignments from proposal_v2 (which is a superset of D's 15,
  differing by one assignment that D excluded as "dominated")
"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_smoke'

MODELS = ['medium', 'large', 'coder']
Z_OPTIONS = ['NONE', 'LOCAL_REROUTE']

# 16 X assignments (from proposal_v2, validated against executor)
X_ASSIGNMENTS = [
    ('cheap',          {'e1': 'medium', 'e2': 'medium', 'r': 'medium', 'v': 'medium'}),
    ('quality',        {'e1': 'large',  'e2': 'large',  'r': 'large',  'v': 'large'}),
    ('heterogeneous',  {'e1': 'large',  'e2': 'large',  'r': 'medium', 'v': 'coder'}),
    ('balanced',       {'e1': 'medium', 'e2': 'medium', 'r': 'large',  'v': 'medium'}),
    ('type_prior',     {'e1': 'large',  'e2': 'medium', 'r': 'coder',  'v': 'large'}),
    ('coder_heavy',    {'e1': 'coder',  'e2': 'coder',  'r': 'medium', 'v': 'coder'}),
    ('mixed_extract',  {'e1': 'large',  'e2': 'coder',  'r': 'medium', 'v': 'coder'}),
    ('rev_extract',    {'e1': 'coder',  'e2': 'large',  'r': 'medium', 'v': 'large'}),
    ('asym_ext_coder', {'e1': 'large',  'e2': 'coder',  'r': 'medium', 'v': 'coder'}),
    ('asym_ext_large', {'e1': 'coder',  'e2': 'large',  'r': 'medium', 'v': 'coder'}),
    ('coder_reason',   {'e1': 'large',  'e2': 'large',  'r': 'coder',  'v': 'coder'}),
    ('cheap_r_coder',  {'e1': 'medium', 'e2': 'medium', 'r': 'coder',  'v': 'coder'}),
    ('verify_large',   {'e1': 'large',  'e2': 'large',  'r': 'medium', 'v': 'large'}),
    ('verify_medium',  {'e1': 'large',  'e2': 'large',  'r': 'medium', 'v': 'medium'}),
    ('cheap_v_large',  {'e1': 'medium', 'e2': 'medium', 'r': 'medium', 'v': 'large'}),
    ('large_reasoner', {'e1': 'medium', 'e2': 'medium', 'r': 'large',  'v': 'coder'}),
]


def config_id(x_name, x, z):
    return f'{x["e1"][:3]}_{x["e2"][:3]}_{x["r"][:3]}_{x["v"][:3]}__{z}'


def build_space():
    configs = []
    for x_name, x in X_ASSIGNMENTS:
        for z in Z_OPTIONS:
            configs.append(dict(
                id=config_id(x_name, x, z),
                X=x, Z=z, X_name=x_name,
                features=[
                    len(set(x.values())),          # n_distinct_models
                    1.0 if 'coder' in x.values() else 0.0,
                    1.0 if 'large' in x.values() else 0.0,
                    1.0 if x['e1'] == x['e2'] else 0.0,
                    {'medium': 0, 'coder': 1, 'large': 2}[x['r']],
                    {'medium': 0, 'coder': 1, 'large': 2}[x['v']],
                    1.0 if z == 'LOCAL_REROUTE' else 0.0,
                ]))
    return configs


SEARCH_INTERFACE = dict(
    methods=[
        dict(name='proposed', display='SA-PGFS (cost-aware EHVI + state surrogate)',
             type='proposed'),
        dict(name='random', display='Random Search', type='baseline'),
        dict(name='scalarized_bo', display='Scalarized BO (frozen weight bank)',
             type='baseline'),
        dict(name='qnehvi', display='qNEHVI (noisy EHVI)', type='strongest baseline'),
        dict(name='wo_state', display='SA-PGFS w/o state conditioning (ablation)',
             type='ablation'),
        dict(name='wo_incr_cost', display='SA-PGFS w/o incremental cost (ablation)',
             type='ablation'),
    ],
    q_b_baseline=dict(
        name='q_b_direct', display='Direct Q(B) optimization',
        description='evaluate configs by budget-constrained quality only; '
                    'included as an external reference, not in the 6-method comparison'),
    information_boundary=dict(
        surrogate_may_use=[
            'structural features of any config (7 dims)',
            '(Q,C,L) of configs revealed in the CURRENT run',
            'pre-estimated incremental evaluation cost',
        ],
        surrogate_may_not_use=[
            'true (Q,C,L) of unrevealed configs',
            'Reference Cube results as labels (different panel/protocol)',
            'fault30 v1 results (execution defect versions)',
            'any gold-derived features',
        ],
    ),
)

UNIFIED = dict(
    role='unified_config_space_v1',
    created_unix=int(time.time()),
    space_size=f'{len(X_ASSIGNMENTS)} X × {len(Z_OPTIONS)} Z = '
               f'{len(X_ASSIGNMENTS) * len(Z_OPTIONS)} configs',
    z_exclusion_note='Z=FULL excluded: executor does not implement full-graph '
                     're-execution recovery; only NONE and LOCAL_REROUTE supported',
    x_source='16 unique assignments from proposal_v2 SEARCH_DESIGN.json (superset '
             'of design_d 15; the one extra is large_reasoner which D excluded '
             'as potentially dominated but is retained for completeness)',
    configs=build_space(),
    search_interface=SEARCH_INTERFACE,
    code_sha=hashlib.sha256(
        (ROOT / 'collab_scheduler_v1/fault30_run.py').read_bytes()).hexdigest()[:16],
)

if __name__ == '__main__':
    (OUT / 'UNIFIED_SPACE.json').write_text(json.dumps(UNIFIED, indent=1))
    print(json.dumps(dict(
        n_configs=len(UNIFIED['configs']),
        n_x=len(X_ASSIGNMENTS), n_z=len(Z_OPTIONS),
        n_methods=len(SEARCH_INTERFACE['methods']),
        z_excluded='FULL'), indent=1))
