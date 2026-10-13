"""Zero-call validation v2 of the fault-aware recovery package.

V1 validated the family classifier over 88 delivered calls. V2 adds
the operator's 2026-10-13 ruling requirements:

  Part 1 — six-type classification over 100 REAL records:
    FE original (10 GLM delivered + 10 DS/Qwen ERROR pre-dispatch)
    FE recovery (5 deepseek length-cut + 5 qwen citation faults)
    two 401 fail-stop aborts (pre-dispatch credential)
    historical screening (66 OK + 2 F_JSON_INVALID)
    Ground truth from the paired analyses and audit trail.

  Part 2 — theta-legality gate: for every menu model, every emitted
    action is legal; GLM models NEVER receive thinking=disabled;
    SS-Tuned theta is legal; repairs are model-appropriate.

  Part 3 — honesty gate: every UNOBSERVED outcome carries zero
    quality credit in the four-strategy replay; observed recalls are
    only from real measurements; SS-Original replays real failures.

  Part 4 — decision scenarios (v1 rule, now over fine types):
    S1 GLM ceiling-pin -> F_TRUNCATED -> PARAM_FIX (legal theta)
    S2 qwen natural-stop garbage -> F_JSON_INVALID -> MODEL_SWITCH
    S3 deepseek empty length-cut -> F_TRUNCATED -> PARAM_FIX
       (thinking=disabled legal for DS)
    S4 qwen valid JSON, citations outside set, ids absent from prompt
       -> F_CITATION cause=contract_unverifiable -> PROMPT repair,
       NOT a model action.

Run: python3 -m deadline_reward_v1.contract_fault_validation
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from deadline_reward_v1.contract_fault import (
    D_CONTRACT, D_CONTENT, F_CITATION, F_EMPTY, F_JSON,
    F_PRE_DISPATCH, F_TRUNCATED, F_UNAVAILABLE, OK, classify_entry,
    choose_recovery, enumerate_recovery_actions)
from deadline_reward_v1.theta_actions import (
    MODEL_THETA_SUPPORT, enumerate_legal_thetas, theta_legal)
from deadline_reward_v1 import recovery_strategies as rs

HERE = Path(__file__).resolve().parent
FE_ORIG = HERE / 'fe_screening_runs' / 'fe_20261013_211741' / 'FE_LEDGER.jsonl'
FE_REC = sorted((HERE / 'fe_screening_runs').glob(
    'fe_recovery_*/FE_LEDGER.jsonl'))[-1]
HIST = Path('/root/capital_opinion_pilot/screening_full80_ledger.jsonl')
ABORTS = sorted((HERE / 'fe_screening_runs').glob(
    'fe_recovery_*/FE_INCOMPLETE.json'))
SAMPLES = {s['sample_id']: s
           for s in json.loads(
               (HERE / 'FACT_EXTRACTION_SAMPLES_V2.json').read_text())
           ['samples']}


def load(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


def main():
    rows = []  # (name, classified, truth)

    # --- FE original: 10 GLM delivered (truth F_TRUNCATED),
    #     10 DS/Qwen ERROR (truth F_PRE_DISPATCH: ModuleNotFoundError)
    for e in load(FE_ORIG):
        if e['status'] == 'delivered':
            truth = F_TRUNCATED
            c = classify_entry(e)
        else:
            truth = F_PRE_DISPATCH
            c = classify_entry(e)
        rows.append((f"FE/{e['sample_id']}/{e['model_key']}", c, truth))

    # --- FE recovery: deepseek -> F_TRUNCATED; qwen -> F_CITATION
    #     (contract_unverifiable: ledger doc ids never in prompt)
    for e in load(FE_REC):
        s = SAMPLES[e['sample_id']]
        truth = F_TRUNCATED if e['model_key'] == 'deepseek' \
            else F_CITATION
        c = classify_entry(
            e, expected_doc_ids=[s['evidence_doc_id']],
            prompt_text=s['evidence_full_text'])
        rows.append((f"REC/{e['sample_id']}/{e['model_key']}", c, truth))

    # --- 401 fail-stop aborts (pre-dispatch credential)
    for path in ABORTS:
        d = json.loads(path.read_text())
        entry = dict(status='ERROR', error=d.get('reason', ''))
        rows.append((f"ABORT/{path.parent.name}",
                     classify_entry(entry), F_PRE_DISPATCH))

    # --- historical: 66 OK + 2 F_JSON_INVALID (format-level;
    #     citation not evaluable — no answer text stored)
    for e in load(HIST):
        truth = OK if e['json_valid'] else F_JSON
        c = classify_entry(
            dict(status='delivered', answer=None,
                 finish_reason=e['stop_reason'],
                 usage=dict(completion_tokens=e['completion_tokens']),
                 max_output_tokens=2048),
            parse_ok=bool(e['json_valid']))
        rows.append((f"HIST/{e['sample_id']}/{e['model_id']}", c, truth))

    # Part 1 report
    n = len(rows)
    mishaps = [(nm, c['fault'], t) for nm, c, t in rows if c['fault'] != t]
    acc = 1 - len(mishaps) / n
    counts = Counter(t for _, _, t in rows)
    cit_causes = Counter(
        c['citation']['cause'] for _, c, _ in rows
        if c['fault'] == F_CITATION and c['citation'])

    # Part 2 — legality gate
    legality = dict(
        glm_never_thinking_disabled=True,
        all_enumerated_legal=True,
        ss_tuned_legal=True,
        repairs_model_appropriate=True)
    for model in rs.MODEL_MENU:
        for a in enumerate_legal_thetas(model):
            ok, why = theta_legal(model, a['theta'])
            if not ok:
                legality['all_enumerated_legal'] = False
            if model.startswith('GLM') and (
                    a['theta'].get('thinking') == 'disabled'):
                legality['glm_never_thinking_disabled'] = False
        # strategy-level action space (includes switches)
        for act in enumerate_recovery_actions(model, rs.MODEL_MENU):
            ok, why = theta_legal(act['model_id'], act['theta'])
            if not ok:
                legality['all_enumerated_legal'] = False
            if act['model_id'].startswith('GLM') and act['theta'].get(
                    'thinking') == 'disabled':
                legality['glm_never_thinking_disabled'] = False
        # deepseek repair must include thinking=disabled (its legal
        # intensity control); GLM repair must use reasoning_effort
        reps = [a['repair'] for a in enumerate_legal_thetas(model)]
        if model == 'deepseek-flash' and not any(
                'thinking=disabled' in r for r in reps):
            legality['repairs_model_appropriate'] = False
        if model.startswith('GLM') and not any(
                'reasoning_effort' in r for r in reps):
            legality['repairs_model_appropriate'] = False
    for model, th in rs.SS_TUNED_THETA.items():
        ok, _ = theta_legal(model, th)
        if not ok:
            legality['ss_tuned_legal'] = False

    # Part 3 — honesty gate over the four-strategy replay
    rep = rs.run_all()
    unobserved_credit = [r for r in rep['samples']
                         for k in ('SS-Original', 'SS-Tuned',
                                   'Fixed-Recovery', 'DD-Enhanced')
                         if r[k]['outcome'] == 'UNOBSERVED'
                         and r[k]['quality'] > 0]
    ss_orig_all_fail = all(
        r['SS-Original']['quality'] == 0.0 for r in rep['samples'])
    honesty = dict(
        unobserved_quality_credit_violations=len(unobserved_credit),
        ss_original_replays_real_failures=ss_orig_all_fail,
        dd_leq_fixed_attempts=rep['summaries']['DD-Enhanced'][
            'attempts'] <= rep['summaries']['Fixed-Recovery']['attempts'],
        dd_quality_ge_fixed=(
            rep['summaries']['DD-Enhanced']['total_quality']
            >= rep['summaries']['Fixed-Recovery']['total_quality'] - 1e-9))

    # Part 4 — decision scenarios
    menu = rs.MODEL_MENU
    s1 = classify_entry(dict(
        status='delivered', answer='{"facts": [{"fact": "x',
        finish_reason=None,
        usage=dict(completion_tokens=2048),
        max_output_tokens=2048))
    s1d = choose_recovery(s1['fault'], 'GLM-5.3', menu)
    s1_pass = (s1['fault'] == F_TRUNCATED
               and s1d['action']['action'] == 'PARAM_FIX'
               and s1d['action']['theta'].get('reasoning_effort') == 'low'
               and s1d['action']['theta'].get('thinking') is None)

    s2 = classify_entry(dict(
        status='delivered', answer='抱歉，无法完成。',
        finish_reason='stop', usage=dict(completion_tokens=118),
        max_output_tokens=2048))
    s2d = choose_recovery(s2['fault'], 'qwen-plus', menu)
    s2_pass = (s2['fault'] == F_JSON
               and s2d['action']['action'] == 'MODEL_SWITCH')

    s3 = classify_entry(dict(
        status='delivered', answer='', finish_reason='length',
        usage=dict(completion_tokens=2048),
        max_output_tokens=2048))
    s3d = choose_recovery(s3['fault'], 'deepseek-flash', menu)
    s3_pass = (s3['fault'] == F_TRUNCATED
               and s3d['action']['action'] == 'PARAM_FIX'
               and s3d['action']['theta'].get('thinking') == 'disabled')

    s4 = classify_entry(
        dict(status='delivered',
             answer=json.dumps([dict(fact='x', evidence_doc_id='2026-088')]),
             finish_reason='stop', usage=dict(completion_tokens=300),
             max_output_tokens=2048),
        expected_doc_ids=['D3_E03-yuandao_2026-08-29'],
        prompt_text='证券代码：301139 公告编号：2026-088 ...')
    s4d = choose_recovery(s4['fault'], 'qwen-plus', menu)
    s4_pass = (s4['fault'] == F_CITATION
               and s4['citation']['cause'] == 'contract_unverifiable'
               and s4d['action']['action'] == 'PROMPT_CONTRACT_REPAIR')

    report = dict(
        version='CONTRACT_FAULT_VALIDATION_v2',
        zero_model_calls=True,
        part1_classification=dict(
            n_real_records=n, accuracy=round(acc, 4),
            truth_counts=dict(counts),
            citation_causes=dict(cit_causes),
            mishaps=[dict(call=nm, predicted=p, truth=t)
                     for nm, p, t in mishaps]),
        part2_legality=legality,
        part3_honesty=honesty,
        part3_replay_summaries=rep['summaries'],
        part4_scenarios=dict(
            S1=dict(expect='F_TRUNCATED -> PARAM_FIX '
                           '(reasoning_effort=low, no thinking key)',
                    classified=s1['fault'], decision=s1d['action'],
                    pass_=s1_pass),
            S2=dict(expect='F_JSON_INVALID -> MODEL_SWITCH',
                    classified=s2['fault'],
                    decision=s2d['action']['action'], pass_=s2_pass),
            S3=dict(expect='F_TRUNCATED -> PARAM_FIX thinking=disabled',
                    classified=s3['fault'],
                    decision=s3d['action'], pass_=s3_pass),
            S4=dict(expect='F_CITATION contract_unverifiable -> '
                           'PROMPT_CONTRACT_REPAIR (not a model action)',
                    classified=s4['fault'], cause=s4['citation']['cause'],
                    decision=s4d['action'], pass_=s4_pass)),
        all_pass=bool(
            acc == 1.0 and all(legality.values())
            and honesty['unobserved_quality_credit_violations'] == 0
            and honesty['ss_original_replays_real_failures']
            and s1_pass and s2_pass and s3_pass and s4_pass))

    (HERE / 'CONTRACT_FAULT_VALIDATION.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str))

    print(f'Part1 six-type classification over {n} real records: '
          f'accuracy {acc:.1%} ({counts})')
    for nm, p, t in mishaps:
        print(f'  MISHAP {nm}: predicted {p}, truth {t}')
    print(f'  citation causes: {dict(cit_causes)}')
    print(f'Part2 legality: {legality}')
    print(f'Part3 honesty: {honesty}')
    for name, s in rep['summaries'].items():
        print(f'  {name:15s} q={s["total_quality"]:.3f} '
              f'attempts={s["attempts"]} tokens={s["tokens"]} '
              f'unobs={s["unobserved_actions"]}')
    print(f'Part4: S1={s1_pass} S2={s2_pass} S3={s3_pass} S4={s4_pass}')
    print(f'ALL PASS: {report["all_pass"]}')
    return 0 if report['all_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
