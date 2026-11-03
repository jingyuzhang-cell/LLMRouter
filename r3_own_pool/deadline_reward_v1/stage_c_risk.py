"""stage_c_risk — the ONE risk-adjusted discrimination experiment
(operator-directed, zero paid calls). Same 22 anomaly states as
STAGE_C_V1; evaluator corrected on all six required axes:

  1. per-node failure probability p_f (exec success 1-p_f; failure
     delivers q_garbage) — swept, NOT assumed away
  2. common-cause failure correlation rho between replicas (same
     source & same model); diverse-model replicas get rho/2
  3. best-of selection at the redundancy join is IMPERFECT (picks
     the good output with prob s_v only when outputs differ)
  4. redundancy costs enter the ledger: duplicate node + join node
     tokens & latency (join = cross_check-class call)
  5. deadline kept (D as frozen; lateness penalty honest)
  6. REDUNDANT keeps contract/evidence (semantic guard, unchanged)

Policies (same state, same search-eval budget, same evaluator):
  JRP        Joint(R, pi) without structure edits
  JZRP       Joint(Z, R, pi) over semantic-guarded Z options
  RULE_RED   simple rule: REDUNDANT the root unconditionally, then
             greedy (R, pi)   [is joint search better than dumb rule?]

Conditions: p_f in {.05,.15,.30} x rho in {0,.5,.9} x s_v in {.9,.7}
x regime {(Ccap .02, D140) nominal, (Ccap .005, D140) tight-budget,
(Ccap .02, D100) tight-deadline}.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime, Planner, NodeResult, z_options
from runtime_v2_exec import ReplayBackend, Meter, ROLE_LAT_TOK
import runtime_v2_retrieval as RET
from stage_c_v1 import make_state, legal_R_candidates

Q_GARBAGE = 0.05
C0 = 60000.0


def node_q(spec_nodes, n, pi):
    return R.PROFILE[R.ROLE_CLASS[spec_nodes[n]['role']]][
        pi.get(n, 'Flash')][0]


def node_cost(spec_nodes, n, pi):
    m = pi.get(n, 'Flash')
    return ROLE_LAT_TOK.get(spec_nodes[n]['role'], (13.0, 2200))


def expected_quality(spec, state, Rset, pi, p_f, rho, s_v):
    """risk-adjusted expected terminal quality. REDUNDANT regions
    (dup node + join) handled with correlated failure + imperfect
    best-of selection."""
    nodes = {n['id']: n for n in spec['nodes']}
    N = len(nodes)
    w = 1.0 / N
    q_exp = 0.0
    dup_of = {n['id'].rstrip("'"): n['id']
              for n in spec['nodes'] if n['id'].endswith("'")}
    joins = {n['id'] for n in spec['nodes'] if n['role'] == 'cross_check'
             and len(n['inputs']) == 2
             and n['id'].endswith('|join')}
    join_inputs = {n['id']: n['inputs'] for n in spec['nodes']
                   if n['id'] in joins}
    for nid, n in nodes.items():
        qm = node_q(nodes, nid, pi)
        if nid in joins:
            a, b = join_inputs[nid]
            qa, qb = node_q(nodes, a, pi), node_q(nodes, b, pi)
            ma, mb = pi.get(a, 'Flash'), pi.get(b, 'Flash')
            r = rho if ma == mb else rho / 2.0
            p_both = r * p_f                          # common-cause
            p_a = (1 - r) * p_f * (1 - (1 - r) * p_f)  # only A fails
            p_b = (1 - r) * p_f * (1 - (1 - r) * p_f)  # only B fails
            p_none = 1 - p_both - p_a - p_b
            q_pair = (qm * (p_none + s_v * (p_a + p_b))
                      + Q_GARBAGE * (p_both + (1 - s_v) * (p_a + p_b)))
            q_exp += w * (q_pair * (1 - p_f) + Q_GARBAGE * p_f)
        elif nid in dup_of:
            continue        # counted via its join
        else:
            executed_now = (nid in Rset or nid not in state)
            if executed_now:
                q_exp += w * (qm * (1 - p_f) + Q_GARBAGE * p_f)
            elif nid in state:
                q_exp += w * state[nid].q
    return q_exp


def risk_eU(spec, state, Rset, pi, p_f, rho, s_v, Ccap, D):
    nodes = {n['id']: n for n in spec['nodes']}
    cash = state['cash']
    tok = state['tokens']
    for n in nodes:
        if n in Rset or n not in state['done']:
            m = pi.get(n, 'Flash')
            cash += R.PROFILE[R.ROLE_CLASS[nodes[n]['role']]][m][1]
            tok += node_cost(nodes, n, pi)[1]
    if cash > Ccap + 1e-12:
        return -9.0
    by_lvl = {}
    for n in nodes:
        if n in Rset or n not in state['done']:
            d, seen, stack = 0, set(), list(nodes[n]['inputs'])
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                if (x in Rset or x not in state['done']) and x != n:
                    d = max(d, 1)
                    stack.extend(nodes[x]['inputs'])
            by_lvl.setdefault(d, []).append(n)
    lat = state['lat'] + sum(
        max(node_cost(nodes, n, pi)[0] for n in ids)
        for ids in by_lvl.values())
    q = expected_quality(spec, state, Rset, pi, p_f, rho, s_v)
    return q - 0.5 * tok / C0 - max(0.0, lat - D) / D


def state_view(rt):
    return dict(done={n for n, r in rt.state.items()
                      if r.status == 'done'},
                cash=rt.spent['cash'], lat=rt.spent['lat'],
                tokens=rt.spent['tokens'])


def greedy_pi(spec, sv, Rset, p_f, rho, s_v, Ccap, D, budget):
    todo = [n for n in R.topo_order(spec) if n not in sv['done']]
    pi = {n: 'Flash' for n in todo}
    cur = risk_eU(spec, sv, Rset, pi, p_f, rho, s_v, Ccap, D)
    ev = 1
    improved = True
    while improved and ev < budget:
        improved = False
        for n in todo:
            bm, bv = pi[n], cur
            for m in ('DS', 'Qwen'):
                pi2 = dict(pi)
                pi2[n] = m
                v = risk_eU(spec, sv, Rset, pi2, p_f, rho, s_v,
                            Ccap, D)
                ev += 1
                if v > bv + 1e-12:
                    bm, bv = m, v
            if bm != pi[n]:
                pi[n] = bm
                cur = bv
                improved = True
    return cur, pi, ev


def act(policy, spec, rt, p_f, rho, s_v, Ccap, D, budget=120):
    sv = state_view(rt)
    cands, bad = legal_R_candidates(spec, rt.state)
    # TERMINATE option
    nodes = {n['id']: n for n in spec['nodes']}
    w = 1.0 / len(nodes)
    q_term = sum(w * rt.state[n].q for n in rt.state) + \
        sum(w * 0.0 for n in nodes if n not in rt.state)
    best = dict(z='IDENTITY', R=None, pi={}, terminate=True,
                v=q_term - 0.5 * sv['tokens'] / C0 - max(
                    0.0, sv['lat'] - D) / D, evals=1)
    specs_pool = [('IDENTITY', spec)]
    if policy == 'JZRP':
        specs_pool += [(zn, zs) for zn, zs in z_options(spec)
                       if zn != 'IDENTITY']
    if policy == 'RULE_RED':
        rr = [(zn, zs) for zn, zs in z_options(spec)
              if zn.startswith('REDUNDANT')]
        specs_pool = rr[:1] if rr else [('IDENTITY', spec)]
    evals = 1
    for zname, zspec in specs_pool:
        zview = dict(done=set(sv['done']), cash=sv['cash'],
                     lat=sv['lat'], tokens=sv['tokens'])
        zcands, _ = legal_R_candidates(zspec, rt.state)
        for Rset in zcands:
            v, pi, ev = greedy_pi(zspec, zview, Rset, p_f, rho, s_v,
                                 Ccap, D, budget)
            evals += ev
            if v > best['v'] + 1e-12:
                best = dict(z=zname, R=sorted(Rset), pi=pi,
                            terminate=False, v=v, evals=evals)
    return best


def main():
    specs = []
    files = sorted(glob.glob(str(HERE / 'fe_screening_runs' /
                                  'planner_v1_20261028/*_spec.json')))
    for f in files:
        specs.append((Path(f).name[:16], json.loads(Path(f).read_text())))
    provider = RET.LocalCorpusProvider()
    # build the 22 states once (paired)
    states = []
    for name, spec in specs:
        order = R.topo_order(spec)
        for fault in [order[len(order) // 3],
                      order[2 * len(order) // 3]]:
            meter = Meter()
            backend = ReplayBackend(meter, provider)
            rt = make_state(spec, backend, fault, None)
            states.append((name, spec, fault, rt))
    out = []
    for p_f in (0.05, 0.15, 0.30):
        for rho in (0.0, 0.5, 0.9):
            for s_v in (0.9, 0.7):
                for reg, (Ccap, D) in (('nom', (.02, 140.0)),
                                       ('tb', (.005, 140.0)),
                                       ('td', (.02, 100.0))):
                    vals = dict(JRP=[], JZRP=[], RULE=[])
                    zpick = []
                    for name, spec, fault, rt in states:
                        row = {}
                        for pol, key in (('JRP', 'JRP'),
                                         ('JZRP', 'JZRP'),
                                         ('RULE_RED', 'RULE')):
                            import copy
                            rt2 = DAGRuntime(spec, rt.adapter,
                                             spec['constraints'])
                            rt2.state = dict(rt.state)
                            rt2.spent = dict(rt.spent)
                            a = act(pol, spec, rt2, p_f, rho, s_v,
                                    Ccap, D)
                            row[key] = round(a['v'], 4)
                            if key == 'JZRP':
                                zpick.append(a['z'][:12])
                        vals['JRP'].append(row['JRP'])
                        vals['JZRP'].append(row['JZRP'])
                        vals['RULE'].append(row['RULE'])
                    import statistics as st
                    gz = [a - b for a, b in
                          zip(vals['JZRP'], vals['JRP'])]
                    gr = [a - b for a, b in
                          zip(vals['JZRP'], vals['RULE'])]
                    rec = dict(p_f=p_f, rho=rho, s_v=s_v, reg=reg,
                               JRP=round(st.mean(vals['JRP']), 4),
                               JZRP=round(st.mean(vals['JZRP']), 4),
                               RULE=round(st.mean(vals['RULE']), 4),
                               gap_Z=round(st.mean(gz), 4),
                               gap_Z_vs_rule=round(st.mean(gr), 4),
                               Z_pos=sum(1 for x in gz if x > 1e-9),
                               Z_neg=sum(1 for x in gz if x < -1e-9),
                               redundant_pick=sum(
                                   1 for z in zpick
                                   if z.startswith('REDUNDANT')))
                    out.append(rec)
                    print(json.dumps(rec, ensure_ascii=False),
                          flush=True)
    json.dump(out, open(HERE / 'STAGE_C_RISK.json', 'w'),
              ensure_ascii=False, indent=1)
    pos = sum(1 for r in out if r['gap_Z'] > 1e-9)
    print(f'\ncells where Z increment survives: {pos}/{len(out)}')


if __name__ == '__main__':
    main()
