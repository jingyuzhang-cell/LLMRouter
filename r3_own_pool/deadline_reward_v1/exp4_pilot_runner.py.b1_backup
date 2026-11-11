"""Experiment 4 real paired Pilot runner.

Executes 6 tasks × 3 arms × 2 reps with shared first attempts,
using the frozen protocol (EXP4_REAL_PAIRED_FREEZE.json).

Run: EXP4_GO=1 python3 -m deadline_reward_v1.exp4_pilot_runner
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from deadline_reward_v1.complex_dag import (
    STRUCTURES, topo_sort, downstream, enumerate_joint_actions)
from deadline_reward_v1.quality_models import (
    q_D0, q_D2, utility, lat_est, tok_est, select_best,
    arm_c_simple, NODE_TYPE_QUALITY, MODELS)
from deadline_reward_v1.full_dag_executor import (
    load_env_creds, real_call, _ok)
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs

HERE = Path(__file__).resolve().parent
FREEZE = HERE / 'EXP4_REAL_PAIRED_FREEZE.json'
GO_FLAG = 'EXP4_GO'


def build_node_types(edges):
    nodes = topo_sort(edges)
    depth = {}
    for n in nodes:
        depth[n] = max([depth[m] + 1 for m, vs in
                        edges.items() if n in vs] + [0])
    md = max(depth.values()) if depth else 0
    return {n: ('extraction' if depth[n] / max(1, md) < 0.34
                else 'reasoning' if depth[n] / max(1, md) < 0.67
                else 'verification') for n in nodes}


def run_pilot():
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1')
    fz = json.loads(FREEZE.read_text())
    creds = load_env_creds()
    docs = load_docs()

    caps = fz['budget']['caps']
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'exp4_pilot_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)

    attempts = 0
    tokens = 0
    cash = 0.0
    wall_start = time.monotonic()

    all_results = []

    try:
        for task_spec in fz['tasks']:
            tid = task_spec['task_id']
            edges = STRUCTURES[task_spec['structure']](
                task_spec['size'])
            nodes = topo_sort(edges)
            all_nodes = set(nodes)
            node_types = build_node_types(edges)
            faulted = task_spec['fault_node']
            D = task_spec['deadline_s']
            doc = docs.get(task_spec['doc_slot'])
            doc_text = doc['text'] if doc else ''

            for rep in range(fz['reps']):
                # ---- SHARED FIRST ATTEMPTS: run planned calls once --
                clock_t = 60.0
                tokens_spent = 20000
                planned_outputs = {}
                for node in nodes:
                    model = 'deepseek-flash'  # planned: DS for all
                    prompt = (f'Node {node} type='
                              f'{node_types[node]} doc='
                              f'{task_spec["doc_id"]}')
                    # inject fault
                    if node == faulted:
                        if task_spec['fault_type'] == 'F_TRUNCATED':
                            o = real_call(model, {}, prompt, creds,
                                          force_max_tokens=64)
                        else:
                            o = real_call(model, {}, prompt, creds)
                            o = dict(o, answer='[{"fact":"占位",'
                                     '"evidence_doc_id":"?"}]',
                                     finish_reason='stop')
                    else:
                        o = real_call(model, {}, prompt, creds)
                    planned_outputs[node] = o
                    attempts += 1
                    tokens += (o['tokens_in'] + o['tokens_out'])
                    cash += o['cash_cny']
                    clock_t += o['latency_s']
                    tokens_spent += (o['tokens_in']
                                     + o['tokens_out'])
                    if attempts >= caps['attempts']:
                        raise RuntimeError(
                            f'budget stop: attempts {attempts}')
                    if tokens >= caps['tokens']:
                        raise RuntimeError(
                            f'budget stop: tokens {tokens}')
                    if cash >= caps['cash_cny']:
                        raise RuntimeError(
                            f'budget stop: cash {cash:.4f}')
                    if time.monotonic() - wall_start > caps['wall_s']:
                        raise RuntimeError('budget stop: wall')

                # ---- each arm makes its recovery decision + executes
                actions = enumerate_joint_actions(
                    edges, faulted, all_nodes)
                for arm_name in ('C', 'D0', 'D2'):
                    if arm_name == 'C':
                        dec = arm_c_simple(edges, all_nodes,
                                           faulted, clock_t, D,
                                           tokens_spent)
                    else:
                        q_fn = q_D0 if arm_name == 'D0' else q_D2
                        best = select_best(
                            actions, q_fn, edges, node_types,
                            all_nodes, faulted, clock_t, D,
                            tokens_spent)
                        dec = best[0] if best else dict(
                            Z='NONE', R=set(), pi={})

                    # execute recovery calls (if any)
                    arm_outputs = dict(planned_outputs)
                    arm_tokens = tokens_spent
                    arm_clock = clock_t
                    R = dec.get('R', set())
                    pi = dec.get('pi', {})
                    for rn in sorted(R):
                        m = pi.get(rn, 'deepseek-flash')
                        o = real_call(m, {}, f'recovery {rn}',
                                      creds)
                        arm_outputs[rn] = o
                        attempts += 1
                        tokens += (o['tokens_in'] + o['tokens_out'])
                        cash += o['cash_cny']
                        arm_tokens += (o['tokens_in']
                                       + o['tokens_out'])
                        arm_clock += o['latency_s']
                        if attempts >= caps['attempts']:
                            raise RuntimeError(
                                f'budget stop: attempts')

                    # ---- INDEPENDENT evaluation of this arm's outputs
                    combined = ' '.join(
                        str(v.get('answer', '')) for v in
                        arm_outputs.values())
                    import re
                    atoms = doc_atoms(doc_text)
                    all_atoms = (atoms['dates'] + atoms['amounts']
                                 + atoms['penalties'])
                    if all_atoms:
                        hits = sum(
                            1 for a in all_atoms
                            if re.sub(r'\s+', '', a)
                            in re.sub(r'\s+', '', combined))
                        coverage = hits / len(all_atoms)
                    else:
                        coverage = None
                    q_eval = coverage if coverage is not None else 0.0
                    eU = utility(q_eval, arm_tokens, arm_clock, D)

                    all_results.append(dict(
                        task=tid, rep=rep, arm=arm_name,
                        Z=dec['Z'], R_size=len(R),
                        pi=sorted(set(pi.values())),
                        q_indep=round(q_eval, 4),
                        coverage=round(coverage, 4)
                        if coverage is not None else None,
                        tokens=arm_tokens,
                        cash=round(arm_tokens * 3e-6, 4),
                        latency=round(arm_clock, 1),
                        deadline_met=arm_clock <= D,
                        eU=eU,
                        event=task_spec['event']))
                    print(json.dumps(dict(
                        task=tid, rep=rep, arm=arm_name,
                        R=len(R), q=round(q_eval, 3),
                        eU=round(eU, 3))), flush=True)

        # ---- summary ----
        summary = dict(
            status='COMPLETE',
            budget=dict(attempts=attempts, tokens=tokens,
                        cash_cny=round(cash, 4),
                        wall_s=round(
                            time.monotonic() - wall_start, 1)),
            results=all_results)
        (run_dir / 'EXP4_PILOT_RESULTS.json').write_text(
            json.dumps(summary, indent=1, ensure_ascii=False))
        print(json.dumps(dict(status='COMPLETE',
                              attempts=attempts,
                              tokens=tokens,
                              cash=round(cash, 4)), indent=1))
        return 0
    except BaseException as exc:
        import traceback
        (run_dir / 'EXP4_PILOT_INCOMPLETE.json').write_text(
            json.dumps(dict(status='INCOMPLETE',
                            reason=repr(exc),
                            partial_results=all_results,
                            budget=dict(
                                attempts=attempts, tokens=tokens,
                                cash=round(cash, 4)),
                            traceback=traceback.format_exc()),
                       indent=1, ensure_ascii=False))
        raise
    finally:
        # always save partial results
        if all_results:
            p = run_dir / 'EXP4_PILOT_PARTIAL.json'
            if not p.exists():
                p.write_text(json.dumps(all_results, indent=1,
                                        ensure_ascii=False))


if __name__ == '__main__':
    raise SystemExit(run_pilot())
