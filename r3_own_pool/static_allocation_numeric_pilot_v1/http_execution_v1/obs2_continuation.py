"""OBS2 continuation: deepseek x extract_purchase (authorized 2nd call)."""
import copy, hashlib, importlib.util, json, sys, traceback
from decimal import Decimal
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from binding import load_plan, load_keys_after_authorization
import http_transport

def main():
    plan = load_plan()
    cfg = json.loads((HERE.parent / 'ab_execution_binding_v2'
                      / 'AB_CONFIG.json').read_text())
    spec = importlib.util.spec_from_file_location(
        'ev', HERE.parent / 'terminal_contract_v1' / 'evaluate_terminal.py')
    terminal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(terminal)
    REAL = HERE / 'REAL_RUN_20261026_012116'
    OUT = HERE / 'MINI_OBS_20261026_QXP_DXP_RUN2'
    frozen = {r['request_id']: r for r in cfg['requests']}
    plan_reqs = {r['request_id']: r for r in plan['requests']}
    keys = load_keys_after_authorization(plan)
    donor = frozen['R1_B_extract_purchase']
    body = copy.deepcopy(donor['body']); body['model'] = 'deepseek-flash'
    my_sha = hashlib.sha256(json.dumps(body['messages'], ensure_ascii=False,
                                       sort_keys=True).encode()).hexdigest()
    assert my_sha == donor['messages_sha256'], 'PROMPT_IDENTITY_BROKEN'
    ep = next(pr['endpoint'] for rid, pr in plan_reqs.items()
              if frozen[rid]['model'] == 'deepseek-flash')
    r = dict(request_id='OBS2_DxPurchase', body=body, endpoint=ep)
    worst = (Decimal(8383) * Decimal('0.3')
             + Decimal(1024) * Decimal('1.2')) / Decimal(10**6)
    print(f'OBS2 reserved worst USD {worst:.6f}', flush=True)
    try:
        env = http_transport.call_once(r, keys['deepseek-flash'],
                                       timeout_s=180)
        parsed = http_transport.parse_response(env, r, {'deepseek-flash'})
        u = parsed['usage']
        assert u['prompt_tokens'] <= 8383, 'INPUT_BOUND_VIOLATION'
        assert u['completion_tokens'] <= 1024, 'OUTPUT_CAP_VIOLATION'
        assert parsed['finish_reason'] == 'stop', 'TRUNCATED_OR_INCOMPLETE'
        e = (Decimal(u['prompt_tokens']) * Decimal('0.3')
             + Decimal(u['completion_tokens']) * Decimal('1.2')) / Decimal(10**6)
        rec = dict(request_id='OBS2_DxPurchase', arm='D+D',
                   node='extract_purchase',
                   model_requested='deepseek-flash',
                   model_returned=parsed['model_returned'], endpoint=ep,
                   messages_sha256=my_sha,
                   donor_request='R1_B_extract_purchase',
                   usage=u, finish_reason=parsed['finish_reason'],
                   reasoning_tokens=parsed['reasoning_tokens'],
                   cached_tokens=parsed['cached_tokens'], currency='USD',
                   public_cold_miss_estimate=str(e), actual_cash=None,
                   bill_status='PENDING_ACCOUNT_BILL_VERIFICATION',
                   client_call_wall_s=env['client_call_wall_s'],
                   status='COMMITTED', evidence_class='REAL_HTTP_ATTEMPT',
                   automatic_retries=0, response_id=parsed['response_id'])
        (OUT / 'OBS2_DxPurchase_RECORD.json').write_text(json.dumps(
            rec, ensure_ascii=False, indent=1))
        (OUT / 'OBS2_DxPurchase_MODEL_OUTPUT.txt').write_text(
            parsed['raw_output'])
        print(f'  -> in={u["prompt_tokens"]} '
              f'out={u["completion_tokens"]} USD {e:.7f} '
              f'finish={parsed["finish_reason"]} '
              f'wall={env["client_call_wall_s"]:.2f}s', flush=True)
        lane = terminal.evaluate({'extract_purchase': parsed['raw_output']})
        lo = lane['branches']['extract_purchase']
        print(f'  lane: schema={lo["schema"]} '
              f'slots={lo["assigned_slots_exact"]} '
              f'evidence={lo["evidence_IDs_valid"]} '
              f'legal={lo["numeric_lane_legal"]}', flush=True)
        if lo['numeric_lane_legal']:
            merged = terminal.evaluate({
                'extract_purchase': parsed['raw_output'],
                'extract_payables': (REAL /
                    'R1_B_extract_payables_MODEL_OUTPUT.txt').read_text()})
            print(f'  [MERGE D+D] content_Q={merged["content_Q"]} '
                  f'legal_correct/6='
                  f'{merged["legal_correct_targets_over_six"]} '
                  f'all_lanes='
                  f'{merged["all_branches_numeric_lane_legal"]}', flush=True)
            (OUT / 'MINI_OBS_FINAL.json').write_text(json.dumps(dict(
                status='COMPLETE', obs2_record=rec, obs2_merge=merged,
                obs1_outcome='LANE_FAILURE_bare_array_schema',
                note='OBS2 continuation after OBS1 scientific outcome'),
                ensure_ascii=False, indent=1, default=str))
            print('OBS2 COMPLETE')
        else:
            (OUT / 'OBS2_LANE_FAILURE.json').write_text(json.dumps(
                dict(status='OBS2_LANE_FAILURE', record=rec, branch=lo),
                ensure_ascii=False, indent=1))
            print('OBS2 lane failure recorded')
    except BaseException as exc:
        (OUT / 'OBS2_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc),
            traceback=traceback.format_exc()), indent=1))
        print(f'INCOMPLETE: {exc}')

if __name__ == '__main__':
    main()
