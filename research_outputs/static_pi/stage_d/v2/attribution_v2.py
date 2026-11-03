"""Phase Pi V2 — Section-4 slot-level terminal attribution.

Deterministic cache-only replay of the 36 executed cells (identical arm|rep
tags, so every provider call is a ledger hit). Any cache miss raises, which
proves ZERO new provider calls. Frozen terminal_quality is the only scorer.

Outputs ATTRIBUTION_V2.json:
  - per-execution slot table (23 slots): answer presence, value correctness,
    evidence support, evidence localization (doc-id binding), missing fields
  - per-node output completeness and per-node token usage
  - degraded / failed / normal node rates
  - paired arm contrasts for the six acceptance questions
"""
import json, re, sys, statistics as st
sys.path.insert(0, '.')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
import executor as SA
import engine_v22 as E
import real_provider_v22 as R
from stage_d_v2_transport import Transport, Ledger
from terminal_quality import evaluate_terminal_quality

REQ = SA.CONTRACT['required_facts']
FIDS = [f['fact_id'] for f in REQ]
GOLD = {f['fact_id']: f.get('value') for f in REQ}
SRC_IDS = set(SA.SRC)
SCEN = ('S1', 'S1b')
REPS = (1, 2, 3)
ARMS = E.ARMS

VALUE_OK = ('CORRECT_GOLD', 'CORRECT_BUT_UNSUPPORTED_CITATION',
            'SEMANTICALLY_CORRECT', 'SEMANTICALLY_CORRECT_BUT_UNSUPPORTED_CITATION')
EVID_OK = ('CORRECT_GOLD', 'SEMANTICALLY_CORRECT')


def tag_for(arm, rep):
    return f'{arm}|' if rep == 1 else f'{arm}|r{rep}|'


def purpose_tag(tag, sc):
    return f'{tag}{sc}:'


def score_full(rec):
    sink = rec['outputs'].get('SINK')
    if not isinstance(sink, dict):
        return None, None
    term = SA.build_terminal_output(json.loads(json.dumps(sink)))
    res = evaluate_terminal_quality(SA.CONTRACT, term, SA.SRC)
    return term, res


def localization(claim):
    """Evidence localization against the frozen SRC inventory (diagnostic only)."""
    cits = (claim or {}).get('citations') or []
    if not cits:
        return dict(state='no_citation', doc=None, page=None)
    c = cits[0]
    doc, page = c.get('doc_id'), c.get('page')
    if c.get('page_sha256'):
        return dict(state='valid', doc=doc, page=page)
    m = re.search(r'D[1-4]', str(doc) if doc is not None else '')
    if m:
        return dict(state='label_drift', doc=doc, page=page, intended_doc=m.group(0))
    if doc not in SRC_IDS:
        return dict(state='unknown_doc', doc=doc, page=page)
    return dict(state='bad_page', doc=doc, page=page)


def run_cell(tr, lg, sc, rep, arm):
    tag = tag_for(arm, rep)
    prov = R.RealProvider(tr, lg, sc, cap_calls=16, tag=tag)
    rec = E.run_execution(arm, sc, cap_calls=16, provider=prov, simulated=False)
    term, res = score_full(rec)
    prefix = purpose_tag(tag, sc)
    slice_ = [r for r in lg.records if str(r.get('purpose', '')).startswith(prefix)]

    slots = []
    status_by_claim = {c.get('claim_id'): c.get('status') for c in (res or {}).get('claim_results', [])}
    claims_by_fid = {}
    for c in (term or {}).get('claims', []):
        if c.get('fact_id') is not None:
            claims_by_fid.setdefault(c['fact_id'], c)
    for f in REQ:
        fid = f['fact_id']
        claim = claims_by_fid.get(fid)
        cid = f'c_{fid}'
        status = status_by_claim.get(cid, 'NO_CLAIM' if claim is None else 'UNMAPPED')
        loc = localization(claim)
        slots.append(dict(
            fact_id=fid, gold_value=f.get('value'), gold_status=f.get('status'),
            answered=claim is not None,
            got_value=(claim or {}).get('value'),
            status=status,
            value_correct=status in VALUE_OK,
            evidence_ok=status in EVID_OK,
            evidence_localization=loc,
        ))

    node_out = {}
    for n, o in rec['outputs'].items():
        if isinstance(o, dict):
            node_out[n] = dict(keys=sorted(o.keys()), has_positions='positions' in o,
                               positions_n=len(o.get('positions') or []) if isinstance(o.get('positions'), list) else None,
                               chars=len(json.dumps(o, ensure_ascii=False)))
        else:
            node_out[n] = dict(keys=None, chars=len(json.dumps(o, ensure_ascii=False)))

    node_tok = {}
    for r in slice_:
        rest = str(r.get('purpose'))[len(prefix):]
        parts = rest.split(':')
        node = parts[0]
        u = r.get('usage', {})
        d = node_tok.setdefault(node, dict(calls=0, input_tokens=0, output_tokens=0))
        d['calls'] += 1
        d['input_tokens'] += u.get('input_tokens', 0)
        d['output_tokens'] += u.get('output_tokens', 0)

    states = {k: v for k, v in rec['states'].items() if v != 'DELETED'}
    return dict(
        scenario=sc, repeat=rep, arm=arm, stop=rec['stop_reason'],
        dag_version=rec['dag_version'], z_actions=rec['z_actions'], pi_scope=rec['pi_scope'],
        degraded_fields=rec['degraded_fields'], states=states,
        l1_fixed=rec['l1_fixed'], residual=rec['residual'],
        tp=sum(1 for s in slots if s['value_correct']),
        tp_evid=sum(1 for s in slots if s['evidence_ok']),
        q=(res or {}).get('Q_final'), q_raw=(res or {}).get('Q_raw'),
        blocking=(res or {}).get('blocking_reasons'), critical_gate=(res or {}).get('critical_gate'),
        fact_metrics=(res or {}).get('fact_metrics'),
        calls=rec['call_count'],
        cost_yuan=round(sum(r.get('accounting_yuan') or 0 for r in slice_), 8),
        tokens=sum(r['usage']['input_tokens'] + r['usage']['output_tokens'] for r in slice_),
        latency_s=round(sum(r.get('latency_s') or 0 for r in slice_), 2),
        slots=slots, node_outputs=node_out, node_tokens=node_tok,
        audits=[a for a in rec['audit'] if a.get('step') in ('R0', 'Z', 'pi', 'degraded', 'detect', 'policy')],
    )


