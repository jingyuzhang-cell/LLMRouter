"""Independent validation runner design (zero calls in this module).

Randomness controls (operator design):
  SHARED FIRST ATTEMPTS — within one repetition of a task, the four
  planned node calls are executed ONCE (physically) and replayed to
  EVERY arm with identical answers/finish/tokens/latency. Arms
  diverge only at RECOVERY decisions — the pilot's T05 confound
  (different first GLM outputs between arms) is eliminated by
  construction.
  REPETITIONS — R=3 repetitions per task; planned calls are re-run
  per repetition (service randomness varies ACROSS reps, held
  WITHIN rep). Per-task dU is averaged over reps.

  E SEPARATE + PRECONDITION GATES — E runs once per task AFTER the
  B/C/D block; its learning study is reported only where BOTH gates
  hold: (i) legal learning samples existed (repair/fallback calls),
  (ii) store posteriors actually changed a later decision.

Accounting: each arm's U settles on the FULL task cost (shared
planned calls charged to every arm's ledger); the PHYSICAL budget
is charged once for shared planned calls + each arm's own
recoveries.

Run: python3 -m deadline_reward_v1.deadline_validation_run --drill
Real: VALIDATION_GO=1 python3 -m
      deadline_reward_v1.deadline_validation_run --run-real
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks
from deadline_reward_v1.four_arm_v2 import ArmRunner
from deadline_reward_v1.full_dag_executor import (
    DagChain, GlobalBudget, TaskClock, _ok, topo_order, real_call)
from deadline_reward_v1.full_dag_protocol import TUNED_THETA

HERE = Path(__file__).resolve().parent
VTASKS = json.loads(
    (HERE / 'INDEPENDENT_VALIDATION_TASKS.json').read_text())['tasks']
FREEZE = HERE / 'INDEPENDENT_VALIDATION_FREEZE.json'
GO_FLAG = 'VALIDATION_GO'
REPS = 3
PRIMARY_ARMS = ('B-Fixed-Norm', 'C-Fixed-Gate', 'D-DD-Gate')


def _materialize(task):
    """Attach the fe/er prompts from the frozen builders so
    DagChain.build_prompt works for V-tasks."""
    if 'nodes' in task and task['nodes']:
        return task
    from deadline_reward_v1.full_dag_tasks import (
        prompt_er, prompt_fe)
    t = dict(task)
    t['nodes'] = dict(
        fe=dict(prompt=prompt_fe(task['doc_id'], task['_text']),
                depends=[]),
        tl=dict(prompt='RUNTIME', depends=['fe']),
        er=dict(prompt=prompt_er(task['doc_id'], task['_text']),
                depends=[]),
        xc=dict(prompt='RUNTIME', depends=['tl', 'er']))
    return t


def run_planned_once(task, docs_text, transport, creds, rep):
    """Execute the four planned calls ONCE (with the frozen fault
    injections); returns the recorded outcomes for replay."""
    task = _materialize(dict(task, _text=docs_text))
    chain = DagChain(task, docs_text)
    clock = TaskClock(task['deadline_s'])
    recorded = {}
    for node in topo_order():
        model = task['planned_pi'][node]
        theta = TUNED_THETA[model]
        inject = (task['fault_type']
                  if node == task['fault_node'] else None)
        prompt, consumed = chain.build_prompt(node)
        force = 64 if (inject == 'F_TRUNCATED') else None
        o = transport(model, theta, prompt, creds,
                      force_max_tokens=force)
        if inject == 'F_JSON':
            o = dict(o, answer='[{"fact":"占位",'
                             '"evidence_doc_id":"?"}]',
                     injected='output_replaced')
        chain.set_output(node, o, 'planned')
        clock.add(node, o['latency_s'], 'planned')
        recorded[node] = dict(o, model=model)
    return recorded


def replay_arm(task, docs_text, arm, recorded, transport, creds,
               budget, ledger_path, store=None):
    """One arm over ONE repetition with the SHARED planned outcomes
    injected verbatim (same answer/finish/tokens/latency); only
    recovery actions make real calls."""
    task = _materialize(dict(task, _text=docs_text)) if 'nodes' not in task or not task['nodes'] else task
    runner = ArmRunner(arm, creds, budget, ledger_path,
                       transport=transport, store=store)
    runner.task_id = task['task_id']
    runner.reset_task()
    runner._task_seq += 1

    class SharedChain(DagChain):
        """Replays recorded planned outputs; build_prompt uses the
        same dynamic chaining so downstream consumes identical
        content across arms."""

        def __init__(self, task, docs_text, recorded):
            super().__init__(task, docs_text)
            self.recorded = dict(recorded)

        def build_prompt(self, node):
            p, consumed = super().build_prompt(node)
            self.prompt_meta[node] = consumed
            return p, consumed

    chain = SharedChain(task, docs_text, recorded)
    clock = TaskClock(task['deadline_s'])
    for node in topo_order():
        model = task['planned_pi'][node]
        o = dict(recorded[node])
        # charge the shared planned call to THIS arm's accounting
        runner.records.append(dict(
            node=node, tag='planned', model=model,
            injected=(node == task['fault_node']),
            theta=dict(TUNED_THETA[model]),
            tokens=o['tokens_in'] + o['tokens_out'],
            cash=o['cash_cny'], latency=o['latency_s'],
            service_lat=o['latency_s'], answer=o['answer'],
            finish=o['finish_reason']))
        runner._log(dict(
            task=task['task_id'], node=node, model=model,
            theta={k: v for k, v in TUNED_THETA[model].items()
                   if v},
            tag='planned(shared)', arm=arm,
            finish_reason=o['finish_reason'],
            usage=dict(prompt_tokens=o['tokens_in'],
                       completion_tokens=o['tokens_out']),
            cash_cny=o['cash_cny'], latency_s=o['latency_s'],
            answer=o['answer'], prompt_sha256=None,
            consumed_upstream=chain.prompt_meta.get(node, {}),
            injected=(node == task['fault_node']),
            task_t_s=round(clock.t, 3), deadline_s=clock.D,
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S')))
        budget.settle(o)
        clock.add(node, o['latency_s'], 'planned')
        chain.set_output(node, o, 'planned')
        if not _ok(o):
            if runner._try_local_repair(chain, clock, task,
                                        node, o):
                continue
            if node == 'xc':
                from deadline_reward_v1.full_dag_executor import \
                    diagnose_root
                root, ev, conf = diagnose_root(
                    chain, {task['doc_id']})
                runner.last_diagnosis = dict(
                    root=root, confidence=conf, evidence=ev)
                if root is not None:
                    runner._gate_recover_root(task, chain, clock,
                                              root)
                    continue
            act, m, th = runner._choose_recovery(
                task, clock, node, model, o, set())
            runner._execute_action(task, chain, clock, node,
                                   act, m, th)
    return runner, chain, clock


def drill():
    """Fake-transport proof: planned outputs IDENTICAL across arms
    within a rep; arms diverge only in recovery."""
    import tempfile
    from deadline_reward_v1.full_dag_scoring import settle_task
    from deadline_reward_v1.theta_actions import PriorStore
    silver = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}

    calls = []

    def fake(model_id, theta, prompt, creds,
             force_max_tokens=None):
        calls.append(('recovery-only' if 'RECOVERY' in prompt
                      else 'planned', model_id))
        if force_max_tokens == 64:
            return dict(answer='{"facts":[{"fact":"cut',
                        finish_reason='max_tokens', tokens_in=800,
                        tokens_out=64, cash_cny=0.0, latency_s=8.0)
        if 'fact_extraction' in prompt:
            return dict(answer='[{"fact":"ok",'
                               '"evidence_doc_id":"VDOC"}]',
                        finish_reason='stop', tokens_in=900,
                        tokens_out=200, cash_cny=0.0,
                        latency_s=20.0)
        if 'timeline' in prompt:
            return dict(answer='```json\n[{"date":"2024-01-01",'
                               '"event":"e","evidence":"VDOC"}]'
                               '\n```', finish_reason='stop',
                        tokens_in=700, tokens_out=150,
                        cash_cny=0.0, latency_s=18.0)
        if 'entity_relations' in prompt:
            return dict(answer='[{"entity":"X","role":"r",'
                               '"relation":"y",'
                               '"evidence_doc_id":"VDOC"}]',
                        finish_reason='stop', tokens_in=700,
                        tokens_out=150, cash_cny=0.002,
                        latency_s=12.0)
        return dict(answer='[{"claim":"c","source_a":"VDOC",'
                           '"source_b":"VDOC",'
                           '"verdict":"SUPPORTED"}]',
                    finish_reason='stop', tokens_in=600,
                    tokens_out=120, cash_cny=0.003, latency_s=15.0)

    docs = full_dag_tasks.load_docs()
    with tempfile.TemporaryDirectory() as td:
        # one rep of V01 across the three primary arms
        t0 = dict(VTASKS[0])
        t0['planned_pi'] = dict(fe='GLM-5.3', tl='GLM-5.3',
                                er='deepseek-flash', xc='qwen-plus')
        t0['nodes'] = {}
        text = docs[t0['doc_slot']]['text']
        rec = run_planned_once(t0, text, fake, {}, rep=0)
        answers = {}
        for arm in PRIMARY_ARMS:
            budget = GlobalBudget()
            r, chain, clock = replay_arm(
                t0, text, arm, rec, fake, {}, budget,
                Path(td) / f'{arm}.jsonl')
            planned_answers = tuple(
                (chain.current(n) or {}).get('answer', '')[:50]
                for n in ('fe', 'tl', 'er', 'xc'))
            answers[arm] = planned_answers
        identical = (answers[PRIMARY_ARMS[0]]
                     == answers[PRIMARY_ARMS[1]]
                     == answers[PRIMARY_ARMS[2]])
        print(json.dumps(dict(
            shared_planned_identical_across_arms=identical,
            recovery_calls_made=len(calls)), indent=1))
        print('DRILL:', 'PASS' if identical else 'FAIL')
        return 0 if identical else 2


def run_real():
    import os
    import hashlib
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(
            f'requires {GO_FLAG}=1 (operator authorization)')
    fz = json.loads(FREEZE.read_text())
    for f, sha in fz['freeze_shas'].items():
        now = hashlib.sha256((HERE / f).read_bytes()).hexdigest()
        if now != sha:
            raise PermissionError(f'{f} drifted')
    from deadline_reward_v1.full_dag_executor import load_env_creds
    creds = load_env_creds()
    import deadline_reward_v1.full_dag_executor as ex
    ex.CAPS = dict(attempts=fz['caps']['attempts'],
                   tokens=fz['caps']['tokens'],
                   cash=fz['caps']['cash_cny'],
                   wall=fz['caps']['wall_s'])
    budget = GlobalBudget()
    docs = full_dag_tasks.load_docs()
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'validation_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)
    from deadline_reward_v1.theta_actions import PriorStore
    e_store = PriorStore()
    summary = {}
    try:
        for vt in fz['tasks']:
            task = dict(vt)
            task['planned_pi'] = dict(fe='GLM-5.3',
                                      tl='GLM-5.3',
                                      er='deepseek-flash',
                                      xc='qwen-plus')
            text = docs[task['doc_slot']]['text']
            reps = fz['randomness_controls']['reps']
            for rep in range(reps):
                rec = run_planned_once(task, text, real_call,
                                       creds, rep)
                for arm in fz['arms']:
                    replay_arm(task, text, arm, rec, real_call,
                               creds, budget,
                               run_dir / f'DAG_LEDGER_{arm}_rep{rep}'
                                         '.jsonl')
                # E separate pass (same shared planned outputs, the
                # cross-task e_store, L1/L2 gates evaluated at
                # analysis)
                e_arm = fz['e_arm_separate']['arm']
                replay_arm(task, text, e_arm, rec, real_call,
                           creds, budget,
                           run_dir / f'DAG_LEDGER_{e_arm}_rep{rep}'
                                     '.jsonl', store=e_store)
                summary[f"{task['task_id']}:rep{rep}"] = dict(
                    attempts=budget.attempts,
                    tokens=budget.tokens,
                    cash=round(budget.cash, 4))
                print(json.dumps(summary[
                    f"{task['task_id']}:rep{rep}"]), flush=True)
        (run_dir / 'VALIDATION_RESULTS.json').write_text(
            json.dumps(dict(status='COMPLETE', summary=summary),
                       indent=1, ensure_ascii=False))
        return 0
    except BaseException as exc:
        import traceback as _tb
        (run_dir / 'VALIDATION_INCOMPLETE.json').write_text(
            json.dumps(dict(status='INCOMPLETE',
                            reason=repr(exc),
                            traceback=_tb.format_exc()), indent=1))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill', action='store_true')
    parser.add_argument('--run-real', action='store_true')
    args = parser.parse_args()
    if args.run_real:
        return run_real()
    return drill()


if __name__ == '__main__':
    raise SystemExit(main())
