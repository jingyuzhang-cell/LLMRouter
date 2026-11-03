"""Full 36-execution Phase Pi matrix: S1, S1b x 6 arms x 3 reps.
Reuses the smoke's S1-r1 calls via purpose caching; runs the remaining 30."""
import json, sys, time
sys.path.insert(0, '.'); sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import engine_v22 as E
import real_provider_v22 as R
import scoring_v22 as S
from stage_d_v2_transport import Transport, Ledger

SCEN = ('S1', 'S1b')
REPS = (1, 2, 3)

def tag_for(arm, rep):
    return f'{arm}|' if rep == 1 else f'{arm}|r{rep}|'

def main():
    ledger = Ledger('/root/research_outputs/static_pi/stage_d/v2/PILOT_V2_LEDGER.jsonl')
    tr = Transport(ledger, cap_calls=330, cap_tokens=4_030_000)
    rows = []
    for sc in SCEN:
        for rep in REPS:
            for arm in E.ARMS:
                prov = R.RealProvider(tr, ledger, sc, cap_calls=16, tag=tag_for(arm, rep))
                try:
                    r = E.run_execution(arm, sc, cap_calls=16, provider=prov, simulated=False)
                except Exception as ex:
                    rows.append(dict(task_id='T1', scenario_id=sc, repeat_id=rep, arm=arm,
                                     error=f'{type(ex).__name__}: {ex}'[:160]))
                    print(f"  {sc} r{rep} {arm:12s} ERROR {type(ex).__name__}", flush=True)
                    continue
                sc_res = S.score_terminal_record(r)
                merged = r['outputs'].get('E2_merge') or r['outputs'].get('E1_merge') or {}
                has_pos = bool(isinstance(merged, dict) and merged.get('positions'))
                rows.append(dict(task_id='T1', scenario_id=sc, repeat_id=rep, arm=arm,
                                 pair_id=f'T1|{sc}|r{rep}', calls=r['call_count'], stop=r['stop_reason'],
                                 tp=sc_res['tp'], q=sc_res['q'], claims=sc_res.get('claims'),
                                 positions=has_pos, dag_version=r['dag_version'],
                                 z=len(r['z_actions']), pi=len(r['pi_scope']),
                                 l1_fixed=r['l1_fixed'], residual=r['residual'],
                                 thinking_mode='glm:enabled/low|ds:disabled',
                                 cost_yuan=None))
                print(f"  {sc} r{rep} {arm:12s} calls={r['call_count']:2d} stop={r['stop_reason']:11s} "
                      f"TP={sc_res['tp']:2d} Q={sc_res['q']:.4f} pos={has_pos} dag_v={r['dag_version']}", flush=True)
    # attach per-execution cost from the ledger slice
    json.dump(dict(batch='PHASE_PI_V2', task_id='T1', simulated=False, executions=rows,
                   calls=len(ledger.records), tokens=ledger.tokens, cost_yuan=round(ledger.cost, 6)),
              open('PILOT_V2_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n  total calls={len(ledger.records)}/576 tokens={ledger.tokens} cost=¥{ledger.cost:.4f}")

if __name__ == '__main__':
    main()
