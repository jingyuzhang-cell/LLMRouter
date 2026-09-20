"""Multi-objective budget response surface Q(B_C, B_L) — offline over the frozen
116-criterion-pure-failure recovery records (zero model calls).

For each (token budget, latency budget) cell and each sequential recovery policy, an
action is feasible only if its measured tokens fit the remaining token budget AND its
measured latency fits the remaining time budget; the ladder stops at first success.
Reports Q per (policy, cell), oracle Q per cell, regret, and per-policy Pareto/
hypervolume summary against the (C, L) plane."""
import json
import random
from collections import defaultdict

from .recovery_matrix_v2_devset import BASE
from .dynamic_v2_dev import OUT as DEV2
import pathlib
BASE_LIVE = BASE / 'recovery_matrix_v2/full_4983983'

SEED = 20260918
B = 2000
OUT = BASE / 'budget_surface'
RECOVERY = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']
LADDERS = {
    'retry_only': ['retry_same'],
    'retry_then_switch': ['retry_same', 'switch_model'],
    'retry_switch_then_retrieval': ['retry_same', 'switch_model', 'evidence_retrieval'],
    'all_four_in_order': RECOVERY,
}
C_GRID = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 4500, 6000, None]
L_GRID = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, None]

def load():
    full = json.loads((BASE_LIVE / 'FULL_RESULTS.json').read_text())['results']
    orig = {r['nid']: r for r in json.loads((BASE_LIVE / 'ORIG_CORRECTNESS.json').read_text())}
    nodes = []
    for r in full:
        o = orig[r['node_id']]
        if o['orig_correct']: continue
        nodes.append(dict(uid=r['task_uid'], label=r['label'],
                          succ={a: r['actions'][a]['success'] for a in RECOVERY},
                          cost={a: r['actions'][a]['tokens'] for a in RECOVERY},
                          dt={a: r['actions'][a]['dt_s'] for a in RECOVERY}))
    return nodes

def q_at(nodes, ladder, bc, bl):
    """Mean recovery Q under hard token/latency budgets."""
    tot = 0; ok = 0
    for n in nodes:
        rem_c = bc; rem_t = bl; hit = 0
        for a in ladder:
            if n['cost'][a] is None or n['dt'][a] is None: continue
            if rem_c is not None and n['cost'][a] > rem_c: continue
            if rem_t is not None and n['dt'][a] > rem_t: continue
            if rem_c is not None: rem_c -= n['cost'][a]
            if rem_t is not None: rem_t -= n['dt'][a]
            if n['succ'][a]: hit = 1; break
        tot += hit
    return tot / len(nodes)

def oracle_at(nodes, bc, bl):
    tot = 0
    for n in nodes:
        hit = 0
        for a in RECOVERY:
            if n['cost'][a] is None or n['dt'][a] is None: continue
            if bc is not None and n['cost'][a] > bc: continue
            if bl is not None and n['dt'][a] > bl: continue
            if n['succ'][a]: hit = 1; break
        tot += hit
    return tot / len(nodes)

def boot_ci(nodes, ladder, bc, bl):
    rng = random.Random(SEED)
    clusters = defaultdict(list)
    for n in nodes: clusters[n['uid']].append(n)
    uids = list(clusters.keys())
    out = []
    for _ in range(B):
        sample = [n for u in [uids[rng.randrange(len(uids))] for _ in uids] for n in clusters[u]]
        out.append(q_at(sample, ladder, bc, bl))
    out.sort()
    return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]

def run():
    OUT.mkdir(parents=True, exist_ok=True)
    nodes = load()
    rep = dict(seed=SEED, B=B, n=len(nodes),
               grid=dict(token_budgets=[c for c in C_GRID], latency_budgets=[l for l in L_GRID]),
               surface={}, oracle={}, regret={}, frontier_note=None)
    for bc in C_GRID:
        for bl in L_GRID:
            cell = f'C={bc},L={bl}'
            o = round(oracle_at(nodes, bc, bl), 4)
            rep['oracle'][cell] = o
            rep['surface'][cell] = {}
            for name, ladder in LADDERS.items():
                q = round(q_at(nodes, ladder, bc, bl), 4)
                rep['surface'][cell][name] = dict(Q=q, regret=round(o - q, 4))
    # detailed CIs for the headline cells
    rep['ci_highlights'] = {}
    for (bc, bl) in [(0, 0), (500, 1.0), (1000, 2.0), (2000, 3.0), (None, None)]:
        cell = f'C={bc},L={bl}'
        rep['ci_highlights'][cell] = {name: dict(
            Q=round(q_at(nodes, ladder, bc, bl), 4),
            ci95=boot_ci(nodes, ladder, bc, bl)) for name, ladder in LADDERS.items()}
    # best policy per cell (deployable, excl. oracle implied by ladders themselves)
    best = {}
    for cell, d in rep['surface'].items():
        best[cell] = max(d, key=lambda k: d[k]['Q'])
    rep['best_policy_per_cell'] = best
    # hypervolume-style summary per ladder over the token-budget axis (latency unlimited):
    # sum of Q across all grid cells normalized by oracle sum
    for name in LADDERS:
        qs = [rep['surface'][f'C={c},L={bl}'][name]['Q'] for c in C_GRID for bl in L_GRID]
        os_ = [rep['oracle'][f'C={c},L={bl}'] for c in C_GRID for bl in L_GRID]
        rep.setdefault('aggregate', {})[name] = dict(
            mean_Q=round(sum(qs) / len(qs), 4),
            mean_regret=round(sum(o - q for o, q in zip(os_, qs)) / len(qs), 4))
    (OUT / 'BUDGET_SURFACE.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    r = run()
    print(json.dumps(dict(n=r['n'], aggregate=r['aggregate'],
                          best={k: v for k, v in list(r['best_policy_per_cell'].items())[:6]},
                          ci=r['ci_highlights']), ensure_ascii=False, indent=1))
