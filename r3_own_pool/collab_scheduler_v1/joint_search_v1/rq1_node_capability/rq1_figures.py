"""Figures for RQ1 node-capability analysis (reads RQ1_NODE_CAPABILITY.json)."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
d = json.loads((HERE / 'RQ1_NODE_CAPABILITY.json').read_text())

# ---- Fig 1: stage-level rates by model ----
fig, axes = plt.subplots(1, 4, figsize=(15, 3.6))
panels = [
    ('extract_e1', 'Extraction e1 (table)', ['parse_ok', 'operand_recall']),
    ('extract_e2', 'Extraction e2 (text)', ['parse_ok', 'operand_recall']),
    ('reason_r', 'Reasoning r', ['expr_ok', 'eval_ok', 'gold_match']),
    ('verify_v', 'Verification v', ['parse_ok', 'consistency', 'gold_match']),
]
for ax, (key, title, metrics) in zip(axes, panels):
    agg = d['stage_aggregates'][key]
    models = sorted(agg)
    width = 0.8 / len(metrics)
    for i, met in enumerate(metrics):
        xs = [j + (i - (len(metrics) - 1) / 2) * width for j in range(len(models))]
        ys = [agg[m].get(met) or 0 for m in models]
        ax.bar(xs, ys, width, label=met)
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.015, f'{y:.2f}', ha='center', fontsize=6.5)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([f'{m}\n(n={agg[m]["n"]})' for m in models], fontsize=8)
    ax.set_ylim(0, 1.12)
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=6.5)
fig.suptitle('RQ1 node-capability by stage and model (frozen observations; rates '
             'over node-level records; v2.1 contract)', fontsize=9)
fig.tight_layout()
fig.savefig(HERE / 'fig1_stage_rates.png', dpi=150)

# ---- Fig 2: e2 mixed tasks by model ----
mix = d['missing_output_accounting']['e2_mixed_tasks_by_model']
tasks = sorted(mix)
fig, ax = plt.subplots(figsize=(9, 3.6))
xs, labels = [], []
x = 0
for t in tasks:
    for m in sorted(mix[t]):
        ok, n = mix[t][m]['ok'], mix[t][m]['n']
        ax.bar(x, ok / n, 0.8, color='#3b6' if m == 'large' else '#69c')
        ax.bar(x, 1 - ok / n, 0.8, bottom=ok / n, color='#ccc')
        ax.text(x, 1.03, f'{ok}/{n}', ha='center', fontsize=7)
        xs.append(x)
        labels.append(f'{t[:8]}\n{m}')
        x += 1
    x += 0.6
ax.set_xticks(xs)
ax.set_xticklabels(labels, fontsize=7)
ax.set_ylabel('usable-facts rate')
ax.set_ylim(0, 1.15)
ax.set_title('e2 (text extraction) on MIXED tasks: complementary, task-dependent '
             'model failures (green=large, blue=medium; grey=empty facts)', fontsize=9)
fig.tight_layout()
fig.savefig(HERE / 'fig2_e2_mixed_tasks.png', dpi=150)
print('figures written')
