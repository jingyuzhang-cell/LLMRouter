"""Static DAG vs Dynamic DAG (replay tier, zero new model calls).

Both arms share: 100-task confirmation panel, per-type dependency order
(extraction -> transformation -> reasoning -> verification), initial assignment
FrozenNodeRouter, and per-task token budget = initial Static plan tokens.

Static: node failure -> one local fallback (frozen-utility second best);
downstream successors keep the initial plan and budget (topology unchanged).

Dynamic: node failure -> failure-state memory update (type, model), node-level
fallback fused with reroute memory (lambda'=0.5); DOWNSTREAM RESCHEDULING: each
successor's model is re-chosen from the updated state (fused utility); when an
upstream node failed, verification switches to the strongest measured
verification model if remaining budget allows ('stronger verifier'); remaining
token budget recomputed after every pick; escalation only if B_rem allows.
Topology is NEVER modified (Local Replan remains future work).

Metrics: task success (reasoning correct), mean tokens, mean latency, failure
recovery rate, downstream reallocation rate, budget violation rate; task-cluster
bootstrap 95% CIs. All outcomes from measured per-(node, model) Q/C/L matrices
(conditional-input replay tier, same caveat as 5.4 replays)."""
import json
import random
from collections import defaultdict

import numpy as np

from . import core
from .recovery_matrix_v2_devset import BASE

SRC = BASE / 'fresh_static_confirmation'
OUT = BASE / 'static_vs_dynamic'
POOL = ['medium', 'large', 'coder']
TYPE_ORDER = {'extraction': 0, 'transformation': 1, 'reasoning': 2, 'verification': 3}
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA_FAIL = 0.5
SEED = 20260918
B = 10000
HEADROOM = 1.2  # frozen: per-task token budget = 1.2 x Static arm realized tokens

def beta_mem(S, N):
    return (S + 1) / (N + 2)

