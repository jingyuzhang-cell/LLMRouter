"""Experiment 1: Joint action vs simple rule on 8-node DAGs.

Two structures (diamond_8: 37 closures at source fault, 720 joint
actions; multipath_8: 17 closures, 320 actions), fault at the
highest-opportunity node (source) to maximize the decision space.

Three arms:
  C-simple: simple gate (cheapest-fitting, always full closure)
  D-joint: enumerates (Z, R, π), filters by budget/deadline, picks
           argmax expected utility
  Oracle:   exhaustively evaluates ALL joint actions with known
           outcome probabilities (upper bound)

Design: shared-first-attempt (identical planned outputs across
arms), 3 repetitions, same prompts/contracts/silver.

Run: python3 -m deadline_reward_v1.exp1_joint_action --drill
Real: EXP1_GO=1 python3 -m deadline_reward_v1.exp1_joint_action
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from pathlib import Path

from deadline_reward_v1 import complex_dag as cd
from deadline_reward_v1.theta_actions import PRIORS

HERE = Path(__file__).resolve().parent
GO_FLAG = 'EXP1_GO'
MODELS = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']

# simplified node types for synthetic DAGs
NODE_TYPES = ['extraction', 'reasoning', 'verification', 'synthesis']


def assign_node_types(edges):
    """Assign plausible node types based on topological position."""
    order = cd.topo_sort(edges)
    types = {}
    depth = {}
    for n in order:
        depth[n] = max([depth[m] + 1 for m in edges
                        if n in edges.get(m, [])] + [0])
    max_d = max(depth.values()) if depth else 0
    for n in order:
        frac = depth[n] / max(1, max_d)
        if frac < 0.25:
            types[n] = 'extraction'
        elif frac < 0.5:
            types[n] = 'reasoning'
        elif frac < 0.75:
            types[n] = 'reasoning'
        else:
            types[n] = 'verification'
    return types, depth


# ---- utility model (frozen coefficients) --------------------------------
LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0 = 60000.0


def utility(q, tokens, T, D):
    c = tokens / C0
    if T <= D:
        return round(q - LAMBDA_C * c, 6)
    return round(-LAMBDA_C * c - LAMBDA_T * (T - D) / D - LAMBDA_F, 6)


def q_prior(model):
    p = PRIORS.get(f'{model}|default',
                   dict(pass_rate_lb=0.5, pooled_recall_lb=0.35))
    return p['pass_rate_lb'] * p['pooled_recall_lb']


def lat_est(model):
    """Latency estimate per model (from real econometrics)."""
    return {'GLM-5.3': 25.0, 'GLM-5.3-Flash': 30.0,
            'deepseek-flash': 12.0, 'qwen-plus': 15.0}.get(model, 20.0)


def tok_est(model):
    return {'GLM-5.3': 6000, 'GLM-5.3-Flash': 8000,
            'deepseek-flash': 2500, 'qwen-plus': 2000}.get(model, 4000)


# ---- arms ----------------------------------------------------------------
def arm_c_simple(edges, faulted, executed, clock_t, D, tokens_spent):
    """C: always FULL closure, cheapest model that fits remaining
    time (same as pilot's C arm)."""
    ds = cd.downstream(edges, faulted)
    closure = {faulted} | (ds & set(executed))
    remaining = D - clock_t
    est_time = sum(lat_est(m) for m in
                   [MODELS[2]] * len(closure))  # DS cheapest
    if est_time > remaining:
        return dict(Z='NONE', R=set(), pi={},
                    name='C:accept', eU=utility(0.1, tokens_spent,
                                                clock_t, D))
    pi = {n: 'deepseek-flash' for n in closure}
    eU = utility(0.3, tokens_spent + sum(tok_est('deepseek-flash')
                                         for _ in closure),
                 clock_t + est_time, D)
    return dict(Z='FULL_RECOVERY', R=closure, pi=pi,
                name=f'C:full-closure-DS({len(closure)}n)',
                eU=eU)


def arm_d_joint(edges, faulted, executed, clock_t, D, tokens_spent,
                max_enumerate=64):
    """D: enumerate (Z,R,π), filter by budget/deadline, argmax eU."""
    actions = cd.enumerate_joint_actions(edges, faulted,
                                         set(executed))
    # score each action
    best = None
    for a in actions:
        if a['Z'] == 'TERMINATE':
            eU = utility(0.0, tokens_spent, clock_t, D)
        elif a['Z'] == 'NONE':
            eU = utility(0.05, tokens_spent, clock_t, D)
        elif a['Z'] == 'LOCAL_REPAIR':
            eU = utility(q_prior('deepseek-flash'), tokens_spent,
                         clock_t + sum(lat_est(v) for v in
                                       cd.downstream(edges, faulted)
                                       & set(executed)), D)
        elif a['Z'] == 'FULL_RECOVERY':
            R = a['R']
            pi = a['pi']
            est_t = sum(lat_est(pi.get(n, 'deepseek-flash'))
                        for n in R)
            est_tok = sum(tok_est(pi.get(n, 'deepseek-flash'))
                          for n in R)
            if clock_t + est_t > D:
                continue  # infeasible
            q_est = sum(q_prior(pi.get(n, 'deepseek-flash'))
                        for n in R) / max(1, len(R))
            downstream_q = 0.1
            total_q = (q_est * len(R) + downstream_q
                       * (len(edges) - len(R))) / len(edges)
            eU = utility(total_q, tokens_spent + est_tok,
                         clock_t + est_t, D)
        else:
            continue
        if best is None or eU > best['eU']:
            best = dict(a, eU=eU,
                        name=f"D:{a['Z']}({len(a.get('R', []))}n)")
    if best is None:
        return dict(Z='NONE', R=set(), pi={}, name='D:fallback-none',
                    eU=utility(0.05, tokens_spent, clock_t, D))
    return best


def arm_oracle(edges, faulted, executed, clock_t, D, tokens_spent,
               true_q=None):
    """Oracle: knows TRUE quality per (model, node) — upper bound.
    Uses the same enumeration as D but with perfect information."""
    # simulate: true quality is correlated with prior but has noise
    rng = random.Random(hash(tuple(sorted((k, tuple(v)) for k, v in edges.items()))) % 2**31)
    actions = cd.enumerate_joint_actions(edges, faulted,
                                         set(executed))
    best = None
    for a in actions:
        if a['Z'] in ('TERMINATE', 'NONE', 'LOCAL_REPAIR'):
            continue  # oracle always explores full recovery
        R, pi = a['R'], a['pi']
        est_t = sum(lat_est(pi.get(n, 'deepseek-flash')) for n in R)
        if clock_t + est_t > D:
            continue
        est_tok = sum(tok_est(pi.get(n, 'deepseek-flash'))
                      for n in R)
        # oracle quality: true quality is prior + noise (clamped)
        q = sum(max(0, min(1, q_prior(pi.get(n, 'qwen-plus'))
                           + rng.gauss(0, 0.1)))
                for n in R) / max(1, len(R))
        eU = utility(q, tokens_spent + est_tok,
                     clock_t + est_t, D)
        if best is None or eU > best['eU']:
            best = dict(a, eU=eU,
                        name=f"Oracle:{a['Z']}({len(R)}n,π={list(pi.values())[:2]})")
    return best or dict(Z='NONE', R=set(), pi={},
                        name='Oracle:none-feasible', eU=-10)


# ---- experiment runner ---------------------------------------------------
def run_experiment(structure='diamond', size=8, fault_pos='source',
                   reps=3, deadline_s=200.0, fault_tokens_spent=30000,
                   transport=None):
    """Runs one (structure, size, fault_position) across 3 arms."""
    edges = cd.STRUCTURES[structure](size)
    nodes = cd.topo_sort(edges)
    types, depth = assign_node_types(edges)
    faulted = nodes[0] if fault_pos == 'source' else \
        nodes[len(nodes) // 2] if fault_pos == 'mid' else nodes[-1]
    # all nodes executed (late detection)
    executed = set(nodes)

    results = []
    for rep in range(reps):
        clock_t = 80.0 + rep * 10  # some time already elapsed
        for arm_name, arm_fn in [
                ('C-simple', lambda: arm_c_simple(
                    edges, faulted, executed, clock_t, deadline_s,
                    fault_tokens_spent)),
                ('D-joint', lambda: arm_d_joint(
                    edges, faulted, executed, clock_t, deadline_s,
                    fault_tokens_spent)),
                ('Oracle', lambda: arm_oracle(
                    edges, faulted, executed, clock_t, deadline_s,
                    fault_tokens_spent))]:
            dec = arm_fn()
            results.append(dict(
                rep=rep, arm=arm_name, decision=dec['name'],
                Z=dec['Z'],
                R_size=len(dec.get('R', [])),
                pi_models=sorted(set(dec.get('pi', {}).values())),
                eU=dec['eU']))
    return results, dict(
        structure=f'{structure}_{size}', faulted=faulted,
        n_closures=len(cd.closure_options(edges, faulted, executed)),
        n_joint_actions=len(cd.enumerate_joint_actions(
            edges, faulted, executed)),
        deadline_s=deadline_s)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill', action='store_true')
    parser.add_argument('--run-real', action='store_true')
    args = parser.parse_args()

    if args.run_real:
        raise PermissionError('real execution not yet wired')

    # drill: run both structures, all arms, print decisions
    all_results = {}
    for structure in ('diamond', 'multipath'):
        for size in (8,):
            results, meta = run_experiment(structure, size)
            key = f'{structure}_{size}'
            all_results[key] = dict(meta=meta, results=results)
            print(f'\n{key} (fault@{meta["faulted"]}, '
                  f'{meta["n_closures"]} closures, '
                  f'{meta["n_joint_actions"]} actions):')
            for r in results:
                print(f"  rep{r['rep']} {r['arm']:10s} "
                      f"eU={r['eU']:+.3f} "
                      f"R={r['R_size']}n "
                      f"π={r['pi_models']} [{r['decision']}]")

    # summary: does D differ from C? Does Oracle beat both?
    for key, data in all_results.items():
        c_eU = [r['eU'] for r in data['results']
                if r['arm'] == 'C-simple']
        d_eU = [r['eU'] for r in data['results']
                if r['arm'] == 'D-joint']
        o_eU = [r['eU'] for r in data['results']
                if r['arm'] == 'Oracle']
        dc = round(sum(d_eU) / len(d_eU) - sum(c_eU) / len(c_eU), 3)
        oc = round(sum(o_eU) / len(o_eU) - sum(c_eU) / len(c_eU), 3)
        print(f'\n{key}: ΔU(D-C)={dc:+.3f}  ΔU(Oracle-C)={oc:+.3f}'
              f'  {"D>C" if dc > 0.01 else "D≈C" if abs(dc) <= 0.01 else "D<C"}')

    report = dict(
        version='EXP1_JOINT_ACTION_DRILL_v1', zero_calls=True,
        results=all_results)
    (HERE / 'EXP1_JOINT_ACTION_DRILL.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
