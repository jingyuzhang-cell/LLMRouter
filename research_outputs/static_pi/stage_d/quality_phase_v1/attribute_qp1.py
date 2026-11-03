"""QP1 error attribution on EXISTING real outputs (zero calls).

Sources:
  - V2 pilot: 36 SINK cells (T1 contract, 23 facts), all six arms
  - S2 A-condition: 24 SINK cells (12 tasks x 2 reps), full materials only

Descriptive only: this is not a new experiment and cannot confirm any candidate
scorer. It answers "where does terminal quality go wrong?" on outputs that
already exist.
"""
import json, sys, os, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import scorer_qp1 as Q

ROOT = '/root/research_outputs/static_pi/stage_d'
T1 = json.load(open('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/TASK_CONTRACT_PHASE2B_v2_1.json'))
CANDS = {t['event_key']: t for t in json.load(open(f'{ROOT}/v23a/TASK_CANDIDATES_V23A.json'))['candidates']}


def parse(t):
    dec = json.JSONDecoder()
    c = (t or '').strip()
    if c.startswith('```'):
        c = '\n'.join(c.split('\n')[1:]).replace('```', '').strip()
    try:
        return json.loads(c)
    except Exception:
        pass
    for i, ch in enumerate(c):
        if ch in '{[':
            try:
                return dec.raw_decode(c[i:])[0]
            except Exception:
                continue
    return None


def subtype(f):
    vk = f.get('value_kind')
    txt = str(f.get('bucket', '')) + str(f.get('predicate', ''))
    if vk in ('number', 'amount', 'percent') or any(k in txt for k in ('金额', '罚款', '收入', '利润', '占用', '担保', '对价', '比例', '价')):
        return 'amount'
    if vk == 'date' or any(k in txt for k in ('日期', '时点', '何时')):
        return 'date'
    if any(k in txt for k in ('对象', '主体', '职务')):
        return 'subject'
    if any(k in txt for k in ('关系', '同一', '对应', '一致', '比对')):
        return 'relation'
    return 'other'


def loc_cause(contract, a):
    pages = contract.get('source_pages', {})
    doc = pages.get(str(a.get('doc')))
    if not doc:
        return 'doc_not_found'
    pg = (doc.get('pages') or {}).get(str(a.get('page')))
    if not pg:
        return 'page_not_found'
    if not str(a.get('quote', '')).strip():
        return 'quote_missing'
    from scorer_qp1 import _norm
    if _norm(a['quote']) not in _norm(pg.get('text', '')):
        return 'quote_not_verbatim'
    return 'other'


def load_contract(path):
    if not os.path.isabs(path):
        path = f'{ROOT}/v23a/{path}'
    return json.load(open(path))


def score_cells(cells, contract_for):
    out = []
    for key, sink in cells:
        con = contract_for(key)
        r = Q.score_task(con, sink)
        out.append((key, con, sink, r))
    return out


def v2_cells():
    recs = [json.loads(l) for l in open(f'{ROOT}/v2/PILOT_V2_LEDGER.jsonl')]
    cells = {}
    for r in recs:
        p = r['purpose']
        if not p.endswith(':SINK:SINK'):
            continue
        tag = p[:-len(':SINK:SINK')]
        cells[tag] = parse(r['text'])
    return list(cells.items())


def s2_a_cells():
    recs = [json.loads(l) for l in open(f'{ROOT}/v23a/S2_LEDGER.jsonl')]
    cells = {}
    for r in recs:
        parts = r['purpose'].split('|')
        if len(parts) < 5 or parts[2] != 'A' or parts[4] != 'SINK':
            continue
        cells[(parts[1], parts[3])] = parse(r['text'])
    return list(cells.items())


