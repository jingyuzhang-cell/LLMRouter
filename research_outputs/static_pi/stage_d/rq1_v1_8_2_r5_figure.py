#!/usr/bin/env python3
"""R5 population Pareto figure: quality vs cost, color=makespan; 128 points/scenario."""
import json, os, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

OUT = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(OUT, 'RQ1_V1_8_2_R5_POPULATION.json')))
SLUGS = [o['slug'] for o in R.values()]
NROWS, NCOLS = 2, 4
fig, axes = plt.subplots(NROWS, NCOLS, figsize=(18, 8.6), dpi=150)
axes = axes.ravel()

market = {
    'Static': ('o', 'black', 'Static'),
    'Node-Type': ('^', 'tab:blue', 'Node-Type'),
    'Budget-Con': ('s', 'tab:orange', 'Budget-Con 20'),
    'MGC': ('*', 'tab:green', 'MGC 20'),
    'CPA': ('D', 'tab:olive', 'CPA 20'),
    'JP-matched': ('X', 'tab:purple', 'Joint-Pareto 20'),
    'CO-matched': ('o', 'tab:red', 'Constrained Oracle 20'),
}

for ax, name in zip(axes, R):
    o = R[name]
    z = np.load(os.path.join(OUT, f'RQ1_V1_8_2_R5_POP_{o["slug"]}.npz'))
    base_cost = o['base']['cost']; base_mk = o['base']['mk']
    term = z['term']; cost = z['cost'] / base_cost - 1.0
    mk = z['mk'] / base_mk - 1.0
    sc = ax.scatter(cost * 100, term, c=mk * 100, cmap='viridis', s=18, alpha=0.55,
                    edgecolors='none', vmin=-5, vmax=35)
    # 2D quality-cost Pareto front
    front = o['pareto_q_cost']
    xs = [z['cost'][m] / base_cost * 100 - 100 for m in front]
    ys = [z['term'][m] for m in front]
    order = np.argsort(xs)
    ax.plot(np.array(xs)[order], np.array(ys)[order], '-', color='tab:red', lw=1.0, alpha=0.75)
    c = o['caps']['20']['arms']
    for arm in market:
        if arm not in c:
            continue
        m = c[arm].get('mask', -1)
        if m is None or m < 0:
            continue
        ax.scatter(c[arm]['cost_ratio'] * 100 - 100, c[arm]['q_mean'],
                   marker=market[arm][0], s=90, color=market[arm][1],
                   edgecolors='white', linewidths=0.6, zorder=5)
    ax.set_title(name, fontsize=10)
    ax.set_xlabel('cost increase vs Static (%)', fontsize=8)
    ax.set_ylabel('terminal answer Q (13 slots)', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.2)
    ax.axvline(10, color='gray', ls=':', lw=0.8)
    ax.axvline(20, color='gray', ls=':', lw=0.8)
    ax.text(0.02, 0.97, f'Static ${o["base"]["cost"]:.2f}$, mk ${o["base"]["mk"]:.2f}$',
            transform=ax.transAxes, fontsize=7, va='top')

handles = [Line2D([0], [0], marker=v[0], color='w', markerfacecolor=v[1],
                  markersize=8, label=v[2]) for k, v in market.items()]
handles.append(Line2D([0], [0], color='tab:red', lw=1.2, label='Q-cost Pareto front'))
axes[7].axis('off')
axes[7].text(0.0, 0.98,
    'Reading guide (frozen R5 rules)\n\n'
    'MVS = +1/13 = 7.69% terminal Q; not lowered.\n'
    'Cost levels vs all-DS: 1 GLM +9.5%, 2 +19.0%,\n'
    '3 +28.6%, 4 +38.1%. With Static=DS, 10%/15% caps\nallow <=1 GLM;\n'
    '20% allows <=2 GLM.\n\n'
    'Strict deadline = 1.10x Static makespan (all caps):\n'
    'only m is the high-quality fit (+7.9%); t+m also\n'
    'fits but has lower Q. m+v is +14.9%.\n'
    'Matched deadline = (1+cap)x Static makespan.\n\n'
    'Only stable delta=.20, 20% matched crosses MVS\n'
    '(population dQ +0.078); strict JOINT = 0.\n'
    'CO = constrained oracle, test-selected, non-deployable.\n'
    'MGC/JP/CO markers overlap where assignments coincide.',
    transform=axes[7].transAxes, fontsize=8, va='top', ha='left', linespacing=1.35)
fig.legend(handles=handles, loc='lower center', ncol=4, fontsize=8, frameon=False)
fig.suptitle('R5: 128 DAG model assignments, quality-cost-makespan (color=makespan increase %). '
             'SYNTHETIC; zero API', fontsize=11)
fig.tight_layout(rect=[0, 0.06, 1, 0.95])
cbar = fig.colorbar(sc, ax=axes[:7], orientation='vertical', fraction=0.015, pad=0.01)
cbar.set_label('makespan increase vs Static (%)', fontsize=8)
cbar.ax.tick_params(labelsize=7)
fig.savefig(os.path.join(OUT, 'RQ1_V1_8_2_R5_PARETO.png'), dpi=300, bbox_inches='tight')
print('wrote RQ1_V1_8_2_R5_PARETO.png')
