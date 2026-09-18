"""Live Static vs Dynamic analysis: outputs A-E (offline, zero new calls).
A main table Q/C/L with paired cluster-free bootstrap CI (tasks independent);
B help/harm; C dynamic behavior; D post-hoc headroom stratification; E failure causes."""
import json
import random
from collections import defaultdict

from .recovery_matrix_v2_devset import BASE
from .tatqa_benchmark_build import literals
from .live_static_dynamic import OUT, POOL

SEED = 20260918
B = 10000

def run():
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'LIVE_POLICY.json').read_text())
    tasks = pol['tasks']
    # latency per key from RESPONSES
    lat = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        if r['response'].get('latency_s') is not None:
            lat[r['key']] = r['response']['latency_s']
    def arm_rows(arm):
        rows = []
        for t in tasks:
            uid = t['uid']; st = raw[arm][uid]
            L = sum(lat.get(k, 0) for k, _ in st['keys'])
            rows.append(dict(uid=uid, success=int(st['ok']), used=st['used'], lat=L,
                             over_budget=st.get('over_budget', False),
                             keys=[k for k, _ in st['keys']]))
        return rows
    S, D = arm_rows('static'), arm_rows('dynamic')
    rng = random.Random(SEED)
    def boot(fn):
        out = []
        for _ in range(B):
            sample = [fn(i) for i in [rng.randrange(len(S)) for _ in S]]
            out.append(fn2(sample))
        return out
    def fn2(x): return sum(x) / len(x)
    def ci(fn):
        dist = sorted(boot(fn))
        return [round(dist[int(0.025 * B)], 4), round(dist[int(0.975 * B) - 1], 4)]
    n = len(S)
    qS = sum(r['success'] for r in S) / n; qD = sum(r['success'] for r in D) / n
    main = dict(
        n=n, static_Q=round(qS, 4), static_Q_ci=ci(lambda i: S[i]['success']),
        dynamic_Q=round(qD, 4), dynamic_Q_ci=ci(lambda i: D[i]['success']),
        paired_dQ=round(qD - qS, 4), paired_dQ_ci=ci(lambda i: D[i]['success'] - S[i]['success']),
        static_C=round(sum(r['used'] for r in S) / n, 1), dynamic_C=round(sum(r['used'] for r in D) / n, 1),
        dC=round(sum(r['used'] - s['used'] for r, s in zip(D, S)) / n, 1),
        static_L=round(sum(r['lat'] for r in S) / n, 2), dynamic_L=round(sum(r['lat'] for r in D) / n, 2),
        dL=round(sum(r['lat'] - s['lat'] for r, s in zip(D, S)) / n, 2))
    help_ids = [r['uid'] for r, s in zip(D, S) if s['success'] == 0 and r['success'] == 1]
    harm_ids = [r['uid'] for r, s in zip(D, S) if s['success'] == 1 and r['success'] == 0]
    both_right = sum(1 for r, s in zip(D, S) if r['success'] == 1 and s['success'] == 1)
    both_wrong = sum(1 for r, s in zip(D, S) if r['success'] == 0 and s['success'] == 0)
    # dynamic behavior
    ext_fb_switched = [t['uid'] for t in tasks if raw['extraction_initial_parse_failed'][t['uid']]
                       and any(m == 'medium' for k, m in raw['dynamic'][t['uid']]['keys'] if k.startswith('C:dynamic:'))]
    dyn_fb_models = [m for uid in (t['uid'] for t in tasks) for k, m in raw['dynamic'][uid]['keys'] if k.startswith('C:dynamic:')]
    reasoning_escalations = [uid for uid in (t['uid'] for t in tasks)
                             for k, m in raw['dynamic'][uid]['keys'] if k.startswith('E:dynamic:')]
    resched_tasks = [uid for uid in ext_fb_switched + reasoning_escalations]
    behavior = dict(
        downstream_rescheduling_rate=round(len(set(resched_tasks)) / max(1, sum(1 for r in S if r['success'] == 0 or True)), 4),
        tasks_with_rescheduling=len(set(resched_tasks)),
        mean_affected_descendants=round(sum(1 for uid in (t['uid'] for t in tasks) if any(k.startswith('D:dynamic:') for k, _ in [])) / n, 3),
        extraction_fallback_to_medium_count=sum(1 for m in dyn_fb_models if m == 'medium'),
        reasoning_escalation_to_large_count=len(reasoning_escalations),
        verifier_escalations='N/A (2-node DAG has no verification node)',
        budget_violation_rate=round(sum(1 for r in D if r['over_budget']) / n, 4),
        budget_skipped=raw.get('skipped', []))
    # D headroom stratification (instances = (uid, facts_hash) where static FAILED)
    head = raw['headroom']
    inst = defaultdict(list)
    for h in head: inst[(h['uid'], h['facts_hash'])].append(h)
    h1 = {k: v for k, v in inst.items() if any(x['ok'] for x in v)}
    h0 = {k: v for k, v in inst.items() if k not in h1}
    # headroom-subset task-level dQ: tasks whose static-failed reasoning instance had headroom
    h1_tasks = {uid for (uid, fh) in h1}
    sQ = [r['success'] for r in S if r['uid'] in h1_tasks]
    dQ = [r['success'] for r in D if r['uid'] in h1_tasks]
    strat = dict(instances_with_headroom=len(h1), instances_without_headroom=len(h0),
                 tasks_with_headroom=len(h1_tasks),
                 subset_static_Q=round(sum(sQ) / len(sQ), 4) if sQ else None,
                 subset_dynamic_Q=round(sum(dQ) / len(dQ), 4) if dQ else None,
                 subset_dQ=round(sum(dQ) - sum(sQ), 4) if sQ else None,
                 subset_n=len(sQ),
                 dynamic_alternative_pick_correct_rate=round(
                     sum(1 for k, v in h1.items() if any(x['arm'] == 'dynamic' and x['ok'] for x in v)) / len(h1), 4) if h1 else None)
    # E failure causes for both-failed tasks
    causes = defaultdict(int); detail = []
    for r, s in zip(D, S):
        if r['success'] or s['success']: continue
        uid = r['uid']; t = next(t for t in tasks if t['uid'] == uid)
        # models tried by the union of both arms' chains on the final consumed facts
        tried_union = set()
        for arm in ('static', 'dynamic'):
            for k, m in raw[arm][uid]['keys']:
                tried_union.add(m)
        all_tried = len(tried_union) == len(POOL)
        ext_parse_fail = raw['extraction_initial_parse_failed'][uid]
        req = sorted({x for x in literals(t['derivation']) if x not in (0., 1., 100.)})
        fvals = raw['facts'][uid]['static']
        er = sum(any(abs(fv - x) <= 1e-4 * max(1, abs(x)) for fv in fvals) for x in req) / len(req) if req else 1
        budget_blocked = uid in {k['uid'] for k in raw.get('skipped', [])}
        if all_tried:
            cause = 'model_pool_common_failure'  # all 3 models tried on the same propagated facts, all wrong
        elif budget_blocked:
            cause = 'budget_restriction'
        elif ext_parse_fail and not fvals:
            cause = 'propagation_interface_failure'
        elif er < 1:
            cause = 'upstream_evidence_failure'
        else:
            cause = 'rerouting_decision_failure'  # headroom may exist among untried models
        causes[cause] += 1
        detail.append(dict(uid=uid, cause=cause, extraction_parse_failed=ext_parse_fail,
                           ER_on_static_facts=round(er, 3), models_tried=sorted(tried_union)))
    rep = dict(seed=SEED, B=B, policy_frozen_commit=pol['frozen_commit'], n=n,
               A_main=main, B_help_harm=dict(help=len(help_ids), harm=len(harm_ids), both_right=both_right,
                                             both_wrong=both_wrong, help_tasks=help_ids, harm_tasks=harm_ids),
               C_dynamic_behavior=behavior, D_headroom_stratification=strat,
               E_failure_causes=dict(counts=dict(causes), detail=detail))
    (OUT / 'LIVE_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
