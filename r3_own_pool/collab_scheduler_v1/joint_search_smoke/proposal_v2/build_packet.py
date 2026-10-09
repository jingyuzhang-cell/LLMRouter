"""Prepare a review packet only. Never executes a model or changes frozen results."""
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = Path(__file__).resolve().parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

source = ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json'
tasks = json.loads(source.read_text())['tasks']
eligible = [t for t in tasks if not t['uid'].startswith('3117a2bf')]
selected = sorted(eligible, key=lambda t: hashlib.sha256(
    ('joint_smoke_v2:' + t['uid']).encode()).hexdigest())[:8]
assert len(selected) == 8 and len({t['uid'] for t in selected}) == 8
write('TASK_MANIFEST.json', dict(source=str(source), source_sha256=sha(source),
    task_uids=[t['uid'] for t in selected], role='exposed diagnostic tasks only; never independent confirmation'))
models = [('medium', 'large'), ('medium', 'large'), ('medium', 'large'), ('coder', 'large')]
configs = [dict(id='__'.join((*x,z)), X=dict(zip(('e1','e2','r','v'),x)), Z=z)
           for x in itertools.product(*models) for z in ('NONE','LOCAL','FULL')]
assert len(configs) == len({c['id'] for c in configs}) == 48
methods = ['proposed_state_incremental', 'random', 'scalarized_bo',
           'official_qnehvi_same_state', 'proposed_without_state',
           'proposed_without_incremental_cost']
write('SEARCH_DESIGN.json', dict(status='DESIGN_ONLY_NOT_IMPLEMENTED',
    topology=dict(nodes=['e1','e2','r','v'],edges=[['e1','r'],['e2','r'],['r','v']]),
    configs=configs, methods=methods, no_topology_patch=True,
    information_boundary='No gold, injected identities, unrevealed Q/C/L or old faulty LR labels.',
    evaluator_permissions='Identical legal dependency cache access for all six methods.',
    cost_separation='Physical evaluation tokens are search expenditure. Workflow Q/C/L require a separately frozen runtime-cache and deployment convention; historical used/lat are NOT physical expenditure.',
    scope='48-config search is not authorized or launched by this packet.'))
files = ['collab_scheduler_v1/fault30_run.py',
         'collab_scheduler_v1/fault30_cache_accounting_tests.py',
         'collab_scheduler_v1/test_physical_accounting.py',
         'collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py',
         'collab_scheduler_v1/joint_search_smoke/proposal_v2/test_smoke_runner.py',
         'collab_scheduler_v1/fault30_protocol.py',
         'static_dag_v0/run.py', 'static_dag_v0/multidag_dynamic.py',
         'static_dag_v0/tool_aware_v1.py',
         'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json']
write('SMOKE_PROTOCOL.json', dict(version='joint_smoke_v2', status='ZERO_CALL_CHECKS_PASSED_PENDING_EXECUTION_APPROVAL',
    tasks='TASK_MANIFEST.json (8 previously exposed tasks)',
    purpose='Physical metering, valid cache reuse, fresh-prompt miss handling and budget stops; not algorithm efficacy.',
    states=[dict(name='clean',rate=0),dict(name='fault30',rate=.3,seed=20260923)],
    configs=['DYNAMICDAG__HETEROGENEOUS__NONE__FRESH',
             'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH',
             'DYNAMICDAG__QUALITY__NONE__FRESH',
             'DYNAMICDAG__QUALITY__LOCAL_REROUTE__FRESH'],
    logical_max=8*2*4*12,
    proposed_hard_budget=dict(new_request_attempts=200,new_total_tokens=200*8192,
        request_token_reservation=8192,max_output_tokens=512,wall_seconds=3600,
        logical_calls_per_task_config_state=12,automatic_retries=0,
        note='Operational ceilings for approval, NOT cost predictions or a guarantee of completing all cells.'),
    dispatch_guard=['Persist and reserve request attempt and token upper bound BEFORE server dispatch.',
        'Count failed and timed-out dispatched requests too. Unknown usage retains full reservation.',
        'Do not dispatch if request/token/wall cap would be exceeded.',
        'Release unused reservation only after actual usage is recorded.',
        'Cache hits and injections consume zero physical requests/tokens/service time; lookup overhead stays in wall time.',
        'After crash, reconcile pending reservations; never reset budget or retry automatically.'],
    termination=['Stop on any cap, accounting mismatch, invalid cache provenance, stale successor, gold-dependent decision, infra error or missing usage.',
        'Persist partial trajectories and INCOMPLETE status; never turn partial panels into completed Q/C/L.',
        'No automatic budget increase, fallback experiment or full 48-config search.'],
    cache=dict(policy='COLD_START: no historical answer cache imported; only successful fresh responses within this run may be reused.',
        key=['model_provenance_sha','generation_code_sha','full_serialized_prompt_sha','task_uid','node_role','fault_scope'],
        dependency_semantics='Full prompt binds the serialized dependency values actually consumed by the node; raw upstream response identity is not separately keyed. Task/node/state scope is conservative.',
        legal='Unchanged exact node inputs only, with source request provenance.',
        forbidden='Old LR outcomes as labels; copying historical token/latency into physical counters; alias to injected/dry/failed output.',
        repeated_request_check='Stub verifies exact alias adds zero physical charge; real trajectories must be checked for natural aliases, and absence of aliases means this acceptance item remains unverified.'),
    metrics=dict(new_requests='successful new server requests per completed row; run attempt ledger also counts failures',
        new_tokens='actual newly consumed input+output tokens, never alias usage',
        new_latency_s='sum of actual new request service duration, never source historical latency',
        logical_calls='all logical node attempts',cache_hits='alias reads',injected_calls='synthetic failures',
        dry_calls='structural placeholders',wall_time='monotonic observed execution time; cache overhead and model switching reported separately',
        legacy='used/lat retained as historical workflow diagnostics, not physical cost'),
    admission_requirements=['Accounting regressions pass and recorded code hashes match.',
        'Isolated smoke_runner.py dispatch guard and 64-cell Stub integration passed; no real cost validation yet.',
        'Runner records wall and failed attempts; unknown usage retains reservation; interrupted runs require manual reconciliation and cannot resume automatically. Wall deadline stops work; GPU cleanup may extend elapsed wall.',
        'Explicit user execution approval; GPU lock available; no other window executes.'],
    output='proposal_v2/runs/<run_id>/ (runner must refuse overwrite)',
    code_sha256={f:sha(ROOT/f) for f in files}, execution_authorized=False))
write('ADMISSION.json',dict(accounting='PASS: five unit cases and three production-eval_config stub cases',
    mechanism_regression='Existing R2/r_changed evidence retained; not rerun in this task.',
    physical_calls_issued_by_preparation=0,execution_authorized=False,
    runner_checks='PASS: 13 zero-call budget/executor/integration tests; includes 64 Stub cells, NOT real results.',
    blockers=['Explicit approval of the proposed 200-attempt/token/wall ceilings is pending.'],
    old_packet='SMOKE_PROTOCOL_C/SEARCH_DESIGN_D/SMOKE_ADMISSION_E are historical; do not use for this approval.'))
print('Prepared 8-task manifest, 48 unique configurations, six methods; execution remains disabled.')
