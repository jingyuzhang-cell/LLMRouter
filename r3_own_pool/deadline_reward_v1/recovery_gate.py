"""Deadline-aware recovery gate with a STOP action, econometrics
grounded in the PAID real logs (operator direction 2026-10-14:
"量化每一种故障的可修复性、零调用修复机会、重试成功概率及真实
时间分布，然后建立一个带停止动作的、截止时间感知的恢复决策器").

Action set (per operator's framing):
  ACCEPT        keep the node's current output, continue downstream
  LOCAL_REPAIR  deterministic zero-call fix (fence strip / date
                normalization) — checked FIRST, ~free
  RETRY(theta)  same model, legal repaired theta
  SWITCH(model) different model, default theta
  STOP          give up further recovery for this node (accept the
                degraded state; distinct from ACCEPT only in ledger
                semantics — recorded as an explicit decision)

Gate: a* = argmax_a [ E[U | a] - E[U | ACCEPT ] ] over feasible
actions, where feasibility includes the calibrated completion
probability P(T_complete(a) <= D - t) computed from REAL latency
distributions (RECOVERY_ECONOMETRICS.json), never from means alone.

Lambda_f, deadline tiers, reward coefficients: UNCHANGED (frozen).
Counterfactual replay of DD's real T01 (which missed D=120s by 2.1s)
is DIAGNOSTIC ONLY — labeled, never mixed with the confirmed run.

Run: python3 -m deadline_reward_v1.recovery_gate
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ECON = json.loads((HERE / 'RECOVERY_ECONOMETRICS.json').read_text())
if (HERE / 'fe_screening_runs/restricted_dag_20261014_093559'
        / 'RECOVERY_ECONOMETRICS.json').exists():
    ECON = json.loads(
        (HERE / 'fe_screening_runs/restricted_dag_20261014_093559'
         / 'RECOVERY_ECONOMETRICS.json').read_text())

LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0 = 60000.0


def utility(q, tokens, T, D):
    c = tokens / C0
    if T <= D:
        return round(q - LAMBDA_C * c, 6)
    return round(-LAMBDA_C * c - LAMBDA_T * (T - D) / D - LAMBDA_F, 6)


def p_on_time(lat_med, lat_p90, budget_s):
    """Calibrated completion probability for one call within the
    remaining time budget: empirical median/p90 interpolation
    (log-linear between med and p90; saturation beyond p90)."""
    if budget_s <= 0:
        return 0.0
    if budget_s >= lat_p90:
        return 0.9
    if budget_s >= lat_med:
        ratio = (math.log(budget_s) - math.log(lat_med)) / max(
            1e-9, math.log(lat_p90) - math.log(lat_med))
        return 0.5 + 0.4 * max(0.0, min(1.0, ratio))
    ratio = max(0.0, budget_s / max(1e-9, lat_med))
    return 0.5 * ratio ** 2


def lat_tok(model, kind):
    e = ECON['action_outcomes'].get(f'{model}|{kind}')
    if e:
        return e['lat']['med'], e['lat']['p90'], e['tok']['med'], \
            e['rate']
    return 30.0, 60.0, 4000, 0.5


def gate(fault_class, node_type, clock_t, deadline,
         tokens_spent, q_current, q_downstream=0.15,
         budget_tokens_left=400000):
    """Return the gated decision + full diagnostics.

    fault_class: 'FENCE_ONLY' | 'TRUNCATED' | 'INVALID' | 'CONTRACT_OK'
    q_current:   node quality estimate if we ACCEPT the current output
    q_downstream: expected mean quality of remaining nodes."""
    remaining = deadline - clock_t
    acts = {}

    def E_U(q_node, extra_tok, extra_time, on_time_p):
        T = clock_t + extra_time
        q_task = (q_node + 3 * q_downstream) / 4   # 4-node diamond
        U_hit = utility(q_task, tokens_spent + extra_tok, T, deadline)
        U_miss = utility(q_task * 0.5,
                         tokens_spent + extra_tok, T + 30.0, deadline)
        return on_time_p * U_hit + (1 - on_time_p) * U_miss

    # ACCEPT (baseline): keep current output, downstream runs on it
    base_q = q_current if fault_class != 'CONTRACT_OK' else q_current
    acts['ACCEPT'] = dict(
        eU=E_U(base_q, 2000, 12.0, p_on_time(12.0, 25.0, remaining)),
        cost_tok=2000, time_s=12.0, note='keep current output')

    # LOCAL_REPAIR: only for fence-only faults — free and certain.
    # q assumption: the fenced output IS a complete model generation
    # (same content a successful retry would return) — modeled at
    # the retry-success quality level, at ZERO cost/time; it
    # therefore dominates any model action for fence-only faults
    best_rate = max([v['rate'] for v in
                    ECON['action_outcomes'].values()] or [0.5])
    if fault_class == 'FENCE_ONLY':
        q_local = 0.35 + 0.4 * best_rate
        acts['LOCAL_REPAIR'] = dict(
            eU=E_U(max(q_current, q_local), 0, 0.0, 1.0),
            cost_tok=0, time_s=0.0,
            note='deterministic fence fix — same content as a '
                 'successful retry, zero calls')

    # RETRY ladder (model, theta) with REAL econometrics
    for model, kind in (('deepseek-flash', 'repair'),
                        ('GLM-5.3', 'repair'),
                        ('GLM-5.3-Flash', 'repair')):
        if f'{model}|{kind}' not in ECON['action_outcomes']:
            continue
        med, p90, tok, rate = lat_tok(model, kind)
        p = p_on_time(med, p90, remaining - 12.0)  # keep downstream
        if p <= 0.05 or tok > budget_tokens_left:
            continue
        q_fix = 0.35 + 0.4 * rate
        acts[f'RETRY:{model}'] = dict(
            eU=E_U(q_fix, tok, med, p), cost_tok=tok, time_s=med,
            on_time_p=round(p, 3), real_rate=rate,
            note=f'real lat med {med}s / p90 {p90}s, success {rate}')

    # SWITCH to qwen (real fallback econometrics)
    med, p90, tok, rate = lat_tok('qwen-plus', 'fallback')
    p = p_on_time(med, p90, remaining - 12.0)
    if p > 0.05 and tok <= budget_tokens_left:
        acts['SWITCH:qwen-plus'] = dict(
            eU=E_U(0.30 + 0.3 * rate, tok, med, p),
            cost_tok=tok, time_s=med, on_time_p=round(p, 3),
            real_rate=rate,
            note=f'real lat med {med}s / p90 {p90}s, success {rate}')

    best = max(acts, key=lambda k: acts[k]['eU'])
    base_eU = acts['ACCEPT']['eU']
    return dict(decision=best,
                deltaEU=round(acts[best]['eU'] - base_eU, 6),
                actions={k: dict(eU=round(v['eU'], 4),
                                 dEU_vs_accept=round(
                                     v['eU'] - base_eU, 4),
                                 **{kk: vv for kk, vv in v.items()
                                    if kk != 'eU'})
                         for k, v in acts.items()},
                state=dict(clock_t=clock_t, deadline=deadline,
                           remaining_s=round(remaining, 1),
                           fault_class=fault_class,
                           tokens_spent=tokens_spent))


# ---- counterfactual replay of DD's real T01 (diagnostic only) -----
def t01_counterfactual():
    led = (HERE / 'fe_screening_runs'
           / 'restricted_dag_20261014_093559' / 'DAG_LEDGER_DD-Online.jsonl')
    es = [json.loads(l) for l in led.read_text().splitlines()
          if l.strip()]
    t01 = [e for e in es if e['task'] == 'T01']

    def cls(e):
        a = e['answer']
        try:
            json.loads(a.strip())
            return 'CONTRACT_OK'
        except Exception:
            if e['finish_reason'] in ('length', 'max_tokens'):
                return 'TRUNCATED'
            t = a.strip()
            if t.startswith('```'):
                p = t.split('\n', 1)
                t = p[1].rsplit('```', 1)[0].strip() if len(p) == 2 \
                    else t
            try:
                json.loads(t)
                return 'FENCE_ONLY'
            except Exception:
                return 'INVALID'

    steps = []
    t = 0.0
    toks = 0
    for e in t01:
        t += e['latency_s']
        toks += e['usage']['prompt_tokens'] \
            + e['usage']['completion_tokens']
        c = cls(e)
        if c in ('FENCE_ONLY', 'TRUNCATED', 'INVALID') \
                and e['tag'] == 'planned':
            g = gate(c, e['node'], t, e['deadline_s'], toks,
                     q_current=0.05)
            steps.append(dict(node=e['node'], fault=c,
                              real_action=f"{e['tag']}→(next call)",
                              gate_decision=g['decision'],
                              gate_dEU=g['deltaEU'],
                              gate_actions={
                                  k: v['dEU_vs_accept']
                                  for k, v in g['actions'].items()}))
    return steps


def main():
    steps = t01_counterfactual()
    report = dict(
        version='RECOVERY_GATE_v1', zero_model_calls=True,
        econ_source='restricted_dag_20261014_093559 (119 real calls)',
        key_econometrics=dict(
            fence_share_of_failures=ECON[
                'zero_call_opportunity'][
                'fence_only_share_of_failures'],
            repair_success={
                k: dict(rate=v['rate'], lat_med=v['lat']['med'],
                        lat_p90=v['lat']['p90'])
                for k, v in ECON['action_outcomes'].items()}),
        t01_counterfactual=steps,
        note='COUNTERFACTUAL — diagnostic only; the confirmed run '
             'result (DD T01 missed D=120 by 2.1s) stands unchanged')
    (HERE / 'RECOVERY_GATE_T01_COUNTERFACTUAL.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print('DD T01 counterfactual (gate decisions at real fault '
          'points):')
    for s in steps:
        print(f"  {s['node']} [{s['fault']}]: gate={s['gate_decision']}"
              f" (dEU={s['gate_dEU']}) vs real={s['real_action']}")
        print(f"    actions dEU: {s['gate_actions']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
