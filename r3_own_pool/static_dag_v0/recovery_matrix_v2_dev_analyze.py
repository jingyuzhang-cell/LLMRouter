"""Dev replan pilot analysis (offline scoring, zero new calls).
Per-action recovery vs criterion-pure gold; ceiling comparison with and without local_replan;
replan-specific diagnostics; task_uid cluster bootstrap; go/no-go rule."""
import json
import random
from collections import defaultdict
from .recovery_matrix_v2_audit import close
from .recovery_matrix_v2_devset import DEV

SEED = 20260918
B = 10000
ACTIONS = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose', 'local_replan']
FROZEN4 = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']

def analyze():
    dev = json.loads((DEV / 'dev_failure_set.json').read_text())
    rows = [json.loads(l) for l in (DEV / 'ACTION_RESULTS.jsonl').read_text().splitlines()]
    offline = {}
    for p in (DEV / 'offline').glob('*.json'):
        d = json.loads(p.read_text()); offline[d['node_id']] = d
    nodes = {n['node_id']: n for n in dev['nodes']}
    grouped = defaultdict(dict)
    for r in rows:
        grouped[r['node_id']][r['action']] = r
    # score success
    scored = []
    for nid, acts in grouped.items():
        gold = offline[nid]['gold_answer']
        rec = dict(nid=nid, label=nodes[nid]['label'], domain=nodes[nid]['domain'],
                   task_uid=nodes[nid]['task_uid'], success={}, value={}, tokens={}, dt={})
        for a in ACTIONS:
            r = acts.get(a)
            if r is None: continue
            rec['success'][a] = bool(r.get('value') is not None and close(r['value'], gold))
            rec['value'][a] = r.get('value'); rec['tokens'][a] = r.get('tokens'); rec['dt'][a] = r.get('dt_s')
            if a == 'local_replan':
                rec['replan'] = dict(plans_made=r.get('plans_made'), evidence_repaired=r.get('evidence_repaired'),
                                     affected_nodes=r.get('affected_nodes'), executor_error=r.get('executor_error'),
                                     first_error=r.get('first_error'))
        scored.append(rec)
    rng = random.Random(SEED)
    clusters = defaultdict(list)
    for s in scored: clusters[s['task_uid']].append(s)
    uids = list(clusters.keys())
    def boot(node_stat):
        out = []
        for _ in range(B):
            sample = [s for u in [uids[rng.randrange(len(uids))] for _ in uids] for s in clusters[u]]
            out.append(node_stat(sample))
        out.sort()
        return [round(out[int(0.025 * B)], 4), round(out[int(0.975 * B) - 1], 4)]
    # per-action rates
    rates = {}
    for a in ACTIONS:
        sub = [s for s in scored if a in s['success']]
        point = sum(s['success'][a] for s in sub) / len(sub)
        rates[a] = dict(n=len(sub), rate=round(point, 4), ci95=boot(lambda sm, a=a: sum(x['success'][a] for x in sm) / len(sm)))
    # ceiling
    oracle4 = [s for s in scored if any(s['success'][a] for a in FROZEN4)]
    oracle5 = [s for s in scored if any(s['success'][a] for a in ACTIONS)]
    def ceiling_stat(fn):
        return boot(fn)
    c4 = len(oracle4) / len(scored); c5 = len(oracle5) / len(scored)
    added = [s for s in oracle5 if not any(s['success'][a] for a in FROZEN4)]
    rep = dict(seed=SEED, B=B, n=len(scored),
               rates=rates,
               ceiling=dict(oracle_frozen4=round(c4, 4),
                            oracle_frozen4_ci95=boot(lambda sm: sum(any(x['success'][a] for a in FROZEN4) for x in sm) / len(sm)),
                            oracle_with_replan=round(c5, 4),
                            oracle_with_replan_ci95=boot(lambda sm: sum(any(x['success'][a] for a in ACTIONS) for x in sm) / len(sm)),
                            nodes_added_by_replan=len(added),
                            added_detail=[dict(nid=s['nid'], label=s['label'],
                                               replan_value=s['value'].get('local_replan'),
                                               replan_success=s['success'].get('local_replan'),
                                               replan_meta=s.get('replan')) for s in added]),
               by_label={l: {a: dict(n=sum(s['label'] == l and a in s['success'] for s in scored),
                                     ok=sum(s['label'] == l and s['success'].get(a) for s in scored))
                             for a in ACTIONS} for l in ['evidence', 'reasoning', 'structural']},
               replan_diagnostics=dict(
                   executed=sum('local_replan' in s['success'] for s in scored),
                   plans_made=defaultdict(int),
                   evidence_repaired=sum(bool(s.get('replan', {}).get('evidence_repaired')) for s in scored),
                   executor_errors=sum(s.get('replan', {}).get('executor_error') is not None for s in scored),
                   affected_nodes_hist=defaultdict(int),
               ),
               cost=dict(**{a: dict(mean_tokens=round(sum(s['tokens'].get(a) or 0 for s in scored) / len(scored), 1),
                                    mean_dt=round(sum(s['dt'].get(a) or 0 for s in scored) / len(scored), 3)) for a in ACTIONS},
                         no_recovery=dict(mean_tokens=0, mean_dt=0)))
    for s in scored:
        if 'local_replan' in s['success']:
            m = s.get('replan', {})
            rep['replan_diagnostics']['plans_made'][str(m.get('plans_made'))] += 1
            rep['replan_diagnostics']['affected_nodes_hist'][str(m.get('affected_nodes'))] += 1
    # go/no-go
    rep['go_no_go'] = dict(
        criterion='replan must lift the frozen-4 oracle by more than 2 nodes of 40 (5pp) to continue',
        nodes_added_by_replan=len(added),
        verdict='GO: continue to frozen-116 test' if len(added) > 2 else 'NO-GO: write local replan as future work')
    (DEV / 'DEV_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    print(json.dumps(analyze(), ensure_ascii=False, indent=2))