def run():
    OUT.mkdir(parents=True, exist_ok=True)
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX_EXEC.npz', allow_pickle=False))
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    order = {t['uid']: k for k, t in enumerate(json.loads((SRC / 'TASKS.json').read_text()))}
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    idx.sort(key=lambda i: order[nodes_all[i]['task_uid']])
    nodes = [nodes_all[i] for i in idx]
    sub = {k: matrix[k][idx] for k in ('Q', 'C', 'L', 'FrozenNodeRouter')}
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    types = np.array([[1.0 if n['node_type'] == t else 0.0 for t in ['extraction', 'transformation', 'reasoning', 'verification']] for n in nodes])
    ctx = np.log1p(np.array([len(n['question']) for n in nodes], dtype=float)).reshape(-1, 1)
    X = np.hstack([np.array([emb['emb'][qmap[n['question']]] for n in nodes]), types, ctx])
    qhat = X @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept']
    u_frozen = qhat - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
    # group nodes by task in dependency order; shared extraction call counted once
    tasks = defaultdict(list)
    for j, n in enumerate(nodes):
        tasks[n['task_uid']].append(j)
    task_ids = sorted(tasks, key=lambda t: order[t])
    task_nodes = []
    for t in task_ids:
        js = sorted(tasks[t], key=lambda j: (TYPE_ORDER[nodes[j]['node_type']], nodes[j]['node_id']))
        task_nodes.append(js)

    def plan_task(js, assign, plan_state=None):
        """Execute one task under an assignment; returns dict of task metrics."""
        used = 0.0; lat = 0.0; calls = []
        outcomes = {}; failures = []; ext_calls = set()
        for j in js:
            n = nodes[j]
            m = assign(j, plan_state)
            if n['node_type'] == 'extraction' and n['shares_model_call'] in ext_calls:
                outcomes[j] = outcomes.get(n['shares_model_call'], 0)
                continue
            if n['node_type'] == 'extraction':
                ext_calls.add(n['shares_model_call'])
            used += float(sub['C'][j, m]); lat += float(sub['L'][j, m])
            outcomes[j] = float(sub['Q'][j, m])
            calls.append((j, m))
            if outcomes[j] == 0:
                failures.append((j, m))
        reasoning_js = [j for j in js if nodes[j]['node_type'] == 'reasoning']
        success = 0
        if reasoning_js:
            success = 1 if max(outcomes[j] for j in reasoning_js) > 0 else 0
        return dict(used=used, lat=lat, failures=failures, success=success,
                    reasoning=reasoning_js[0] if reasoning_js else None)

    # ---------------- Static arm ----------------
    def static_assign(j, _s=None):
        return int(sub['FrozenNodeRouter'][j])
    static_rows = []
    for js in task_nodes:
        plan = plan_task(js, static_assign)
        extra = 0.0; extra_lat = 0.0
        handled = set()
        for j, m in plan['failures']:
            n = nodes[j]
            key = n['shares_model_call'] if n['node_type'] == 'extraction' else n['node_id']
            if key in handled: continue
            handled.add(key)
            alt = [k for k in range(3) if k != m]
            alt.sort(key=lambda k: -u_frozen[j, k])
            fm = alt[0]
            extra += float(sub['C'][j, fm]); extra_lat += float(sub['L'][j, fm])
            if n['node_type'] == 'reasoning' and float(sub['Q'][j, fm]) > 0: plan['success'] = 1
        static_rows.append(dict(used=plan['used'] + extra, lat=plan['lat'] + extra_lat,
                                success=plan['success'], realloc=0,
                                budget=(plan['used'] + extra) * HEADROOM,
                                plan_exceed=plan['used'] + extra > plan['used'],
                                failed_nodes=len(plan['failures'])))

    # ---------------- Dynamic arm ----------------
    mem_fail = {(t, m): [0, 0] for t in ('extraction', 'reasoning', 'verification') for m in POOL}
    def dynamic_assign(j, state):
        """state: dict with rem_budget, upstream_failed, planned, failed node info."""
        n = nodes[j]
        planned = int(sub['FrozenNodeRouter'][j])
        s = state
        if s is None or not s.get('reschedule'):
            return planned
        t = n['node_type']
        if t == 'transformation':
            return planned
        # fused utility with failure-state memory
        fused = np.array([(1 - LAMBDA_FAIL) * u_frozen[j, k] + LAMBDA_FAIL * beta_mem(*mem_fail[(t, POOL[k])]) for k in range(3)])
        pick = int(np.argmax(fused))
        # stronger verifier when upstream failed: upgrade only if it improves
        # measured verification quality and fits the remaining budget
        if t == 'verification' and s.get('upstream_failed'):
            best_v = int(np.argmax(sub['Q'][j]))
            if (best_v != pick and float(sub['Q'][j, best_v]) > float(sub['Q'][j, planned])
                    and s['rem_budget'] >= float(sub['C'][j, best_v])):
                pick = best_v
        if s['rem_budget'] < float(sub['C'][j, pick]):
            # escalation infeasible: keep cheapest feasible of planned/pick
            feasible = [k for k in (planned, pick) if float(sub['C'][j, k]) <= s['rem_budget']]
            if not feasible: pick = planned
            else: pick = min(feasible, key=lambda k: float(sub['C'][j, k]))
        return pick

    dynamic_rows = []
    for js in task_nodes:
        # phase 1: initial plan execution (same as static)
        plan = plan_task(js, static_assign)
        used = plan['used']; lat = plan['lat']
        failures = list(plan['failures'])
        reschedule = False; upstream_failed = False; realloc_nodes = set(); extra_calls = 0
        budget = static_rows[len(dynamic_rows)]['used'] * HEADROOM
        success = plan['success']
        if failures:
            # node-level fallback with reroute memory (one per failed call; shared extraction counted once)
            handled = set()
            for j, m in failures:
                n = nodes[j]
                key = n['shares_model_call'] if n['node_type'] == 'extraction' else n['node_id']
                if (key, m) in handled: continue
                handled.add((key, m))
                t = n['node_type']
                if t == 'transformation': continue
                mem_fail[(t, POOL[m])][1] += 1
                fused = np.array([(1 - LAMBDA_FAIL) * u_frozen[j, k] + LAMBDA_FAIL * beta_mem(*mem_fail[(t, POOL[k])]) for k in range(3)])
                fused[m] = -np.inf
                fm = int(np.argmax(fused))
                used += float(sub['C'][j, fm]); lat += float(sub['L'][j, fm]); extra_calls += 1
                if n['node_type'] == 'reasoning' and float(sub['Q'][j, fm]) > 0: success = 1
                else: mem_fail[(t, POOL[fm])][1] += 1
                reschedule = True
            # downstream rescheduling (successors of failed nodes; topology unchanged)
            failed_types = {nodes[j]['node_type'] for j, _ in failures}
            upstream_failed = bool(failed_types & {'extraction', 'reasoning'})
            for jj in js:
                n = nodes[jj]
                if n['node_type'] in ('extraction', 'transformation'):
                    continue
                planned = int(sub['FrozenNodeRouter'][jj])
                state = dict(reschedule=True, rem_budget=max(0.0, budget - used), upstream_failed=upstream_failed)
                pick = dynamic_assign(jj, state)
                if pick != planned:
                    realloc_nodes.add(jj)
                # re-execution cost/latency of the successor under the new pick
                # (replacement of the planned call, not additive; use delta)
                used += float(sub['C'][jj, pick]) - float(sub['C'][jj, planned])
                lat += float(sub['L'][jj, pick]) - float(sub['L'][jj, planned])
                if float(sub['Q'][jj, pick]) > 0 and n['node_type'] == 'reasoning':
                    success = 1
        dynamic_rows.append(dict(used=max(used, 0.0), lat=lat, success=success,
                                 realloc=1 if realloc_nodes else 0, realloc_count=len(realloc_nodes),
                                 budget=budget, plan_exceed=used > plan['used'],
                                 failed_nodes=len(failures), extra_calls=extra_calls))

    # ---------------- statistics ----------------
    rng = random.Random(SEED)
    tid = [task_ids[i] for i in range(len(task_ids))]
    def boot(fn):
        out = []
        for _ in range(B):
            sample = [fn(i) for i in [rng.randrange(len(task_ids)) for _ in task_ids]]
            out.append(sum(sample) / len(sample))
        out.sort()
        return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]
    def arm_stats(rows):
        n = len(rows)
        return dict(n=n, success=round(sum(r['success'] for r in rows) / n, 4),
                    success_ci=boot(lambda i: rows[i]['success']),
                    mean_tokens=round(sum(r['used'] for r in rows) / n, 1),
                    mean_latency_s=round(sum(r['lat'] for r in rows) / n, 3),
                    recovery_rate=round(sum(r['success'] for r in rows) / max(1, sum(1 for r in rows if r['failed_nodes'])), 4),
                    failed_tasks=sum(1 for r in rows if r['failed_nodes']),
                    downstream_realloc_rate=round(sum(r['realloc'] for r in rows) / max(1, sum(1 for r in rows if r['failed_nodes'])), 4),
                    budget_violation_rate=round(sum(1 for r in rows if r['used'] > r['budget'] + 1e-9) / n, 4),
                    plan_exceed_rate=round(sum(1 for r in rows if r.get('plan_exceed')) / n, 4),
                    mean_realloc_nodes=round(sum(r.get('realloc_count', 0) for r in rows) / max(1, sum(1 for r in rows if r['failed_nodes'])), 3))
    rep = dict(seed=SEED, B=B, panel='fresh_static_confirmation 100-task confirmation set',
               tier='replay over measured per-(node,model) Q/C/L; conditional-input caveat as in 5.4',
               budget_definition='per-task token budget = 1.2 x Static arm realized tokens (frozen 20% headroom); violation = realized tokens exceed this budget; plan_exceed = realized tokens exceed the initial plan (no budget controller)',
               dynamic_definition='feedback-conditioned downstream re-scheduling of model assignment + budget reallocation + verification adjustment; topology unchanged',
               static=arm_stats(static_rows), dynamic=arm_stats(dynamic_rows),
               paired=dict(
                   dQ=boot(lambda i: dynamic_rows[i]['success'] - static_rows[i]['success']),
                   dC=round(sum(r['used'] - s['used'] for r, s in zip(dynamic_rows, static_rows)) / len(task_ids), 1),
                   dL=round(sum(r['lat'] - s['lat'] for r, s in zip(dynamic_rows, static_rows)) / len(task_ids), 3),
                   reallocated_tasks=sum(r['realloc'] for r in dynamic_rows),
                   dynamic_recovered=sum(1 for r, s in zip(dynamic_rows, static_rows) if r['success'] and not s['success']),
                   static_recovered=sum(1 for r, s in zip(dynamic_rows, static_rows) if s['success'] and not r['success'])),
               note='Dynamic+Forest equals Dynamic on this panel: distinct tasks offer no cross-task reuse opportunity; forest reuse evidence lives in 5.6 multi-turn workload')
    (OUT / 'RESULTS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
