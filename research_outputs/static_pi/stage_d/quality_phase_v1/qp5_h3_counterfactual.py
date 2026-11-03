"""H3 counterfactual on QP4 raw outputs (zero calls). Clean implementation.

Structure-robust builder (qp3 normalizer) + deterministic delivery:
  H3-attach: TP if the actual SINK value strict-passes gold AND a verified,
             name-matched evidence entry exists (runner attaches doc/page/quote).
  H3-full:   TP if additionally/alternatively a verified entry's own value
             strict-passes gold (value delivered from the table too).
Census of the shipped-builder defect (empty table from structure mismatch).
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp2_chain as CH
import qp3_primitives as P3
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def strict_val(v, f):
    if v in (None, ''):
        return False
    return bool(Q1.TQ._value_equal({'value': v, 'value_kind': f.get('value_kind')}, dict(f)))


def verbatim(e, contract):
    pg = (contract['source_pages'].get(str(e.get('doc'))) or {}).get('pages', {}).get(str(e.get('page')))
    if not pg or not e.get('quote'):
        return False
    return Q1._norm(e['quote']) in Q1._norm(pg.get('text', ''))


def usable_for(f, e_objs, contract):
    """E entries that deterministic delivery could bind to this fact:
    quote verbatim in the cited page AND (name-matched OR the gold value is
    grounded in the quote). Evidence-grounded join is the operative key;
    name matching is a secondary signal only."""
    out = []
    for obj in e_objs:
        for e in P3.normalize_stage(obj):
            if not verbatim(e, contract):
                continue
            q = e.get('quote', '')
            grounds = Q1.value_in_quote(f.get('value'), q)
            v = e.get('raw') or e.get('value')
            val_match = strict_val(v, f) or P3.value_equal_anyway(v, f)[0]
            if grounds or (P3.name_matches(e, f) and val_match):
                out.append(e)
    return out


class _F(dict):
    pass


_FACT = _F()


def main():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    d = json.load(open(f'{QP}/QP4_RESULTS.json'))
    rows = []
    for r in d['results']:
        if r.get('q') is None or r['cell'] not in 'BD':
            continue
        t, c, rep = r['task'], r['cell'], f"r{r['rep']}"
        contract = F.load_contract(t)
        e0 = extract_any(led[(t, c, rep, 'e0')]['text'])
        e1 = extract_any(led[(t, c, rep, 'e1')]['text'])
        sink = extract_any(led[(t, c, rep, 'p')]['text'])
        res = Q1.score_task(contract, sink)
        ans = {}
        for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
            if isinstance(a, dict) and a.get('fact_id'):
                ans.setdefault(a['fact_id'], a)

        facts = contract['required_facts']
        n = len(facts)
        tp = h3a = h3f = amb = tp_lost = 0
        for f in facts:
            fid = f['fact_id']
            row = next(x for x in res['rows'] if x['fact_id'] == fid)
            sink_val = (ans.get(fid) or {}).get('value')
            usable = usable_for(f, (e0, e1), contract)
            vals = {str(e.get('raw') or e.get('value')) for e in usable}
            amb += len(vals) > 1
            sink_ok = strict_val(sink_val, f)
            entry_val_ok = any(strict_val(e.get('raw') or e.get('value'), f) for e in usable)
            is_tp = row['status'] == 'TP'
            tp += is_tp
            tp_lost += is_tp and not usable
            h3a += bool(sink_ok and usable)
            h3f += bool((sink_ok and usable) or entry_val_ok)
        table = CH.build_evidence_table({'e0': e0, 'e1': e1})
        rows.append(dict(task=t, cell=c, rep=int(rep[1:]), n=n,
                         q_actual=round(tp / n, 4), h3_attach=round(h3a / n, 4),
                         h3_full=round(h3f / n, 4),
                         tp_at_risk=int(tp_lost),
                         shipped_defect=len(table) == 0, ambiguities=int(amb)))
    json.dump(dict(batch='QP5_H3_COUNTERFACTUAL', model_calls=0, rows=rows),
              open(f'{QP}/QP5_H3_COUNTERFACTUAL.json', 'w'), ensure_ascii=False, indent=1)
    by = collections.defaultdict(list)
    for r in rows:
        by[(r['task'], r['cell'])].append(r)
    print(f"{'task':9s} {'cell':4s} {'Q_act':>6s} {'H3att':>6s} {'H3full':>6s}  shipdef")
    for k in sorted(by):
        g = by[k]
        print(f"{k[0]:9s} {k[1]:4s} {st.mean(x['q_actual'] for x in g):6.3f} "
              f"{st.mean(x['h3_attach'] for x in g):6.3f} {st.mean(x['h3_full'] for x in g):6.3f}  "
              f"{'YES' if any(x['shipped_defect'] for x in g) else 'no':>4s} "
              f"tpRisk={sum(x['tp_at_risk'] for x in g)}")
    for c in ('B', 'D'):
        g = [x for x in rows if x['cell'] == c]
        print(f"\n{c}: actual {st.mean(x['q_actual'] for x in g):.3f} -> "
              f"H3attach {st.mean(x['h3_attach'] for x in g):.3f} -> "
              f"H3full {st.mean(x['h3_full'] for x in g):.3f} "
              f"(shipped-defect cells {sum(1 for x in g if x['shipped_defect'])}/{len(g)}; "
              f"ambiguous buckets {sum(x['ambiguities'] for x in g)})")
    dcells = [x for x in rows if x['cell'] == 'D']
    macro_now = st.mean(x['q_actual'] for x in dcells)
    macro_h3a = st.mean(x['h3_attach'] for x in dcells)
    macro_h3f = st.mean(x['h3_full'] for x in dcells)
    per_task_h3f = {t: st.mean(x['h3_full'] for x in dcells if x['task'] == t)
                    for t in F.TASKS}
    print(f"\nD macro: actual {macro_now:.3f} | H3-attach {macro_h3a:.3f} | H3-full {macro_h3f:.3f}")
    print('H3-full per task:', {k: round(v, 3) for k, v in per_task_h3f.items()},
          '| macro', round(st.mean(per_task_h3f.values()), 4))


if __name__ == '__main__':
    main()
