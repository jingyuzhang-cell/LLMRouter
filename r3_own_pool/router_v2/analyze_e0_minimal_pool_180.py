"""E0: enumerate model subpools on the frozen six-model stratified-180 screening panel.

Zero generation cost. For every non-empty subset of the six screened models we
report pool oracle accuracy, the pool's best single model, and the oracle gap,
per domain and overall. Marginal oracle contribution identifies models that add
routing headroom versus models that only add complexity. Diagnostic only:
labels are single-generation screening outcomes.
"""
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'data/model_pool_screening_stratified_180/SCREENING_LABELS.jsonl'
OUT = ROOT / 'router_v2/e0_minimal_pool_180'
SLOTS = ['small', 'medium', 'large', 'coder', 'math', 'reasoning']
DOMAINS = ['overall', 'knowledge', 'math', 'code']


def main():
    rows = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    if len(rows) != 180 or {len(r['models']) for r in rows} != {6}:
        raise ValueError('Unexpected screening panel shape')
    domains = {}
    for d in DOMAINS[1:]:
        domains[d] = [r for r in rows if r['task_type'] == d]
    domains['overall'] = rows

    def pool_stats(pool, subset):
        """Oracle acc, best single model in subset, its acc, gap."""
        oracle = sum(max(pool[r['query_id']][m] for m in subset) for r in rows_dom) / len(rows_dom)
        per_model = {m: sum(pool[r['query_id']][m] for r in rows_dom) / len(rows_dom) for m in subset}
        best = max(per_model, key=per_model.get)
        return oracle, best, per_model[best], oracle - per_model[best]

    results = {}
    for d in DOMAINS:
        rows_dom = domains[d]
        qmap = {r['query_id']: {m: float(r['models'][m]['quality']) for m in SLOTS} for r in rows_dom}
        table = []
        for size in range(1, len(SLOTS) + 1):
            for subset in itertools.combinations(SLOTS, size):
                oracle, best, best_acc, gap = pool_stats(qmap, subset)
                table.append({'pool': list(subset), 'n': len(rows_dom), 'oracle': round(oracle, 6),
                              'best_single': best, 'best_single_acc': round(best_acc, 6),
                              'oracle_gap_pp': round(gap * 100, 3)})
        full = next(t for t in table if len(t['pool']) == 6)
        # Marginal oracle contribution of each model to the full pool.
        marginal = {}
        for m in SLOTS:
            reduced = next(t for t in table if sorted(t['pool']) == sorted(s for s in SLOTS if s != m))
            marginal[m] = round((full['oracle'] - reduced['oracle']) * 100, 3)
        # Greedy forward selection maximizing oracle at each size.
        greedy, remaining = [], list(SLOTS)
        while remaining:
            pick = max(remaining, key=lambda m: pool_stats(
                qmap, tuple(greedy + [m]))[0])
            greedy.append(pick)
            remaining.remove(pick)
        greedy_path = []
        for i in range(1, len(greedy) + 1):
            oracle, best, best_acc, gap = pool_stats(qmap, tuple(greedy[:i]))
            greedy_path.append({'pool': greedy[:i], 'oracle': round(oracle, 6),
                                'oracle_gap_pp': round(gap * 100, 3)})
        # Smallest pools retaining most of the full-pool oracle.
        minimal = {}
        for frac in (0.95, 0.99, 1.0):
            target = full['oracle'] * frac
            hit = min((t for t in table if t['oracle'] >= target - 1e-9), key=lambda t: len(t['pool']))
            minimal[f'{int(frac * 100)}pct'] = hit
        results[d] = {'full_pool': full, 'marginal_oracle_pp': marginal,
                      'greedy_forward': greedy_path, 'minimal_pools': minimal,
                      'subsets': table}

    named = {}
    for d in DOMAINS:
        table = {tuple(sorted(t['pool'])): t for t in results[d]['subsets']}
        candidates = [['reasoning'], ['reasoning', 'large'], ['reasoning', 'large', 'medium'],
                      ['reasoning', 'large', 'math'], ['reasoning', 'large', 'small'],
                      ['reasoning', 'large', 'coder'], SLOTS[:]]
        named[d] = [table[tuple(sorted(c))] for c in candidates]

    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'RESULTS.json').write_text(json.dumps(results, indent=1) + '\n')
    lines = ['# E0 minimal effective pool (stratified-180, single-generation labels)', '']
    for d in DOMAINS:
        r = results[d]
        lines += [f'## {d} (n={r["full_pool"]["n"]})',
                  f'full-6 oracle {r["full_pool"]["oracle"]:.4f}; marginal oracle pp: '
                  + ', '.join(f'{m} {v:+.2f}' for m, v in sorted(r['marginal_oracle_pp'].items(), key=lambda kv: -kv[1])),
                  '', '| pool | oracle | gap pp | best single |', '|---|---|---|---|']
        for t in named[d]:
            lines.append(f'| {"+".join(t["pool"])} | {t["oracle"]:.4f} | {t["oracle_gap_pp"]:.2f} | {t["best_single"]} ({t["best_single_acc"]:.4f}) |')
        lines.append(f'| greedy path | {" -> ".join("+".join(g["pool"]) + f' ({g["oracle"]:.4f})' for g in r["greedy_forward"])} | | |')
        lines += ['', f'minimal pools: ' + '; '.join(
            f'{k}: {"+".join(v["pool"])} oracle {v["oracle"]:.4f}' for k, v in r['minimal_pools'].items()), '']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({d: {'marginal_pp': results[d]['marginal_oracle_pp'],
                          'minimal_95': results[d]['minimal_pools']['95pct']['pool']} for d in DOMAINS}, indent=1))


if __name__ == '__main__':
    main()
