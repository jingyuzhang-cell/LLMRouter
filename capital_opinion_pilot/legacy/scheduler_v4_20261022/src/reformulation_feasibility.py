"""Reformulation feasibility (zero-pay): task-level quality model + non-trivial
action enumeration on REAL states, vs a strong two-stage baseline.

Data provenance (all from saved real responses, no assumptions):
  grounding g(event,node,model) = fraction of extracted facts whose quote is a
  verbatim substring (norm) of the node's frozen evidence pack.
  verdict stats from t5 outputs; per-(node,model) tokens/latency from ledgers.

Q_task_hat(R, pi | S) = expected # of evidence-chained facts surviving to the
deliverable, estimated as:
    sum over extraction nodes v of  g(ev,v,pi(v)) * surv(v)
    (cached outputs use their OWN observed grounding, not the class rate)
  where surv = empirical chain-survival multiplier from the RF2 trace study
  (extraction-layer signal reaches deliverable at measured rates; mid-chain
  survival treated as observed range with n). Cells with n=0 -> UNIDENTIFIED
  (never filled with guesses). NO reward term for larger R.

States (real, from logs):
  X = f7v2 R2 double-fault moment (KDX): t1 already recovered on glm53 (its
      cached output observed); second fault = t2 truncation; F7 still blocks
      (t1,deepseek). Decision: R for the second recovery.
  Y = stv2 clean post-t5 (ST): t5 emitted UNRESOLVED verdicts (observable
      trigger for selective re-verification). Decision: expand R or not.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
import evidence_packer as ep
import st_window_validation as swv
from json_compat import parse_layers

P = PILOT_DIR

# ---------- evidence packs ----------
kdx_ranked = ep.rank_chunks(ep.build_index())
KDX = ep.pack_lines(10000, {'t1': ['kdx_penalty_2020', 'kdx_notice_2019', 'kdx_notice_2020'],
                            't2': ['kdx_inquiry_2018', 'kdx_inquiry_2019']}, ranked=kdx_ranked)
st_index = swv.build_st_index(); st_ranked = swv.rank_st(st_index)
ST = {line: ep.pack_global(5000, doc_ids=docs, index=st_index, ranked=st_ranked)
      for line, docs in swv.LINE_DOCS.items()}
PACKS = {'kdx': KDX, 'st': ST}


def load_resp(files):
    rows = []
    for f in files:
        for l in open(P / f):
            if l.strip():
                rows.append(json.loads(l))
    return rows


def grounding_table(rows, event_of):
    agg = {}
    for r in rows:
        if r['node'] not in ('t1', 't2'):
            continue
        ev = event_of(r['run_id'])
        if ev is None:
            continue
        pl = parse_layers(r['text'])
        if not pl['compat_ok']:
            continue
        facts = (pl['value'] or {}).get('facts', [])
        if not isinstance(facts, list) or not facts:
            continue
        hay = norm(PACKS[ev][r['node']]['text'])
        g = t = 0
        for f_ in facts:
            if not isinstance(f_, dict):
                continue
            t += 1
            q = norm(str(f_.get('quote', '') or ''))
            if q and len(q) >= 6 and q in hay:
                g += 1
        if t:
            a = agg.setdefault((ev, r['node'], r['model']), [0, 0])
            a[0] += g; a[1] += t
    return {k: {'grounded': g, 'total': t, 'rate': round(g / t, 3), 'n_calls': 1}
            for k, (g, t) in agg.items()}


# ---------- task-level quality estimator (provenance-labelled) ----------
class QTask:
    """Expected chained-fact count. surv: extraction-layer RF2-signal survival
    measured zero-pay earlier (t1->deliverable): DS 0.70, GLM 0.29 on KDX
    (n=10/7); mid-chain re-statement treated as already inside those rates.
    UNIDENTIFIED cells return None and PROPAGATE (never guessed)."""

    SURV = {('kdx', 'deepseek'): 0.70, ('kdx', 'glm53'): 0.29}
    SURV_ST = None  # no ST-specific chain-survival measurement -> unidentified

    def __init__(self, gtable):
        self.g = gtable

    def rate(self, ev, node, model):
        cell = self.g.get((ev, node, model))
        return cell['rate'] if cell else None

    def expected_chained_facts(self, ev, assign, cached):
        """assign: {t1:model,t2:model} AFTER action; cached: observed grounded
        counts for outputs we KEEP (dict node->(grounded,total)) or None."""
        total = 0.0
        identified = True
        for node in ('t1', 't2'):
            if cached and node in cached:
                g, t = cached[node]
                surv = self.SURV.get((ev, assign.get(node, 'glm53'))) if ev == 'kdx' else self.SURV_ST
                if surv is None:
                    identified = False
                    continue
                total += g * surv
            else:
                r = self.rate(ev, node, assign[node])
                surv = self.SURV.get((ev, assign[node])) if ev == 'kdx' else self.SURV_ST
                if r is None or surv is None:
                    identified = False
                    continue
                # expected facts per extraction from history (mean of cells)
                cell = self.g.get((ev, node, assign[node]))
                mean_facts = cell['total']  # conservative: one call's count
                total += r * mean_facts * surv
        return (total if identified else None)


# ---------- state X enumeration (KDX, f7v2 R2 second fault) ----------
def state_x(rows):
    # t1 cached output = f7v2 R2's t1-glm53 response (observed grounding)
    t1_resp = [r for r in rows if r['run_id'] == 'R2_S5Cap_F7' and r['node'] == 't1' and r['model'] == 'glm53']
    pl = parse_layers(t1_resp[-1]['text'])
    facts = (pl['value'] or {}).get('facts', [])
    hay = norm(PACKS['kdx']['t1']['text'])
    g = sum(1 for f_ in facts if isinstance(f_, dict) and norm(str(f_.get('quote', '')))[:40] in hay)
    return {'cached_t1': (g, len(facts)), 'n_t1_facts': len(facts)}


def enumerate_x(qtask, cached_t1):
    """R options for the SECOND fault (t2), all dependency-legal:
       A  min-closure(t2)            keep t1 cache
       A+ min-closure(t2) + re-exec t1 (model from pool minus blocked DS)
       F  FULL
    pi freedom per node; costs from IN_EST-ish real ledger means."""
    TOK = {('t1', 'glm53'): 5530, ('t1', 'glm53flash'): 5530, ('t1', 'qwen'): 5000,
           ('t2', 'deepseek'): 5100, ('t2', 'glm53'): 5100, ('t2', 'glm53flash'): 5100, ('t2', 'qwen'): 4800,
           ('t3', 'glm53'): 4000, ('t3', 'deepseek'): 4000, ('t3', 'glm53flash'): 3600,
           ('t4', 'glm53'): 4300, ('t4', 'deepseek'): 5300, ('t4', 'glm53flash'): 4300,
           ('t5', 'deepseek'): 3500, ('t5', 'glm53'): 2700,
           ('t6', 'glm53'): 2600, ('t6', 'deepseek'): 3500, ('t6', 'glm53flash'): 3300}
    LAT = {('t1', 'glm53'): 17.6, ('t1', 'glm53flash'): 15.0, ('t1', 'qwen'): 10.0,
           ('t2', 'deepseek'): 7.8, ('t2', 'glm53'): 13.0, ('t2', 'glm53flash'): 13.0, ('t2', 'qwen'): 10.0,
           ('t3', 'glm53'): 9.0, ('t3', 'deepseek'): 4.0, ('t3', 'glm53flash'): 12.0,
           ('t4', 'glm53'): 15.0, ('t4', 'deepseek'): 7.0, ('t4', 'glm53flash'): 12.0,
           ('t5', 'deepseek'): 6.0, ('t5', 'glm53'): 12.0,
           ('t6', 'glm53'): 15.0, ('t6', 'deepseek'): 5.0, ('t6', 'glm53flash'): 17.0}
    CASH = {'deepseek': 0.0000005, 'qwen': 0.0000014}  # ¥/token approx (off-peak DS)
    PLANS = []
    base_down = {'t3': ['glm53', 'deepseek'], 't4': ['glm53', 'deepseek'],
                 't5': ['deepseek', 'glm53'], 't6': ['glm53', 'deepseek']}
    for t2m in ('deepseek', 'glm53', 'glm53flash'):
        for expand_t1 in (False, True):
            t1m_opts = ['glm53flash', 'qwen'] if expand_t1 else [None]
            for t1m in t1m_opts:
                # downstream: greedy Q/C/L (the STRONG BASELINE) to keep the
                # comparison at the R dimension; joint-over-pi noted separately
                down = {}
                for n, opts in base_down.items():
                    down[n] = min(opts, key=lambda m: (LAT[(n, m)], TOK[(n, m)]))
                nodes = ['t2', 't3', 't4', 't5', 't6'] + (['t1'] if expand_t1 else [])
                assign = {'t1': t1m or 'glm53(cache)', 't2': t2m, **down}
                cost = sum(TOK[(n, assign[n])] for n in nodes if (n, assign[n]) in TOK)
                # parallel critical path from decision point (~27s elapsed in R2)
                def lat_of(n, m):
                    return LAT.get((n, m), 10.0)
                path = max(lat_of('t2', t2m) if True else 0,
                           (lat_of('t1', t1m) if expand_t1 else 0)) \
                    + max(lat_of('t3', down['t3']), lat_of('t4', down['t4'])) \
                    + lat_of('t5', down['t5']) + lat_of('t6', down['t6'])
                cash = sum(CASH.get(assign[n], 0) * TOK[(n, assign[n])] for n in nodes if (n, assign[n]) in TOK)
                # task-level quality
                assign_for_q = {'t1': t1m or 'glm53', 't2': t2m}
                cached = None if expand_t1 else {'t1': cached_t1}
                q = qtask.expected_chained_facts('kdx', assign_for_q, cached)
                PLANS.append({'plan': f"R={'closure(t2)+t1' if expand_t1 else 'closure(t2)'}",
                              'pi_t1': assign['t1'], 'pi_t2': t2m, 'down': down,
                              'tokens': cost, 'cash_rmb': round(cash, 4),
                              'path_s': round(path, 1), 'q_task': q,
                              'q_identified': q is not None})
    return PLANS


def pareto(plans):
    """mutual non-dominance on (max q, min tokens, min path, min cash);
    UNIDENTIFIED q plans listed separately (never counted as wins)."""
    ident = [p for p in plans if p['q_identified']]
    dom = []
    for p in ident:
        dominated = any(q is not p and q['q_task'] >= p['q_task'] and q['tokens'] <= p['tokens']
                        and q['path_s'] <= p['path_s'] and q['cash_rmb'] <= p['cash_rmb']
                        and (q['q_task'] > p['q_task'] or q['tokens'] < p['tokens']
                             or q['path_s'] < p['path_s'] or q['cash_rmb'] < p['cash_rmb'])
                        for q in ident)
        if not dominated:
            dom.append(p)
    return dom, [p for p in plans if not p['q_identified']]


def main():
    rows = load_resp(['f7v2_resp.jsonl', 'stv2_resp.jsonl', 'stv4_resp.jsonl'])

    def ev_of(rid):
        if rid.startswith('R'):  # f7v2/f7min KDX
            return 'kdx'
        return 'st'

    gt = grounding_table(rows, ev_of)
    print('== grounding table (measured, n=facts) ==')
    for k, v in sorted(gt.items()):
        print(f"  {k}: {v['grounded']}/{v['total']} = {v['rate']}")

    qt = QTask(gt)
    sx = state_x(rows)
    print(f"\nstate X cached t1(glm53): {sx['cached_t1']} grounded/total facts")

    plans = enumerate_x(qt, sx['cached_t1'])
    dom, unident = pareto(plans)
    print(f"\n== state X enumeration: {len(plans)} plans, identified {len(plans)-len(unident)}, "
          f"unidentified {len(unident)}, Pareto {len(dom)} ==")
    for p in dom:
        print(f"  PARETO {p['plan']} t2={p['pi_t2']} t1={p['pi_t1']} "
              f"Q̂={p['q_task']:.2f} tok={p['tokens']} path={p['path_s']}s ¥{p['cash_rmb']}")
    for p in unident[:4]:
        print(f"  UNIDENT q: {p['plan']} t2={p['pi_t2']} t1={p['pi_t1']} (missing cell)")

    # two-stage baseline on X: rule picks min closure; per-node assignment same
    base = next(p for p in plans if p['plan'] == 'R=closure(t2)' and p['pi_t2'] == 'glm53')
    print(f"\n  two-stage baseline: {base['plan']}/glm53 Q̂={base['q_task']} "
          f"tok={base['tokens']} path={base['path_s']}s")

    # State Y: ST post-t5 UNRESOLVED — grounding deltas
    print("\n== state Y (ST, post-t5 UNRESOLVED): available grounding cells ==")
    for k in (('st', 't1', 'glm53'), ('st', 't1', 'glm53flash'), ('st', 't2', 'deepseek')):
        print(f"  {k}: {gt.get(k)}")

    out = {'grounding_table': {str(k): v for k, v in gt.items()},
           'state_X': {'cached_t1': sx['cached_t1'], 'plans': plans,
                       'pareto': dom, 'unidentified': unident,
                       'baseline': base},
           'survival_provenance': {'kdx deepseek': '7/10 RF2-signal (zero-pay trace)',
                                   'kdx glm53': '2/7 RF2-signal (zero-pay trace)',
                                   'st': 'NOT MEASURED -> unidentified'}}
    (P / 'reformulation_feasibility.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('\nsaved reformulation_feasibility.json')


if __name__ == '__main__':
    main()
