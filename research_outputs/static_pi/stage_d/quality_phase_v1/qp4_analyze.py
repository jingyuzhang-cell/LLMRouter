"""QP4 2x2 factorial analysis (zero calls)."""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def main():
    d = json.load(open(f'{QP}/QP4_RESULTS.json'))
    cells = d['results']
    by = collections.defaultdict(dict)
    for r in cells:
        if r.get('parse_error') or r.get('error') or r.get('q') is None:
            by[(r['task'], r['cell'])][r['rep']] = dict(q=None, parse_error=True)
        else:
            by[(r['task'], r['cell'])][r['rep']] = dict(
                q=r['q'], val=r['value'], loc=r['loc'], sup=r['sup'],
                reuse=r['reuse_rate'], gate=r['gate'])

    TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN', 'ZIJING', 'ZEDA']

    def tq(t, c):
        vals = [v['q'] for v in by[(t, c)].values() if v.get('q') is not None]
        return st.mean(vals) if vals else None

    print(f"{'task':9s} {'A':>6s} {'B':>6s} {'C':>6s} {'D':>6s}   H1eff  H2eff  interact")
    eff = dict(h1=[], h2=[], i=[])
    for t in TASKS:
        A, B, C, D = tq(t, 'A'), tq(t, 'B'), tq(t, 'C'), tq(t, 'D')
        h1 = ((B - A) + (D - C)) / 2 if None not in (A, B, C, D) else None
        h2 = ((C - A) + (D - B)) / 2 if None not in (A, B, C, D) else None
        i = (D - C) - (B - A) if None not in (A, B, C, D) else None
        for k, v in (('h1', h1), ('h2', h2), ('i', i)):
            if v is not None:
                eff[k].append(v)
        f = lambda x: f'{x:6.3f}' if x is not None else '   -- '
        print(f"{t:9s} {f(A)} {f(B)} {f(C)} {f(D)}   {f(h1)} {f(h2)} {f(i)}")

    macro = {c: st.mean([tq(t, c) for t in TASKS if tq(t, c) is not None]) for c in 'ABCD'}
    print('\nmacro Q by cell:', {k: round(v, 4) for k, v in macro.items()})
    print('H1 main effect (macro):', round(st.mean(eff['h1']), 4),
          'task deltas:', [round(x, 3) for x in eff['h1']])
    print('H2 main effect (macro):', round(st.mean(eff['h2']), 4),
          'task deltas:', [round(x, 3) for x in eff['h2']])
    print('interaction (macro):', round(st.mean(eff['i']), 4),
          'task deltas:', [round(x, 3) for x in eff['i']])
    pos = lambda xs: (sum(1 for x in xs if x > 0), len(xs))
    print('H1 positive tasks:', pos(eff['h1']), '| H2 positive tasks:', pos(eff['h2']))

    # reuse compliance vs Q (mechanism)
    rows = [v for (t, c), reps in by.items() if c in 'BD' for v in reps.values()
            if v.get('q') is not None]
    hi = [v for v in rows if v.get('reuse') == 1.0]
    lo = [v for v in rows if v.get('reuse') is not None and v['reuse'] < 1.0]
    print(f"\nreuse-mandate compliance (B/D cells): {len(hi)}/{len(rows)} cells fully comply")
    if hi:
        print(f"  Q | reuse=1.0 : mean {st.mean(v['q'] for v in hi):.3f}")
    if lo:
        print(f"  Q | reuse<1.0 : mean {st.mean(v['q'] for v in lo):.3f}")

    # C-arm value axis (H2 without retention)
    cval = [v['val'] for (t, c), reps in by.items() if c == 'C' for v in reps.values()
            if v.get('q') is not None]
    aval = [v['val'] for (t, c), reps in by.items() if c == 'A' for v in reps.values()
            if v.get('q') is not None]
    print(f"\nvalue-axis: A mean {st.mean(aval):.3f} -> C mean {st.mean(cval):.3f} (H2 alone)")

    parse_fail = [f"{t}|{c}|r{r}" for (t, c), reps in by.items()
                  for r, v in reps.items() if v.get('parse_error')]
    json.dump(dict(batch='QP4_ANALYSIS', macro={k: round(v, 4) for k, v in macro.items()},
                   effects=dict(h1=[round(x, 4) for x in eff['h1']],
                                h2=[round(x, 4) for x in eff['h2']],
                                interaction=[round(x, 4) for x in eff['i']]),
                   reuse=dict(cells=len(rows), full=len(hi),
                              q_when_full=round(st.mean(v['q'] for v in hi), 4) if hi else None,
                              q_when_not=round(st.mean(v['q'] for v in lo), 4) if lo else None),
                   value_axis=dict(A=round(st.mean(aval), 4), C=round(st.mean(cval), 4)),
                   parse_fail_cells=parse_fail),
              open(f'{QP}/QP4_ANALYSIS.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
