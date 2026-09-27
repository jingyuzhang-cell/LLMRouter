"""collab_scheduler_v1 — Phase 1: enumerate + evidence-map + state-conditioned
exact Pareto audit. NO surrogate, NO search — honest bookkeeping only.

Decision object (frozen for paper 2):
    G = (Y, X, Z, M)
    Y in {Single, SER, SERV, Parallel-ER, DynamicDAG}
    X in {cheap, balanced, quality, heterogeneous, type-prior}
    Z in {none, local-reroute, local-recompute}   (Single: {none, retry})
    M in {fresh, reuse, reuse-if-supported}       (M != fresh needs history state)
State slices:
    s_clean   (frozen200 clean, 200 tasks)     s_fault30 (frozen200 f30, 600)
    s_history (P0-2 96-task follow-up panel)   budget slices from Q(B) curves
Evidence policy: a cell is MEASURED only if a frozen artifact contains its
(Q, C, L) directly; composed/estimated values are FORBIDDEN; everything else
is UNEVALUATED (or PARTIAL: Q-only from cross_model_matrix). sa_pgfs_v1
calibrated numbers are never used as results.
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1'
F200 = ROOT / 'static_dag_v0/frozen200/FROZEN200_CORRECTED_SUMMARY.json'
P02 = ROOT / 'static_dag_v0/graph_forest_v2_p02/RESULTS.json'
CM = ROOT / 'static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json'

YS = ['Single', 'SER', 'SERV', 'Parallel-ER', 'DynamicDAG']
XS = ['cheap', 'balanced', 'quality', 'heterogeneous', 'type-prior']
ZS = ['none', 'local-reroute', 'local-recompute']
MS = ['fresh', 'reuse', 'reuse-if-supported']
X_FOR_SINGLE = {'cheap', 'quality'}
Z_FOR_SINGLE = {'none', 'retry'}
DAG_YS = {'SER', 'SERV', 'Parallel-ER', 'DynamicDAG'}


def enumerate_space(history_state):
    """Feasible configs for a state slice. M != fresh only with history."""
    out = []
    for y in YS:
        for x in XS:
            if y == 'Single' and x not in X_FOR_SINGLE:
                continue
            for z in (Z_FOR_SINGLE if y == 'Single' else ZS):
                if y != 'DynamicDAG' and z not in ('none',):
                    continue  # recovery edges exist only on DynamicDAG (v1)
                for m in MS:
                    if m != 'fresh' and not history_state:
                        continue
                    if m == 'reuse-if-supported' and not history_state:
                        continue
                    out.append(dict(y=y, x=x, z=z, m=m))
    return out


def load_evidence():
    f = json.loads(F200.read_text())
    p02 = json.loads(P02.read_text())
    cm = json.loads(CM.read_text())['matrix']
    ev = {}

    def add(state, cfg, src, n, q, c, l):
        ev.setdefault(state, {})['|'.join(cfg)] = dict(
            source=src, n=n, Q=q, C=c, L=l, evidence='measured')

    def base(y, x, z, m):
        return [y, x, z, m]

    # frozen200: Single(large=quality, retry), DynamicDAG het none/reroute
    for state, tag in [('s_clean', 'clean'), ('s_fault30', None)]:
        if tag:
            a = f['arms'][f'{tag}_single'], f['arms'][f'{tag}_static'], f['arms'][f'{tag}_dynamic']
        else:
            a = (f['arms']['f30_single'], f['arms']['f30_static'], f['arms']['f30_dynamic'])
        add(state, base('Single', 'quality', 'retry', 'fresh'), 'frozen200', 200 if tag else 600,
            *[a[0][k] for k in ('Q', 'C', 'L')])
        add(state, base('DynamicDAG', 'heterogeneous', 'none', 'fresh'), 'frozen200',
            200 if tag else 600, *[a[1][k] for k in ('Q', 'C', 'L')])
        add(state, base('DynamicDAG', 'heterogeneous', 'local-reroute', 'fresh'), 'frozen200',
            200 if tag else 600, *[a[2][k] for k in ('Q', 'C', 'L')])
    # P0-2 history-hit panel (write-state chain, X=type-prior, Z=none)
    c = p02['cells']
    add('s_history', base('SER', 'type-prior', 'none', 'reuse'), 'P0-2 (A, V0)', 96,
        c['A0']['Q'], c['A0']['C'], c['A0']['L'])
    add('s_history', base('SER', 'type-prior', 'none', 'reuse-if-supported'),
        'P1b-3 Step1 replay (T-gated reuse)', 76, 0.2763, 573.4, 0.0)
    add('s_history', base('SER', 'type-prior', 'none', 'fresh'), 'P0-2 (C-prime)', 96,
        c['Cp']['Q'], c['Cp']['C'], c['Cp']['L'])
    add('s_history', base('SER', 'type-prior', 'none', 'partial-recompute'),
        'P0-2 (B, regenerate reasoning; M-extension)', 96,
        c['B']['Q'], c['B']['C'], c['B']['L'])
    # cross_model: X-family exploration on SER (Q-only)
    partial = {}
    for k, v in cm.items():
        me, mr = k.split('->')
        partial[f'SER|{me.split("_")[1]}-to-{mr.split("_")[1]}'] = dict(
            source='cross_model_matrix', n=v['n'], Q=v['Q'], evidence='partial (Q-only)')
    return ev, partial


def dominates(a, b):
    return (a['Q'] >= b['Q'] and a['C'] <= b['C'] and a['L'] <= b['L']
            and (a['Q'], -a['C'], -a['L']) != (b['Q'], -b['C'], -b['L']))


def nd_set(cells):
    keys = list(cells)
    keep = [k for k in keys
            if not any(dominates(cells[j], cells[k]) for j in keys if j != k)]
    return keep


def run():
    OUT.mkdir(exist_ok=True)
    ev, partial = load_evidence()
    slices = {}
    for state, history in [('s_clean', False), ('s_fault30', False), ('s_history', True)]:
        space = enumerate_space(history)
        measured = ev.get(state, {})
        cells = {k: dict(v, gid=k) for k, v in measured.items()}
        nd = nd_set(cells) if cells else []
        slices[state] = dict(space_size=len(space), measured=len(cells),
                             unevaluated=len(space) - len(cells),
                             front=[(k, cells[k]['Q'], cells[k]['C'], cells[k]['L']) for k in nd],
                             all_measured=cells)
    budget = json.loads(F200.read_text())['budget']
    out = dict(slices={s: {k: v for k, v in d.items() if k != 'all_measured'}
                       for s, d in slices.items()},
               budget_curves_f30=budget,
               x_exploration_Q_only=partial,
               headline=None)
    (OUT / 'AUDIT_V1.json').write_text(json.dumps(out, indent=1, default=str))
    for s, d in slices.items():
        print(f"{s}: space={d['space_size']} measured={d['measured']} "
              f"unevaluated={d['unevaluated']}")
        for k, q, c, l in d['front']:
            print(f"   ND {k}: Q={q} C={c} L={l}")


if __name__ == '__main__':
    run()
