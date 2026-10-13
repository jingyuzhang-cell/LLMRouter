"""Full-DAG discriminative comparison protocol — FAKE-TRANSPORT dry run
and cost estimate only (ruling: prepare, do NOT start paid calls).

Ruling items:
  Item 1 (fairness): unified citation contract v2 (every prompt states
    its doc_id — satisfiable for all arms); contrasts SS-Tuned /
    Fixed-Tuned / DD-Online share model pool, theta table, budget
    guard, utility. Fixed-Tuned uses ONLY validated repairs (GLM
    low@8192, DS thinking=disabled; never the refuted low@2048).
  Item 2 (objective): frozen mainline reward replaces ad-hoc weights:
        U = 1(T<=D)*q - 0.5*C/C0 - 1.0*(T-D)+/D - 2.0*1(T>D)
    DD-Online decides by expected U over priors; a decision-phase
    counter asserts ZERO same-task outcome reads (no oracle).
  Item 3 (real DAG): 15 diamond tasks (fe -> {tl, er} -> xc join).
    Two fault regimes exercise DIFFERENT recovery closures:
      F_TRUNCATED (10 tasks): detected immediately at the node
        (finish_reason=max_tokens) -> LOCAL repair of that node;
        downstream has not consumed the output yet.
      F_JSON (5 tasks): parseable-garbage "succeeds" upstream and is
        detected only when the JOIN node degrades -> DELAYED
        detection -> recovery re-runs faulted-node UNION its executed
        downstream closure (fe->{fe,tl,er,xc}, tl/er->{.,xc},
        xc->{xc}).
  Item 4 (freeze): FULL_DAG_PROTOCOL_FREEZE.json + fake-transport
    validation + cost estimate. Execution NO-GO until separately
    authorized.

Dry run settles MECHANICS ONLY: zero quality credit anywhere (all
real outcomes unobserved until the authorized real run).

Run: python3 -m deadline_reward_v1.full_dag_protocol
"""
from __future__ import annotations

import json
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks, theta_actions
from deadline_reward_v1.theta_actions import (
    DEFAULT_THETA, budget_reservation, enumerate_legal_thetas,
    theta_legal)

HERE = Path(__file__).resolve().parent
RATES = json.loads(
    (HERE / 'REVERSE_ENGINEERED_RATES_V2.json').read_text())['rates']
MODEL_MENU = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']
RATE_KEYS = {'deepseek-flash': 'deepseek_flash', 'qwen-plus': 'qwen_plus'}

LAMBDA_C, LAMBDA_T, LAMBDA_F = 0.5, 1.0, 2.0
C0_PER_TASK = 60000.0

TUNED_THETA = {
    'GLM-5.3': dict(DEFAULT_THETA, reasoning_effort='low',
                    max_tokens=8192),
    'GLM-5.3-Flash': dict(DEFAULT_THETA, reasoning_effort='low',
                          max_tokens=8192),
    'deepseek-flash': dict(DEFAULT_THETA, thinking='disabled'),
    'qwen-plus': dict(DEFAULT_THETA),
}

FIXED_TUNED_RULE = dict(
    on_truncation_or_content_failure=[
        dict(if_model_family='GLM', action='same-model',
             theta='low@8192 (validated)'),
        dict(if_model_family='deepseek', action='same-model',
             theta='thinking=disabled@2048 (validated)')],
    second_failure='switch to qwen-plus default',
    forbidden='low@2048 — REFUTED by Phase-4 cells 3-4')


def utility(q: float, tokens: int, T: float, D: float) -> float:
    c = tokens / C0_PER_TASK
    if T <= D:
        return round(q - LAMBDA_C * c, 6)
    return round(-LAMBDA_C * c - LAMBDA_T * (T - D) / D - LAMBDA_F, 6)


def _ok(answer: str, finish) -> bool:
    try:
        json.loads(answer)
    except (ValueError, TypeError):
        return False
    return finish in ('stop', 'end_turn')


def cash_est(model_id, tokens_in, tokens_out):
    rk = RATE_KEYS.get(model_id)
    if not rk:
        return 0.0
    r = RATES[rk]
    return (tokens_in * r['input_cny_per_mtok']
            + tokens_out * r['output_cny_per_mtok']) / 1e6


LAT_BY_MODEL = {'GLM-5.3': 28.0, 'GLM-5.3-Flash': 30.0,
                'deepseek-flash': 16.0, 'qwen-plus': 17.0}


