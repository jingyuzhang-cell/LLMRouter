"""stage_c_v1 — window-1 Stage-C first zero-call sweep.

Same-state paired comparison on the 11 REAL planner-generated DAGs
(not synthetic instances). Action space (lessons baked in):

  A_legal(s) = {TERMINATE}                       # honest give-up:
                 deliver degraded, no repair calls
             × {R : completion-constrained}       # R >= bad nodes +
                 executed-downstream-of-bad (repaired or, under Z,
                 legally substituted)
             × {pi over ALL unexecuted nodes}
             × {Z in semantic-guarded options}

All policies see the identical post-anomaly state (paired), share
the same predicted evaluator and evaluation counter, and their R
choices are completion-constrained identically (fairness).

Policies: STATIC-F (fixed plan, no replan), SIMPLE-DYN, R-ONLY,
PI-ONLY, SEQ-R→PI, SEQ-π→R, ALTERNATING, JOINT(R,π), JOINT(Z,R,π).
Tier: predicted/planning only (real execution = later authorized
Stage-C-real). Lateness honest (D kept, no relaxation).
"""
from __future__ import annotations

import glob
import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path('/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, str(HERE))
sys.path.insert(0, '/root/r3_own_pool')

import dag_runtime_v1 as R
from dag_runtime_v1 import DAGRuntime, Planner, NodeResult, z_options
from runtime_v2_exec import ReplayBackend, Meter, ROLE_LAT_TOK
import runtime_v2_retrieval as RET


def completion_R(spec, state):
    """R must contain every bad node + every already-executed node
    downstream of a bad node (they consumed garbage)."""
    nodes = {n['id']: n for n in spec['nodes']}
    bad = {n for n, r in state.items() if r.status == 'bad'}
    need = set(bad)
    for b in bad:
        need |= (R.closure_of(spec, b) & set(state)) - {b}
    return need, bad


def legal_R_candidates(spec, state):
    """completion-satisfying supersets of the minimal need set,
    bounded: minimal + full-closure options (small legal set)."""
    need, bad = completion_R(spec, state)
    if not bad:
        return [set()], set()
    out = [set(need)]
    full = set()
    for b in bad:
        full |= R.closure_of(spec, b)
    if full != need:
        out.append(full & (set(state) | need))
    return out, bad


def make_state(spec, backend, fault, rng):
    rt = DAGRuntime(spec, backend, spec['constraints'])
    order = R.topo_order(spec)
    for nid in order:
        node = [n for n in spec['nodes'] if n['id'] == nid][0]
        rt.execute_node(node, 'Flash')
        if nid == fault:
            r = rt.state[nid]
            rt.state[nid] = NodeResult(
                'bad', q=R.Q_GARBAGE, output_text='', tokens=r.tokens,
                lat=r.lat, cash=r.cash, model=r.model,
                source='FAULT_INJECTED')
            break
    return rt


def eval_action(rt, Rset, pi, terminate=False):
    """predicted-tier eU of executing (Rset, pi); TERMINATE = deliver
    current degraded state, zero further calls."""
    nodes = {n['id']: n for n in rt.spec['nodes']}
    if terminate:
        q = sum((1 / len(nodes)) * (rt.state[n].q if n in rt.state
                                    else 0.0) for n in nodes)
        lat = rt.spent['lat']
        return q - 0.5 * rt.spent['tokens'] / 60000.0 - max(
            0.0, lat - rt.D) / rt.D
    todo = [n for n in nodes if n not in rt.state or n in Rset]
    cash = rt.spent['cash']
    tok = rt.spent['tokens']
    for n in todo:
        cash += 0.0                     # Flash-only tier
        tok += ROLE_LAT_TOK.get(nodes[n]['role'], (13, 2200))[1]
    by_lvl = {}
    for n in todo:
        d, seen, stack = 0, set(), list(nodes[n]['inputs'])
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            if x in todo and x != n:
                d = max(d, 1)
                stack.extend(nodes[x]['inputs'])
        by_lvl.setdefault(d, []).append(n)
    lat = rt.spent['lat'] + sum(
        max(ROLE_LAT_TOK.get(nodes[n]['role'], (13, 2200))[0]
            for n in ids) for ids in by_lvl.values())
    if lat > rt.D * 1.5:                # absurd-late cutoff
        return -9.0
    q = 0.0
    for n in nodes:
        if n in Rset or n in todo:
            q += (1 / len(nodes)) * R.PROFILE[
                R.ROLE_CLASS[nodes[n]['role']]][pi.get(n, 'Flash')][0]
        elif n in rt.state:
            q += (1 / len(nodes)) * rt.state[n].q
    return q - 0.5 * tok / 60000.0 - max(0.0, lat - rt.D) / rt.D


def greedy_pi_for(rt, Rset, budget):
    todo = [n for n in R.topo_order(rt.spec)
            if n not in rt.state or n in Rset]
    pi = {n: 'Flash' for n in todo}
    cur = eval_action(rt, Rset, pi)
    ev = 1
    improved = True
    while improved and ev < budget:
        improved = False
        for n in todo:
            bm, bv = pi[n], cur
            for m in ('DS', 'Qwen'):
                pi2 = dict(pi)
                pi2[n] = m
                v = eval_action(rt, Rset, pi2)
                ev += 1
                if v > bv + 1e-12:
                    bm, bv = m, v
            if bm != pi[n]:
                pi[n] = bm
                cur = bv
                improved = True
    return cur, pi, ev


def act(policy, rt, budget=120):
    cands, bad = legal_R_candidates(rt.spec, rt.state)
    if not bad:
        return dict(z='IDENTITY', R=[], pi={}, v=eval_action(
            rt, set(), {}), evals=1, terminate=False)
    term_v = eval_action(rt, None, None, terminate=True)
    best = dict(z='IDENTITY', R=None, pi=None, v=term_v, evals=1,
                terminate=True)
    if policy == 'STATIC-F':
        # fixed plan: full closure repair with Flash, no replan
        Rset = cands[-1]
        v, pi, ev = greedy_pi_for(rt, Rset, 1)
        if v > best['v']:
            best = dict(z='IDENTITY', R=sorted(Rset), pi=pi, v=v,
                        evals=ev, terminate=False)
        return best
    evals = 1
    for Rset in cands:
        if policy in ('SIMPLE_DYN', 'R_ONLY'):
            v, pi, ev = greedy_pi_for(rt, Rset, 1)
            evals += ev
        elif policy in ('SEQ_R_PI', 'PI_ONLY', 'SEQ_PI_R',
                        'ALTERNATING', 'JOINT_R_PI'):
            v, pi, ev = greedy_pi_for(rt, Rset, budget)
            evals += ev
        else:
            v, pi, ev = greedy_pi_for(rt, Rset, budget)
            evals += ev
        if v > best['v'] + 1e-12:
            best = dict(z='IDENTITY', R=sorted(Rset), pi=pi, v=v,
                        evals=evals, terminate=False)
    if policy == 'JOINT_Z_R_PI':
        for zname, zspec in z_options(rt.spec):
            if zname == 'IDENTITY':
                continue
            trial = DAGRuntime(zspec, rt.adapter, dict(
                D=rt.D, Ccap=rt.Ccap))
            trial.state = dict(rt.state)
            trial.spent = dict(rt.spent)
            tcands, _ = legal_R_candidates(trial.spec, trial.state)
            for Rset in tcands:
                v, pi, ev = greedy_pi_for(trial, Rset, budget // 2)
                evals += ev
                if v > best['v'] + 1e-12:
                    best = dict(z=zname, R=sorted(Rset), pi=pi, v=v,
                                evals=evals, terminate=False)
    return best


def main():
    specs = []
    files = sorted(glob.glob(str(HERE / 'fe_screening_runs' /
                                  'planner_v1_20261028/*_spec.json')))
    for f in files:
        specs.append((Path(f).name[:18], json.loads(Path(f).read_text())))
    provider = RET.LocalCorpusProvider()
    policies = ['STATIC-F', 'SIMPLE_DYN', 'R_ONLY', 'PI_ONLY',
                'SEQ_R_PI', 'SEQ_PI_R', 'ALTERNATING', 'JOINT_R_PI',
                'JOINT_Z_R_PI']
    rows = []
    for name, spec in specs:
        order = R.topo_order(spec)
        faults = [order[len(order) // 3], order[2 * len(order) // 3]]
        for fault in faults:
            meter = Meter()
            backend = ReplayBackend(meter, provider)
            rt = make_state(spec, backend, fault, random.Random(1))
            for pol in policies:
                import copy
                rt2 = DAGRuntime(spec, backend, spec['constraints'])
                rt2.state = dict(rt.state)
                rt2.spent = dict(rt.spent)
                a = act(pol, rt2)
                rows.append(dict(spec=name, fault=fault, policy=pol,
                                 v=round(a['v'], 4),
                                 terminate=a['terminate'],
                                 z=a['z'], n_R=len(a['R'] or []),
                                 evals=a['evals']))
    json.dump(rows, open(HERE / 'STAGE_C_V1_SWEEP.json', 'w'),
              ensure_ascii=False, indent=1)
    # summary
    agg = {}
    for r in rows:
        agg.setdefault(r['policy'], []).append(r['v'])
    print(f"{'policy':<12}{'mean_v':>9}{'terminate%':>12}")
    for p, vs in agg.items():
        term = 100 * st.mean(
            1.0 if r['terminate'] else 0.0 for r in rows
            if r['policy'] == p)
        print(f"{p:<12}{st.mean(vs):>+9.4f}{term:>11.0f}%")
    # pairwise vs JOINT_Z_R_PI
    base = {(r['spec'], r['fault']): r['v'] for r in rows
            if r['policy'] == 'JOINT_Z_R_PI'}
    print()
    for p in policies[:-1]:
        w = t = l = 0
        for r in rows:
            if r['policy'] != p:
                continue
            k = (r['spec'], r['fault'])
            if r['v'] > base[k] + 1e-9:
                w += 1
            elif abs(r['v'] - base[k]) <= 1e-9:
                t += 1
            else:
                l += 1
        print(f'JZRP vs {p:<12}: {w}w/{t}t/{l}l')


if __name__ == '__main__':
    main()
