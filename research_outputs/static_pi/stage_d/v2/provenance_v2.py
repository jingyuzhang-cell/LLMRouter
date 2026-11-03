"""Per-node contribution: which upstream node's output actually carries the
answered value for each slot. Cache-only replay (zero new provider calls).

Heuristic: normalized containment of the answer's core token in the node's
serialized output. Reported as a data-flow diagnostic, not as scoring.
"""
import json, re, sys
sys.path.insert(0, '.')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
import engine_v22 as E
import real_provider_v22 as R
from stage_d_v2_transport import Transport, Ledger

SCEN, REPS, ARMS = ('S1', 'S1b'), (1, 2, 3), E.ARMS
ORDER = ['E1', 'E2', 'E3', 'E4', 'E1_pos', 'E1_rest', 'E2_pos', 'E2_rest', 'E1_merge', 'E2_merge', 'J1', 'J2', 'SINK']


def tag_for(arm, rep):
    return f'{arm}|' if rep == 1 else f'{arm}|r{rep}|'


def norm(x):
    return re.sub(r'\s+', '', str(x or '')).replace('\u3000', '')


def core(got):
    v = norm(got)
    if '_' in v:
        v = v.rsplit('_', 1)[-1]
    v = re.split(r'[（(]', v)[0]
    return v[:20]


def main():
    lg = Ledger('/root/research_outputs/static_pi/stage_d/v2/PILOT_V2_LEDGER.jsonl')
    n0, t0 = len(lg.records), lg.tokens
    tr = Transport(lg, cap_calls=len(lg.records), cap_tokens=10 ** 12)
    rows = []
    for sc in SCEN:
        for rep in REPS:
            for arm in ARMS:
                prov = R.RealProvider(tr, lg, sc, cap_calls=16, tag=tag_for(arm, rep))
                rec = E.run_execution(arm, sc, cap_calls=16, provider=prov, simulated=False)
                texts = {n: norm(json.dumps(o, ensure_ascii=False)) for n, o in rec['outputs'].items()
                         if isinstance(o, (dict, list))}
                sink = rec['outputs'].get('SINK') or {}
                for a in (sink.get('answers') or []) if isinstance(sink, dict) else []:
                    fid, val = a.get('fact_id'), a.get('value')
                    c = core(val)
                    hit = None
                    if c:
                        for node in ORDER:
                            if node in texts and c in texts[node]:
                                hit = node
                                break
                    rows.append(dict(scenario=sc, repeat=rep, arm=arm, fact_id=fid,
                                     value=str(val)[:80], source=hit or 'none'))
    assert len(lg.records) == n0 and lg.tokens == t0, 'cache miss during provenance replay'

    agg = {}
    for arm in ARMS:
        per_node, per_fact = {}, {}
        for r in rows:
            if r['arm'] != arm:
                continue
            per_node[r['source']] = per_node.get(r['source'], 0) + 1
            per_fact.setdefault(r['fact_id'], {}).setdefault(r['source'], 0)
            per_fact[r['fact_id']][r['source']] += 1
        agg[arm] = dict(per_node=per_node, per_fact=per_fact)

    json.dump(dict(batch='PHASE_PI_V2_NODE_CONTRIBUTION', heuristic='normalized containment',
                   new_calls=len(lg.records) - n0, rows=rows, arms=agg),
              open('/root/research_outputs/static_pi/stage_d/v2/NODE_CONTRIBUTION_V2.json', 'w'),
              ensure_ascii=False, indent=1)
    print('zero new calls:', len(lg.records) - n0)
    for arm in ARMS:
        print(arm.ljust(12), agg[arm]['per_node'])


if __name__ == '__main__':
    main()