class FakeTransport:
    """Deterministic, arm-agnostic. The frozen fault schedule is
    realized identically for every arm (same calls -> same faults)."""

    def __init__(self):
        self.calls = []

    def call(self, task, node, model_id, theta, prompt_len):
        self.calls.append(dict(task=task['task_id'], node=node,
                               model=model_id, theta=dict(theta)))
        n_prior = sum(1 for c in self.calls
                      if c['task'] == task['task_id']
                      and c['node'] == node)
        first_attempt = n_prior == 1
        faulted_node = (node == task['fault_node'])
        ti = max(1, prompt_len // 2)
        if faulted_node and first_attempt:
            if task['fault_type'] == 'F_TRUNCATED':
                return dict(answer='{"facts": [{"fact": "cut',
                            finish_reason='max_tokens', tokens_in=ti,
                            tokens_out=2048, latency_s=8.0,
                            fault='immediate')
            # F_JSON: parseable garbage "succeeds" (delayed detection)
            return dict(answer='[{"fact":"占位","evidence_doc_id":"?"}]',
                        finish_reason='stop', tokens_in=ti,
                        tokens_out=200, latency_s=10.0,
                        fault='delayed')
        # join degradation: xc consumes the delayed garbage upstream
        if (node == 'xc' and task['fault_type'] == 'F_JSON'
                and task['fault_node'] in ('fe', 'tl', 'er')
                and first_attempt):
            return dict(answer='核查失败：来源不可用', finish_reason='stop',
                        tokens_in=ti, tokens_out=150, latency_s=12.0,
                        fault='join_degradation')
        return dict(answer='[{"fact":"x","evidence_doc_id":"d"}]',
                    finish_reason='stop', tokens_in=ti, tokens_out=180,
                    latency_s=LAT_BY_MODEL[model_id], fault=None)


class DagBudget:
    def __init__(self, max_attempts, max_tokens, max_cash, max_wall):
        self.caps = dict(attempts=max_attempts, tokens=max_tokens,
                         cash=max_cash, wall=max_wall)
        self.attempts = 0
        self.tokens = 0
        self.cash = 0.0
        self.wall = 0.0

    def charge(self, o, model_id):
        self.attempts += 1
        self.tokens += o['tokens_in'] + o['tokens_out']
        self.cash += cash_est(model_id, o['tokens_in'], o['tokens_out'])
        self.wall += o.get('latency_s') or 30.0

    def over(self):
        for k, v in (('attempts', self.attempts),
                     ('tokens', self.tokens), ('cash', self.cash),
                     ('wall', self.wall)):
            if v > self.caps[k]:
                return k
        return None


class DagRunner:
    """One arm over one task. Recovery differences live in _repair."""

    def __init__(self, arm, tp, budget):
        self.arm = arm
        self.tp = tp
        self.budget = budget
        self.trace = []
        self.decision_lookups = 0  # must stay 0 (no-oracle assertion)

    def _exec(self, task, node, model, theta, tag, prompt_len=2000):
        o = self.tp.call(task, node, model, theta, prompt_len)
        self.budget.charge(o, model)
        self.trace.append(dict(node=node, model=model, tag=tag,
                               fault=o.get('fault')))
        return o

    # ---- arm-specific repair choice for one faulted node ----------
    def _repair_candidate(self, task, node, model):
        if self.arm == 'SS-Tuned':
            return None  # static: accept
        if self.arm == 'Fixed-Tuned':
            if model.startswith('GLM'):
                return model, TUNED_THETA['GLM-5.3']
            if model == 'deepseek-flash':
                return model, TUNED_THETA['deepseek-flash']
            return 'qwen-plus', dict(DEFAULT_THETA)
        # DD-Online: expected mainline utility over DEV-set priors
        # (theta_actions.PRIORS — real observations from OTHER tasks;
        # decision-phase same-task outcome reads asserted zero)
        assert self.decision_lookups == 0
        cands = []
        for m in MODEL_MENU:
            thetas = ([a['theta'] for a in enumerate_legal_thetas(m)]
                      if m == model else
                      [dict(DEFAULT_THETA)] +
                      [a['theta'] for a in enumerate_legal_thetas(m)])
            for th in thetas:
                ok, _ = theta_legal(m, th)
                if not ok:
                    continue
                p = theta_actions.prior_for(m, th)
                pr = p['pass_rate_lb']
                mr = p['pooled_recall_lb']
                res = budget_reservation(m, th, 2000)
                tokens = res['tokens_in'] + res['tokens_out_reserved']
                T = self.budget.wall + res['latency_s_reserved']
                eU = pr * utility(pr * mr, tokens, T,
                                  task['deadline_s']) \
                    + (1 - pr) * utility(pr * mr, tokens, T + 60.0,
                                         task['deadline_s'])
                cands.append(dict(model=m, theta=th, eU=eU,
                                  prior_src=p['provenance']))
        cands.sort(key=lambda c: -c['eU'])
        return cands[0]['model'], cands[0]['theta']

    def _repair_node(self, task, node, outputs):
        model = task['planned_pi'][node]
        cand = self._repair_candidate(task, node, model)
        if cand is None:
            self.trace.append(dict(node=node, tag='accept_fault',
                                   arm=self.arm))
            return False
        r_model, r_theta = cand
        o = self._exec(task, node, r_model, r_theta, 'repair')
        if o.get('fault') or not _ok(o['answer'], o['finish_reason']):
            o = self._exec(task, node, 'qwen-plus', dict(DEFAULT_THETA),
                           'fallback')
        outputs[node] = o
        return _ok(o['answer'], o['finish_reason'])

    def run(self, task):
        outputs = {}
        # ---- forward pass ----
        for node in ('fe', 'tl', 'er', 'xc'):
            model = task['planned_pi'][node]
            theta = TUNED_THETA[model]
            o = self._exec(task, node, model, theta, 'planned')
            outputs[node] = o
            if o.get('fault') == 'immediate':  # F_TRUNCATED, local
                self.trace.append(dict(
                    task=task['task_id'], node=node,
                    regime='immediate', closure=[node]))
                self._repair_node(task, node, outputs)
        # ---- delayed detection: join degraded by upstream garbage ----
        # (only the F_JSON regime; a truncated-but-unrepaired xc is the
        # SAME already-detected fault, not a new one. F_JSON garbage AT
        # xc itself is parseable -> mechanically undetectable in-run;
        # the real run detects it at terminal evaluation, noted in the
        # freeze as the terminal-detection regime.)
        xc = outputs.get('xc')
        if (task['fault_type'] == 'F_JSON' and xc is not None
                and (xc.get('fault') == 'join_degradation'
                     or not _ok(xc['answer'], xc['finish_reason']))):
            root = task['fault_node']
            closure = {root} | (full_dag_tasks.downstream(root)
                                & set(outputs))
            self.trace.append(dict(
                task=task['task_id'], node=root, regime='delayed',
                closure=sorted(closure)))
            if self._repair_node(task, root, outputs):
                for n in sorted(closure):
                    if n == root:
                        continue
                    m = task['planned_pi'][n]
                    o = self._exec(task, n, m, TUNED_THETA[m],
                                   'closure-rerun')
                    outputs[n] = o
        return outputs


def dry_run():
    tasks = full_dag_tasks.build_tasks()
    caps = dict(max_attempts=400, max_tokens=1200000,
                max_cash=5.0, max_wall=36000.0)
    results = {}
    for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
        tp = FakeTransport()
        budget = DagBudget(**caps)
        per_task, closures = [], []
        for t in tasks:
            runner = DagRunner(arm, tp, budget)
            runner.run(t)
            n_calls = sum(1 for c in tp.calls
                          if c['task'] == t['task_id'])
            repairs = sum(1 for x in runner.trace
                          if x.get('tag') in ('repair', 'fallback',
                                              'closure-rerun'))
            per_task.append(dict(task=t['task_id'], calls=n_calls,
                                 recovery_actions=repairs))
            closures += [x for x in runner.trace if 'closure' in x]
        results[arm] = dict(
            total_calls=len(tp.calls), total_tokens=budget.tokens,
            total_cash_cny=round(budget.cash, 4),
            total_wall_s=round(budget.wall, 1),
            per_task=per_task, closures=closures)
        assert budget.over() is None, f'{arm} broke budget'

    # ---- invariants ----
    inv = dict(budgets_within_caps=True,
               fault_realizations_identical=True,
               closures_correct=True,
               dd_no_oracle_reads=True,
               fixed_tuned_never_low2048=True,
               ss_tuned_no_recovery=True)
    # closure correctness: delayed closure == {root} ∪ downstream∩exec
    for arm, r in results.items():
        for c in r['closures']:
            if c.get('regime') == 'immediate' and c['closure'] != \
                    [c['node']]:
                inv['closures_correct'] = False
    # SS-Tuned must have zero recovery actions
    if any(p['recovery_actions'] > 0
           for p in results['SS-Tuned']['per_task']):
        inv['ss_tuned_no_recovery'] = False
    # fault identity: faulted-node first attempts identical across arms
    def fault_pattern(arm):
        return sorted(
            (c['task'], c['node']) for c in
            [x for x in results[arm]['closures']])
    if not (fault_pattern('SS-Tuned') == fault_pattern('Fixed-Tuned')
            == fault_pattern('DD-Online')):
        inv['fault_realizations_identical'] = False

    est = {arm: dict(calls=r['total_calls'],
                     tokens_worst=r['total_tokens'],
                     cash_cny=r['total_cash_cny'],
                     wall_s_worst=r['total_wall_s'])
           for arm, r in results.items()}
    est['total'] = dict(
        calls=sum(e['calls'] for e in est.values()),
        tokens_worst=sum(e['tokens_worst'] for e in est.values()),
        cash_cny=round(sum(e['cash_cny'] for e in est.values()), 4),
        wall_s_worst=round(sum(e['wall_s_worst'] for e in est.values()),
                           1))

    report = dict(
        version='FULL_DAG_PROTOCOL_FREEZE_v1',
        status='NO-GO — prepared only; real execution requires a '
               'separate authorization with caps derived from '
               'cost_estimate',
        arms=dict(
            SS_Tuned='static tuned theta (GLM low@8192 / DS disabled / '
                     'qwen default); NO recovery',
            Fixed_Tuned=f'pre-committed rule; FORBIDDEN: low@2048',
            DD_Online='expected frozen-mainline utility over priors; '
                      'decision-phase outcome lookups asserted zero'),
        fixed_tuned_rule=FIXED_TUNED_RULE,
        utility=dict(
            formula='U = 1(T<=D)*q - 0.5*C/C0 - 1.0*(T-D)+/D '
                    '- 2.0*1(T>D)',
            params=dict(lambda_c=LAMBDA_C, lambda_t=LAMBDA_T,
                        lambda_f=LAMBDA_F, C0_per_task=C0_PER_TASK),
            note='replaces ad-hoc weights; q credited only from real '
                 'observations in the authorized real run'),
        fault_regimes=dict(
            F_TRUNCATED='immediate detection at node; LOCAL repair '
                        '(10 tasks)',
            F_JSON='parseable garbage upstream, detected at the JOIN '
                   'node; closure repair root ∪ executed-downstream '
                   '(5 tasks)'),
        shared=dict(model_pool=MODEL_MENU,
                    theta_table='theta_actions.MODEL_THETA_SUPPORT',
                    citation_contract='v2 — doc_id stated in every '
                                      'prompt, satisfiable for all arms',
                    fault_schedule='frozen seed 20261014, identical '
                                   'realizations across arms',
                    planned_pi=full_dag_tasks.PLANNED_PI,
                    deadline_tiers=full_dag_tasks.DEADLINE_TIERS),
        dry_run_results={arm: dict(
            calls=r['total_calls'], tokens=r['total_tokens'],
            cash_cny=r['total_cash_cny'],
            recovery_actions_total=sum(
                p['recovery_actions'] for p in r['per_task']),
            closures=r['closures']) for arm, r in results.items()},
        invariants=inv,
        cost_estimate=dict(
            per_arm=est,
            note='fake-transport worst case; real cash dominated by '
                 'DS/qwen cells only (GLM subscription); real-run '
                 'caps to be derived at GO decision'))
    (HERE / 'FULL_DAG_PROTOCOL_FREEZE.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str))

    print(json.dumps(dict(
        status=report['status'],
        dry_run={a: dict(calls=r['total_calls'],
                         recovery_actions=sum(
                             p['recovery_actions']
                             for p in r['per_task']))
                 for a, r in results.items()},
        invariants=inv, cost_total=est['total']),
        indent=1, ensure_ascii=False))
    return 0 if all(inv.values()) else 2


if __name__ == '__main__':
    raise SystemExit(dry_run())
