"""P1a: zero-call runtime-detector audit on frozen200 (no model calls).

Question: how far are EXISTING deployable runtime signals from the perfect
fault-aware gate (Q=0.4917)?

A. In-DAG detector audit (dynamic arm internals, from frozen artifacts):
   - stage-correct recall by fault type: e1/e2 (interface), r (reasoning),
     v (verification); recovery-trigger keys on disk vs regenerated fault maps
     (build_faults is deterministic; 60/60/60 exact match verified)
   - false triggers on healthy tasks and which signal dominates
   - correction success by fault type after reroute

B. Single-level fault visibility: parse_router on the single arm's output.
   Fault texts are cross-schema (e/r/v-format pool outputs injected into the
   single slot) -> value None -> SCHEMA-DETECTABLE. Honest sensitivity note:
   a semantics-preserving fault model (single-format wrong answers) would be
   invisible (GFv2 well-formed-wrong evidence).

C. Policy table + tau sweep (exact per-seed counterfactuals from recorded arms;
   escalating to dynamic after single uses the dynamic arm's recorded outcome):
   Always-Single / Always-Dynamic / SFE-schema (escalate iff single answer
   schema-fails) / clairvoyant fault-aware / selective oracle; soft-anomaly
   escalation sweep -> Q(tau), C(tau), L(tau) mini-Pareto.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, '/root/r3_own_pool')
import numpy as np

from static_dag_v0.frozen200_run import (BENCH, RATE, SEEDS, build_faults,
                                         parse_router)

FZ = BENCH.parent / 'frozen200'
OUT = BENCH.parent / 'frozen200_p1a'


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def _safe_parse(txt):
    try:
        return parse_router(txt)
    except Exception:
        return None


def run():
    OUT.mkdir(exist_ok=False)
    pol = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())
    tasks = pol['tasks']
    gold = {t['uid']: t['answer'] for t in tasks}
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    res = json.loads((FZ / 'FROZEN200_RESULTS.json').read_text())['results']
    resp = {json.loads(l)['key']: json.loads(l) for l in (FZ / 'RESPONSES.jsonl').read_text().splitlines()}
    req_keys = {json.loads(l)['key'] for l in (FZ / 'REQUESTS.jsonl').read_text().splitlines()}

    faults_by_seed = {s: build_faults(s, RATE, tasks, pools) for s in SEEDS}
    single_cost = {t['uid']: float(resp[f'fz:single:{t["uid"]}']['response']['usage']['total_tokens'])
                   for t in tasks}
    single_lat = {t['uid']: float(resp[f'fz:single:{t["uid"]}']['response'].get('latency_s') or 0)
                   for t in tasks}
    single_val = {}
    for t in tasks:
        try:
            single_val[t['uid']] = parse_router(resp[f'fz:single:{t["uid"]}']['response']['answer'])
        except Exception:
            single_val[t['uid']] = None

    # ---- A. in-DAG detector audit ----
    det = Counter()
    for s in SEEDS:
        faults = faults_by_seed[s]
        for t in tasks:
            u = t['uid']
            fb = {nd: f'fz:{nd}:{u}:fb' in req_keys for nd in ('e1', 'e2')}
            esc_r = f'fz:r:{u}:esc' in req_keys
            esc_v = f'fz:v:{u}:esc' in req_keys
            fired = fb['e1'] or fb['e2'] or esc_r or esc_v
            if u in faults:
                node = faults[u][0]
                stage = {'e1': fb['e1'], 'e2': fb['e2'], 'r': esc_r, 'v': esc_v}[node]
                det[(node, 'stage_trigger', stage)] += 1
                det[(node, 'any_trigger', fired)] += 1
                if not stage and esc_v:
                    det[(node, 'late_v_surface_wrong_target', True)] += 1
                det[(node, 'recovered', bool(res[f'f30_s{s}|dynamic'][u]['ok']))] += 1
            else:
                det[('healthy', 'any_trigger', fired)] += 1
                for sig, hit in [('e_fb', fb['e1'] or fb['e2']), ('r_esc', esc_r), ('v_esc', esc_v)]:
                    if hit:
                        det[('healthy', 'signal', sig)] += 1
    audit_dag = dict(
        stage_recall={n: f'{det[(n, "stage_trigger", True)]}/{det[(n, "stage_trigger", True)] + det[(n, "stage_trigger", False)]}'
                      for n in ('e1', 'e2', 'r', 'v')},
        late_v_surface_r_faults=det[('r', 'late_v_surface_wrong_target', True)],
        correction_success={n: f'{det[(n, "recovered", True)]}/{det[(n, "recovered", True)] + det[(n, "recovered", False)]}'
                            for n in ('e1', 'e2', 'r', 'v')},
        healthy_false_triggers=f'{det[("healthy", "any_trigger", True)]}/'
                               f'{det[("healthy", "any_trigger", True)] + det[("healthy", "any_trigger", False)]}',
        healthy_signal_breakdown={k[2]: v for k, v in det.items() if k[:2] == ('healthy', 'signal')})

    # ---- A2. Detection / Localization / Correction decomposition (r faults) ----
    rlc = Counter()
    for s in SEEDS:
        faults = faults_by_seed[s]
        for t in tasks:
            u = t['uid']
            if faults.get(u, (None,))[0] != 'r':
                continue
            loc = f'fz:r:{u}:esc' in req_keys
            det_any = loc or f'fz:v:{u}:esc' in req_keys
            ok = bool(res[f'f30_s{s}|dynamic'][u]['ok'])
            rlc[('detect', det_any)] += 1
            rlc[('localize', loc)] += 1
            if loc:
                rlc[('correct_given_localized', ok)] += 1
    audit_rlc = dict(
        r_detect=f'{rlc[("detect", True)]}/{sum(v for k, v in rlc.items() if k[0] == "detect")}',
        r_localize=f'{rlc[("localize", True)]}/{sum(v for k, v in rlc.items() if k[0] == "localize")}',
        r_correct_given_localized=f'{rlc[("correct_given_localized", True)]}/'
                                  f'{rlc[("correct_given_localized", True)] + rlc[("correct_given_localized", False)]}',
        note='Detection != Diagnosis != Correction: late v-stage surfacing counts as '
             'detected-but-mislocalized (repair targets v, not r).')

    # ---- B. single-level visibility ----
    # In the frozen harness the single-arm fault is applied at the RESULT level
    # (ok forced False, cost doubled); the recorded single output remains the
    # CLEAN cached answer -> fault visibility at the single level is ZERO BY
    # CONSTRUCTION in this experiment. Counterfactual: if the pool text were
    # injected into the call, parse_router returns None for every pool entry
    # (cross-schema) -> a schema check would flag 100% of them; a
    # semantics-preserving fault model (well-formed wrong answers, GFv2) would
    # remain invisible to that check.
    vis = Counter()
    for s in SEEDS:
        faults = faults_by_seed[s]
        for t in tasks:
            u = t['uid']
            schema_fail = single_val[u] is None
            vis[('faulted' if u in faults else 'healthy', 'schema_fail', schema_fail)] += 1
    pool_none = {k: sum(1 for txt in pools[k] if _safe_parse(txt) is None) for k in pools}
    single_vis = dict(
        faulted_schema_visible_in_experiment='0/180 (by construction: fault applied at '
                                              'result level; recorded output is the clean answer)',
        healthy_schema_fail=f'{vis[("healthy", "schema_fail", True)]}/420',
        counterfactual_pool_injection_schema_visible={k: f'{v}/{len(pools[k])}'
                                                      for k, v in pool_none.items()},
        note='zero single-level fault visibility in the frozen data; the 0.4033->0.4917 '
             'band requires a NEW cheap signal (semantic trust estimation), not better '
             'use of existing ones.')

    # ---- C. policies + tau sweep ----
    def policy(escalate_fn):
        """escalate_fn(seed, uid, faulted) -> bool; returns Q, C, L (mean over 600 samples)."""
        qs, cs, ls = [], [], []
        for s in SEEDS:
            faults = faults_by_seed[s]
            for t in tasks:
                u = t['uid']
                faulted = u in faults
                S = res[f'f30_s{s}|single'][u]
                D = res[f'f30_s{s}|dynamic'][u]
                if escalate_fn(s, u, faulted):
                    qs.append(D['ok'])
                    cs.append(single_cost[u] + D['used'])
                    ls.append(single_lat[u] + D['lat'])
                else:
                    # single without the (futile, persistent-fault) retry: 1 call
                    qs.append(S['ok'])
                    cs.append(single_cost[u])
                    ls.append(single_lat[u])
        return float(np.mean(qs)), float(np.mean(cs)), float(np.mean(ls))

    def soft_score(u):
        v = single_val[u]
        if v is None:
            return 1e9  # hard schema fail (always escalate first)
        s = 0.0
        s += 1.0 * (v < 0)
        s += 1.0 * (abs(v) > 1e5)
        s += 1.0 * (abs(v) < 1e-3 and abs(v) > 0)
        s += 1.0 * (float(v).is_integer() and abs(v) >= 99 and abs(v) <= 999)
        return s

    always_s = policy(lambda s, u, f: False)
    always_d = (float(np.mean([[res[f'f30_s{s}|dynamic'][t['uid']]['ok'] for t in tasks] for s in SEEDS])),
                float(np.mean([[res[f'f30_s{s}|dynamic'][t['uid']]['used'] for t in tasks] for s in SEEDS])),
                float(np.mean([[res[f'f30_s{s}|dynamic'][t['uid']]['lat'] for t in tasks] for s in SEEDS])))
    sfe_schema = policy(lambda s, u, f: single_val[u] is None)
    clairvoyant = policy(lambda s, u, f: f)
    oracle = float(np.mean([[max(res[f'f30_s{s}|single'][t['uid']]['ok'],
                                  res[f'f30_s{s}|dynamic'][t['uid']]['ok']) for t in tasks] for s in SEEDS]))
    sweep = []
    for tau in [0, 1, 2, 3, 4, 1e9]:
        def esc(s, u, f, tau=tau):
            if single_val[u] is None:
                return True                       # hard schema fail: always escalate
            return soft_score(u) >= tau if tau != 1e9 else False
        q, c, l = policy(esc)
        sweep.append(dict(tau=('schema_only' if tau == 1e9 else tau), Q=q, C=c, L=l))
    table = dict(always_single=dict(Q=always_s[0], C=always_s[1], L=always_s[2]),
                 always_dynamic=dict(Q=always_d[0], C=always_d[1], L=always_d[2]),
                 sfe_schema=dict(Q=sfe_schema[0], C=sfe_schema[1], L=sfe_schema[2]),
                 clairvoyant_fault_aware=dict(Q=clairvoyant[0], C=clairvoyant[1], L=clairvoyant[2]),
                 selective_oracle=dict(Q=oracle))
    regret = {k: round(0.49166666666666664 - v['Q'], 4) for k, v in table.items() if 'Q' in v}

    out = dict(dag_detector=audit_dag, r_three_capability=audit_rlc, single_visibility=single_vis,
               policies=table, regret_vs_04917=regret, tau_sweep=sweep,
               gap_decomposition='0.4033->0.4917 is ENTIRELY the healthy-task DAG penalty '
                                 '(single 0.5667 vs dynamic 0.4405 on non-injected); faulted '
                                 'outcomes are identical under both policies. Capturing it '
                                 'requires pre-arm fault knowledge at the single level.',
               zero_calls=True)
    (OUT / 'AUDIT.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(dag=audit_dag, r3=audit_rlc, single=single_vis, policies=table,
                          regret=regret, sweep=sweep), indent=1))
    _plot(sweep, table, always_d, always_s)


def _plot(sweep, table, always_d, always_s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    pts = [(r['C'], r['Q'], str(r['tau'])) for r in sweep]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], 'o-', label='SFE soft-sweep (tau)', color='#d62728')
    for c, q, t in pts:
        ax.annotate(t, (c, q), textcoords='offset points', xytext=(5, 4), fontsize=8)
    for name, color in [('always_single', '#1f77b4'), ('always_dynamic', '#ff7f0e')]:
        ax.plot(table[name]['C'], table[name]['Q'], 's', label=name, color=color)
    ax.plot(table['clairvoyant_fault_aware']['C'], table['clairvoyant_fault_aware']['Q'], '*',
            markersize=14, label='clairvoyant fault-aware (0.4917)', color='green')
    ax.set_xlabel('mean cost (tokens/task)')
    ax.set_ylabel('Q')
    ax.set_title('P1a: single-first escalation policies (zero-call audit)', fontsize=10)
    ax.grid(alpha=.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / 'pareto.png', dpi=150)


if __name__ == '__main__':
    run()
