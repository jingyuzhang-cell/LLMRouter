"""E: Smoke Admission Report — known limitations + GO conditions + metric definitions."""
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_smoke'

REPORT = dict(
    role='smoke_admission_report',
    created_unix=int(time.time()),

    # === Known Unresolved Issues (from 1900a08 audit) ===
    known_issues=[
        dict(
            id='ISSUE-1',
            title='V1/V2 duplicate billing on cache hit',
            detail='When V2 fires (r_changed=True) with same model+prompt as V1, '
                   'V2 hits cache. No new model computation occurs, but logical '
                   'billing records 100 tokens for V2 (historical cache response). '
                   'Total tokens billed overstates real cost.',
            evidence='1900a08 S2: V1 sha=b2b96da3, V2 sha=b2b96da3, V2 source=cache, '
                     'both billed 100 tokens',
            impact='C is inflated by cache-hit charges for superseded/refresh calls',
            min_fix='Separate real_tokens (only non-cache, non-injected) from '
                    'logical_tokens (all billed). Report both. Use real_tokens '
                    'for the C objective in search.',
            status='must_fix_before_GO'),
        dict(
            id='ISSUE-2',
            title='r_changed does not distinguish A→B→A from A→B→C',
            detail='r_changed is set when ANY intermediate r output differs. '
                   'If R2 changes r from A to B, then R3 restores to A, '
                   'r_changed remains True (cumulative). V2 fires unnecessarily.',
            evidence='1900a08 S3 tested A→A→C (not the required A→B→A)',
            impact='Unnecessary V2 execution in rare restoration cases',
            min_fix='Change r_changed to compare FINAL r output vs ORIGINAL r '
                    'output: r_changed = (last_r_answer != first_r_answer). '
                    'This correctly handles A→B→A (False) and A→B→C (True).',
            status='must_fix_before_GO'),
        dict(
            id='ISSUE-3',
            title='billing_inflation conflates cache, injected, and real retry',
            detail='billing_inflation = logical_calls - computed_requests mixes '
                   'cache-hit charges, fault-injection entries, and genuine '
                   'superseded calls. Not a clean measure of wasted cost.',
            evidence='S3: billing_inflation=4 includes 3 fault entries + 1 superseded',
            impact='Cannot use billing_inflation as a reliable cost metric',
            min_fix='Report four separate metrics (see metric definitions below). '
                    'Do not compute a single inflation number.',
            status='must_fix_before_GO'),
    ],

    # === Metric Definitions (four distinct cost/time dimensions) ===
    metric_definitions=dict(
        physical_model_cost=dict(
            name='real_tokens',
            definition='sum of usage.total_tokens from calls where '
                       'source=real (not cache, not injected_fault)',
            search_objective='YES — this is the C objective for Pareto search',
        ),
        logical_execution_count=dict(
            name='logical_calls',
            definition='total number of keys in the execution ledger '
                       '(includes cache hits and fault injections)',
            search_objective='NO — diagnostic only',
        ),
        cumulative_service_latency=dict(
            name='service_L',
            definition='sum of per-call latency_s across all calls in the '
                       'execution ledger (serial estimate)',
            search_objective='secondary — report alongside L_wall',
        ),
        end_to_end_wall_clock=dict(
            name='wall_L',
            definition='time.monotonic() difference from task start to task end '
                       '(includes model switching, queueing)',
            search_objective='YES — this is the L objective for Pareto search',
        ),
        note='C = real_tokens (not logical_tokens); L = wall_L (not service_L). '
             'service_L and logical_calls reported as diagnostics.',
    ),

    # === GO Conditions ===
    go_conditions=[
        'ISSUE-1 fixed: real_tokens separated from logical_tokens in per-task results',
        'ISSUE-2 fixed: r_changed compares final vs original r output',
        'ISSUE-3 fixed: four separate metrics reported (not single inflation)',
        '8-task smoke protocol (C) frozen',
        '48-config design (D) frozen',
        'GPU available and no conflicting processes',
        'Budget approved: 200 real LLM calls for smoke',
    ],

    # === What Smoke Does NOT Prove ===
    smoke_limitations=[
        '8 tasks is not enough for statistical significance',
        'Single fault seed — no robustness across fault draws',
        'Search comparison on 10 configs is illustrative, not conclusive',
        'Results apply to this DAG topology, not generalizable to other structures',
    ],
)

(OUT / 'SMOKE_ADMISSION_E.json').write_text(json.dumps(REPORT, indent=1))
print(json.dumps(dict(
    n_known_issues=3,
    n_must_fix=3,
    n_go_conditions=7,
    n_metric_dimensions=4,
    issues=[i['id'] + ': ' + i['title'] for i in REPORT['known_issues']]), indent=1))
