"""Expanded candidate space for SA-PGFS, ground truth composed from frozen
measurements (zero model calls).

Design space (offline graph-design Pareto): G = (Y, X, Z) on FRESH tasks;
state conditioning (M reuse policy) is applied on top by `apply_state`.

All level anchors come from ONE panel (frozen200, clean arms) so qualities
are mutually comparable:
    Single                Q=0.550  C=612.8   L=0.46   (clean_single)
    E1E2RV planned none   Q=0.335  C=1485.7  L=4.56   (clean_static,
                          planned = e:large, r:medium, v:coder)
    E1E2RV planned switch Q=0.415  C=2349.1  L=6.51   (clean_dynamic)
Relative model effects are dimensionless ratios from
    fresh_static_confirmation/SCORED_MATRIX.npz  (per node-type x model Q/C/L)
    cross_model_matrix (measured E->R joint Q, 9 combos, n=200)
Calibrated constants:
    GAMMA chain-Q scale:  E1E2RV(planned, none) -> 0.335
    KAPPA extraction context-split cost factor: C(E1E2RV planned) -> 1485.7
    LAM   latency scale: L(E1E2RV planned) -> 4.56
    recovery: r_rec=(0.415-0.335)/(1-0.335) of remaining error; per-failure
              cost (2349.1-1485.7)/0.665, latency (6.51-4.56)/0.665

Documented composition assumptions: (1) succ(m_e,m_r) = rho * q_e * q_r with
rho = measured ER joint / independence product (interaction correction);
(2) dual extraction: both must succeed (extra q_e factor); (3) verification is
QUALITY-NEUTRAL and cost-positive — the measured 7B verifier accepts correct
chains rarely (vfpos ~0.12-0.30) so gating would misrepresent how the panels
actually used it; the real search evaluates V's true effect; (4) judge pick
skill proxied by acc_neg (reject-corrupted capability); (5) parallel branches
take max latency (critical path); (6) recovery multiplicative in remaining
error. This composed truth powers the zero-call search simulation only; real
evaluations replace it in the online phase.
"""
import json
from pathlib import Path

import numpy as np

from .graph_spec import MODELS, Graph

ROOT = Path('/root/r3_own_pool')
FRESH = ROOT / 'static_dag_v0/fresh_static_confirmation'

R_REC, REC_COST_PER_FAIL, REC_LAT_PER_FAIL = 0.1194, 1298.2, 2.932
Q_CEILING = 0.65  # ~clean-panel selective ceiling: union(single 0.55, dynamic 0.415) with correlation discount
CAL = {}


def _node_stats():
    nodes = json.loads((FRESH / 'NODES.json').read_text())
    m = dict(np.load(FRESH / 'SCORED_MATRIX.npz', allow_pickle=False))
    idx = {n['node_id']: i for i, n in enumerate(nodes)}
    groups = {'extraction': [], 'reasoning': [], 'vfpos': [], 'vfneg': []}
    for n in nodes:
        if n['node_type'] in ('extraction', 'reasoning'):
            groups[n['node_type']].append(idx[n['node_id']])
        elif n['node_type'] == 'verification':
            groups['vfpos' if n['node_id'].endswith('vfpos') else 'vfneg'].append(idx[n['node_id']])
    out = {}
    for k, ids in groups.items():
        out[k] = dict(Q=np.mean([m['Q'][i].astype(float) for i in ids], axis=0),
                      C=np.mean([m['C'][i].astype(float) for i in ids], axis=0),
                      L=np.mean([m['L'][i].astype(float) for i in ids], axis=0))
    return out


def _succ(me, mr, st, measured_er):
    """rho * q_e * q_r == measured ER joint Q for the (me, mr) combo."""
    return measured_er[(me, mr)]


def topo(nodes, edges, depth, width, tid, parallel=()):
    return dict(id=tid, nodes=nodes, edges=edges, depth=depth, width=width, parallel=parallel)


TOPOLOGIES = {
    'S': topo([('answer', 'a')], [], 1, 1, 'S'),
    'ER': topo([('extraction', 'e'), ('reasoning', 'r')], [('e', 'r')], 2, 1, 'ER'),
    'ERV': topo([('extraction', 'e'), ('reasoning', 'r'), ('verification', 'v')],
                [('e', 'r'), ('r', 'v')], 3, 1, 'ERV'),
    'ERVcond': topo([('extraction', 'e'), ('reasoning', 'r'), ('verification', 'v')],
                    [('e', 'r'), ('r', 'v')], 3, 1, 'ERVcond'),
    'E1E2R': topo([('extraction', 'e1'), ('extraction', 'e2'), ('reasoning', 'r')],
                  [('e1', 'r'), ('e2', 'r')], 2, 2, 'E1E2R', parallel=[('e1', 'e2')]),
    'E1E2RV': topo([('extraction', 'e1'), ('extraction', 'e2'), ('reasoning', 'r'),
                    ('verification', 'v')],
                   [('e1', 'r'), ('e2', 'r'), ('r', 'v')], 3, 2, 'E1E2RV', parallel=[('e1', 'e2')]),
    'ER1R2J': topo([('extraction', 'e'), ('reasoning', 'r1'), ('reasoning', 'r2'),
                    ('judge', 'j')],
                    [('e', 'r1'), ('e', 'r2'), ('r1', 'j'), ('r2', 'j')], 3, 2, 'ER1R2J_dual_r',
                    parallel=[('r1', 'r2')]),
    'SERJ': topo([('answer', 's'), ('extraction', 'e'), ('reasoning', 'r'), ('judge', 'j')],
                 [('e', 'r'), ('r', 'j'), ('s', 'j')], 3, 2, 'SERJ_union',
                 parallel=[('s', 'e')]),
}


