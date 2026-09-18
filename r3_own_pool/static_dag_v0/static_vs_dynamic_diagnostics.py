"""Diagnostics for the Static vs Dynamic replay (same frozen policy as static_vs_dynamic.py,
zero model calls). Instruments every task to answer: is Dynamic's null delta caused by no
rerouting headroom (model-pool coverage) or by the scheduler itself (help vs harm)?

D1 help/harm confusion matrix; D2 affected-subset dQ with cluster CI; D3 rerouting headroom
per rescheduled descendant and pick-accuracy on headroom>0; D4 per-task harm attribution;
D5 change-source decomposition (fallback vs reasoning reroute vs verifier escalation)."""
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
HEADROOM = 1.2

def beta_mem(S, N):
    return (S + 1) / (N + 2)

def load():
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
    tasks = defaultdict(list)
    for j, n in enumerate(nodes):
        tasks[n['task_uid']].append(j)
    task_ids = sorted(tasks, key=lambda t: order[t])
    task_nodes = [sorted(tasks[t], key=lambda j: (TYPE_ORDER[nodes[j]['node_type']], nodes[j]['node_id'])) for t in task_ids]
    return nodes, sub, u_frozen, task_ids, task_nodes

def run():
    nodes, sub, u_frozen, task_ids, task_nodes = load()
    mem_fail = {(t, m): [0, 0] for t in ('extraction', 'reasoning', 'verification') for m in POOL}
    rows = []
    for ti, js in enumerate(task_nodes):
        rec = dict(task=task_ids[ti][:8], failures=[], static=dict(), dynamic=dict())
        # planned execution (identical for both arms)
        planned_costs = 0.0; extcalls = set()
        outcomes = {}
        for j in js:
            n = nodes[j]
            m = int(sub['FrozenNodeRouter'][j])
            if n['node_type'] == 'extraction' and n['shares_model_call'] in extcalls:
                outcomes[j] = outcomes.get(n['shares_model_call'], 0); continue
            if n['node_type'] == 'extraction': extcalls.add(n['shares_model_call'])
            planned_costs += float(sub['C'][j, m])
            outcomes[j] = float(sub['Q'][j, m])
            if outcomes[j] == 0:
                rec['failures'].append(dict(idx=j, type=n['node_type'], nid=n['node_id'][-3:],
                                            planned=m, Q_planned=int(outcomes[j]),
                                            Q_all=[int(x) for x in sub['Q'][j]],
                                            headroom=any(float(x) > 0 for x in sub['Q'][j])))
        reasoning_js = [j for j in js if nodes[j]['node_type'] == 'reasoning']
        ridx = reasoning_js[0] if reasoning_js else None
        s_success = int(outcomes[ridx] > 0) if ridx is not None else 1
        d_success = s_success
        # ---- Static arm: local fallback, frozen-utility second best ----
        s_extra = 0.0; handled = set()
        for f in rec['failures']:
            j, m = f['idx'], f['planned']
            n = nodes[j]
            key = n['shares_model_call'] if n['node_type'] == 'extraction' else n['node_id']
            if key in handled: continue
            handled.add(key)
            alt = [k for k in range(3) if k != m]
            alt.sort(key=lambda k: -u_frozen[j, k])
            fm = alt[0]
            s_extra += float(sub['C'][j, fm])
            f['static_fallback'] = fm
            f['static_fallback_q'] = int(sub['Q'][j, fm])
            if n['node_type'] == 'reasoning' and float(sub['Q'][j, fm]) > 0: s_success = 1
        rec['static'] = dict(success=s_success, extra=s_extra)
        # ---- Dynamic arm: memory-fused fallback + downstream rescheduling ----
        d_extra = 0.0; handled = set(); resched = []
        failed_types = {f['type'] for f in rec['failures']}
        upstream_failed = bool(failed_types & {'extraction', 'reasoning'})
        s_realized = planned_costs + s_extra
        budget = s_realized * HEADROOM
        used = planned_costs
        for f in rec['failures']:
            j, m = f['idx'], f['planned']
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
            d_extra += float(sub['C'][j, fm]); used += float(sub['C'][j, fm])
            f['dynamic_fallback'] = fm
            f['dynamic_fallback_q'] = int(sub['Q'][j, fm])
            f['fallback_changed'] = fm != f['static_fallback']
            if n['node_type'] == 'reasoning' and float(sub['Q'][j, fm]) > 0: d_success = 1
            else: mem_fail[(t, POOL[fm])][1] += 1
        if rec['failures']:
            for jj in js:
                n = nodes[jj]
                if n['node_type'] in ('extraction', 'transformation'): continue
                planned = int(sub['FrozenNodeRouter'][jj]); t = n['node_type']
                fused = np.array([(1 - LAMBDA_FAIL) * u_frozen[jj, k] + LAMBDA_FAIL * beta_mem(*mem_fail[(t, POOL[k])]) for k in range(3)])
                pick = int(np.argmax(fused))
                reason = 'fused_reroute'
                if t == 'verification' and upstream_failed:
                    best_v = int(np.argmax(sub['Q'][jj]))
                    if best_v != pick and float(sub['Q'][jj, best_v]) > float(sub['Q'][jj, planned]) and (budget - used) >= float(sub['C'][jj, best_v]):
                        pick = best_v; reason = 'verifier_escalation'
                if (budget - used) < float(sub['C'][jj, pick]):
                    feas = [k for k in (planned, pick) if float(sub['C'][jj, k]) <= (budget - used)]
                    if not feas: pick = planned
                    else: pick = min(feas, key=lambda k: float(sub['C'][jj, k])); reason = 'budget_limited'
                if pick != planned:
                    resched.append(dict(idx=jj, type=t, nid=n['node_id'][-3:], planned=planned, pick=pick,
                                        reason=reason, Q_planned=int(sub['Q'][jj, planned]),
                                        Q_pick=int(sub['Q'][jj, pick]),
                                        Q_all=[int(x) for x in sub['Q'][jj]],
                                        headroom=any(float(x) > 0 for x in sub['Q'][jj])))
                used += float(sub['C'][jj, pick]) - float(sub['C'][jj, planned])
                if t == 'reasoning' and float(sub['Q'][jj, pick]) > 0: d_success = 1
        rec['dynamic'] = dict(success=d_success, resched=resched, used=used)
        rows.append(rec)
    # ---- diagnostics ----
    n_help = sum(1 for r in rows if r['static']['success'] == 0 and r['dynamic']['success'] == 1)
    n_harm = sum(1 for r in rows if r['static']['success'] == 1 and r['dynamic']['success'] == 0)
    n_both = sum(1 for r in rows if r['static']['success'] == 1 and r['dynamic']['success'] == 1)
    n_neither = sum(1 for r in rows if r['static']['success'] == 0 and r['dynamic']['success'] == 0)
    affected = [r for r in rows if r['dynamic']['resched']]
    unaffected = [r for r in rows if not r['dynamic']['resched']]
    rng = random.Random(SEED)
    def boot(fn, universe):
        out = []
        for _ in range(B):
            sample = [fn(r) for r in [universe[rng.randrange(len(universe))] for _ in universe]]
            out.append(sum(sample) / len(sample))
        out.sort()
        return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]
    def q(arm, r): return r[arm]['success']
    resched_nodes = [s for r in rows for s in r['dynamic']['resched']]
    headroom_nodes = [s for s in resched_nodes if s['headroom']]
    reason_nodes = [s for s in resched_nodes if s['type'] == 'reasoning']
    reason_headroom = [s for s in reason_nodes if s['headroom']]
    harm_rows = [r for r in rows if r['static']['success'] == 1 and r['dynamic']['success'] == 0]
    help_rows = [r for r in rows if r['static']['success'] == 0 and r['dynamic']['success'] == 1]
    failed_planned_resched = [s for s in resched_nodes if s['Q_planned'] == 0 and s['headroom']]
    reason_failed = [s for s in failed_planned_resched if s['type'] == 'reasoning']
    def static_fallback_q(j, planned):
        alt = [k for k in range(3) if k != planned]
        alt.sort(key=lambda k: -u_frozen[j, k])
        return int(sub['Q'][j, alt[0]])
    D3b = dict(
        resched_where_planned_failed_with_headroom=len(failed_planned_resched),
        dynamic_pick_correct=sum(s['Q_pick'] == 1 for s in failed_planned_resched),
        static_fallback_correct=sum(static_fallback_q(s['idx'], s['planned']) == 1 for s in failed_planned_resched),
        reasoning_subset=dict(n=len(reason_failed),
            dynamic_pick_correct=sum(s['Q_pick'] == 1 for s in reason_failed),
            static_fallback_correct=sum(static_fallback_q(s['idx'], s['planned']) == 1 for s in reason_failed)))
    diag = dict(
        D1_confusion=dict(n=len(rows), static_wrong_dynamic_right=n_help, static_right_dynamic_wrong=n_harm,
                          both_right=n_both, both_wrong=n_neither),
        D2_affected_subset=dict(
            n_affected=len(affected), n_unaffected=len(unaffected),
            static_Q=round(sum(r['static']['success'] for r in affected) / len(affected), 4) if affected else None,
            dynamic_Q=round(sum(r['dynamic']['success'] for r in affected) / len(affected), 4) if affected else None,
            dQ_ci=boot(lambda r: r['dynamic']['success'] - r['static']['success'], affected) if affected else None,
            unaffected_Q=round(sum(r['dynamic']['success'] for r in unaffected) / len(unaffected), 4) if unaffected else None),
        D3_headroom=dict(
            rescheduled_descendants=len(resched_nodes),
            with_headroom=len(headroom_nodes), without_headroom=len(resched_nodes) - len(headroom_nodes),
            headroom_rate=round(len(headroom_nodes) / len(resched_nodes), 4) if resched_nodes else None,
            reasoning_rescheduled=len(reason_nodes), reasoning_with_headroom=len(reason_headroom),
            dynamic_pick_correct_on_headroom=sum(s['Q_pick'] == 1 for s in headroom_nodes),
            static_planned_correct_on_headroom=sum(s['Q_planned'] == 1 for s in headroom_nodes)),
        D3b_headroom_where_planned_failed=D3b,
        D4_harm_tasks=[dict(task=r['task'], failures=[(f['type'], f['nid'], f['Q_all'], f.get('fallback_changed'), f.get('static_fallback'), f.get('static_fallback_q'), f.get('dynamic_fallback'), f.get('dynamic_fallback_q')) for f in r['failures']],
                            resched=[(s['type'], s['nid'], s['planned'], s['pick'], s['reason'], s['Q_planned'], s['Q_pick']) for s in r['dynamic']['resched']])
                       for r in harm_rows],
        D4_help_tasks=[dict(task=r['task'], resched=[(s['type'], s['nid'], s['planned'], s['pick'], s['reason'], s['Q_planned'], s['Q_pick']) for s in r['dynamic']['resched']]) for r in help_rows],
        D5_sources=dict(
            tasks_with_fallback_change=sum(1 for r in rows if any(f.get('fallback_changed') for f in r['failures'])),
            fallback_help=sum(1 for r in rows if r['static']['success'] == 0 and r['dynamic']['success'] == 1 and not r['dynamic']['resched']),
            fallback_harm=sum(1 for r in rows if r['static']['success'] == 1 and r['dynamic']['success'] == 0 and not r['dynamic']['resched']),
            reasoning_reroute_help=sum(1 for r in rows if r['static']['success'] == 0 and r['dynamic']['success'] == 1 and any(s['type'] == 'reasoning' for s in r['dynamic']['resched'])),
            reasoning_reroute_harm=sum(1 for r in rows if r['static']['success'] == 1 and r['dynamic']['success'] == 0 and any(s['type'] == 'reasoning' for s in r['dynamic']['resched'])),
            verifier_escalations=sum(1 for s in resched_nodes if s['reason'] == 'verifier_escalation'),
            budget_limited=sum(1 for s in resched_nodes if s['reason'] == 'budget_limited'),
            resched_by_reason=dict((k, sum(1 for s in resched_nodes if s['reason'] == k)) for k in ['fused_reroute', 'verifier_escalation', 'budget_limited'])),
        D5_note='success flips are task-level reasoning outcomes; fallback vs reroute attribution splits tasks by whether any reasoning successor was rerouted',
    )
    (OUT / 'DIAGNOSTICS.json').write_text(json.dumps(diag, ensure_ascii=False, indent=2))
    print(json.dumps(diag, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
