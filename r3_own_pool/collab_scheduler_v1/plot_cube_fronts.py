"""Figure templates for the reference cube (F1-F3), CPU-only, zero calls.

F1 (Q,C) and F2 (Q,L): per-config scatter + ND fronts for s_clean and, when
available, s_fault30, with the SINGLE anchor marked.
F3: HV-vs-#evaluations replay curves from REPLAY_CLEAN.json.

Run: python3 -m collab_scheduler_v1.plot_cube_fronts   ->  collab_scheduler_v1/figs/
"""
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/figs'

COLORS = {'SER': '#4c72b0', 'SERV': '#dd8452', 'PARALLELER': '#55a868',
          'DYNAMICDAG': '#c44e52', 'Single': '#8172b3'}


def load_state(name):
    if name == 's_clean':
        d = json.loads((ROOT / 'collab_scheduler_v1/CUBE_CLEAN_ANALYSIS.json').read_text())
        pts = {k: v for k, v in d['complete'].items()}
        pts['SINGLE__QUALITY__RETRY__FRESH'] = dict(Q=0.55, C=612.8, L=0.46)
        front = d['pareto']['front']
        return pts, front
    f = ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json'
    if not f.exists():
        return None, None
    d = json.loads(f.read_text())
    pts = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'])
           for cid, v in d.get('fault_per_config', {}).items() if v.get('n') == 600}
    if not pts:
        return None, None
    return pts, d.get('fronts', {}).get('P_fault')


def scatter(ax, pts, front, x, y, xlabel, ylabel, title):
    for cid, v in pts.items():
        topo = cid.split('__')[0]
        ax.scatter(v[x if x in v else {'C': 'C', 'L': 'L'}[x]],
                   v[y if y in v else {'C': 'C', 'L': 'L'}[y]],
                   color=COLORS.get(topo, '#999'), s=42, zorder=3,
                   marker='*' if topo == 'Single' else 'o',
                   edgecolor='k', linewidth=.4)
    if front:
        fpts = sorted([pts[c] for c in front if c in pts],
                      key=lambda v: v['C'])
        ax.step([p['C'] for p in fpts], [p['Q'] for p in fpts], where='post',
                color='#222', lw=1, zorder=2)
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Q_workflow')
    ax.set_title(title, fontsize=10)
    ax.grid(alpha=.3)


def run():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    OUT.mkdir(exist_ok=True)
    clean_pts, clean_front = load_state('s_clean')
    fault_pts, fault_front = load_state('s_fault30')

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    scatter(axes[0], clean_pts, clean_front, 'C', 'Q', 'C_workflow (tokens)',
            'Q_workflow', 'F1: clean cube (Q vs C)' + (' + fault front' if fault_pts else ''))
    if fault_pts:
        axes[0].scatter([v['C'] for v in fault_pts.values()], [v['Q'] for v in fault_pts.values()],
                        facecolors='none', edgecolors='#c44e52', s=90, lw=1.2, zorder=4)
    scatter(axes[1], clean_pts, clean_front, 'L', 'Q', 'L_critical_path (s)',
            'Q_workflow', 'F2: clean cube (Q vs L)')
    handles = [plt.Line2D([], [], marker='o', ls='', color=c, label=t)
               for t, c in COLORS.items()]
    axes[0].legend(handles=handles, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / 'f1_f2_fronts.png', dpi=150)

    rp = ROOT / 'sa_pgfs_v1/results_cube_replay/REPLAY_CLEAN.json'
    if rp.exists():
        d = json.loads(rp.read_text())
        fig2, ax = plt.subplots(figsize=(5.5, 4))
        for strat in ('random', 'greedy_q', 'ehvi', 'cost_aware_ehvi'):
            ts = d['strategy_summary'][strat]
            mean = ts.get('final_hv_ratio_mean', 1 - ts['final_regret']['mean']
                          if 'final_regret' in ts else ts['final_regret_mean'])
            err = ts.get('final_hv_ratio_std', ts['final_regret']['std']
                         if 'final_regret' in ts else ts['final_regret_std'])
            ax.bar(strat, mean, yerr=err, capsize=3,
                   color={'random': '#999', 'greedy_q': '#4c72b0',
                          'ehvi': '#dd8452', 'cost_aware_ehvi': '#c44e52'}[strat])
        ax.set_ylabel('final HV / HV(true front)')
        ax.set_title('F3: SA-PGFS reveal/replay on the clean cube (8-eval budget)', fontsize=10)
        ax.grid(alpha=.3, axis='y')
        fig2.tight_layout()
        fig2.savefig(OUT / 'f3_replay.png', dpi=150)
    print('figures ->', OUT)


if __name__ == '__main__':
    run()