def _calibrate(st, measured_er):
    mi = lambda m: MODELS.index(m)
    planned_c = (2 * st['extraction']['C'][mi('large')] + st['reasoning']['C'][mi('medium')]
                 + st['vfpos']['C'][mi('coder')])
    planned_l = (st['extraction']['L'][mi('large')] + st['reasoning']['L'][mi('medium')]
                 + st['vfpos']['L'][mi('coder')])
    CAL['GAMMA'] = 0.335 / (measured_er[('large', 'medium')] * st['extraction']['Q'][mi('large')])
    CAL['KAPPA'] = (1485.7 - st['reasoning']['C'][mi('medium')] - st['vfpos']['C'][mi('coder')]) \
        / (2 * st['extraction']['C'][mi('large')])
    CAL['LAM'] = 4.56 / planned_l


def build_space():
    st = _node_stats()
    cm = json.loads((ROOT / 'static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json').read_text())['matrix']
    measured_er = {}
    for k, v in cm.items():
        me, mr = k.split('->')
        measured_er[(me.split('_')[1], mr.split('_')[1])] = v['Q']
    _calibrate(st, measured_er)

    graphs, rows = [], []
    for tid, t in TOPOLOGIES.items():
        slots = [s for role, s in t['nodes'] if role != 'answer']
        assigns = [{'a': 'medium'}] if tid == 'S' else \
            [dict(zip(slots, combo)) for combo in _prod([MODELS] * len(slots))]
        recs = ['none'] if tid == 'S' else ['none', 'switch']  # no deployable
        # failure detection on a direct answer -> no recovery semantics for S
        for a in assigns:
            for rec in recs:
                g = Graph(t, a, rec, 'fresh')
                q, c, l = evaluate(g, st, measured_er)
                graphs.append(g)
                rows.append((q, c, l))
    truth = dict(Q=np.array([r[0] for r in rows]), C=np.array([r[1] for r in rows]),
                 L=np.array([r[2] for r in rows]))
    ai = next(i for i, g in enumerate(graphs)
              if g.topo['id'] == 'E1E2RV' and g.recovery == 'none'
              and g.assign == {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'})
    si = next(i for i, g in enumerate(graphs) if g.topo['id'] == 'E1E2RV'
              and g.recovery == 'switch'
              and g.assign == {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'})
    calib = dict(GAMMA=CAL['GAMMA'], KAPPA=CAL['KAPPA'], LAM=CAL['LAM'], n_configs=len(graphs),
                 anchor_static=dict(composed=[round(truth['Q'][ai], 4), round(truth['C'][ai], 1),
                                              round(truth['L'][ai], 2)],
                                   measured=[0.335, 1485.7, 4.56]),
                 anchor_dynamic=dict(composed=[round(truth['Q'][si], 4), round(truth['C'][si], 1),
                                               round(truth['L'][si], 2)],
                                     measured=[0.415, 2349.1, 6.51]))
    return graphs, truth, calib


def _prod(pools):
    out = [()]
    for p in pools:
        out = [o + (m,) for o in out for m in p]
    return out


def evaluate(g, st, measured_er, ext_perfect=False):
    """Composed (Q, C, L) for graph g. ext_perfect: extraction replayed from
    the forest (deterministic, zero calls) — quality 1, cost/latency 0."""
    mi = lambda m: MODELS.index(m)
    t, a = g.topo, g.assign
    qe = np.ones(3) if ext_perfect else st['extraction']['Q']
    Ce = np.zeros(3) if ext_perfect else st['extraction']['C']
    Le = np.zeros(3) if ext_perfect else st['extraction']['L']
    ke = 0.0 if ext_perfect else CAL['KAPPA']
    q_r, acc_neg = st['reasoning']['Q'], st['vfneg']['Q']
    C_r, C_v = st['reasoning']['C'], st['vfpos']['C']
    L_r, L_v = st['reasoning']['L'], st['vfpos']['L']
    GAMMA, LAM = CAL['GAMMA'], CAL['LAM']
    tid = t['id']
    if tid == 'S':
        q, c, l = 0.55, 612.8, 0.46
    else:
        if tid in ('ER', 'ERV', 'ERVcond'):
            me, mr = a['e'], a['r']
            succ = measured_er[(me, mr)]          # rho*q_e*q_r on its own panel
            q = GAMMA * succ / st['extraction']['Q'][mi(me)] * qe[mi(me)]
            c = Ce[mi(me)] + C_r[mi(mr)]
            l = Le[mi(me)] + L_r[mi(mr)]
            if tid == 'ERV':
                c += C_v[mi(a['v'])]
                l += L_v[mi(a['v'])]
            elif tid == 'ERVcond':
                c += 0.5 * C_v[mi(a['v'])] + 20.0
                l += 0.5 * L_v[mi(a['v'])]
        elif tid in ('E1E2R', 'E1E2RV'):
            me, mr = a['e1'], a['r']
            succ = measured_er[(me, mr)]
            q = GAMMA * succ / st['extraction']['Q'][mi(me)] * qe[mi(me)] ** 2
            c = ke * 2 * Ce[mi(me)] + C_r[mi(mr)]
            l = Le[mi(me)] + L_r[mi(mr)]           # parallel e1,e2 -> one L_e
            if tid == 'E1E2RV':
                c += C_v[mi(a['v'])]
                l += L_v[mi(a['v'])]
        elif tid == 'SERJ_union':
            # direct answer ∥ extraction chain -> judge: instantiates the MEASURED
            # complementarity between the single and dynamic arms (selective-oracle
            # headroom on the frozen200 panel). Union gain discounted 0.5 for error
            # correlation; 's' slot fixed to medium (Single anchor).
            me, mr, mj = a['e'], a['r'], a['j']
            p_s = 0.55  # 's' slot fixed to medium (Single anchor)
            p_er = GAMMA * measured_er[(me, mr)] / st['extraction']['Q'][mi(me)] * qe[mi(me)]
            union = 1 - (1 - p_s) * (1 - p_er)
            union_eff = max(p_s, p_er) + 0.5 * (union - max(p_s, p_er))
            q = union_eff * acc_neg[mi(mj)]
            c = 612.8 + Ce[mi(me)] + C_r[mi(mr)] + C_v[mi(mj)]
            chain_l = (Le[mi(me)] + L_r[mi(mr)]) * LAM
            l = max(0.46, chain_l) + L_v[mi(mj)]
        elif tid == 'ER1R2J_dual_r':
            me, m1, m2, mj = a['e'], a['r1'], a['r2'], a['j']
            rho1 = measured_er[(me, m1)] / max(1e-9, st['extraction']['Q'][mi(me)]
                                                * st['reasoning']['Q'][mi(m1)])
            rho2 = measured_er[(me, m2)] / max(1e-9, st['extraction']['Q'][mi(me)]
                                                * st['reasoning']['Q'][mi(m2)])
            pr1, pr2 = rho1 * q_r[mi(m1)], rho2 * q_r[mi(m2)]
            union = 1 - (1 - pr1) * (1 - pr2)
            union_eff = max(pr1, pr2) + 0.4 * (union - max(pr1, pr2))  # error-correlation discount
            q = GAMMA * qe[mi(me)] * union_eff * acc_neg[mi(mj)]
            c = Ce[mi(me)] + C_r[mi(m1)] + C_r[mi(m2)] + C_v[mi(mj)]
            l = Le[mi(me)] + max(L_r[mi(m1)], L_r[mi(m2)]) + L_v[mi(mj)]
        else:
            raise ValueError(tid)
        l *= LAM
    if g.recovery == 'switch':
        q = q + R_REC * (1 - q)
        c = c + REC_COST_PER_FAIL * (1 - q)
        l = l + REC_LAT_PER_FAIL * (1 - q)
    q = min(q, Q_CEILING)
    return float(q), float(c), float(l)


def apply_state(graphs, truth, state='reuse_ext'):
    """State-conditioned objectives for a follow-up task that hits the forest.

    reuse_ext: extraction slots replayed deterministically (perfect, 0 calls);
    reuse_full: whole chain replayed (Arm B semantics: correctness inherited
    from round 1, ~zero new calls). Returns a fresh truth dict.
    """
    st = _node_stats()
    cm = json.loads((ROOT / 'static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json').read_text())['matrix']
    measured_er = {}
    for k, v in cm.items():
        me, mr = k.split('->')
        measured_er[(me.split('_')[1], mr.split('_')[1])] = v['Q']
    Q, C, L = truth['Q'].copy(), truth['C'].copy(), truth['L'].copy()
    for i, g in enumerate(graphs):
        if state == 'reuse_ext':
            q, c, l = evaluate(g, st, measured_er, ext_perfect=True)
            Q[i], C[i], L[i] = q, c, l
        elif state == 'reuse_full':
            Q[i] = truth['Q'][i] * 0.60  # Arm B: round-1 reasoning correctness ceiling
            C[i], L[i] = 1.0, 0.05
    return dict(Q=Q, C=C, L=L)
