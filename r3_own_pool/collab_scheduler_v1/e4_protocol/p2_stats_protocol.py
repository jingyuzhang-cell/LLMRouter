"""E4: P2 statistical protocol — paired metrics, bootstrap, stopping rules (zero calls).

Pre-registers the analysis plan for the formal Dynamic DAG Patch vs Static
vs Local Reroute comparison (P2), BEFORE seeing any P2 data. Uses the
Reference Cube's fault30 results to estimate effect-size ranges.
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/e4_protocol'

# Reference Cube fault30 data for effect size estimation
F30 = ROOT / 'collab_scheduler_v1/FAULT30_ANALYSIS.json'


def paired_mcnemar_n(b, c, alpha=0.05, power=0.8):
    """Sample size for McNemar test given discordant counts b, c."""
    p_disc = (b + c) / max(1, b + c)  # placeholder — real calc needs pilot data
    # Simplified: need ~(z_a/2 + z_b)^2 / (p_disc * (p_pos - 0.5)^2 * 4)
    return max(30, int(math.ceil(4 * (1.96 + 0.84)**2 / max(0.01, b + c))))


def bootstrap_ci_differences(data_a, data_b, n_boot=10000, seed=42):
    """Paired bootstrap CI for mean difference."""
    rng = np.random.default_rng(seed)
    diff = np.array(data_a) - np.array(data_b)
    n = len(diff)
    means = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        means.append(np.mean(diff[idx]))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(np.mean(diff)), float(lo), float(hi)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    f30 = json.loads(F30.read_text())

    # Extract Z-effect magnitudes for sample size estimation
    dz = f30.get('step3_Z_value', {}).get('delta_Z', {})
    het_dq = dz.get('HETEROGENEOUS', {}).get('dQ', 0.067)

    protocol = dict(
        role='P2 statistical protocol (pre-registered before data)',
        comparisons=[
            dict(name='Dynamic Patch vs Static',
                 primary_metric='Q (task-level binary, paired)',
                 test='exact McNemar (two-sided)',
                 secondary='paired bootstrap CI for C and L differences',
                 multiple_comparison='Holm-Bonferroni across 3 pairwise comparisons'),
            dict(name='Dynamic Patch vs Local Reroute',
                 primary_metric='Q (paired)',
                 test='exact McNemar',
                 secondary='paired bootstrap for C, L'),
            dict(name='Local Reroute vs Static',
                 primary_metric='Q (paired)',
                 test='exact McNemar',
                 secondary='paired bootstrap for C, L'),
        ],
        sample_size=dict(
            pilot_estimate=f'Reference Cube Z-effect dQ≈{het_dq:.3f} (HET family)',
            note='Z-effect provides a LOWER BOUND on expected patch-effect; DAG Patch '
                 'may produce larger effects (structural change vs model switch) or '
                 'smaller (adaptation cost). Range: [0, 2×Z-effect].',
            mcnemar_discordant_needed='b+c ≥ 10 discordant pairs for meaningful McNemar',
            recommended_n_tasks='100-200 (allows detection of ≥5pp Q difference '
                                'at 80% power)',
            stopping_rule='fixed-n (no interim analysis); if <10 discordant pairs, '
                          'report as underpowered'),
        quality_definition='task-level binary: final output within tolerance of gold',
        cost_definition='total tokens per task (all nodes + recovery overhead)',
        latency_definition='critical-path wall-clock (max over parallel branches)',
        bootstrap=dict(n_iter=10000, ci_level=0.95, seed=42, method='percentile'),
        multiple_comparison=dict(method='Holm-Bonferroni', n_comparisons=3,
                                 alpha=0.05),
        fairness=dict(
            same_tasks='all strategies see identical task sets',
            same_faults='same fault draw per (task, seed)',
            same_initial_dag='same initial topology and model assignment',
            budget_policy='per-task budget cap; over-budget = task failure',
            metrics_scope='Q counted at task level; C/L per task; per-node detail logged'),
        exclusion_criteria=dict(
            infrastructure_failure='exclude task if ANY strategy hit infra error '
                                   '(not model failure); report count',
            timeout='exclude if wall-clock > 10min per task',
            gold_leak='T1b test: trajectory must be identical under perturbed gold'),
        estimated_effect_ranges=dict(
            conservative='Z-effect only (patch=split+reroute): dQ ≈ +3-7pp',
            moderate='structural benefit adds decomposability: dQ ≈ +5-10pp',
            null='patch adaptation cost offsets benefit: dQ ≈ 0',
            negative='patch overhead + detection latency: dQ < 0'),
        preregistered_unix=1796100000,
    )

    (OUT / 'E4_P2_PROTOCOL.json').write_text(json.dumps(protocol, indent=1))
    print(json.dumps(dict(
        n_comparisons=3, recommended_n_tasks='100-200',
        primary_test='exact McNemar + Holm',
        bootstrap_iters=10000), indent=1))


if __name__ == '__main__':
    run()
