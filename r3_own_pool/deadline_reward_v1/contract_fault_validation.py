"""Zero-call validation of the D-contract fault module.

Part 1 — classifier accuracy over 88 REAL calls:
  - FE original run (10 GLM: ground truth D_CONTRACT x10, via the
    ceiling-pin signature — finish_reason was not recorded there)
  - FE recovery run (5 deepseek-flash length-cut + empty: D_CONTRACT x5;
    5 qwen-plus stop + valid JSON: OK x5)
  - historical screening_full80_ledger (68 calls, all natural stop,
    truncated=False: OK x66, D_CONTENT x2 — the two json_valid=false
    with low completion are content faults, NOT contract faults)

Part 2 — decision-rule stub scenarios (no transport, no calls):
  S1: GLM-5.3 call under a 2048 JSON contract fails with completion
      2048/2048 -> classifier says D_CONTRACT -> choose_recovery must
      pick PARAM_FIX on GLM-5.3 (NOT a switch to deepseek-flash).
  S2: qwen-plus call returns natural-stop garbage -> D_CONTENT ->
      must pick MODEL_SWITCH (param repair must not lead).
  S3: deepseek-flash length-cut empty -> D_CONTRACT -> PARAM_FIX with
      thinking=disabled available (historical compatibility evidence).

Run: python3 -m deadline_reward_v1.contract_fault_validation
"""
from __future__ import annotations

import json
from pathlib import Path

from deadline_reward_v1.contract_fault import (
    D_CONTRACT, D_CONTENT, OK, classify_call, choose_recovery,
    parse_strict_json, enumerate_recovery_actions)

HERE = Path(__file__).resolve().parent
PILOT = Path('/root/capital_opinion_pilot')

FE_ORIG = HERE / 'fe_screening_runs' / 'fe_20261013_211741' / 'FE_LEDGER.jsonl'
FE_REC = sorted((HERE / 'fe_screening_runs').glob(
    'fe_recovery_*/FE_LEDGER.jsonl'))[-1]
HIST = PILOT / 'screening_full80_ledger.jsonl'


