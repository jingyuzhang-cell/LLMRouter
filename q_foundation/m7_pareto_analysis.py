"""M7-1: Empirical multi-objective (Q, C, L) Pareto analysis over the existing
corpus (ZERO model calls). Reads only recorded results.

Discipline (from M6-4): Q is NEVER compared across experiments — every cell
uses its own experiment's scoring. Within a cell all arms share task, fault
and reference, so (Q, C, L) comparisons are Level-A valid.

INCOMPLETE handling (from M6-3): Q is undefined (null) for INCOMPLETE runs —
never 0. Dominance definitions:
  strict_dominance   both COMPLETE: Q>=, C<=, L<= with >=1 strict
  recovery_dominate  COMPLETE arm cheaper-or-equal AND faster-or-equal than an
                     INCOMPLETE arm (Q not compared; completion dominates)
  cheaper_failure    both INCOMPLETE: C<=, L<=
  tradeoff           none of the above (price must be paid somewhere)
"""
import json
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
OUT = Path('/root/q_foundation/M7_PARETO_RESULTS.json')


def load_cells():
    """-> {exp: {cell: {arm: {q, c, l, status, q_metric}}}}"""
    cells = {}

    # ---- H1 (Q metric = confirmed terminal facts; INCOMPLETE -> null)
    qm = 'confirmed_terminal_facts'
    c = {}
    for g in ['G1_Static', 'G2_R_only', 'G3_pi_only', 'G4_R_pi',
              'G5_Z_R_pilock', 'G6_Z_R_pi_full']:
        d = json.load(open(BENCH / f'h1_runs/EXEC_174649/SC-E1-{g}.json'))
        ts = d.get('terminal_stats') or {}
        c[g] = {'q': ts.get('confirmed') if d['status'] == 'COMPLETE' else None,
                'c': d['tokens'], 'l': d['makespan'],
                'status': d['status'], 'q_metric': qm}
    cells['H1'] = {'SC-E1': c}
    c = {}
    for g in ['G1_Static', 'G2_R_only']:
        d = json.load(open(BENCH / f'h1_runs/EXEC_174649/SC-E3-{g}.json'))
        c[g] = {'q': None, 'c': d['tokens'], 'l': d['makespan'],
                'status': d['status'], 'q_metric': qm}
    cells['H1']['SC-E3'] = c

    # ---- R9B (Q metric = confirmed terminal facts; FINAL8 complete + SCORED
    #      supplies makespan where present)
    qm = 'confirmed_terminal_facts'
    cells['R9B'] = {}
    mk_map = {}
    for e in json.load(open(BENCH / 'stage_c_r9_runs/R9B_SCORED.json')):
        mk_map[(e['task'], e['arm'], e['rep'])] = e.get('makespan')
    for e in json.load(open(BENCH / 'stage_c_r9_runs/R9B_FINAL8_SCORED.json')):
        arm = 'B_split' if 'Z' in e['arm'] else 'A_nosplit'
        cell = f"{e['task']}|{e['rep']}"
        cells['R9B'].setdefault(cell, {})[arm] = {
            'q': e.get('facts') if e['status'] == 'COMPLETE' else None,
            'c': e['tokens'],
            'l': mk_map.get((e['task'], e['arm'], e['rep'])),
            'status': e['status'], 'q_metric': qm}

    # ---- DYNPI (Q metric = experiment's own adjudicated q from PAIRS)
    pairs = json.load(open(BENCH / 'stage_c_dynpi_runs/EXEC_160551/PAIRS.json'))
    cells['DYNPI'] = {}
    for cell, arms in pairs.items():
        cc = {}
        for a, v in arms.items():
            ok = v.get('ok') or v.get('status') == 'COMPLETE'
            cc[a] = {'q': v['q'] if ok else None, 'c': v['tok'],
                     'l': v['mk'], 'status': v.get('status'),
                     'q_metric': 'dynpi_adjudicated_q'}
        cells['DYNPI'][cell] = cc

    # ---- R6 (Q = Q_terminal from R6_FINAL_SCORES; C/L from trace.json)
    scores = {e['run_id']: e for e in
              json.load(open(BENCH / 'stage_c_r6_runs/R6_FINAL_SCORES.json'))}
    cells['R6'] = {}
    for dr in sorted((BENCH / 'stage_c_r6_runs').glob('R6-*')):
        t = json.load(open(dr / 'trace.json'))
        sc = scores.get(dr.name, {})
        cell = dr.name.split('SC-')[1].rsplit('-', 1)[0] + '|' \
            + dr.name.rsplit('-', 1)[1]
        arm = dr.name[len('R6-'):].split('-SC-')[0]
        complete = t['final_status'] == 'COMPLETE'
        cells['R6'].setdefault(cell, {})[arm] = {
            'q': sc.get('Q_terminal') if complete else None,
            'c': sum(r['usage']['in'] + r['usage']['out']
                     for r in t['node_records']),
            'l': t.get('makespan'),
            'status': t['final_status'],
            'q_metric': 'r6_Q_terminal'}

    # ---- TGV (rS3 only; all arms identical under dedup)
    pairs = json.load(open(BENCH / 'stage_c_tgv_runs/EXEC_205635/PAIRS.json'))
    cells['TGV'] = {}
    for cell, arms in pairs.items():
        if 'rS3' not in cell:
            continue
        cc = {}
        for a, v in arms.items():
            cc[a] = {'q': v['q'], 'c': v['tok'], 'l': v['mk'],
                     'status': 'COMPLETE', 'q_metric': 'tgv_adjudicated_q'}
        cells['TGV'][cell] = cc
    return cells


