"""Node GAP Audit: score every (node, model) and quantify the node-level gap.

Zero generation. Scoring per frozen PROTOCOL: extraction = v1 operand recall;
transformation = parsed value vs gold; reasoning = v1 expression-on-gold-facts;
verification = verdict matches expect_accept (wrong_fact reported as diagnostic
only). Writes NODE_GAP_AUDIT.json with the per-type table, leave-top-k-out gap
robustness, and per-node winner structure.
"""
import argparse
import json

import numpy as np

from . import core
from . import tool_aware_v1 as v

OUT = v.OUT / 'node_benchmark'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
POOL = ['medium', 'large', 'coder']  # frozen router pool; R1 = capability shadow


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def score(node, answer):
    try:
        if node['node_type'] == 'extraction':
            return float(any(close(f['value'], node['gold_operand'])
                             for f in v.parse_facts(answer)['facts']))
        if node['node_type'] == 'transformation':
            return float(close(v.decode(answer)['value'], node['gold_value']))
        if node['node_type'] == 'reasoning':
            return float(close(v.calculate(v.decode(answer)['expression'], node['gold_facts']), node['answer']))
        if node['node_type'] == 'verification':
            return float(v.decode(answer)['verdict'] == ('yes' if node['expect_accept'] else 'no'))
    except Exception:
        return 0.0
    return 0.0


def run():
    if (OUT / 'NODE_GAP_AUDIT.json').exists():
        raise FileExistsError('Node gap audit already exists')
    nodes = {n['node_id']: n for n in json.loads((OUT / 'NODES.json').read_text())}
    responses = {}
    for s in SLOTS:
        for r in core.lines(OUT / (s + '_RESPONSES.jsonl')):
            for nid in r['node_ids']:
                responses[(nid, s)] = r
    q = {}
    missing = 0
    for nid, node in nodes.items():
        for s in SLOTS:
            row = responses.get((nid, s))
            if row is None or row['status'] != 'delivered' or not row.get('answer'):
                q[(nid, s)] = None
                missing += 0 if row is not None else 1
            else:
                q[(nid, s)] = score(node, row['answer'])
    table = {}
    for nt in ['extraction', 'transformation', 'reasoning', 'verification']:
        ids = [nid for nid, n in nodes.items() if n['node_type'] == nt]
        per_model = {s: float(np.mean([q[(nid, s)] for nid in ids])) for s in SLOTS}
        oracle = float(np.mean([max(q[(nid, s)] for s in SLOTS) for nid in ids]))
        oracle_pool = float(np.mean([max(q[(nid, s)] for s in POOL) for nid in ids]))
        best_fixed = max(POOL, key=lambda s: per_model[s])
        gains = sorted(((max(q[(nid, s)] for s in POOL) - q[(nid, best_fixed)]) for nid in ids), reverse=True)
        n_win = sum(g > 0 for g in gains)
        drop_k = {f'remove_top_{k}': float(np.mean(sorted((max(q[(nid, s)] for s in POOL) - per_model[best_fixed])
                                                          for nid in ids)[k:]))
                  for k in (0, 1, 2)}
        table[nt] = dict(n=len(ids), per_model=per_model, best_fixed_model=best_fixed,
                         best_fixed=per_model[best_fixed], oracle_pool=oracle_pool,
                         oracle_all=oracle, gap_pool=oracle_pool - per_model[best_fixed],
                         nodes_with_pool_winner_advantage=n_win,
                         gap_after_removing_top_k_drivers=drop_k,
                         r1_shadow_note='R1 column is capability data only; not in frozen pool')
    core.write(OUT / 'NODE_GAP_AUDIT.json', dict(
        scored_nodes=len(nodes), models=SLOTS, frozen_pool=POOL,
        missing_cells=missing, by_type=table,
        gates=dict(gate1=[nt for nt, d in table.items() if d['gap_pool'] > 0
                          and d['nodes_with_pool_winner_advantage'] > 2
                          and d['gap_after_removing_top_k_drivers']['remove_top_2'] > 0])))
    print(json.dumps({nt: dict(n=d['n'], **{f'Q_{s}': round(d['per_model'][s], 3) for s in SLOTS},
                                 BestFixed=f"{d['best_fixed_model']}:{d['best_fixed']:.3f}",
                                 OraclePool=round(d['oracle_pool'], 3), GAP=round(d['gap_pool'], 3),
                                 winners=d['nodes_with_pool_winner_advantage'],
                                 gap_rm2=round(d['gap_after_removing_top_k_drivers']['remove_top_2'], 3))
                      for nt, d in table.items()}, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
