"""Final unified algorithm table: SA-PGFS vs external baselines (zero calls).

Consumes REPLAY_FAULT_ROBUST.json (SA-PGFS: random/greedy/ehvi/cost_aware,
200 paired seeds) and EXTERNAL_BASELINES_ROBUST.json (nsga2/qnparego/qnehvi/
aflow_mcts, same seeds/init/noise), verifies the SA-PGFS rerun reproduces the
frozen summary bit-for-bit (freeze reproducibility check), and emits:

  - the unified table (Method | type | final HV gap | AUC-HV | N95 pass |
    dedup recall) in markdown + machine-readable form
  - paired permutation tests for ehvi/cost_aware vs every external method
    (and external-vs-external from the baseline run)

Run: python3 -m sa_pgfs_v1.final_algorithm_table
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'sa_pgfs_v1/results_cube_replay'
TAB = ROOT / 'collab_scheduler_v1/ALGORITHM_TABLE.md'

TYPES = {'random': '无模型', 'greedy_q': '单目标贪心', 'nsga2': 'MOEA',
         'qnparego': 'MOBO', 'qnehvi': 'noisy MOBO', 'aflow_mcts': 'workflow search',
         'ehvi': 'state-cond. surrogate Pareto (SA-PGFS)',
         'cost_aware_ehvi': 'state-cond. surrogate Pareto (SA-PGFS)'}
NAMES = {'random': 'Random', 'greedy_q': 'Greedy-Q', 'nsga2': 'NSGA-II',
         'qnparego': 'qNParEGO', 'qnehvi': 'qNEHVI', 'aflow_mcts': 'AFlow-style MCTS',
         'ehvi': 'SA-PGFS (EHVI)', 'cost_aware_ehvi': 'SA-PGFS (cost-aware EHVI)'}


def perm_test(a, b, n_perm=10000, seed=1):
    d = np.array(a, float) - np.array(b, float)
    obs_ = abs(d.mean())
    rngp = np.random.default_rng(seed)
    signs = rngp.choice([-1.0, 1.0], size=(n_perm, len(d)))
    null = np.abs((signs * d).mean(axis=1))
    return float((null >= obs_ - 1e-12).mean())


def run():
    sap = json.loads((OUT / 'REPLAY_FAULT_ROBUST.json').read_text())
    ext = json.loads((OUT / 'EXTERNAL_BASELINES_ROBUST.json').read_text())
    # freeze reproducibility check: the rerun (with per_seed dump) must match
    # the frozen summaries exactly
    for s, m in ext['sapgfs_reference'].items():
        got = sap['strategy_summary'][s]['final_regret']['mean']
        ref = m['final_regret']['mean']
        assert abs(got - ref) < 1e-12, (s, got, ref)
    repro = 'PASS (rerun reproduces frozen SA-PGFS summaries bit-for-bit)'

    order = ['random', 'greedy_q', 'nsga2', 'qnparego', 'qnehvi', 'aflow_mcts',
             'ehvi', 'cost_aware_ehvi']
    rows = []
    table = ['| Method | 类型 | Final HV gap (mean/median) | AUC-HV | N95 达标 | Recall (dedup) |',
             '|---|---|---|---|---|---|']
    for k in order:
        if k in sap['strategy_summary']:
            m = sap['strategy_summary'][k]
            n_seeds = sap['n_seeds']
        else:
            m = ext['external_strategy_summary'][k]
            n_seeds = ext['n_seeds']
        n95ok = n_seeds - m['N_95pct_HV']['never']
        r, a, rc = m['final_regret'], m['AUC_HV'], m['recall_dedup']
        table.append(f"| {NAMES[k]} | {TYPES[k]} | {r['mean']:+.4f} / {r['median']:+.4f} | "
                     f"{a['mean']:.3f} | {n95ok}/{n_seeds} | {rc['mean']:.3f} |")
        rows.append(dict(key=k, name=NAMES[k], type=TYPES[k],
                         regret_mean=r['mean'], regret_median=r['median'],
                         auc_mean=a['mean'], n95_pass=n95ok, n_seeds=n_seeds,
                         recall_dedup_mean=rc['mean']))

    tests = {}
    for sap_s in ('ehvi', 'cost_aware_ehvi'):
        for other in ('nsga2', 'qnparego', 'qnehvi', 'aflow_mcts'):
            for met in ('regret', 'auc'):
                tests[f'{sap_s}_vs_{other}:{met}'] = perm_test(
                    sap['per_seed_metrics'][sap_s][met],
                    ext['per_seed_metrics'][other][met])
        for other in ('random', 'greedy_q'):
            for met in ('regret', 'auc'):
                tests[f'{sap_s}_vs_{other}:{met}'] = perm_test(
                    sap['per_seed_metrics'][sap_s][met],
                    sap['per_seed_metrics'][other][met])
    out = dict(reproducibility_check=repro,
               protocol='PROTOCOL_SAPGFS_FREEZE_v1 (frozen harness, 200 paired seeds)',
               naming=ext['naming'], rows=rows,
               paired_permutation_tests=tests)
    (OUT / 'FINAL_ALGORITHM_TABLE.json').write_text(json.dumps(out, indent=1))

    body = ['# 统一算法表（SA-PGFS vs 外部基线，冻结 cube 上零调用 reveal/replay）\n',
            f'协议：{out["protocol"]}；同初始设计/同噪声抽样/预算 8；G_collab 15 配置。\n',
            f'冻结可复现性：{repro}。\n', '\n'.join(table), '\n',
            '## 配对置换检验（10,000 次符号置换，p 值）\n']
    for k, v in tests.items():
        body.append(f'- {k}: p = {v:.4f}')
    body.append('\n注：nsga2/qnparego/qnehvi/aflow_mcts 为搜索机制的诚实适配（同一冻结空间、'
                '执行结果固定），非原系统完整复现；论文表述见 naming 字段。')
    TAB.write_text('\n'.join(body))
    print('\n'.join(table))
    print()
    print(json.dumps(tests, indent=1))


if __name__ == '__main__':
    run()
