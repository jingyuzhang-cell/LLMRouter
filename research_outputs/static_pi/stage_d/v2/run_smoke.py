"""Six real smoke executions: one per arm on S1. Cap 16 calls/execution (<=96 total)."""
import json, os, sys, time
sys.path.insert(0, '.')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import engine_v22 as E
import real_provider_v22 as R
import scoring_v22 as S
from stage_d_v2_transport import Transport, Ledger

def main():
    ledger = Ledger('/root/research_outputs/static_pi/stage_d/v2/PILOT_LEDGER.jsonl')
    tr = Transport(ledger, cap_calls=576, cap_tokens=4_500_000)
    rows = []
    for arm in E.ARMS:
        t0 = time.time()
        prov = R.RealProvider(tr, ledger, 'S1', cap_calls=16, tag=f'{arm}|')
        try:
            r = E.run_execution(arm, 'S1', cap_calls=16, provider=prov, simulated=False)
        except Exception as ex:
            rows.append(dict(arm=arm, error=f'{type(ex).__name__}: {ex}'[:200]))
            print(f"  {arm:14s} ERROR {type(ex).__name__}: {str(ex)[:120]}", flush=True)
            continue
        sc = S.score_terminal_record(r)
        merged = r['outputs'].get('E2_merge') or r['outputs'].get('E2') or {}
        has_pos = bool(isinstance(merged, dict) and merged.get('positions'))
        src_node = 'E2_merge' if 'E2_merge' in r['outputs'] else 'E2'
        n_calls = r['call_count']
        cost = sum(c.get('accounting_yuan', 0) for c in ledger.records[-n_calls:]) if n_calls else 0
        rows.append(dict(arm=arm, calls=n_calls, stop=r['stop_reason'], tp=sc['tp'], q=sc['q'],
                         positions=has_pos, dag_v=r['dag_version'],
                         z=len(r['z_actions']), pi=len(r['pi_scope']),
                         cost_yuan=round(cost, 6), wall_s=round(time.time()-t0, 1),
                         e2_state=r['states'].get('E2'), err=None))
        print(f"  {arm:14s} calls={n_calls:2d} stop={r['stop_reason']:11s} TP={sc['tp']:2d} Q={sc['q']:.4f} "
              f"positions={has_pos} dag_v={r['dag_version']} ¥{cost:.4f} {time.time()-t0:.0f}s", flush=True)
    json.dump(dict(batch='PHASE_PI_SMOKE_V1', simulated=False, executions=rows,
                   calls=len(ledger.records), tokens=ledger.tokens,
                   cost_yuan=round(ledger.cost, 6)),
              open('SMOKE_RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"\n  total calls={len(ledger.records)} tokens={ledger.tokens} cost=¥{ledger.cost:.4f}")

if __name__ == '__main__':
    main()
