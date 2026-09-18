"""Budget-aware sequential recovery — offline counterfactual simulation over the existing
740 action results. Zero model calls: each node's per-action outcome/tokens/dt are the
measured frozen values; a chain stops at first success. Universe = nodes whose ORIGINAL final
answer was verifiably wrong (ORIG_CORRECTNESS.json), the clean success criterion surfaced by
the retry-semantics audit. Cluster bootstrap by task_uid, fixed seed."""
import json
from collections import defaultdict
from .recovery_matrix_v2_pilot import ACTIONS
from .recovery_matrix_v2_full_prep import OUT

SEED = 20260918
B = 10000
RECOVERY = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']
LABELS = ['evidence', 'reasoning', 'structural']

STRATEGIES = {
    'retry_only': ['retry_same'],
    'switch_only': ['switch_model'],
    'retrieval_then_decompose': ['evidence_retrieval', 'local_decompose'],
    'decompose_then_retrieval': ['local_decompose', 'evidence_retrieval'],
    'retry_then_switch': ['retry_same', 'switch_model'],
    'retry_then_retrieval': ['retry_same', 'evidence_retrieval'],
    'retry_switch_then_retrieval': ['retry_same', 'switch_model', 'evidence_retrieval'],
    'all_four_in_order': RECOVERY,
    'label_conditional': {  # per failure type, informed only by the corrected matrix point estimates
        'evidence': ['retry_same', 'evidence_retrieval'],
        'reasoning': ['retry_same', 'switch_model'],
        'structural': ['retry_same', 'evidence_retrieval']},
    'oracle_upper': 'any',
}
T_REM_GRID = [0.5, 1.0, 2.0, 5.0, None]  # None = unlimited

def load():
    full = json.loads((OUT / 'FULL_RESULTS.json').read_text())['results']
    orig = {r['nid']: r for r in json.loads((OUT / 'ORIG_CORRECTNESS.json').read_text())}
    nodes = []
    for r in full:
        nid = r['node_id']
        o = orig[nid]
        nodes.append(dict(nid=nid, label=r['label'], task_uid=r['task_uid'],
                          orig_correct=o['orig_correct'],
                          succ={a: r['actions'][a]['success'] for a in ACTIONS},
                          cost={a: r['actions'][a]['tokens'] for a in ACTIONS},
                          dt={a: r['actions'][a]['dt_s'] for a in ACTIONS}))
    return nodes

def simulate(nodes, chain, t_rem=None):
    """chain: list of actions or 'any' for oracle. Returns per-node (recovered, tokens, dt)."""
    out = []
    for n in nodes:
        if chain == 'any':
            acts = [a for a in RECOVERY if n['succ'][a]]
            out.append((bool(acts), sum(n['cost'][a] for a in acts), sum(n['dt'][a] for a in acts)))
            continue
        plan = chain if isinstance(chain, list) else chain[n['label']]
        toks = secs = 0.0; rec = False
        for a in plan:
            if t_rem is not None and n['dt'][a] > t_rem - secs:  # infeasible under remaining budget
                continue
            toks += n['cost'][a]; secs += n['dt'][a]
            if n['succ'][a]: rec = True; break
        out.append((rec, toks, secs))
    return out

def stats(sim):
    n = len(sim)
    q = sum(r for r, _, _ in sim) / n if n else None
    c = sum(t for _, t, _ in sim) / n if n else None
    l = sum(s for _, _, s in sim) / n if n else None
    eff = (sum(r for r, _, _ in sim) / (sum(t for _, t, _ in sim) / 1000)) if n and sum(t for _, t, _ in sim) else None
    return dict(n=n, Q=round(q, 4) if q is not None else None, C_mean_tokens=round(c, 1) if c is not None else None,
                L_mean_s=round(l, 3) if l is not None else None,
                recovered_per_1k_tokens=round(eff, 4) if eff is not None else None)

def bootstrap_ci(nodes, sim):
    import random
    rng = random.Random(SEED)
    clusters = defaultdict(list)
    for n, s in zip(nodes, sim): clusters[n['task_uid']].append(s)
    uids = list(clusters.keys())
    if not uids: return None
    qs = []
    for _ in range(B):
        sample = [s for u in [uids[rng.randrange(len(uids))] for _ in uids] for s in clusters[u]]
        qs.append(sum(r for r, _, _ in sample) / len(sample))
    qs.sort()
    return [round(qs[int(0.025 * B)], 4), round(qs[int(0.975 * B) - 1], 4)]

def run():
    nodes_all = load()
    clean = [n for n in nodes_all if not n['orig_correct']]
    report = dict(seed=SEED, B=B, cluster='task_uid',
                  universe_clean=dict(n=len(clean), by_label={l: sum(n['label'] == l for n in clean) for l in LABELS}),
                  reference_full_148={s: stats(simulate(nodes_all, c if not isinstance(c, dict) else 'any'))
                                      for s, c in STRATEGIES.items() if s != 'oracle_upper'},
                  strategies_clean={}, budget_grid={}, corrected_matrix_ci={})
    for name, chain in STRATEGIES.items():
        sim = simulate(clean, chain)
        st = stats(sim)
        st['Q_ci95_cluster'] = bootstrap_ci(clean, sim)
        report['strategies_clean'][name] = st
    # budget grid: feasibility filter on per-action measured dt
    for t in T_REM_GRID:
        report['budget_grid'][str(t)] = {}
        for name in ['retry_only', 'retry_then_switch', 'retry_then_retrieval', 'all_four_in_order', 'oracle_upper']:
            chain = STRATEGIES[name]
            sim = simulate(clean, chain, t_rem=t)
            report['budget_grid'][str(t)][name] = stats(sim)
    # corrected-matrix cluster CIs (R(a | orig wrong))
    for lab in LABELS:
        sub = [n for n in clean if n['label'] == lab]
        report['corrected_matrix_ci'][lab] = {}
        for a in RECOVERY:
            sim = [(n['succ'][a], 0, 0) for n in sub]
            st = stats(sim); st['Q_ci95_cluster'] = bootstrap_ci(sub, sim)
            report['corrected_matrix_ci'][lab][a] = st
    (OUT / 'SEQUENTIAL_RECOVERY.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report

if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
