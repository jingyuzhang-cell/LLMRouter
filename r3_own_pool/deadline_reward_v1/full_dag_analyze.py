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
ARMS = ('SS-Tuned', 'Fixed-Tuned', 'DD-Online',
        'DD-Online-NoLearn')


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
        led = run_dir / f'DAG_LEDGER_{arm}.jsonl'
        if not led.exists():
            continue   # arm never started (fail-stop) — absent arms
            # are skipped; present-but-partial arms settle partially
        entries = load_ledger(led)
        results[arm] = settle_from_ledger(entries, silver_map)
    paired = paired_analysis(results)
    return dict(results=results, paired=paired)


RESTRICTED_TASKS = ['T01', 'T02', 'T03', 'T04',
                    'T11', 'T12', 'T13', 'T15']


def demo():
    """Equivalence on the RESTRICTED 8-task x 4-arm drill: direct
    settlement vs ledger reconstruction (fix 4)."""
    import tempfile
    from deadline_reward_v1.theta_actions import PriorStore
    tasks = [t for t in full_dag_tasks.build_tasks()
             if t['task_id'] in RESTRICTED_TASKS]
    assert len(tasks) == 8
    silver_map = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    docs = full_dag_tasks.load_docs()
    with tempfile.TemporaryDirectory() as td:
        direct = {}
        for arm in ARMS:
            led = Path(td) / f'DAG_LEDGER_{arm}.jsonl'
            store = PriorStore() if arm.startswith('DD') else None
            runner = RealRunner(
                arm, {}, GlobalBudget(), led,
                transport=_fake_transport_factory(silver_map),
                prior_store=store,
                learn_enabled=(arm == 'DD-Online'))
            from deadline_reward_v1.full_dag_scoring import settle_task
            rows = []
            for t in tasks:
                chain, clock = runner.run_task(
                    t, docs[t['doc_slot']]['text'])
                rows.append(settle_task(t, chain, clock, silver_map,
                                        runner.task_totals()))
            direct[arm] = rows
        rebuilt = analyze_run(Path(td))
    # ensure the ablation pair is present and settled
    assert 'DD-Online_vs_DD-Online-NoLearn' in rebuilt['paired'], \
        rebuilt['paired'].keys()
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
        drill='restricted 8 tasks x 4 arms',
        n_rows_compared=sum(len(direct[a]) for a in ARMS),
        mismatches=mismatches[:5],
        paired_demo={k: v['mean_dU'] for k, v in
                     rebuilt['paired'].items()}), indent=1,
        ensure_ascii=False))
    return 0 if ok else 2


FOUR_ARMS_V2 = ('B-Fixed-Norm', 'C-Fixed-Gate', 'D-DD-Gate',
                 'E-DD-Gate-Learn')


def analyze_four_arm(run_dir: Path):
    """B/C/D/E ledgers -> settled table + the three v2 contrasts.
    TERMINATE tasks are settled by the REAL evaluator: nodes that
    never ran are contract-failed -> semantic 0 (frozen settlement
    semantics; gate predictions are never used as scores)."""
    silver_map = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    results = {}
    for arm in FOUR_ARMS_V2:
        led = run_dir / f'DAG_LEDGER_{arm}.jsonl'
        if not led.exists():
            continue
        results[arm] = settle_from_ledger(load_ledger(led),
                                          silver_map)
    pairs = [('D-DD-Gate', 'C-Fixed-Gate'),
             ('E-DD-Gate-Learn', 'D-DD-Gate'),
             ('C-Fixed-Gate', 'B-Fixed-Norm')]
    paired = {}
    for a, b in pairs:
        if a not in results or b not in results:
            continue
        rows = []
        for ra in results[a]:
            rb = next((x for x in results[b]
                       if x['task_id'] == ra['task_id']), None)
            if rb is None or ra['utility_U'] is None                     or rb['utility_U'] is None:
                continue
            rows.append(dict(task_id=ra['task_id'],
                             dU=round(ra['utility_U']
                                      - rb['utility_U'], 6)))
        dUs = [r['dU'] for r in rows]
        paired[f'{a.split("-")[0]}_vs_{b.split("-")[0]}'] = dict(
            n=len(rows),
            mean_dU=round(sum(dUs) / len(dUs), 6) if dUs else None,
            pos=sum(1 for d in dUs if d > 0),
            neg=sum(1 for d in dUs if d < 0),
            per_task=rows)
    return dict(results=results, paired=paired)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--run-dir')
    parser.add_argument('--four-arm', action='store_true')
    args = parser.parse_args()
    if args.demo:
        return demo()
    if args.run_dir and args.four_arm:
        out = analyze_four_arm(Path(args.run_dir))
        dest = Path(args.run_dir) / 'PILOT_ANALYSIS.json'
        dest.write_text(json.dumps(out, indent=1,
                                   ensure_ascii=False))
        print(f'written {dest}')
        for k, v in out['paired'].items():
            print(f'  {k:12s} n={v["n"]} mean_dU={v["mean_dU"]} '
                  f'+/-={v["pos"]}/{v["neg"]}')
        return 0
    if args.run_dir:
        out = analyze_run(Path(args.run_dir))
        dest = Path(args.run_dir) / 'DAG_ANALYSIS.json'
        out['run_status'] = ('INCOMPLETE (fail-stop: token cap '
                             'during DD-Online; NoLearn never ran)'
                             if 'DD-Online-NoLearn'
                             not in out['results'] else 'COMPLETE')
        dest.write_text(json.dumps(out, indent=1,
                                   ensure_ascii=False))
        print(f'written {dest} [{out["run_status"]}]')
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
