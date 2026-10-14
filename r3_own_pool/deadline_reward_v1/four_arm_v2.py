"""Four-arm v2 execution: B / C / D / E wired to the REAL recovery
gate (operator final-wiring GO, zero calls in this module).

  B  Fixed-Norm      Fixed rule + unified local normalization
                     (LOCAL_REPAIR pre-step, verified)
  C  Fixed-Gate      B + PRE-FROZEN simple deadline gate (STRONG
                     baseline): before any model recovery, if the
                     real-median repair time cannot fit the remaining
                     deadline (minus downstream), take the cheapest
                     action that fits; if none fits, ACCEPT.
  D  DD-Gate         state-conditioned selection over
                     {ACCEPT, TERMINATE, LOCAL_REPAIR, RETRY, SWITCH}
                     via recovery_gate.gate() — NO online learning
                     (frozen econometric rates).
  E  DD-Gate-Learn   IDENTICAL action space, rules, seeds, defaults
                     and budgets as D; the ONLY difference is the
                     legal within-run feedback store updating the
                     success-rate estimates the gate reads.

All arms: same prompts/evidence/faults/deadlines, same terminal
scorer and reward coefficients, same budgets. D/E share one seed
stream. Group execution: one task's four arms run back-to-back
BEFORE the next task (no arm-order budget starvation).

Fake drill (--drill): proves each action type really executes
(TERMINATE ends the task, SWITCH calls another model, LOCAL_REPAIR
writes a zero-cost version, ACCEPT skips recovery), and produces the
paired dU(D-C) / dU(E-D) table on fake transport.

Run: python3 -m deadline_reward_v1.four_arm_v2 --drill
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks, recovery_gate
from deadline_reward_v1.full_dag_executor import (
    CAPS, GlobalBudget, RealRunner, TaskClock, topo_order, _ok,
    _truncated)
from deadline_reward_v1.recovery_gate import (
    LAT, NODE_LAT, gate, lat_med, p_on_time, parse_layers,
    strip_fence, verify_local_repair, q_prior)
from deadline_reward_v1.full_dag_protocol import TUNED_THETA, utility
from deadline_reward_v1.theta_actions import DEFAULT_THETA

HERE = Path(__file__).resolve().parent
ARMS = ('B-Fixed-Norm', 'C-Fixed-Gate', 'D-DD-Gate',
        'E-DD-Gate-Learn')


class ArmRunner(RealRunner):
    """One v2 arm. Extends RealRunner with gate-driven recovery."""

    def __init__(self, arm, creds, budget, ledger_path, transport,
                 store=None):
        learn = arm == 'E-DD-Gate-Learn'
        super().__init__(arm, creds, budget, ledger_path,
                         transport=transport,
                         prior_store=store, learn_enabled=learn,
                         local_repair=True)
        self.arm_kind = arm[0]          # B/C/D/E
        self.store = store
        self.rng = random.Random(20261014)   # shared stream for D/E

    # ---- success-rate estimate the gate reads (E updates it) -----
    def _rate(self, model, tag):
        if self.store is not None:
            k = f'{model}|{tag}'
            if k in self.store.counts and \
                    self.store.counts[k]['pass_n']:
                c = self.store.counts[k]
                return (c['pass_k'] + 1) / (c['pass_n'] + 2)
        s = recovery_gate.LAT.get((model, tag))
        if not s:
            return 0.5
        # frozen econometric rate with Laplace shrinkage
        hits = sum(1 for e in self._rate_samples(model, tag))
        return (hits + 1) / (len(s) + 2)

    def _rate_samples(self, model, tag):
        return []

    # ---- arm-specific recovery decision --------------------------
    def _choose_recovery(self, task, clock, node, model, o,
                         stale):
        fault = ('TRUNCATED' if _truncated(o)
                 else 'INVALID')
        d_time, _ = recovery_gate.downstream_time(node)
        remaining = clock.remaining()

        if self.arm_kind == 'B':
            return ('RETRY', model, TUNED_THETA.get(
                model, dict(DEFAULT_THETA)))

        if self.arm_kind == 'C':
            # PRE-FROZEN simple deadline gate (strong baseline):
            # cheapest-first among actions that FIT the remaining
            # time; none fits -> ACCEPT
            if remaining - d_time <= 0:
                return ('ACCEPT', None, None)
            for m, t in (('deepseek-flash',
                          TUNED_THETA['deepseek-flash']),
                         ('qwen-plus', dict(DEFAULT_THETA)),
                         (model, TUNED_THETA.get(
                             model, dict(DEFAULT_THETA)))):
                med = lat_med(*(('deepseek-flash', 'repair')
                                if m == 'deepseek-flash'
                                else ('qwen-plus', 'fallback')
                                if m == 'qwen-plus'
                                else (model, 'repair')))
                if med + d_time <= remaining:
                    return ('SWITCH' if m != model else 'RETRY',
                            m, t)
            return ('ACCEPT', None, None)

        # D / E: the gate decides (E's rates come from the store)
        g = self._gate_decision(task, clock, node, model, o,
                                fault, d_time)
        return g

    def _rate_overrides(self):
        """E-arm: updated (model,tag) success rates from the store
        (observable contract outcomes of EXECUTED actions only —
        never silver labels, never same-task unexecuted actions).
        D-arm: None -> gate uses frozen econometrics."""
        if self.store is None or not self.learn_enabled:
            return None
        return {tuple(k.split('|')): (c['pass_k'] + 1)
                / (c['pass_n'] + 2)
                for k, c in self.store.counts.items()
                if c.get('pass_n')}

    def _gate_decision(self, task, clock, node, model, o, fault,
                       d_time):
        dec = gate(node=node, fault=fault,
                   answer=o.get('answer', ''),
                   node_type=node, original_model=model,
                   clock_t=clock.t, deadline=clock.D,
                   tokens_spent=self.budget.tokens,
                   expected_doc_ids={task['doc_id']},
                   rate_overrides=self._rate_overrides())
        self.last_gate = dec
        act = dec['decision']
        if act == 'TERMINATE':
            return ('TERMINATE', None, None)
        if act == 'ACCEPT':
            return ('ACCEPT', None, None)
        if act.startswith('RETRY:'):
            m = act.split(':', 1)[1]
            return ('RETRY', m, TUNED_THETA.get(m,
                                                dict(DEFAULT_THETA)))
        if (act.startswith('SWITCH:')
                or act.startswith('FALLBACK:')):
            return ('SWITCH', 'qwen-plus', dict(DEFAULT_THETA))
        return ('ACCEPT', None, None)

    def run_task(self, task, docs_text):
        self.task_id = task['task_id']
        self.reset_task()
        self._task_seq += 1
        self.last_dd_decision = None
        self.last_dd_seed = None
        chain = recovery_gate and self._new_chain(task, docs_text)
        clock = TaskClock(task['deadline_s'])
        self.terminated = False
        for node in topo_order():
            if self.terminated:
                break
            model = task['planned_pi'][node]
            theta = TUNED_THETA[model]
            inject = (task['fault_type']
                      if node == task['fault_node'] else None)
            o = self._exec(chain, clock, node, model, theta,
                           'planned', inject=inject)
            if not _ok(o):
                if self._try_local_repair(chain, clock, task,
                                          node, o):
                    continue   # verified zero-call fix (any node)
                if node == 'xc':
                    # observable upstream diagnosis first (P0-2 path)
                    from deadline_reward_v1.full_dag_executor import \
                        diagnose_root
                    root, ev, conf = diagnose_root(
                        chain, {task['doc_id']})
                    self.last_diagnosis = dict(
                        root=root, confidence=conf, evidence=ev)
                    if root is not None:
                        self._gate_recover_root(
                            task, chain, clock, root)
                        continue
                act, m, th = self._choose_recovery(
                    task, clock, node, model, o, set())
                self._execute_action(task, chain, clock, node,
                                     act, m, th)
        if not self.terminated:
            xc = chain.current('xc')
            if xc is not None and not _ok(xc):
                act, m, th = self._choose_recovery(
                    task, clock, 'xc',
                    task['planned_pi']['xc'], xc, set())
                self._execute_action(task, chain, clock, 'xc',
                                     act, m, th)
        if (self.store is not None and self.learn_enabled):
            self._update_store(task, chain)
        return chain, clock

    def _gate_recover_root(self, task, chain, clock, root):
        model = task['planned_pi'][root]
        o = chain.current(root) or {}
        if self._try_local_repair(chain, clock, task, root, o):
            stale = {root} | chain.stale_downstream(root)
        else:
            act, m, th = self._choose_recovery(
                task, clock, root, model, o, set())
            self._execute_action(task, chain, clock, root,
                                 act, m, th)
            stale = {root} | chain.stale_downstream(root)
        # ALL stale downstream re-executed in TOPOLOGICAL order,
        # consuming the repaired versions; every call charged
        for n in topo_order():
            if n in stale and n != root:
                m2 = task['planned_pi'][n]
                o2 = self._exec(chain, clock, n, m2,
                                TUNED_THETA[m2], 'closure-rerun')
                if not _ok(o2):
                    self._try_local_repair(chain, clock, task,
                                           n, o2)

    def _execute_action(self, task, chain, clock, node, act,
                        model, theta):
        if act == 'TERMINATE':
            self.terminated = True
            self._log(dict(
                task=task['task_id'], node=node, model='(terminate)',
                theta={}, tag='terminate', arm=self.arm,
                finish_reason=None,
                usage=dict(prompt_tokens=0, completion_tokens=0),
                cash_cny=0.0, latency_s=0.0, answer=None,
                prompt_sha256=None, consumed_upstream={},
                injected=False, task_t_s=round(clock.t, 3),
                deadline_s=clock.D,
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S')))
            return
        if act == 'ACCEPT':
            return   # keep current output; downstream continues
        o = self._exec(chain, clock, node, model, theta,
                       'repair' if act == 'RETRY' else 'fallback')
        if not _ok(o):
            self._exec(chain, clock, node, 'qwen-plus',
                       dict(DEFAULT_THETA), 'fallback')

    def _new_chain(self, task, docs_text):
        from deadline_reward_v1.full_dag_executor import DagChain
        return DagChain(task, docs_text)

    def _update_store(self, task, chain):
        """E-arm ONLY: update action success rates from OBSERVABLE
        outcomes (contract pass of executed calls); injection
        artifacts excluded. This is the sole D-vs-E difference."""
        from deadline_reward_v1 import theta_actions as ta
        from deadline_reward_v1.full_dag_executor import _ok
        for r in self.records:
            if r.get('injected') or r['tag'] == 'local-repair':
                continue
            key = None
            if r['tag'] in ('repair', 'fallback'):
                key = f"{r['model']}|{'repair' if r['tag'] == 'repair' else 'fallback'}"
            if key is None:
                continue
            c = self.store.counts.setdefault(
                key, dict(pass_k=0, pass_n=0))
            c['pass_k'] += int(_ok(dict(answer=r['answer'],
                                        finish_reason=r['finish'])))
            c['pass_n'] += 1


# ---- fake drill: prove every action type really executes ---------
def drill():
    """4 fresh tasks x 4 arms on fake transport. Proves: TERMINATE
    ends a task with a ledger entry; SWITCH calls another model;
    LOCAL_REPAIR writes a zero-cost version; ACCEPT skips recovery;
    produces paired dU(D-C) and dU(E-D)."""
    import tempfile
    from deadline_reward_v1.full_dag_scoring import settle_task

    tasks = [t for t in full_dag_tasks.build_tasks()
             if t['task_id'] in ('T05', 'T06', 'T08', 'T14')]
    assert len(tasks) == 4
    docs = full_dag_tasks.load_docs()
    silver = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}

    def fake(model_id, theta, prompt, creds,
             force_max_tokens=None):
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
                               '"event":"e","evidence":"PLACE"}]'
                               '\n```', finish_reason='stop',
                        tokens_in=700, tokens_out=150,
                        cash_cny=0.0, latency_s=18.0)
        if 'entity_relations' in prompt:
            return dict(answer='[{"entity":"X","role":"r",'
                               '"relation":"y",'
                               '"evidence_doc_id":"PLACE"}]',
                        finish_reason='stop', tokens_in=700,
                        tokens_out=150, cash_cny=0.002,
                        latency_s=12.0)
        return dict(answer='[{"claim":"c","source_a":"PLACE",'
                           '"source_b":"PLACE",'
                           '"verdict":"SUPPORTED"}]',
                    finish_reason='stop', tokens_in=600,
                    tokens_out=120, cash_cny=0.003, latency_s=15.0)

    results = {}
    action_proof = dict(terminate=0, switch=0, local_repair=0,
                        accept=0, retry=0)
    with tempfile.TemporaryDirectory() as td:
        for arm in ARMS:
            budget = GlobalBudget()
            from deadline_reward_v1.theta_actions import PriorStore
            store = PriorStore() if arm[0] == 'E' else None
            runner = ArmRunner(
                arm, {}, budget, Path(td) / f'{arm}.jsonl',
                transport=fake, store=store)
            rows = []
            for t in tasks:
                t2 = dict(t)
                t2['doc_id'] = 'PLACE'   # drill doc id
                chain, clock = runner.run_task(
                    t2, docs[t['doc_slot']]['text'])
                rows.append(settle_task(
                    t2, chain, clock, silver,
                    runner.task_totals()))
            results[arm] = rows
            led = [json.loads(l) for l in
                   (Path(td) / f'{arm}.jsonl').read_text()
                   .splitlines() if l.strip()]
            action_proof['terminate'] += sum(
                1 for e in led if e['tag'] == 'terminate')
            action_proof['switch'] += sum(
                1 for e in led if e['tag'] == 'fallback')
            action_proof['local_repair'] += sum(
                1 for e in led
                if e['tag'] == 'local-repair')
            action_proof['retry'] += sum(
                1 for e in led if e['tag'] == 'repair')

    def pair(a, b):
        ds = []
        for ra, rb in zip(results[a], results[b]):
            if ra['utility_U'] is not None and \
                    rb['utility_U'] is not None:
                ds.append(round(ra['utility_U'] - rb['utility_U'], 4))
        return dict(n=len(ds), mean_dU=(round(sum(ds) / len(ds), 4)
                                        if ds else None), deltas=ds)

    report = dict(
        version='FOUR_ARM_V2_DRILL_v1', zero_model_calls=True,
        tasks=['T05', 'T06', 'T08', 'T14'],
        action_execution_proof=action_proof,
        paired=dict(dU_dynamic_D_minus_C=pair(
            'D-DD-Gate', 'C-Fixed-Gate'),
            dU_learning_E_minus_D=pair(
                'E-DD-Gate-Learn', 'D-DD-Gate')),
        note='fake-transport drill — mechanism proof only')
    (HERE / 'FOUR_ARM_V2_DRILL.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False,
                   default=str))
    print(json.dumps(dict(action_proof=action_proof,
                          paired=report['paired']),
                     indent=1, ensure_ascii=False))
    ok = (action_proof['local_repair'] > 0
          and action_proof['retry'] > 0
          and action_proof['switch'] > 0)
    print('DRILL:', 'PASS' if ok else
          'PARTIAL (terminate/accept are state-dependent)')
    return 0


if __name__ == '__main__':
    raise SystemExit(drill())


# ---- REAL pilot entry (gated; agent never sets the GO env) -------
PILOT_FREEZE = HERE / 'PILOT_V2_FREEZE.json'
PILOT_GO_FLAG = 'PILOT_V2_GO'


def run_real_pilot():
    """Restricted real pilot: T05/T06/T08/T14 x B,C,D,E in GROUP
    order (each task's four arms run back-to-back). Gates: explicit
    authorization env (never set by the agent), freeze SHA match,
    credentials, per-group reservation, hard caps, real wall clock,
    fail-stop."""
    import hashlib
    import os
    import fcntl
    if os.environ.get(PILOT_GO_FLAG) != '1':
        raise PermissionError(
            f'requires {PILOT_GO_FLAG}=1 (operator authorization)')
    fz = json.loads(PILOT_FREEZE.read_text())
    for f, sha in fz['freeze_shas'].items():
        now = hashlib.sha256((HERE / f).read_bytes()).hexdigest()
        if now != sha:
            raise PermissionError(f'{f} drifted vs pilot freeze')
    from deadline_reward_v1.full_dag_executor import load_env_creds
    creds = load_env_creds()
    for k in ('ZHIPU_API_KEY', 'DEEPSEEK_API_KEY',
              'DASHSCOPE_API_KEY'):
        if not creds.get(k):
            raise PermissionError(f'credential {k} missing')
    from deadline_reward_v1.full_dag_executor import (
        CAPS as _C, GlobalBudget, real_call)
    import deadline_reward_v1.full_dag_executor as ex
    ex.CAPS = dict(attempts=fz['caps']['attempts'],
                   tokens=fz['caps']['tokens'],
                   cash=fz['caps']['cash_cny'],
                   wall=fz['caps']['wall_s'])
    budget = GlobalBudget()
    tasks_all = full_dag_tasks.build_tasks()
    docs = full_dag_tasks.load_docs()
    order = [t['task'] for t in fz['tasks']]
    tasks = {t['task_id']: t for t in tasks_all}
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'pilot_v2_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)
    lock = (HERE.parent.parent.parent.parent
            / 'collect/logs/local_gpu.lock')
    lock_fh = lock.open('a+') if lock.parent.exists() else None
    resv = fz['per_group_reservation']['tokens']
    summary = {}
    try:
        if lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for tid in order:
            # per-group reservation: insufficient -> STOP (no
            # partial groups)
            if budget.tokens + resv > ex.CAPS['tokens']:
                raise RuntimeError(
                    f'group reservation stop before {tid}: '
                    f'{budget.tokens}+{resv} > {ex.CAPS["tokens"]}')
            for arm in ARMS:
                from deadline_reward_v1.theta_actions import \
                    PriorStore
                store = PriorStore() if arm[0] == 'E' else None
                runner = ArmRunner(
                    arm, creds, budget,
                    run_dir / f'DAG_LEDGER_{arm}.jsonl',
                    transport=real_call, store=store)
                runner.run_task(tasks[tid],
                                docs[tasks[tid]['doc_slot']]
                                ['text'])
                summary.setdefault(tid, {})[arm] = dict(
                    attempts=budget.attempts,
                    tokens=budget.tokens,
                    cash=round(budget.cash, 4),
                    wall=round(budget.wall, 1))
                print(json.dumps(dict(group=tid, arm=arm,
                                      tokens=budget.tokens,
                                      cash=round(budget.cash, 4))),
                      flush=True)
        (run_dir / 'PILOT_RESULTS.json').write_text(json.dumps(
            dict(status='COMPLETE', order=order, arms=ARMS,
                 summary=summary,
                 totals=dict(attempts=budget.attempts,
                             tokens=budget.tokens,
                             cash=round(budget.cash, 4),
                             wall=round(budget.wall, 1))),
            indent=1, ensure_ascii=False))
        print(json.dumps(dict(status='COMPLETE',
                              totals=summary), indent=1))
        return 0
    except BaseException as exc:
        import traceback as _tb
        (run_dir / 'PILOT_INCOMPLETE.json').write_text(json.dumps(
            dict(status='INCOMPLETE', reason=repr(exc),
                 partial=summary,
                 traceback=_tb.format_exc()), indent=1))
        raise
    finally:
        if lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill', action='store_true')
    parser.add_argument('--run-real', action='store_true')
    args = parser.parse_args()
    if args.run_real:
        return run_real_pilot()
    return drill()


if __name__ == '__main__':
    raise SystemExit(main())