def summarize(rows, label):
    fact_rows = [x for _, _, _, r in rows for x in r['rows']]
    status = collections.Counter(x['status'] for x in fact_rows)
    sub = collections.Counter()
    loc = collections.Counter()
    for key, con, sink, r in rows:
        ans = {a.get('fact_id'): a for a in (sink or {}).get('answers', [])
               if isinstance(a, dict)} if isinstance(sink, dict) else {}
        for x in r['rows']:
            if x['status'] == 'VALUE_WRONG':
                f = next((ff for ff in con['required_facts'] if ff['fact_id'] == x['fact_id']), {})
                sub[subtype(f)] += 1
            if x['status'] in ('LOC_WRONG', 'UNSUPPORTED'):
                a = ans.get(x['fact_id']) or {}
                loc[loc_cause(con, a) if x['status'] == 'LOC_WRONG' else 'quote_not_supporting'] += 1
    n = len(fact_rows)
    return dict(label=label, cells=len(rows), facts=n,
                mean_q=round(st.mean(r['q'] for _, _, _, r in rows), 4),
                value_correct_rate=round(st.mean(r['fact_value_correct_rate'] for _, _, _, r in rows), 4),
                localization_rate=round(st.mean(r['evidence_localization_rate'] for _, _, _, r in rows), 4),
                support_rate=round(st.mean(r['evidence_support_rate'] for _, _, _, r in rows), 4),
                unknown_accuracy=round(st.mean([r['unknown_accuracy'] for _, _, _, r in rows
                                                if r['unknown_accuracy'] is not None] or [0]), 4),
                gate_pass_rate=round(sum(1 for _, _, _, r in rows if r['critical_gate'] == 'PASS') / len(rows), 4),
                status_counts=dict(status), value_error_subtypes=dict(sub),
                evidence_failures=dict(loc))


def main():
    v2 = score_cells(v2_cells(), lambda k: T1)
    s2 = score_cells(s2_a_cells(), lambda k: load_contract(CANDS[k[0]]['contract']))
    out = dict(batch='QP1_ERROR_ATTRIBUTION', model_calls=0,
               note='descriptive attribution on existing outputs; not confirmatory',
               v2=summarize(v2, 'V2 pilot (36 cells, T1 23 facts)'),
               s2=summarize(s2, 'S2 A-condition (24 cells, 12 tasks)'),
               per_task={})
    for key, con, sink, r in s2:
        out['per_task'].setdefault(key[0], []).append(
            dict(rep=key[1], q=r['q'], value=r['fact_value_correct_rate'],
                 loc=r['evidence_localization_rate'], sup=r['evidence_support_rate'],
                 gate=r['critical_gate'], n=r['n_facts']))
    agg = {}
    for t, rs in out['per_task'].items():
        agg[t] = dict(n=rs[0]['n'], q=round(st.mean(x['q'] for x in rs), 4),
                      value=round(st.mean(x['value'] for x in rs), 4),
                      loc=round(st.mean(x['loc'] for x in rs), 4),
                      sup=round(st.mean(x['sup'] for x in rs), 4),
                      gate_pass=round(sum(1 for x in rs if x['gate'] == 'PASS') / len(rs), 3))
    out['macro_q_s2'] = round(st.mean(v['q'] for v in agg.values()), 4)
    out['per_task_summary'] = agg
    json.dump(out, open(f'{ROOT}/quality_phase_v1/QP1_ERROR_ATTRIBUTION.json', 'w'),
              ensure_ascii=False, indent=1)
    for k in ('v2', 's2'):
        s = out[k]
        print(f"{s['label']}: cells={s['cells']} Q={s['mean_q']:.3f} value={s['value_correct_rate']:.3f} "
              f"loc={s['localization_rate']:.3f} sup={s['support_rate']:.3f} "
              f"unk={s['unknown_accuracy']:.3f} gate={s['gate_pass_rate']:.3f}")
        print('   status:', s['status_counts'])
        print('   value subtypes:', s['value_error_subtypes'])
        print('   evidence failures:', s['evidence_failures'])
    print('\nS2 per-task Q / gate:')
    for t, v in sorted(agg.items(), key=lambda kv: -kv[1]['q']):
        print(f"  {t[:42]:42s} n={v['n']:2d} Q={v['q']:.3f} val={v['value']:.2f} "
              f"loc={v['loc']:.2f} sup={v['sup']:.2f} gate={v['gate_pass']:.2f}")
    print('\nmacro Q (S2, 12 tasks):', out['macro_q_s2'])


if __name__ == '__main__':
    main()
