"""Freeze resource envelope, not execution permission or statistical admission."""
import hashlib
import json
from pathlib import Path
from .evaluator import space,METHODS

ROOT=Path('/root/r3_own_pool')
OUT=Path(__file__).resolve().parent
SMOKE=ROOT/'collab_scheduler_v1/joint_search_smoke/proposal_v2/runs/smoke8_metering_01'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    audit=json.loads((SMOKE/'METERING_AUDIT.json').read_text())
    assert audit['all_pass']
    s=audit['summary']
    switches=[json.loads(x) for x in (SMOKE/'MODEL_SWITCH.jsonl').read_text().splitlines()]
    per_call=s['new_tokens']/s['new_requests']
    # One search session: six times? 12 rather than 4 selected configurations:
    # use only 3x as a transparent scenario, NEVER a prediction for new X/FULL.
    scenario=dict(tasks=8,states=2,max_selected_configs=12,
        simple_smoke_scaling_requests=3*s['new_requests'],
        simple_smoke_scaling_tokens=3*s['new_tokens'],
        simple_smoke_scaling_wall_s=3*s['observed_wall_s'],
        warning='Not a cost forecast: new X, FULL, charged corrupted responses, cache order and model switches differ.')
    protocol=dict(version='joint_search_resource_envelope_v1',
        status='RESOURCE_CEILINGS_FROZEN_EXECUTION_NOT_AUTHORIZED',
        configs=space(),methods=list(METHODS),
        search_seeds=[20261009,20261010,20261011],
        initial_design_count=2,max_selected_configurations_per_session=12,
        initial_design_rule='Sample two unique configs from public space with session seed; identical for all methods; both included in budget.',
        states=['clean','fault30'],
        task_panel=dict(status='UNASSIGNED: independent task provenance and power assessment required',
            budget_basis_tasks=8,
            note='8 is the measured resource block, not a justified confirmatory sample size. Exposed Smoke tasks cannot become independent test tasks. Larger panels must stay within caps or get a revised approval.'),
        per_session_caps=dict(new_request_attempts=400,new_total_tokens=400*8192,
            request_token_reservation=8192,max_output_tokens=512,wall_seconds=7200,
            logical_calls_per_task_config_state=12,automatic_retries=0),
        campaign_caps=dict(sessions=18,new_request_attempts=7200,new_total_tokens=7200*8192,
                           wall_seconds=18*7200,automatic_retries=0),
        cap_rationale='Operational ceilings: 400 requests rounds above the 330-request unchanged-SMOKE scenario; 7200s allows >3x the scenario wall for new FULL and switching. Neither cap guarantees 12 reveals. NOT estimates or approved spend.',
        scenario=scenario,
        measured=dict(smoke_calls=s['new_requests'],smoke_tokens=s['new_tokens'],
            smoke_wall_s=s['observed_wall_s'],switch_wall_s=s['model_switch_wall_s'],
            switch_fraction=s['model_switch_wall_s']/s['observed_wall_s'],
            switches=len(switches),mean_switch_s=sum(x['wall_s'] for x in switches)/len(switches),
            max_switch_s=max(x['wall_s'] for x in switches),mean_tokens_per_new_request=per_call),
        cache_policy='Empty historical/method cache at each method-seed session; no cross-method physical cache subsidy. Exact prompt reuse inside a session only.',
        objectives=dict(Q='mean terminal exact-match over frozen task panel; only scoring sees gold',
            C='mean cold-workflow token sum over all logical attempts, including replay and pre-corruption source usage; alias sources still contribute',
            L='mean reconstructed serial service demand from underlying response durations; source durations reused on aliases; NOT observed E2E nor parallel critical path',
            noise='L is measured noisy source service time; identical cache evidence yields identical objectives, but cross-run timing equality is NOT guaranteed.'),
        physical_search_cost='Actual new requests/tokens/service sum plus separately observed wall and model-switch wall. Failed attempts retain charges/reservations.',
        fault_policy='Meter valid underlying response then corrupt answer. Corruption is hidden from selector; source usage included in deployment cost. Never use old LR truth labels.',
        full_policy='One full replay on observable failure; alternative model large->coder, medium/coder->large; no gold trigger; four fresh logical node attempts, exact-input physical reuse permitted.',
        stopping='First config/request/token/wall/global cap or infrastructure error stops; incomplete candidate never scored; failed partial work still charged. Compare curves on common budget support; no extension to manufacture equal completed counts.',
        admission_blockers=['Six real selectors and state/incremental-cost feature boundary require independent review.',
            'Independent development/calibration/test manifests and confirmatory sample size are not frozen.',
            'FULL and response-corruption metering have zero-call tests only; new real validation must fit a separately approved allocation.',
            'Session GPU lifecycle and campaign-level durable quota wrapper must be wired before execution; evaluator alone is not an executable campaign runner.',
            'Explicit approval of this resource envelope is pending; previous approval applied only to smoke8_metering_01.'],
        parallel_window='CPU-only read-only selector/ablation review; no GPU, no edits to this evaluator, no synthetic performance claims.',
        evidence_sha256={'METERING_AUDIT.json':sha(SMOKE/'METERING_AUDIT.json')},
        code_sha256={str(p.relative_to(ROOT)):sha(p) for p in [OUT/'evaluator.py',OUT/'test_evaluator.py',OUT/'freeze_budget.py',ROOT/'collab_scheduler_v1/fault30_run.py',ROOT/'collab_scheduler_v1/joint_search_smoke/proposal_v2/smoke_runner.py']})
    target=OUT/'SEARCH_BUDGET_V1.json'
    if target.exists():raise FileExistsError('Frozen budget exists; version amendments explicitly')
    target.write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(path=str(target),sha256=sha(target),scenario=scenario,measured=protocol['measured'],execution_authorized=False),indent=2))

if __name__=='__main__':main()
