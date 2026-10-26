"""Minimal 2-call completion observations (operator authorization
2026-10-26): OBS1 qwen-plus x extract_payables, OBS2 deepseek-flash x
extract_purchase. Frozen DAG/prompts/scorer/model-config unchanged —
ONLY the model field of the frozen B-arm bodies changes (allocation-only
semantics). Partners for full-DAG merge scoring come from the completed
real run R1 outputs (byte-identical prompts).

Discipline (operator boundary): exactly 2 calls, no retries, no other
models; per-call pre-dispatch worst-case reservation check (certified
bounds); usage>bound or finish!=stop or any parse/check failure ->
immediate stop with partial records; CNY/USD budget ledgers separate;
¥0.017 is an ESTIMATE not a proven hard cap; raw outputs, terminal
correctness, tokens, latency, estimates recorded; merge judged on FULL
rebuilt DAG terminal output, not single-node pass.
"""
import copy, hashlib, importlib.util, json, sys, time, traceback
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from binding import Halt, load_plan, load_keys_after_authorization
import http_transport

def main():
        plan = load_plan()                     # frozen-hash-verified
        cfg = json.loads((HERE.parent / 'ab_execution_binding_v2'
                          / 'AB_CONFIG.json').read_text())
        spec = importlib.util.spec_from_file_location(
            'ev', HERE.parent / 'terminal_contract_v1' / 'evaluate_terminal.py')
        terminal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(terminal)

        REAL = HERE / 'REAL_RUN_20261026_012116'
        OUT = HERE / 'MINI_OBS_20261026_QXP_DXP_RUN2'
        OUT.mkdir(exist_ok=False)

        # worst-case per call from INPUT_BOUND_CERTIFICATION (commit 72d160a7):
        # qwen in<=7816, deepseek in<=8383; output caps from frozen bodies.
        WORST = {'qwen-plus': (7816, 1024), 'deepseek-flash': (8383, 1024)}
        RATES = cfg['rates']
        MINI_CAPS = {'CNY': Decimal('0.05'), 'USD': Decimal('0.05')}  # ledger caps

        AUTH = {
         'id': 'MINI_OBS_AUTHORIZATION_20261026',
         'operator_statement': (
           '放行这 2 次最小补测的研究方案，不扩大范围。仅执行上述 2 次模型'
           '调用，不重试、不增加其他模型。保持原有 DAG、Prompt、输入、评分'
           '器和模型配置不变。分别记录原始输出、终端正确性、Token、实际'
           '时延、估算费用及可取得的账单数据。保留人民币与美元的独立预算'
           '记录；¥0.017 只能视为当前预算估计。派发前完成费用风险预检；'
           '任何检查失败立即停止。'),
         'calls': 2, 'not_after_utc': '2026-10-27T23:59:59Z',
         'caps_native': {'CNY': '0.05', 'USD': '0.05'}}

        OBS = [
         dict(request_id='OBS1_QxPayables', model='qwen-plus',
              node='extract_payables',
              donor='R1_B_extract_payables',          # frozen payables body
              partner=REAL / 'R1_B_extract_purchase_MODEL_OUTPUT.txt',
              partner_node='extract_purchase',
              arm_label='Q+Q'),
         dict(request_id='OBS2_DxPurchase', model='deepseek-flash',
              node='extract_purchase',
              donor='R1_B_extract_purchase',          # frozen purchase body
              partner=REAL / 'R1_B_extract_payables_MODEL_OUTPUT.txt',
              partner_node='extract_payables',
              arm_label='D+D'),
        ]

        frozen_reqs = {r['request_id']: r for r in cfg['requests']}
        plan_reqs = {r['request_id']: r for r in plan['requests']}
        keys = load_keys_after_authorization(plan)

        spent = {'CNY': Decimal(0), 'USD': Decimal(0)}
        records, verdicts = [], []

        def est_native(model, u):
            rate = RATES[model]
            return (Decimal(u['prompt_tokens']) * Decimal(rate['input'])
                    + Decimal(u['completion_tokens']) * Decimal(rate['output'])
                    ) / Decimal(10**6)

        try:
            (OUT / 'AUTHORIZATION.json').write_text(json.dumps(
                AUTH, ensure_ascii=False, indent=1))
            for obs in OBS:
                donor = frozen_reqs[obs['donor']]
                body = copy.deepcopy(donor['body'])
                body['model'] = obs['model']
                # prompt identity: messages byte-identical to frozen donor
                my_sha = hashlib.sha256(json.dumps(
                    body['messages'], ensure_ascii=False, sort_keys=True
                ).encode()).hexdigest()
                assert my_sha == donor['messages_sha256'], 'PROMPT_IDENTITY_BROKEN'
                # endpoint belongs to the TARGET model, not the body donor
                ep = next(pr['endpoint'] for rid, pr in plan_reqs.items()
                          if frozen_reqs[rid]['model'] == obs['model'])
                r = dict(request_id=obs['request_id'], body=body, endpoint=ep)
                # --- pre-dispatch reservation check ---
                in_ub, out_ub = WORST[obs['model']]
                rate = RATES[obs['model']]
                worst = (Decimal(in_ub) * Decimal(rate['input'])
                         + Decimal(out_ub) * Decimal(rate['output'])) / Decimal(10**6)
                cur = rate['currency']
                assert spent[cur] + worst <= MINI_CAPS[cur], 'RESERVATION_EXCEEDS_CAP'
                print(f'{obs["request_id"]}: reserved worst {cur} {worst:.6f} '
                      f'(spent {spent[cur]:.6f} <= cap {MINI_CAPS[cur]})', flush=True)
                # --- dispatch (one-shot, 180s client deadline) ---
                env = http_transport.call_once(r, keys[obs['model']], timeout_s=180)
                parsed = http_transport.parse_response(
                    env, r, {obs['model']})
                u = parsed['usage']
                assert u['prompt_tokens'] <= in_ub, 'INPUT_BOUND_VIOLATION'
                assert u['completion_tokens'] <= out_ub, 'OUTPUT_CAP_VIOLATION'
                assert parsed['finish_reason'] == 'stop', 'TRUNCATED_OR_INCOMPLETE'
                e = est_native(obs['model'], u)
                spent[cur] += e
                rec = dict(
                    request_id=obs['request_id'], arm=obs['arm_label'],
                    node=obs['node'], model_requested=obs['model'],
                    model_returned=parsed['model_returned'],
                    endpoint=r['endpoint'],
                    body_sha256=hashlib.sha256(json.dumps(
                        body, ensure_ascii=False, sort_keys=True).encode()
                    ).hexdigest(),
                    messages_sha256=my_sha,
                    donor_request=obs['donor'],
                    usage=u, finish_reason=parsed['finish_reason'],
                    reasoning_tokens=parsed['reasoning_tokens'],
                    cached_tokens=parsed['cached_tokens'],
                    currency=cur, public_cold_miss_estimate=str(e),
                    actual_cash=None, bill_status='PENDING_ACCOUNT_BILL_VERIFICATION',
                    client_call_wall_s=env['client_call_wall_s'],
                    status='COMMITTED', evidence_class='REAL_HTTP_ATTEMPT',
                    automatic_retries=0, response_id=parsed['response_id'])
                records.append(rec)
                (OUT / f'{obs["request_id"]}_RECORD.json').write_text(json.dumps(
                    rec, ensure_ascii=False, indent=1))
                (OUT / f'{obs["request_id"]}_MODEL_OUTPUT.txt').write_text(
                    parsed['raw_output'])
                (OUT / f'{obs["request_id"]}_TRANSPORT.json').write_text(json.dumps(
                    {k: v for k, v in env.items() if k != 'raw_body'},
                    ensure_ascii=False, indent=1, default=str))
                # --- per-branch lane check (executor semantics) ---
                lane = terminal.evaluate({obs['node']: parsed['raw_output']})
                lane_ok = lane['branches'][obs['node']]['numeric_lane_legal']
                print(f'  -> in={u["prompt_tokens"]} out={u["completion_tokens"]} '
                      f'{cur} {e:.6f} finish={parsed["finish_reason"]} '
                      f'lane_legal={lane_ok} '
                      f'wall={env["client_call_wall_s"]:.2f}s', flush=True)
                if not lane_ok:
                    raise Halt('NUMERIC_LANE_CONTRACT_FAILURE_' + obs['request_id'])
                # --- FULL DAG merge with real-run partner ---
                merged = terminal.evaluate({
                    obs['node']: parsed['raw_output'],
                    obs['partner_node']: obs['partner'].read_text()})
                verdicts.append(dict(
                    allocation=obs['arm_label'], evaluation=merged,
                    new_node=obs['node'], new_model=obs['model'],
                    partner_from='REAL_RUN R1 (byte-identical prompts)'))
                print(f'  [MERGE {obs["arm_label"]}] content_Q='
                      f'{merged["content_Q"]} legal_correct/6='
                      f'{merged["legal_correct_targets_over_six"]} '
                      f'all_lanes={merged["all_branches_numeric_lane_legal"]}',
                      flush=True)
            result = dict(status='COMPLETE', records=records, verdicts=verdicts,
                          spent_native={k: str(v) for k, v in spent.items()},
                          caps={k: str(v) for k, v in MINI_CAPS.items()},
                          note='2 calls exactly; estimates not bills; merge '
                               'judged on full rebuilt DAG terminal output')
            (OUT / 'MINI_OBS_RESULT.json').write_text(json.dumps(
                result, ensure_ascii=False, indent=1))
            print(json.dumps({k: result[k] for k in
                              ('status', 'spent_native')}, ensure_ascii=False))
        except BaseException as exc:
            (OUT / 'MINI_OBS_INCOMPLETE.json').write_text(json.dumps(dict(
                status='INCOMPLETE', reason=repr(exc), records=records,
                spent_native={k: str(v) for k, v in spent.items()},
                traceback=traceback.format_exc()), indent=1))
            print(f'INCOMPLETE: {exc}')
    

if __name__ == '__main__':
    main()