def med(xs):
    vals = [x for x in xs if x is not None]
    return round(st.median(vals), 3) if vals else None


def main():
    lg = Ledger('/root/research_outputs/static_pi/stage_d/v2/PILOT_V2_LEDGER.jsonl')
    n0, t0, c0 = len(lg.records), lg.tokens, lg.cost
    # cache-only transport: any real call attempt raises RuntimeError('call cap')
    tr = Transport(lg, cap_calls=len(lg.records), cap_tokens=10 ** 12)
    cells = []
    for sc in SCEN:
        for rep in REPS:
            for arm in ARMS:
                cells.append(run_cell(tr, lg, sc, rep, arm))
                print(f'  replayed {sc} r{rep} {arm:12s} TP={cells[-1]["tp"]} '
                      f'TPevid={cells[-1]["tp_evid"]} deg={bool(cells[-1]["degraded_fields"])}', flush=True)
    new_calls = len(lg.records) - n0
    new_tokens = lg.tokens - t0
    assert new_calls == 0 and new_tokens == 0, f'cache miss: +{new_calls} calls, +{new_tokens} tokens'

    # ---- arm summaries
    summary = {}
    for arm in ARMS:
        for sc in SCEN:
            g = [c for c in cells if c['arm'] == arm and c['scenario'] == sc]
            summary[f'{sc}|{arm}'] = dict(
                tp=[c['tp'] for c in g], tp_median=med([c['tp'] for c in g]),
                tp_evid=[c['tp_evid'] for c in g], tp_evid_median=med([c['tp_evid'] for c in g]),
                q=[c['q'] for c in g], q_median=med([c['q'] for c in g]),
                cost_mean=round(st.mean([c['cost_yuan'] for c in g]), 6),
                tokens_mean=round(st.mean([c['tokens'] for c in g])),
                latency_mean=round(st.mean([c['latency_s'] for c in g]), 1),
                degraded_nodes=sum(1 for c in g if c['degraded_fields']),
                failed_nodes=sum(1 for c in g if any(v == 'FAILED' for v in c['states'].values())),
                stops=sorted({c['stop'] for c in g}),
                positions_restored=sum(1 for c in g if any(
                    (c['node_outputs'].get(n, {}) or {}).get('has_positions') for n in
                    ('E2_merge', 'E1_merge'))),
            )

    # ---- paired contrasts
    def pair(a_arm, b_arm, metric):
        out, vals = [], []
        for sc in SCEN:
            for rep in REPS:
                a = next(c for c in cells if c['scenario'] == sc and c['repeat'] == rep and c['arm'] == a_arm)
                b = next(c for c in cells if c['scenario'] == sc and c['repeat'] == rep and c['arm'] == b_arm)
                d = None if (a[metric] is None or b[metric] is None) else a[metric] - b[metric]
                out.append(dict(scenario=sc, repeat=rep, delta=d))
                if d is not None:
                    vals.append(d)
        return dict(pairs=out, n_defined=len(vals),
                    median_delta=med(vals), mean_delta=round(st.mean(vals), 3) if vals else None,
                    wins=sum(1 for v in vals if v > 0), ties=sum(1 for v in vals if v == 0),
                    losses=sum(1 for v in vals if v < 0))

    contrasts = {}
    for a, b in (('Z-only', 'Retry-only'), ('Joint', 'pi-only'), ('Joint', 'Z-only'),
                 ('pi-only', 'Retry-only'), ('Z-only', 'Static-GLM'), ('Joint', 'Static-GLM')):
        contrasts[f'{a} - {b}'] = {m: pair(a, b, m) for m in ('tp', 'tp_evid', 'q')}

    # ---- slot-level aggregation: TP rate per fact per arm (both scenarios pooled)
    slot_rate = {}
    for arm in ARMS:
        g = [c for c in cells if c['arm'] == arm]
        slot_rate[arm] = {}
        for fid in FIDS:
            vals = [next(s for s in c['slots'] if s['fact_id'] == fid) for c in g]
            slot_rate[arm][fid] = dict(
                value_correct=sum(1 for s in vals if s['value_correct']),
                evidence_ok=sum(1 for s in vals if s['evidence_ok']),
                answered=sum(1 for s in vals if s['answered']),
                n=len(vals),
                drift=sum(1 for s in vals if s['evidence_localization']['state'] == 'label_drift'),
            )

    # ---- localization drift census
    drift = {}
    for arm in ARMS:
        g = [c for c in cells if c['arm'] == arm]
        st_counts = {}
        for c in g:
            for s in c['slots']:
                k = s['evidence_localization']['state']
                st_counts[k] = st_counts.get(k, 0) + 1
        drift[arm] = st_counts

    # ---- node completeness / token profile per arm (S1 only: split happens on E2)
    node_profile = {}
    for arm in ARMS:
        g = [c for c in cells if c['arm'] == arm and c['scenario'] == 'S1']
        node_profile[arm] = dict(
            keys={n: sorted({tuple(c['node_outputs'].get(n, {}).get('keys') or []) for c in g})
                  for n in ('E1', 'E2', 'E2_pos', 'E2_rest', 'E2_merge', 'J1', 'J2', 'SINK')},
            tokens={n: round(st.mean([c['node_tokens'].get(n, {}).get('input_tokens', 0) for c in g]))
                    for n in ('E1', 'E2', 'E2_pos', 'E2_rest', 'J1', 'J2', 'SINK')},
        )

    # ---- degraded census
    deg = {}
    for arm in ARMS:
        g = [c for c in cells if c['arm'] == arm]
        deg[arm] = dict(
            executions_with_degraded=sum(1 for c in g if c['degraded_fields']),
            executions_with_failed=sum(1 for c in g if any(v == 'FAILED' for v in c['states'].values())),
            executions_all_completed=sum(1 for c in g if all(v == 'COMPLETED' for v in c['states'].values())),
            degraded_node_states={},
            n=len(g),
        )
        for c in g:
            for n, v in c['states'].items():
                if v == 'COMPLETED_DEGRADED':
                    deg[arm]['degraded_node_states'][n] = deg[arm]['degraded_node_states'].get(n, 0) + 1

    # ---- V1 reference (summary-level only; V1 predates degraded semantics)
    v1 = json.load(open('/root/research_outputs/static_pi/stage_d/v2/PILOT_V1_RESULTS.json'))
    v1_summary = {}
    for arm in ARMS:
        for sc in SCEN:
            tps = [e['tp'] for e in v1['executions'] if e.get('scenario_id') == sc and e.get('arm') == arm]
            v1_summary[f'{sc}|{arm}'] = dict(tp=tps, tp_median=med(tps))

    out = dict(
        batch='PHASE_PI_V2_SECTION4_ATTRIBUTION', simulated=False,
        ledger_calls=n0, ledger_tokens=t0, ledger_cost_yuan=round(c0, 6),
        replay_new_calls=new_calls, replay_new_tokens=new_tokens,
        executor_unchanged=False,  # filled by freeze script
        summary=summary, contrasts=contrasts, slot_rate=slot_rate,
        localization_drift=drift, node_profile=node_profile, degraded=deg,
        v1_reference=v1_summary, cells=cells,
    )
    json.dump(out, open('/root/research_outputs/static_pi/stage_d/v2/ATTRIBUTION_V2.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f'\n zero new calls verified ({new_calls} calls, {new_tokens} tokens)')
    print(f' wrote ATTRIBUTION_V2.json ({len(cells)} cells)')


if __name__ == '__main__':
    main()