def load(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


def main():
    # ---- Part 1: classifier vs real-call ground truth ----
    rows = []
    gt = []

    for e in load(FE_ORIG):
        if e['status'] != 'delivered':
            continue
        c = classify_call(
            answer=e['answer'], finish_reason=None,
            completion_tokens=e['usage']['completion_tokens'],
            max_output_tokens=e['max_output_tokens'])
        rows.append((f"FE/{e['sample_id']}/{e['model_id']}", c, D_CONTRACT))
        gt.append(D_CONTRACT)

    rec = load(FE_REC)
    for e in rec:
        c = classify_call(
            answer=e['answer'], finish_reason=e['finish_reason'],
            completion_tokens=e['usage']['completion_tokens'],
            max_output_tokens=e['max_output_tokens'])
        truth = D_CONTRACT if e['model_key'] == 'deepseek' else OK
        rows.append((f"REC/{e['sample_id']}/{e['model_id']}", c, truth))
        gt.append(truth)

    for e in load(HIST):
        c = classify_call(
            parse_ok=bool(e['json_valid']),
            finish_reason=e['stop_reason'],
            completion_tokens=e['completion_tokens'],
            max_output_tokens=2048)  # execute_screening_80 output_cap
        truth = D_CONTENT if not e['json_valid'] else OK
        rows.append((f"HIST/{e['sample_id']}/{e['model_id']}", c, truth))
        gt.append(truth)

    confusion = {(a, b): 0 for a in (D_CONTRACT, D_CONTENT, OK)
                 for b in (D_CONTRACT, D_CONTENT, OK)}
    for name, c, truth in rows:
        confusion[(truth, c['fault'])] += 1
    acc = sum(confusion[(t, t)] for t in (D_CONTRACT, D_CONTENT, OK)) \
        / len(rows)
    mishaps = [(n, c['fault'], t) for n, c, t in rows
               if c['fault'] != t]

    # ---- Part 2: decision-rule scenarios ----
    menu = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']

    # S1: GLM ceiling-pinned parse failure (exact FE observation shape)
    s1_obs = dict(answer='{"facts": [{"fact": "2026年5月8日',  # truncated
                  finish_reason=None, completion_tokens=2048,
                  max_output_tokens=2048)
    s1_cls = classify_call(**s1_obs)
    s1_dec = choose_recovery(s1_cls['fault'], 'GLM-5.3', menu)
    s1_pass = (s1_cls['fault'] == D_CONTRACT
               and s1_dec['action']['action'] == 'PARAM_FIX'
               and s1_dec['action']['model_id'] == 'GLM-5.3')

    # S2: qwen natural-stop garbage (TL5 historical shape)
    s2_obs = dict(answer='抱歉，我无法完成该任务。',
                  finish_reason='stop', completion_tokens=118,
                  max_output_tokens=2048)
    s2_cls = classify_call(**s2_obs)
    s2_dec = choose_recovery(s2_cls['fault'], 'qwen-plus', menu)
    s2_pass = (s2_cls['fault'] == D_CONTENT
               and s2_dec['action']['action'] == 'MODEL_SWITCH')

    # S3: deepseek length-cut empty (exact FE recovery observation)
    s3_obs = dict(answer='', finish_reason='length',
                  completion_tokens=2048, max_output_tokens=2048)
    s3_cls = classify_call(**s3_obs)
    s3_dec = choose_recovery(s3_cls['fault'], 'deepseek-flash', menu)
    s3_actions = enumerate_recovery_actions('deepseek-flash', menu)
    s3_has_thinking_off = any(
        a['thinking'] == 'disabled' for a in s3_actions
        if a['action'] == 'PARAM_FIX')
    s3_pass = (s3_cls['fault'] == D_CONTRACT
               and s3_dec['action']['action'] == 'PARAM_FIX'
               and s3_has_thinking_off)

    # structural: blind-switch trap is visible in the action list
    # (switching GLM->deepseek-flash offers ONLY a combined repair,
    # because the target is thinking-default)
    glm_switch = [a for a in enumerate_recovery_actions('GLM-5.3', menu)
                  if a['model_id'] == 'deepseek-flash']
    trap_visible = (len(glm_switch) == 2
                    and glm_switch[0]['action'] == 'MODEL_SWITCH'
                    and glm_switch[0].get('contract_pass_prior') == 0.0
                    and glm_switch[1]['action'] == 'MODEL_SWITCH_PARAMS')

    report = dict(
        version='CONTRACT_FAULT_VALIDATION_v1',
        zero_model_calls=True,
        part1_classifier=dict(
            n_real_calls=len(rows),
            ground_truth={D_CONTRACT: gt.count(D_CONTRACT),
                          D_CONTENT: gt.count(D_CONTENT),
                          OK: gt.count(OK)},
            confusion={f'{t}->{p}': n for (t, p), n in confusion.items()
                       if n},
            accuracy=round(acc, 4),
            mishaps=[dict(call=n, predicted=p, truth=t)
                     for n, p, t in mishaps]),
        part2_scenarios=dict(
            S1_glm_ceiling_pin=dict(
                classified=s1_cls['fault'],
                decision=s1_dec['action']['action'],
                target=s1_dec['action']['model_id'],
                pass_=s1_pass,
                expect='D_CONTRACT -> PARAM_FIX on GLM-5.3 (not a '
                       'switch that re-buys the failure)'),
            S2_qwen_content=dict(
                classified=s2_cls['fault'],
                decision=s2_dec['action']['action'],
                target=s2_dec['action']['model_id'],
                pass_=s2_pass,
                expect='D_CONTENT -> MODEL_SWITCH'),
            S3_deepseek_empty=dict(
                classified=s3_cls['fault'],
                decision=s3_dec['action']['action'],
                param_fix_with_thinking_off=s3_has_thinking_off,
                pass_=s3_pass,
                expect='D_CONTRACT -> PARAM_FIX; thinking=disabled '
                       'repair available'),
            blind_switch_trap_visible=trap_visible),
        all_pass=bool(acc == 1.0 and s1_pass and s2_pass and s3_pass
                      and trap_visible))

    out = HERE / 'CONTRACT_FAULT_VALIDATION.json'
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))

    print(f"classifier over {len(rows)} real calls: "
          f"accuracy {acc:.1%}, mishaps {len(mishaps)}")
    for n, p, t in mishaps:
        print(f'  MISHAP {n}: predicted {p}, truth {t}')
    print(f"ground truth: D_CONTRACT={gt.count(D_CONTRACT)}, "
          f"D_CONTENT={gt.count(D_CONTENT)}, OK={gt.count(OK)}")
    print(f"S1 glm->PARAM_FIX:        {s1_pass}")
    print(f"S2 qwen->MODEL_SWITCH:    {s2_pass}")
    print(f"S3 ds->PARAM_FIX+thinkOff:{s3_pass}")
    print(f"blind-switch trap visible:{trap_visible}")
    print(f"ALL PASS: {report['all_pass']}")
    return 0 if report['all_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