def dominates(a, b):
    """Directional relation of arm a vs arm b.
    Returns 'dominates' | 'dominated_by' | 'tie' | 'tradeoff'.
    Completion (R) is an objective: a COMPLETE arm dominates an INCOMPLETE
    one when cheaper-or-equal AND faster-or-equal (recovery dominance);
    an INCOMPLETE arm can never dominate a COMPLETE one. Q participates
    only when both are COMPLETE. Both-INCOMPLETE pairs fall through to
    cheaper-failure semantics on (C, L)."""
    def _dom(x, y):
        rx, ry = x['q'] is not None, y['q'] is not None
        if rx < ry:                      # x INCOMPLETE, y COMPLETE: never
            return False
        q_ok = (not (rx and ry)) or x['q'] >= y['q']
        strict_q = rx and ry and x['q'] > y['q']
        return q_ok and x['c'] <= y['c'] and x['l'] <= y['l'] and \
            (strict_q or x['c'] < y['c'] or x['l'] < y['l'])

    a_dom, b_dom = _dom(a, b), _dom(b, a)
    if a_dom and b_dom:
        return 'tie'
    if a_dom:
        return 'dominates'
    if b_dom:
        return 'dominated_by'
    if a['q'] == b['q'] and a['c'] == b['c'] and a['l'] == b['l']:
        return 'tie'
    return 'tradeoff'


def rel_class(a, b):
    """Human-readable relation class for the pair (a, b)."""
    qa, qb = a['q'], b['q']
    r = dominates(a, b)
    if r in ('tie', 'tradeoff'):
        return r
    if qa is not None and qb is not None:
        return 'strict_dominance'
    if qa is None and qb is None:
        return 'cheaper_failure'
    return 'recovery_dominate'


def frontier(cell_points):
    """Arms not dominated by any other arm. Members are labelled:
    quality point (COMPLETE) or cheap_failure point (INCOMPLETE — optimal
    only in the degenerate regime budget < cheapest COMPLETE cost)."""
    arms = list(cell_points)
    out = []
    for a in arms:
        if any(dominates(cell_points[b], cell_points[a]) == 'dominates'
               for b in arms if b != a):
            continue
        out.append({'arm': a,
                    'kind': 'quality_point' if cell_points[a]['q'] is not None
                    else 'cheap_failure_point'})
    return out


def weight_sensitivity(points):
    """Winner instability over a normalized linear-weight grid, COMPLETE arms
    only (Q defined). Returns #distinct winners and the winner set."""
    arms = [a for a, p in points.items() if p['q'] is not None]
    if len(arms) < 2:
        return None
    qs = {a: points[a]['q'] for a in arms}
    qn = {a: (q - min(qs.values())) / (max(qs.values()) - min(qs.values()) or 1)
          for a, q in qs.items()}
    cs = {a: points[a]['c'] for a in arms}
    cn = {a: 1 - (c - min(cs.values())) / (max(cs.values()) - min(cs.values()) or 1)
          for a, c in cs.items()}
    ls = {a: points[a]['l'] for a in arms if points[a]['l'] is not None}
    ln = {a: 1 - (points[a]['l'] - min(ls.values())) /
              (max(ls.values()) - min(ls.values()) or 1) if ls else 0.5
          for a in arms}
    winners = set()
    for alpha in [i / 10 for i in range(1, 9)]:
        for beta in [i / 10 for i in range(1, 10)]:
            if alpha + beta >= 1:
                continue
            gamma = 1 - alpha - beta
            best = max(arms, key=lambda a: alpha * qn[a] + beta * cn[a]
                       + gamma * ln[a])
            winners.add(best)
    return {'n_winners': len(winners), 'winners': sorted(winners),
            'grid': 'alpha,beta in 0.1 steps, gamma=1-alpha-beta'}


