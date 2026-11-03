"""QP4 per-fact quality-loss attribution across all six tasks (zero calls).

Operator-requested categories, computed from the 286-call ledger:
  CORRECT                strict TP
  OMISSION               SINK did not answer (subsplit: upstream had it or not)
  VALUE_ERROR_GEN        value wrong, upstream never carried it
  VALUE_ERROR_LOST       value wrong, upstream (E or M) carried it correctly
  EVIDENCE_MISSING       E layer produced no verbatim evidence entry for the fact
  CITATION_ERROR         value correct but doc/page/verbatim wrong
  UNSUPPORTED            value+loc ok, quote does not ground the value
Plus: composite/derived vs simple fact TP rates (multi-evidence direction).
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp3_primitives as P3
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def strict(v, f):
    return bool(v not in (None, '')) and Q1.TQ._value_equal(
        {'value': v, 'value_kind': f.get('value_kind')}, dict(f))


def stage_has(entries, f):
    for e in entries:
        v = e.get('raw') or e.get('value')
        if strict(v, f) or P3.value_equal_anyway(v, f)[0]:
            return True
        if e.get('quote') and Q1.value_in_quote(f.get('value'), e.get('quote', '')):
            return True
    return False


def e_has_verbatim_evidence(e_objs, f, contract):
    for obj in e_objs:
        for e in P3.normalize_stage(obj):
            pg = (contract['source_pages'].get(str(e.get('doc'))) or {}
                  ).get('pages', {}).get(str(e.get('page')))
            if not pg or not e.get('quote'):
                continue
            if Q1._norm(e['quote']) not in Q1._norm(pg.get('text', '')):
                continue
            if Q1.value_in_quote(f.get('value'), e.get('quote', '')) or \
                    P3.name_matches(e, f):
                return True
    return False


def is_composite(f):
    v = str(f.get('value', ''))
    b = str(f.get('bucket', '')) + str(f.get('predicate', ''))
    multi_ev = len(f.get('source_evidence') or []) > 1
    multi_num = sum(1 for ch in v if ch in '、/＋+' and False) or v.count('、') + v.count('/') >= 1
    derived = any(k in b for k in ('关系', '同一', '对应', '是否', '时间链'))
    return multi_ev or multi_num or derived


def main():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    d = json.load(open(f'{QP}/QP4_RESULTS.json'))
    rows = []
    for r in d['results']:
        if r.get('q') is None:
            continue
        t, c, rep = r['task'], r['cell'], f"r{r['rep']}"
        contract = F.load_contract(t)
        e0 = extract_any(led[(t, c, rep, 'e0')]['text'])
        e1 = extract_any(led[(t, c, rep, 'e1')]['text'])
        m = extract_any(led[(t, c, rep, 'm')]['text'])
        sink = extract_any(led[(t, c, rep, 'p')]['text'])
        res = Q1.score_task(contract, sink)
        ans = {}
        for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
            if isinstance(a, dict) and a.get('fact_id'):
                ans.setdefault(a['fact_id'], a)
        e_entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
        m_entries = P3.normalize_stage(m)
        for f in contract['required_facts']:
            fid = f['fact_id']
            row = next(x for x in res['rows'] if x['fact_id'] == fid)
            a = ans.get(fid)
            rec = dict(task=t, cell=c, rep=int(rep[1:]), fact_id=fid,
                       composite=is_composite(f), critical=bool(f.get('critical')))
            e_ok = stage_has(e_entries, f)
            m_ok = stage_has(m_entries, f)
            if row['status'] == 'TP':
                rec['cause'] = 'CORRECT'
            elif a is None or a.get('value') in (None, ''):
                rec['cause'] = 'OMISSION_UPSTREAM_OK' if (e_ok or m_ok) else 'OMISSION_UPSTREAM_MISSING'
            elif not strict(a.get('value'), f):
                if e_ok or m_ok:
                    rec['cause'] = 'VALUE_ERROR_LOST'
                else:
                    rec['cause'] = 'VALUE_ERROR_GEN'
            elif not row.get('localization'):
                rec['cause'] = 'CITATION_ERROR'
            else:
                rec['cause'] = 'UNSUPPORTED'
            rec['evidence_at_e'] = e_has_verbatim_evidence((e0, e1), f, contract)
            rows.append(rec)
    json.dump(dict(batch='QP4_FACT_LOSS_ATTRIBUTION', model_calls=0, rows=rows),
              open(f'{QP}/QP4_FACT_LOSS_ATTRIBUTION.json', 'w'), ensure_ascii=False, indent=1)

    print(f"{'cause':28s} {'n':>4s} {'%':>6s}")
    cnt = collections.Counter(r['cause'] for r in rows)
    for k, v in cnt.most_common():
        print(f'{k:28s} {v:4d} {v/len(rows)*100:5.1f}%')
    print('\nper-task (share CORRECT, D cells):')
    for t in F.TASKS:
        g = [r for r in rows if r['task'] == t and r['cell'] == 'D']
        cor = sum(1 for r in g if r['cause'] == 'CORRECT')
        om = sum(1 for r in g if r['cause'].startswith('OMISSION'))
        ve = sum(1 for r in g if r['cause'].startswith('VALUE_ERROR'))
        cit = sum(1 for r in g if r['cause'] in ('CITATION_ERROR', 'UNSUPPORTED'))
        print(f'  {t:9s} n={len(g):2d} correct={cor/len(g):.3f} omission={om/len(g):.3f} '
              f'value={ve/len(g):.3f} citation={cit/len(g):.3f}')
    print('\ncomposite vs simple (all cells):')
    for label, flag in (('simple', False), ('composite/derived', True)):
        g = [r for r in rows if r['composite'] == flag]
        cor = sum(1 for r in g if r['cause'] == 'CORRECT')
        print(f'  {label:18s} n={len(g):3d} TP rate={cor/len(g):.3f}')


if __name__ == '__main__':
    main()
