"""D: 48-config Joint Search Design (expanded space for the full experiment).

10 base configs from C are the smoke subset. This file designs the full
48-config space for the subsequent large-scale experiment.
"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_smoke'

DESIGN = dict(
    role='joint_search_48config_design',
    created_unix=int(time.time()),

    # === Expanded X Space ===
    # Instead of 5 families, enumerate meaningful assignments
    X_space=dict(
        models=['medium', 'large', 'coder'],
        roles=['e1', 'e2', 'r', 'v'],
        constrained_assignments=[
            # Each is (e1, e2, r, v) — e1/e2 can differ for asymmetric extraction
            ['large', 'large', 'medium', 'coder'],   # heterogeneous (baseline)
            ['large', 'large', 'large', 'large'],    # quality
            ['medium', 'medium', 'medium', 'medium'], # cheap
            ['medium', 'medium', 'large', 'medium'],  # balanced
            ['large', 'medium', 'coder', 'large'],    # type_prior
            ['coder', 'coder', 'medium', 'coder'],    # coder-heavy
            ['large', 'coder', 'medium', 'coder'],    # mixed extractors
            ['coder', 'large', 'medium', 'large'],    # reversed extractors
            # Asymmetric e assignments (parallel branch heterogeneity)
            ['large', 'coder', 'medium', 'coder'],
            ['coder', 'large', 'medium', 'coder'],
            # Reasoner variations
            ['large', 'large', 'coder', 'coder'],
            ['medium', 'medium', 'coder', 'coder'],
            # Verifier variations
            ['large', 'large', 'medium', 'large'],
            ['large', 'large', 'medium', 'medium'],
            ['medium', 'medium', 'medium', 'large'],
        ],
    ),

    # === Expanded Z Space ===
    Z_space=dict(
        options=['none', 'reroute'],
        future_options=['dynpatch (P3, after P2 validation)'],
    ),

    # === Total Configs ===
    config_count='15 X × 2 Z = 30 configs (feasible subset of 3^4 × 2 = 162)',

    # === Selection Rationale ===
    selection_rationale=dict(
        included='15 diverse X assignments covering uniform, heterogeneous, '
                 'asymmetric, and coder-heavy patterns',
        excluded='assignments where e1=e2 with weak models (dominated by '
                 'e1=e2=large in clean cube); assignments with identical '
                 'capability profiles to included ones',
        note='30 configs is large enough for meaningful search comparison '
             'but small enough for exhaustive ground truth on 8-16 tasks',
    ),

    # === State Features for Surrogate ===
    state_features=dict(
        structural=[
            'n_distinct_models (heterogeneity measure)',
            'has_coder (boolean)',
            'has_large (boolean)',
            'e_same_model (boolean: e1==e2)',
            'r_model_strength (0=medium, 1=coder, 2=large)',
            'v_model_strength',
            'recovery_enabled (Z=reroute)',
        ],
        informational_boundary='features encode only the config structure; '
                                'no task-specific or gold-derived information',
    ),

    # === Incremental Cost Model ===
    incremental_cost=dict(
        definition='estimated real tokens to evaluate a config on one task',
        formula='sum of per-node estimated tokens based on model and context length',
        per_model_estimates={'medium': 250, 'large': 350, 'coder': 300},
        recovery_overhead=200,  # extra tokens for reroute recovery attempt
        note='estimated cost used for cost-aware acquisition; actual cost '
             'from real evaluation replaces it once revealed',
    ),

    # === Baseline: Direct Q_B Optimization ===
    q_b_baseline=dict(
        description='directly optimize budget-constrained quality Q(B)',
        method='evaluate configs by scalarized utility w=[1,0,0] (quality only) '
                'under budget constraint C<=B',
        note='this baseline tests whether multi-objective search provides '
             'value beyond single-objective optimization',
    ),

    # === Information Boundary (reiterated) ===
    info_boundary=dict(
        allowed='(1) features of any config; (2) (Q,C,L) of revealed configs from '
                'current run; (3) pre-estimated incremental cost',
        forbidden='(1) true (Q,C,L) of unrevealed configs; (2) Reference Cube results '
                  'as labels; (3) fault30 v1 results (execution defect); (4) any '
                  'gold-derived features',
    ),
)

(OUT / 'SEARCH_DESIGN_D.json').write_text(json.dumps(DESIGN, indent=1))
print(json.dumps(dict(
    n_X=15, n_Z=2, total=30,
    n_state_features=7,
    note='30 configs for full experiment; 10 subset for smoke'), indent=1))
