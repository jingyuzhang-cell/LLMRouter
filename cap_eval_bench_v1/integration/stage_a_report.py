"""Stage-A paired analysis report (zero model calls; runs after the batch).

Reads stage_a/SA-*/{trace,deliverable,scores}.json + the ledger, produces:
- per-task per-arm table (Q, coverage, C_total, L_service, verdict, truncation);
- paired-by-(task,rep) medians and direction counts per arm pair (single vs fixed/auto,
  fixed vs auto) — engineering gate only, no independence claims;
- honest INVALID/BUDGET_STOP accounting;
- retrieval self-sufficiency by task (eval-side, standalone).
"""
import json
import statistics as st
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')


def main():
    rows = []
    for d in sorted((B / 'stage_a').glob('SA-*')):
        tr = d / 'trace.json'
        sc = d / 'scores.json'
        if not tr.exists():
            rows.append({'run_id': d.name, 'status': 'NO-TRACE'})
            continue
        t = json.loads(tr.read_text())
        if not sc.exists():
            rows.append({'run_id': d.name, 'system_id': t['system_id'], 'status': t['status'],
                         'note': 'planner-invalid or aborted before scoring'})
            continue
        s = json.loads(sc.read_text())
        u = s['unified']
        rows.append({'run_id': d.name, 'task': t['task_id'], 'arm': t['system_id'],
                     'rep': d.name.rsplit('-r', 1)[-1], 'status': t['status'],
                     'Q': s['v1']['Q']['Q'], 'coverage': s['v1']['Q']['coverage'],
                     'C_total': u['C']['total_tokens'], 'L_service': u['L']['service_s'],
                     'verdict': u['Reliability']['verdict'],
                     'truncated': bool(u['C'].get('reuse_events') is None and any(
                         n.get('truncated') for n in t['nodes'])) or any(
                         n.get('truncated') for n in t['nodes']),
                     'self_sufficiency': u['E_evidence']['retrieval_self_sufficiency']})
    scored = [r for r in rows if 'Q' in r]
    pairs = {}
    for (task, rep) in {(r['task'], r.get('rep')) for r in scored}:
        cell = {r['arm']: r for r in scored if r['task'] == task and r.get('rep') == rep}
        for a, b in (('single_model', 'fixed_graph'), ('single_model', 'auto_graph'),
                     ('fixed_graph', 'auto_graph')):
            if a in cell and b in cell:
                pairs.setdefault((a, b), []).append(
                    {'task': task, 'rep': rep,
                     'dQ': round(cell[b]['Q'] - cell[a]['Q'], 4),
                     'dC': cell[b]['C_total'] - cell[a]['C_total'],
                     'winner_Q': a if cell[a]['Q'] >= cell[b]['Q'] else b})
    summary = {}
    for (a, b), lst in pairs.items():
        summary[f'{a}_vs_{b}'] = {
            'n_pairs': len(lst),
            'dQ_median': round(st.median([x['dQ'] for x in lst]), 4),
            'dC_median': st.median([x['dC'] for x in lst]),
            'Q_wins': {a: sum(1 for x in lst if x['winner_Q'] == a),
                       b: sum(1 for x in lst if x['winner_Q'] == b)},
            'by_task_direction': {t: [x['dQ'] for x in lst if x['task'] == t] for t in
                                  sorted({x['task'] for x in lst})}}
    out = {'rows': rows, 'paired_summary': summary,
           'note': 'engineering-gate medians/direction counts; same-task runs are correlated; '
                   'no independence or confirmatory claims'}
    (B / 'stage_a' / 'STAGE_A_PAIRED_REPORT.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('\nrows:', len(rows), 'scored:', len(scored),
          'invalid/stopped:', len(rows) - len(scored))


if __name__ == '__main__':
    main()
