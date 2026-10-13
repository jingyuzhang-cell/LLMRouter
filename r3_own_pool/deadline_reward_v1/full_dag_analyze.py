"""Post-run analyzer: rebuild the 15 x 3 settled result table and
paired statistics from the three arm LEDGERS of a full-DAG run
(zero calls; runs on real or fake ledgers).

The ledgers carry everything settlement needs (answer, finish_reason,
tag, task, node, usage, cash, task_t_s, deadline_s, prompt_sha256,
consumed_upstream), so the analysis is fully reproducible from the
raw artifacts alone — no in-memory state required.

Equivalence test (--demo): run the fake-transport experiment with
REAL ledger files, settle directly (scoring module) AND via ledger
reconstruction, assert identical numbers.

Usage:
  python3 -m deadline_reward_v1.full_dag_analyze --demo
  python3 -m deadline_reward_v1.full_dag_analyze \
      --run-dir deadline_reward_v1/fe_screening_runs/full_dag_<ts>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks
from deadline_reward_v1.full_dag_executor import (
    GlobalBudget, RealRunner)
from deadline_reward_v1.full_dag_protocol import C0_PER_TASK, utility
from deadline_reward_v1.full_dag_scoring import (
    _fake_transport_factory, paired_analysis, score_node)

HERE = Path(__file__).resolve().parent
ARMS = ('SS-Tuned', 'Fixed-Tuned', 'DD-Online')


def load_ledger(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines()
            if l.strip()]


def settle_from_ledger(entries, silver_map):
    """Rebuild per-task settlement from raw ledger entries."""
    by_task = {}
    for e in entries:
        by_task.setdefault(e['task'], []).append(e)
    rows = []
    for tid, es in by_task.items():
        silver_task = silver_map[tid]
        # node currents = LAST version per node (set_output semantics)
        current = {}
        for e in es:
            current[e['node']] = e
        sources = dict(
            tl=(current.get('tl') or {}).get('answer', ''),
            er=(current.get('er') or {}).get('answer', ''))
        nodes = {}
        for n in ('fe', 'tl', 'er', 'xc'):
            e = current.get(n) or dict(answer='',
                                       finish_reason=None)
            nodes[n] = score_node(n, e.get('answer', ''),
                                  e.get('finish_reason'),
                                  silver_task,
                                  sources if n == 'xc' else None)
        sems = [nodes[n]['q_sem'] for n in ('fe', 'tl', 'er', 'xc')
                if nodes[n]['q_sem'] is not None]
        q = round(sum(sems) / len(sems), 4) if sems else None
        tokens = sum(e['usage']['prompt_tokens']
                     + e['usage']['completion_tokens'] for e in es)
        cash = sum(e['cash_cny'] for e in es)
        T = max(e['task_t_s'] for e in es)
        D = es[0]['deadline_s']
        U = (utility(q if q is not None else 0.0, tokens, T, D)
             if q is not None else None)
        rows.append(dict(
            task_id=tid, nodes=nodes, terminal_q=q,
            q_available=(q is not None), total_tokens=tokens,
            incremental_cash_cny=round(cash, 6),
            normalized_cost=round(tokens / C0_PER_TASK, 4),
            per_task_budget=dict(
                C0_reference=60000, spent=tokens,
                remaining=round(60000 - tokens, 1),
                recovery_calls=sum(1 for e in es
                                   if e['tag'] != 'planned')),
            task_time_s=round(T, 3), sequential=True,
            deadline_met=(T <= D), deadline_s=D, utility_U=U,
            grade='SILVER-candidate'))
    return rows


def analyze_run(run_dir: Path):
    silver_map = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    results = {}
    for arm in ARMS:
        entries = load_ledger(run_dir / f'DAG_LEDGER_{arm}.jsonl')
        results[arm] = settle_from_ledger(entries, silver_map)
    paired = paired_analysis(results)
    return dict(results=results, paired=paired)


def demo():
    """Equivalence: direct settlement vs ledger reconstruction."""
    import tempfile
    tasks = full_dag_tasks.build_tasks()
    silver_map = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    docs = full_dag_tasks.load_docs()
    with tempfile.TemporaryDirectory() as td:
        direct = {}
        for arm in ARMS:
            led = Path(td) / f'DAG_LEDGER_{arm}.jsonl'
            runner = RealRunner(arm, {}, GlobalBudget(), led,
                                transport=_fake_transport_factory(
                                    silver_map))
            from deadline_reward_v1.full_dag_scoring import settle_task
            rows = []
            for t in tasks:
                chain, clock = runner.run_task(
                    t, docs[t['doc_slot']]['text'])
                rows.append(settle_task(t, chain, clock, silver_map,
                                        runner.task_totals()))
            direct[arm] = rows
        rebuilt = analyze_run(Path(td))
    mismatches = []
    for arm in ARMS:
        for a, b in zip(direct[arm], rebuilt['results'][arm]):
            for k in ('task_id', 'terminal_q', 'total_tokens',
                      'task_time_s', 'utility_U', 'deadline_met'):
                if a[k] != b[k]:
                    mismatches.append((arm, a['task_id'], k,
                                       a[k], b[k]))
    ok = not mismatches
    print(json.dumps(dict(
        equivalence='PASS' if ok else 'FAIL',
        n_rows_compared=sum(len(direct[a]) for a in ARMS),
        mismatches=mismatches[:5],
        paired_demo={k: v['mean_dU'] for k, v in
                     rebuilt['paired'].items()}), indent=1,
        ensure_ascii=False))
    return 0 if ok else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--run-dir')
    args = parser.parse_args()
    if args.demo:
        return demo()
    if args.run_dir:
        out = analyze_run(Path(args.run_dir))
        dest = Path(args.run_dir) / 'DAG_ANALYSIS.json'
        dest.write_text(json.dumps(out, indent=1,
                                   ensure_ascii=False))
        print(f'written {dest}')
        for arm, rows in out['results'].items():
            U = [r['utility_U'] for r in rows
                 if r['utility_U'] is not None]
            print(f'{arm:14s} n={len(rows)} '
                  f'mean_U={sum(U)/len(U) if U else float("nan"):.3f}')
        for k, v in out['paired'].items():
            print(f'  {k:32s} mean_dU={v["mean_dU"]} '
                  f'p={v["perm_p_two_sided"]}')
        return 0
    parser.error('need --demo or --run-dir')


if __name__ == '__main__':
    raise SystemExit(main())
