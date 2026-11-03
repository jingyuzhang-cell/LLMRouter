"""QP5-D negative-result instance tracing (zero calls).

Per (task, rep, fact): 2x2 outcome (F1 vs F2) from frozen scorer rows; for the
discordant cells, pull gold / F1 answer / F2 answer from ledgers and classify
the cause: format / unit / subject / time / numeric / semantic / absent.
"""
import json, sys, collections, statistics as st
from decimal import Decimal
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp3_primitives as P3
import scorer_qp1 as Q1
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def classify_cause(gold, f1v, f2v, kind):
    """Why did the F2 echo break a fact F1 got right (or vice versa)?"""
    causes = []
    if kind in ('number', 'amount', 'percent'):
        g, a, b = P3.deco_amount(gold), P3.deco_amount(f1v), P3.deco_amount(f2v)
        if b and g and abs(b[0] - g[0]) > max(abs(g[0]) * Decimal('0.001'), Decimal('0.01')):
            return ['numeric']
        if b and g and b[0] == g[0] and P3._norm(str(f2v)) != P3._norm(str(gold)):
            return ['format']          # number right, presentation differs
        if a and g and abs(a[0] - g[0]) <= max(abs(g[0]) * Decimal('0.001'), Decimal('0.01')) \
                and b and g and b[0] != g[0] and a[1] != b[1]:
            return ['unit']            # same magnitude class differs by scaling
    if kind == 'date':
        import re
        def d(x):
            m = re.search(r'(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})', str(x or ''))
            return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
        if d(f2v) and d(gold) and d(f2v) != d(gold):
            return ['time']
        return ['format']
    # text
    if P3._norm(f2v) and P3._norm(gold) and P3._norm(gold) in P3._norm(f2v):
        return ['format']
    if f2v in (None, '', 'ABSENT'):
        return ['absent']
    return ['semantic']


def main():
    res = json.load(open(f'{QP}/QP5D_RESULTS.json'))
    by = {}
    for r in res['results']:
        if not r.get('error'):
            by[(r['task'], r['rep'], r['arm'])] = r
    led = {}
    for line in open(f'{QP}/QP5D_LEDGER.jsonl'):
        x = json.loads(line)
        led[x['purpose']] = x

    grid = collections.Counter()
    discord = []
    kinds = collections.Counter()
    per_task = collections.defaultdict(collections.Counter)
    for t in F.TASKS:
        for rep in (1, 2):
            f1, f2 = by.get((t, rep, 'F1')), by.get((t, rep, 'F2'))
            if not f1 or not f2:
                continue
            contract = F.load_contract(t)
            s1 = {x['fact_id']: x['status'] for x in f1['rows']}
            s2 = {x['fact_id']: x['status'] for x in f2['rows']}
            a1, a2 = {}, {}
            for arm, sink_key in (('F1', f'qp5d|{t}|F1|r{rep}|p'), ('F2', f'qp5d|{t}|F2|r{rep}|p')):
                rec = led.get(sink_key)
                if rec:
                    o = extract_any(rec['text'])
                    for a in (o or {}).get('answers', []) if isinstance(o, dict) else []:
                        if isinstance(a, dict) and a.get('fact_id'):
                            (a1 if arm == 'F1' else a2).setdefault(a['fact_id'], a.get('value'))
            for f in contract['required_facts']:
                fid = f['fact_id']
                tp1, tp2 = s1.get(fid) == 'TP', s2.get(fid) == 'TP'
                key = ('TP' if tp1 else 'x') + ('TP' if tp2 else 'x')
                grid[key] += 1
                per_task[t][key] += 1
                kinds[(key, f.get('value_kind'))] += 1
                if tp1 != tp2:
                    gold = f.get('value')
                    v1 = a1.get(fid)
                    v2 = a2.get(fid)
                    if tp1 and not tp2:
                        causes = classify_cause(gold, v1, v2, f.get('value_kind'))
                    else:
                        causes = classify_cause(gold, v2, v1, f.get('value_kind'))
                    discord.append(dict(task=t, rep=rep, fact_id=fid, kind=f.get('value_kind'),
                                        direction='F1ok_F2bad' if tp1 else 'F1bad_F2ok',
                                        gold=str(gold)[:48], f1=str(v1)[:48], f2=str(v2)[:48],
                                        causes=causes))
    json.dump(dict(batch='QP5D_NEGATIVE_TRACING', model_calls=0,
                   grid=dict(grid), per_task={k: dict(v) for k, v in per_task.items()},
                   kind_grid={f'{k[0]}|{k[1]}': v for k, v in kinds.items()},
                   discord=discord),
              open(f'{QP}/QP5D_NEGATIVE_TRACING.json', 'w'), ensure_ascii=False, indent=1)
    print('2x2 grid (F1 x F2):', dict(grid))
    print('per task:')
    for t in F.TASKS:
        print(f"  {t:9s}", dict(per_task[t]))
    dd = [d for d in discord if d['direction'] == 'F1ok_F2bad']
    df = [d for d in discord if d['direction'] == 'F1bad_F2ok']
    print(f"\nD5 broke {len(dd)} facts F1 had right; fixed {len(df)}")
    c1 = collections.Counter(c for d in dd for c in d['causes'])
    c2 = collections.Counter(c for d in df for c in d['causes'])
    print('causes (broke):', dict(c1))
    print('causes (fixed):', dict(c2))
    print('\nsample broke (ZIJING/ZEDA/E06 priority):')
    for d in [x for x in dd if x['task'] in ('ZIJING', 'ZEDA', 'E06')][:10]:
        print(f"  {d['task']} {d['fact_id']:5s} [{d['kind']}] gold={d['gold']!r} f1={d['f1']!r} f2={d['f2']!r} {d['causes']}")
    print('\nsample fixed:')
    for d in df[:6]:
        print(f"  {d['task']} {d['fact_id']:5s} [{d['kind']}] gold={d['gold']!r} f1={d['f1']!r} f2={d['f2']!r} {d['causes']}")


if __name__ == '__main__':
    main()
