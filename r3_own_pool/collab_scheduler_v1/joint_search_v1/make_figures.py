"""Generate paper figures from frozen artifacts (zero model requests).

  v2     : Experiment 5 figures from V2_FORMAL_SEARCH_ANALYSIS.json
  nb     : Experiment 4/2/3/6 figures from real NB_ROWS.jsonl (post-run only)

Run:  python3 -m collab_scheduler_v1.joint_search_v1.make_figures [v2|nb|all]
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
FIGS = OUT / 'figs'
FIGS.mkdir(exist_ok=True)
COLOR = dict(**{
    'proposed_state_incremental': '#d62728', 'random': '#7f7f7f',
    'scalarized_bo': '#1f77b4', 'official_qnehvi_same_state': '#2ca02c',
    'proposed_without_state': '#ff7f0e',
    'proposed_without_incremental_cost': '#9467bd'})


def v2():
    f = json.loads((OUT / 'V2_FORMAL_SEARCH_ANALYSIS.json').read_text())
    # Fig 1: best-so-far Q vs evaluation step (mean over seeds)
    fig, ax = plt.subplots(figsize=(6, 4))
    for m, e in f['methods'].items():
        steps = sorted(int(k[4:]) for k in e['best_Q_mean_by_step'])
        vals = [e['best_Q_mean_by_step'][f'step{s}'] for s in steps]
        ls = '--' if 'without' in m else '-'
        ax.plot(steps, vals, ls, color=COLOR[m], label=e['label'],
                linewidth=1.6 if 'proposed_state' == m else 1.1)
    ax.set_xlabel('evaluation step (config-state reveals)')
    ax.set_ylabel('best-so-far mean Q (8-task panel)')
    ax.set_title('V2 search: best-so-far quality at equal evaluation budget')
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGS / 'v2_best_so_far.png', dpi=180)
    # Fig 2: physical cost to reach the Q=0.5 ceiling
    fig, ax = plt.subplots(figsize=(6, 4))
    labels, reqs = [], []
    for m, e in f['methods'].items():
        if not e['seeds']:
            continue
        labels.append(e['label'])
        reqs.append(sum(s['cum_spend_final']['requests'] for s in e['seeds'].values())
                    / len(e['seeds']))
    ax.barh(labels, reqs, color=[COLOR[m] for m, e in f['methods'].items() if e['seeds']])
    ax.set_xlabel('mean cumulative physical requests for the full 24-eval budget')
    ax.set_title('V2 search: physical cost (all methods reach the Q=0.5 panel ceiling)')
    fig.tight_layout()
    fig.savefig(FIGS / 'v2_physical_cost.png', dpi=180)
    print('v2 figures written')


def nb():
    rows = {}
    for l in (OUT / 'netbenefit_runs/NB_ROWS.jsonl').read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get('status') == 'COMPLETE' and r.get('execute'):
            rows[(r['protocol'], r['arm'], r['state'])] = r
    if not rows:
        print('no real rows yet; skip nb figures')
        return
    BUDGETS = (600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000)

    def qb(rec, b):
        return sum(1 for t in rec['tasks'] if t['Q'] == 1 and t['C_tokens'] <= b) / len(rec['tasks'])

    # Fig 3: budget-vs-within-budget-accuracy curves at fault30 (mechanism)
    fig, ax = plt.subplots(figsize=(6, 4))
    for arm in ('A_single', 'A_single_cross_fallback', 'C_static_hetero',
                'D_dynamic_local', 'E_dynamic_full'):
        k = ('mechanism', arm, 'fault30')
        if k not in rows:
            continue
        ax.plot(BUDGETS, [qb(rows[k], b) for b in BUDGETS], marker='o', markersize=3,
                label={'A_single': 'A Single', 'A_single_cross_fallback': "A' Single+FB",
                       'C_static_hetero': 'C Static DAG', 'D_dynamic_local': 'D Dynamic local',
                       'E_dynamic_full': 'E Dynamic full'}[arm])
    ax.set_xlabel('logical token budget B (per task)')
    ax.set_ylabel('Q_B (correct AND within budget)')
    ax.set_title('Budget curves, mechanism fault30 (n=50)')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / 'nb_budget_curves_fault30.png', dpi=180)

    # Fig 4: Help/Harm at primary point across families
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), sharey=True)
    for ax_, fam in zip(axes, ('mechanism', 'competitive')):
        kA, kD = (fam, 'A_single', 'fault30'), (fam, 'D_dynamic_local', 'fault30')
        if kA not in rows or kD not in rows:
            continue
        A = {t['uid']: t for t in rows[kA]['tasks']}
        D = {t['uid']: t for t in rows[kD]['tasks']}
        h = sum(1 for u in A if A[u]['Q'] == 0 and D[u]['Q'] == 1)
        m = sum(1 for u in A if A[u]['Q'] == 1 and D[u]['Q'] == 0)
        ax_.bar(['Help\n(D right, A wrong)', 'Harm\n(D wrong, A right)'], [h, m],
                color=['#2ca02c', '#d62728'])
        ax_.set_title(f'{fam} (plain Q, fault30)')
        for i, v in enumerate((h, m)):
            ax_.text(i, v, str(v), ha='center', va='bottom')
    fig.suptitle('D vs A discordant pairs')
    fig.tight_layout()
    fig.savefig(FIGS / 'nb_help_harm_fault30.png', dpi=180)
    print('nb figures written')


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('v2', 'all'):
        v2()
    if which in ('nb', 'all'):
        nb()