def budget_curve(points):
    """Constrained winner (max Q s.t. C<=B, tie -> cheaper) as B sweeps the
    cell's observed cost range. COMPLETE arms only for Q."""
    arms = [a for a, p in points.items() if p['q'] is not None]
    if len(arms) < 2:
        return None
    events = []
    prev = None
    for B in sorted({p['c'] for p in points.values()}):
        feas = [a for a in arms if points[a]['c'] <= B]
        if not feas:
            prev = None
            continue
        w = max(feas, key=lambda a: (points[a]['q'], -points[a]['c']))
        if w != prev:
            events.append({'budget': B, 'winner': w, 'q': points[w]['q']})
            prev = w
    return events


def main():
    cells = load_cells()
    report = {'meta': {'date': '2026-10-31', 'model_calls': 0,
                       'discipline': 'within-cell comparisons only; Q never '
                                     'compared across experiments; INCOMPLETE '
                                     '-> Q null (M6-3 rule)'},
              'cells': {}, 'aggregates': {}}
    pair_rels, front_occupancy = [], {}
    for exp, exp_cells in cells.items():
        for cell, pts in exp_cells.items():
            key = f'{exp}|{cell}'
            fr = frontier(pts)
            for a in pts:
                for b in pts:
                    if a < b:
                        pair_rels.append({'cell': key, 'a': a, 'b': b,
                                          'relation': rel_class(pts[a], pts[b]),
                                          'dominator': a if dominates(pts[a], pts[b]) == 'dominates'
                                          else (b if dominates(pts[a], pts[b]) == 'dominated_by'
                                                else None)})
            report['cells'][key] = {
                'points': pts, 'frontier': fr,
                'weight_sensitivity': weight_sensitivity(pts),
                'budget_curve': budget_curve(pts)}
            for a in fr:
                front_occupancy[a['arm']] = front_occupancy.get(a['arm'], 0) + 1

    rel_counts = {}
    for p in pair_rels:
        rel_counts[p['relation']] = rel_counts.get(p['relation'], 0) + 1

    # per-cell regime classification
    for key, v in report['cells'].items():
        pts, fr = v['points'], v['frontier']
        quality = [f['arm'] for f in fr if f['kind'] == 'quality_point']
        cheap = [f['arm'] for f in fr if f['kind'] == 'cheap_failure_point']
        arms = list(pts)
        all_tie = all(dominates(pts[a], pts[b]) == 'tie'
                      for i, a in enumerate(arms) for b in arms[i + 1:])
        if all(p['q'] is None for p in pts.values()):
            regime = 'no_quality_point (all INCOMPLETE)'
        elif len(arms) > 1 and all_tie:
            regime = 'equivalence (all arms identical)'
        elif len(quality) == 1 and all(
                dominates(pts[quality[0]], pts[o]) == 'dominates'
                for o in arms if o != quality[0]):
            regime = 'single_arm_dominance'
        elif len(quality) > 1:
            regime = 'quality_tradeoff (frontier has multiple quality points)'
        elif quality and cheap:
            regime = 'priced_recovery (quality costs more than fail-fast)'
        else:
            regime = 'single_quality_point'
        v['regime'] = regime

    report['aggregates'] = {
        'n_cells': len(report['cells']),
        'n_pairs': len(pair_rels),
        'relation_counts': rel_counts,
        'frontier_occupancy_by_arm': dict(sorted(front_occupancy.items(),
                                                 key=lambda kv: -kv[1])),
        'recovery_price_r9b_tok': {
            'SC-E1|1': 18761 - 11862, 'SC-E1|2': 17225 - 13844,
            'SC-E3|1': 15319 - 11082, 'SC-E3|2': 13825 - 10143},
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                              default=str))
    print(f"cells={report['aggregates']['n_cells']}  "
          f"pairs={report['aggregates']['n_pairs']}")
    print('relations:', rel_counts)
    print('frontier occupancy:', report['aggregates']['frontier_occupancy_by_arm'])
    for k, v in report['cells'].items():
        ws = v['weight_sensitivity']
        print(f"  {k:16} frontier={v['frontier']}  "
              f"ws={ws['n_winners'] if ws else '-'}")


if __name__ == '__main__':
    main()
