"""Offline validation: 4 tasks x 4 arms fake transport -> direct
settlement vs ledger reconstruction equivalence (operator task 4).
Run: python3 -m deadline_reward_v1.four_arm_v2_validate
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks
from deadline_reward_v1.four_arm_v2 import ARMS, ArmRunner
from deadline_reward_v1.full_dag_analyze import analyze_four_arm
from deadline_reward_v1.full_dag_executor import GlobalBudget
from deadline_reward_v1.full_dag_scoring import settle_task
from deadline_reward_v1.theta_actions import PriorStore

HERE = Path(__file__).resolve().parent
TASKS = ('T05', 'T06', 'T08', 'T14')


def fake(model_id, theta, prompt, creds, force_max_tokens=None):
    if force_max_tokens == 64:
        return dict(answer='{"facts":[{"fact":"cut',
                    finish_reason='max_tokens', tokens_in=800,
                    tokens_out=64, cash_cny=0.0, latency_s=8.0)
    if 'fact_extraction' in prompt:
        return dict(answer='[{"fact":"ok",'
                           '"evidence_doc_id":"PLACE"}]',
                    finish_reason='stop', tokens_in=900,
                    tokens_out=200, cash_cny=0.0, latency_s=20.0)
    if 'timeline' in prompt:
        return dict(answer='```json\n[{"date":"2024-04-24",'
                           '"event":"e","evidence":"PLACE"}]\n```',
                    finish_reason='stop', tokens_in=700,
                    tokens_out=150, cash_cny=0.0, latency_s=18.0)
    if 'entity_relations' in prompt:
        return dict(answer='[{"entity":"X","role":"r",'
                           '"relation":"y",'
                           '"evidence_doc_id":"PLACE"}]',
                    finish_reason='stop', tokens_in=700,
                    tokens_out=150, cash_cny=0.002, latency_s=12.0)
    return dict(answer='[{"claim":"c","source_a":"PLACE",'
                       '"source_b":"PLACE",'
                       '"verdict":"SUPPORTED"}]',
                finish_reason='stop', tokens_in=600,
                tokens_out=120, cash_cny=0.003, latency_s=15.0)


def main():
    tasks = [t for t in full_dag_tasks.build_tasks()
             if t['task_id'] in TASKS]
    docs = full_dag_tasks.load_docs()
    silver = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    with tempfile.TemporaryDirectory() as td:
        direct = {}
        for arm in ARMS:
            budget = GlobalBudget()
            store = PriorStore() if arm[0] == 'E' else None
            r = ArmRunner(
                arm, {}, budget,
                Path(td) / f'DAG_LEDGER_{arm}.jsonl',
                transport=fake, store=store)
            rows = []
            for t in tasks:
                t2 = dict(t)
                t2['doc_id'] = 'PLACE'
                chain, clock = r.run_task(
                    t2, docs[t['doc_slot']]['text'])
                rows.append(settle_task(t2, chain, clock, silver,
                                        r.task_totals()))
            direct[arm] = rows
        rebuilt = analyze_four_arm(Path(td))
    mis = []
    for arm in ARMS:
        for a, b in zip(direct[arm], rebuilt['results'][arm]):
            for k in ('task_id', 'terminal_q', 'total_tokens',
                      'utility_U'):
                if a[k] != b[k]:
                    mis.append((arm, a['task_id'], k, a[k], b[k]))
    report = dict(
        equivalence='PASS' if not mis else 'FAIL',
        rows_compared=sum(len(direct[a]) for a in ARMS),
        mismatches=mis[:5],
        paired={k: dict(mean=v['mean_dU'], n=v['n'])
                for k, v in rebuilt['paired'].items()})
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if not mis else 2


if __name__ == '__main__':
    raise SystemExit(main())
