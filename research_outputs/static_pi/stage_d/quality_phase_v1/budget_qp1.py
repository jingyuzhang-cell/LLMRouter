"""QP1 quality-phase budget estimate (zero calls)."""
import json, os

ROOT = '/root/research_outputs/static_pi/stage_d'
CANDS = {t['event_key']: t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']}
DEV = ['E06', 'MVR1', 'KANGMEI', 'GUOEN']
HELD = ['E04', 'MVR2', 'ZHANGZIDAO', 'YJT']
ARMS = ['Baseline', 'E1_evidence_extraction', 'E2_per_fact_verification', 'E3_terminal_integration']
REPS = 2
CALLS_PER_EXEC = 7


def contract(ev):
    p = CANDS[ev]['contract']
    if not os.path.isabs(p):
        p = f'{ROOT}/v23a/{p}'
    return json.load(open(p))


def chars(ev):
    c = contract(ev)
    return sum(len(pg.get('text', '')) for d in c['source_pages'].values()
               for pg in (d.get('pages') or {}).values())


rows, tot = [], dict(calls=0, tin=0, tout=0, cost=0.0)
for ev in DEV + HELD:
    ch = chars(ev)
    per_exec_in = ch * 0.6 + 7 * 300      # docs + prompt/fact overhead
    per_exec_out = 7 * 400
    calls = len(ARMS) * REPS * CALLS_PER_EXEC
    tin = per_exec_in * len(ARMS) * REPS
    tout = per_exec_out * len(ARMS) * REPS
    cost = tin * 0.8e-6 + tout * 2.8e-6
    rows.append(dict(task=ev, split='dev' if ev in DEV else 'heldout', chars=ch,
                     calls=calls, in_tokens=int(tin), out_tokens=int(tout),
                     cost_yuan=round(cost, 4)))
    tot['calls'] += calls; tot['tin'] += tin; tot['tout'] += tout; tot['cost'] += cost

out = dict(batch='QP1_QUALITY_PHASE_BUDGET', model_calls=0,
           design=dict(arms=ARMS, dev_tasks=DEV, heldout_tasks=HELD, reps=REPS,
                       calls_per_execution=CALLS_PER_EXEC, executions=len(DEV + HELD) * len(ARMS) * REPS),
           per_task=rows,
           total=dict(calls=tot['calls'], in_tokens=int(tot['tin']), out_tokens=int(tot['tout']),
                      tokens=int(tot['tin'] + tot['tout']), cost_yuan=round(tot['cost'], 3)),
           hard_stop=dict(calls=int(tot['calls'] * 1.2), tokens=int((tot['tin'] + tot['tout']) * 1.25),
                          yuan=round(tot['cost'] * 1.5, 2)),
           note='estimate only; hard stops are ceilings and require separate authorization')
json.dump(out, open(f'{ROOT}/quality_phase_v1/QP1_BUDGET_ESTIMATE.json', 'w'),
          ensure_ascii=False, indent=1)
for r in rows:
    print(r)
print('TOTAL', out['total'], 'HARD STOP', out['hard_stop'])
