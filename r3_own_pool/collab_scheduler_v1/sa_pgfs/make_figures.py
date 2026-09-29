"""Three main figures for the SA-PGFS + Reference Cube paper section."""
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/sa_pgfs'

cube = json.loads((ROOT / 'collab_scheduler_v1/REFERENCE_CUBE.json').read_text())
sapgfs = json.loads((OUT / 'RESULTS_SAPGFS.json').read_text())

# ---- F1: State-conditioned collaborative fronts ----
fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
for i, (state, label) in enumerate([('clean', 's_clean'), ('fault', 's_fault30')]):
    front = cube['collaborative_front'][state]
    singles = {'clean': (0.55, 612.8), 'fault': (0.3967, 802.0)}
    sq, sc = singles[state]
    ax[i].scatter(sc, sq, marker='*', s=200, c='black', zorder=5, label='Single (external)')
    for cid, q, c, l in front:
        short = cid.split('__')[0][:3] + '-' + cid.split('__')[1][:3] + \
                ('-R' if 'REROUTE' in cid else '')
        ax[i].scatter(c, q, s=100, zorder=4)
        ax[i].annotate(short, (c, q), textcoords='offset points', xytext=(8, 4), fontsize=7)
    ax[i].set_xlabel('C (tokens)')
    ax[i].set_ylabel('Q')
    ax[i].set_title(f'{label}', fontsize=10)
    ax[i].grid(alpha=.3)
    ax[i].legend(fontsize=8)
fig.suptitle('F1: State-conditioned collaborative Pareto fronts\n'
             '(Single-agent baseline is external, globally non-dominated in both states)', fontsize=10)
fig.tight_layout()
fig.savefig(OUT / 'F1_fronts.png', dpi=150)

# ---- F2: Recovery-induced trade-off ----
f30a = json.loads((ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json').read_text())
fig, ax = plt.subplots(figsize=(6, 4.5))
fams = ['BALANCED', 'HETEROGENEOUS', 'QUALITY']
colors = ['#1f77b4', '#ff7f00', '#2ca02c']
for fam, col in zip(fams, colors):
    dz = f30a['step3_Z_value']['delta_Z'][fam]
    none_cfg = f'DYNAMICDAG__{fam}__NONE__FRESH'
    rr_cfg = f'DYNAMICDAG__{fam}__LOCAL_REROUTE__FRESH'
    n_q = f30a['fault_per_config'][none_cfg]['Q']
    n_c = f30a['fault_per_config'][none_cfg]['C']
    r_q = f30a['fault_per_config'][rr_cfg]['Q']
    r_c = f30a['fault_per_config'][rr_cfg]['C']
    ax.annotate('', xy=(r_c, r_q), xytext=(n_c, n_q),
                arrowprops=dict(arrowstyle='->', color=col, lw=2))
    ax.scatter(n_c, n_q, c=col, s=80, marker='o', label=f'{fam[:3]}-none')
    ax.scatter(r_c, r_q, c=col, s=80, marker='^', label=f'{fam[:3]}-reroute')
ax.set_xlabel('C (tokens)')
ax.set_ylabel('Q')
ax.set_title('F2: Recovery-induced trade-off under fault30\n'
             '(arrows: none → local_reroute)', fontsize=10)
ax.grid(alpha=.3)
ax.legend(fontsize=7, ncol=2)
fig.tight_layout()
fig.savefig(OUT / 'F2_recovery.png', dpi=150)

# ---- F3: SA-PGFS sample efficiency ----
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
algo_colors = dict(random='#999', scalarized='#1f77b4', greedy_q='#ff7f0e',
                   ehvi='#2ca02c', sa_pgfs='#d62728')
for i, state in enumerate(['s_clean', 's_fault30']):
    for algo in ['random', 'scalarized', 'greedy_q', 'ehvi', 'sa_pgfs']:
        r = sapgfs['results'][state][algo]
        m = np.array(r['hv_mean'])
        s = np.array(r['hv_std'])
        x = np.arange(3, 3 + len(m))
        axes[i].plot(x, m, label=algo, color=algo_colors[algo])
        axes[i].fill_between(x, m - s, m + s, alpha=.15, color=algo_colors[algo])
    axes[i].set_xlabel('# revealed configurations')
    axes[i].set_ylabel('HV / HV*')
    axes[i].set_title(state, fontsize=10)
    axes[i].grid(alpha=.3)
    axes[i].legend(fontsize=7)
fig.suptitle('F3: SA-PGFS sample efficiency (200 paired replay seeds, zero LLM calls)', fontsize=10)
fig.tight_layout()
fig.savefig(OUT / 'F3_efficiency.png', dpi=150)

print('Figures saved')
