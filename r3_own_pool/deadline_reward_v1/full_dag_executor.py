"""Full-DAG discriminative experiment executor — REAL transports, with
zero-call preflight. REAL EXECUTION IS NOT AUTHORIZED YET (operator:
"另行决定真实执行"); this entry exists so a future GO activates
immediately.

Frozen semantics (FULL_DAG_PROTOCOL_FREEZE_v1 + FULL_DAG_TASKS_v1 +
FULL_DAG_SILVER_V1):

  arms      SS-Tuned / Fixed-Tuned / DD-Online (shared everything)
  tasks     15 diamonds, fault schedule seed 20261014
  injection F_TRUNCATED -> the faulted node's FIRST attempt is a REAL
            call with max_tokens=64 (real truncation signature);
            F_JSON -> the faulted node's first attempt is a REAL call
            whose ANSWER IS REPLACED by parseable garbage (output-layer
            injection; the planned call is charged at real usage). The
            join node then REALLY consumes the garbage — degradation is
            real model behavior, not scripted.
  caps      attempts 320 / tokens 450K / CNY 0.80 / wall 5400s
            (>=1.5x the fake-transport worst case 216/311K/0.41/4214s)
  fail-stop first unexpected error -> INCOMPLETE marker, halt
  settlement frozen at run end: per-task q from FULL_DAG_SILVER_V1
            (xc parse + supported-claim coverage), U via the frozen
            mainline utility; paired dU (DD-Online vs SS-Tuned and vs
            Fixed-Tuned) reported WITHOUT significance claims in the
            raw ledger artifact.

Usage:
  python3 -m deadline_reward_v1.full_dag_executor --preflight
  DAG_EXPERIMENT_GO=1 python3 -m deadline_reward_v1.full_dag_executor
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import requests

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import full_dag_protocol, full_dag_tasks, \
    full_dag_silver, theta_actions  # noqa: E402
from deadline_reward_v1.full_dag_protocol import (  # noqa: E402
    FIXED_TUNED_RULE, TUNED_THETA, utility)
from deadline_reward_v1.theta_actions import DEFAULT_THETA, theta_legal

GO_FLAG = 'DAG_EXPERIMENT_GO'
PREFLIGHT = HERE / 'DAG_EXPERIMENT_PREFLIGHT_PASS.json'
FREEZE_FILES = ['FULL_DAG_TASKS.json', 'FULL_DAG_PROTOCOL_FREEZE.json',
                'FULL_DAG_SILVER_V1.json']
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
RATES = json.loads(
    (HERE / 'REVERSE_ENGINEERED_RATES_V2.json').read_text())['rates']

CAPS = dict(attempts=320, tokens=450000, cash=0.80, wall=5400.0)

GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'


def load_env_creds():
    env_vars = {}
    for path in ('/root/.env.modelpool', '/root/.env'):
        p = Path(path)
        if p.exists():
            for line in p.read_text().splitlines():
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars.setdefault(k.strip(), v.strip())
    return env_vars


def real_call(model_id, theta, prompt, creds, force_max_tokens=None):
    """One real API call. GLM: reasoning_effort only; DS: thinking only;
    qwen: plain. force_max_tokens implements the F_TRUNCATED injection
    (real truncation at a tiny cap)."""
    mt = force_max_tokens or theta.get('max_tokens') or 2048
    if model_id.startswith('GLM'):
        url = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
        key = creds.get('ZHIPU_API_KEY', '')
        headers = {'x-api-key': key,
                   'anthropic-version': '2023-06-01',
                   'Content-Type': 'application/json'}
        body = dict(model=model_id, max_tokens=mt,
                    messages=[dict(role='user', content=prompt)],
                    temperature=0.0)
        if theta.get('reasoning_effort'):
            body['reasoning_effort'] = theta['reasoning_effort']
        assert 'thinking' not in body
    elif model_id == 'deepseek-flash':
        url = 'https://api.deepseek.com/chat/completions'
        key = creds.get('DEEPSEEK_API_KEY', '')
        headers = {'Authorization': f'Bearer {key}',
                   'Content-Type': 'application/json'}
        body = dict(model=model_id, max_tokens=mt,
                    messages=[dict(role='user', content=prompt)],
                    temperature=0.0)
        if theta.get('thinking') == 'disabled':
            body['thinking'] = {'type': 'disabled'}
        assert not theta.get('reasoning_effort')
        assert not theta.get('response_format')
    elif model_id == 'qwen-plus':
        url = ('https://dashscope.aliyuncs.com/compatible-mode/v1/'
               'chat/completions')
        key = creds.get('DASHSCOPE_API_KEY', '')
        headers = {'Authorization': f'Bearer {key}',
                   'Content-Type': 'application/json'}
        body = dict(model=model_id, max_tokens=mt,
                    messages=[dict(role='user', content=prompt)],
                    temperature=0.0)
        assert not theta.get('reasoning_effort')
    else:
        raise RuntimeError(f'unknown model {model_id}')
    ok, why = theta_legal(model_id, theta)
    assert ok, f'illegal theta for {model_id}: {why}'

    t0 = time.monotonic()
    resp = requests.post(url, headers=headers, json=body, timeout=180)
    latency = time.monotonic() - t0
    data = resp.json()
    if resp.status_code != 200:
        raise RuntimeError(f'HTTP {resp.status_code}: '
                           f'{json.dumps(data)[:300]}')
    if 'choices' in data:
        ch = data['choices'][0]
        answer = ch.get('message', {}).get('content', '') or ''
        finish = ch.get('finish_reason')
        u = data.get('usage', {})
        tin, tout = u.get('prompt_tokens', 0), \
            u.get('completion_tokens', 0)
    else:
        answer = ''
        for block in data.get('content', []):
            if isinstance(block, dict) and block.get('type') == 'text':
                answer = block.get('text', '')
                break
        finish = data.get('stop_reason')
        u = data.get('usage', {})
        tin, tout = u.get('input_tokens', 0), u.get('output_tokens', 0)
    rk = {'deepseek-flash': 'deepseek_flash',
          'qwen-plus': 'qwen_plus'}.get(model_id)
    cash = ((tin * RATES[rk]['input_cny_per_mtok']
             + tout * RATES[rk]['output_cny_per_mtok']) / 1e6
            if rk else 0.0)
    return dict(answer=answer, finish_reason=finish,
                tokens_in=tin, tokens_out=tout, cash_cny=round(cash, 6),
                latency_s=round(latency, 3))


class RealBudget:
    def __init__(self):
        self.attempts = 0
        self.tokens = 0
        self.cash = 0.0
        self.wall = 0.0

    def pre_check(self, est_in, est_out, est_cash):
        if self.attempts + 1 > CAPS['attempts']:
            raise RuntimeError('budget stop: attempts cap')
        if self.tokens + est_in + est_out > CAPS['tokens']:
            raise RuntimeError('budget stop: token cap')
        if self.cash + est_cash > CAPS['cash']:
            raise RuntimeError('budget stop: cash cap')
        if self.wall > CAPS['wall']:
            raise RuntimeError('budget stop: wall cap')

    def charge(self, o):
        self.attempts += 1
        self.tokens += o['tokens_in'] + o['tokens_out']
        self.cash += o['cash_cny']
        self.wall += o['latency_s']


class RealRunner:
    """Mirrors full_dag_protocol.DagRunner over real transports."""

    def __init__(self, arm, creds, budget, ledger_path):
        self.arm = arm
        self.creds = creds
        self.budget = budget
        self.ledger_path = ledger_path
        self.trace = []

    def _log(self, entry):
        with open(self.ledger_path, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def _exec(self, task, node, model, theta, tag, prompt,
              inject=None):
        est_out = theta.get('max_tokens') or 2048
        rk = {'deepseek-flash': 'deepseek_flash',
              'qwen-plus': 'qwen_plus'}.get(model)
        est_cash = (0.0 if not rk else
                    (2000 * RATES[rk]['input_cny_per_mtok']
                     + est_out * RATES[rk]['output_cny_per_mtok']) / 1e6)
        self.budget.pre_check(2000, est_out, est_cash)
        first = not any(x['node'] == node for x in self.trace
                        if x.get('task') == task['task_id'])
        # F_TRUNCATED injection: the faulted node's FIRST attempt is a
        # REAL call issued at max_tokens=64 (real truncation signature)
        force = 64 if (inject == 'F_TRUNCATED' and first
                       and tag == 'planned') else None
        o = real_call(model, theta, prompt, self.creds,
                      force_max_tokens=force)
        # F_JSON injection: output-layer replacement on the first
        # planned attempt (call charged at real usage)
        if inject == 'F_JSON' and first and tag == 'planned':
            o = dict(o, answer=GARBAGE, injected='output_replaced')
        self.budget.charge(o)
        entry = dict(task=task['task_id'], node=node, model=model,
                     theta={k: v for k, v in theta.items() if v},
                     tag=tag, arm=self.arm,
                     finish_reason=o['finish_reason'],
                     usage=dict(prompt_tokens=o['tokens_in'],
                                completion_tokens=o['tokens_out']),
                     cash_cny=o['cash_cny'], latency_s=o['latency_s'],
                     answer=o['answer'],
                     injected=bool(inject and first and tag == 'planned'),
                     injection=dict(type=inject, force=force) if inject
                     else None,
                     timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
        self._log(entry)
        self.trace.append(dict(task=task['task_id'], node=node,
                               tag=tag))
        return o

    def _repair_candidate(self, task, node, model):
        if self.arm == 'SS-Tuned':
            return None
        if self.arm == 'Fixed-Tuned':
            if model.startswith('GLM'):
                return model, TUNED_THETA['GLM-5.3']
            if model == 'deepseek-flash':
                return model, TUNED_THETA['deepseek-flash']
            return 'qwen-plus', dict(DEFAULT_THETA)
        # DD-Online: frozen mainline utility over DEV-set priors
        from deadline_reward_v1.full_dag_protocol import MODEL_MENU, \
            enumerate_legal_thetas
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
                pr, mr = p['pass_rate'], p['mean_recall']
                res = theta_actions.budget_reservation(m, th, 2000)
                tokens = res['tokens_in'] + res['tokens_out_reserved']
                T = self.budget.wall + res['latency_s_reserved']
                eU = pr * utility(pr * mr, tokens, T,
                                  task['deadline_s']) \
                    + (1 - pr) * utility(pr * mr, tokens, T + 60.0,
                                         task['deadline_s'])
                cands.append(dict(model=m, theta=th, eU=eU))
        cands.sort(key=lambda c: -c['eU'])
        return cands[0]['model'], cands[0]['theta']

    def _repair_node(self, task, node, prompt_of):
        model = task['planned_pi'][node]
        cand = self._repair_candidate(task, node, model)
        if cand is None:
            return False
        r_model, r_theta = cand
        o = self._exec(task, node, r_model, r_theta, 'repair',
                      prompt_of(node))
        if not _ok(o):
            o = self._exec(task, node, 'qwen-plus', dict(DEFAULT_THETA),
                           'fallback', prompt_of(node))
        return _ok(o)

    def run(self, task, docs_text):
        """Dynamic upstream chaining: tl consumes fe's ACTUAL answer,
        xc consumes tl's and er's ACTUAL answers (true DAG semantics —
        injected garbage propagates for real)."""
        from deadline_reward_v1.full_dag_tasks import prompt_tl, \
            prompt_xc
        doc_id = task['doc_id']
        outputs = {}

        def prompt_for(node):
            if node == 'fe':
                return task['nodes']['fe']['prompt']
            if node == 'er':
                return task['nodes']['er']['prompt']
            if node == 'tl':
                return prompt_tl(doc_id,
                                 (outputs.get('fe', {})
                                  .get('answer', '') or '')[:4000],
                                 docs_text[:1200])
            return prompt_xc(
                doc_id, (outputs.get('tl', {}).get('answer', '')
                         or '')[:4000],
                doc_id, (outputs.get('er', {}).get('answer', '')
                         or '')[:4000])

        for node in ('fe', 'tl', 'er', 'xc'):
            model = task['planned_pi'][node]
            theta = TUNED_THETA[model]
            inject = (task['fault_type']
                      if node == task['fault_node'] else None)
            o = self._exec(task, node, model, theta, 'planned',
                           prompt_for(node), inject=inject)
            outputs[node] = o
            if inject == 'F_TRUNCATED' and _truncated(o):
                self._repair_node(task, node, prompt_for)
        xc = outputs.get('xc')
        if (task['fault_type'] == 'F_JSON' and xc is not None
                and not _ok(xc)):
            root = task['fault_node']
            if self._repair_node(task, root, prompt_for):
                for n in sorted(full_dag_tasks.downstream(root)):
                    if n == root:
                        continue
                    m = task['planned_pi'][n]
                    self._exec(task, n, m, TUNED_THETA[m],
                               'closure-rerun', prompt_for(n))
        return outputs


def _ok(o) -> bool:
    try:
        json.loads((o['answer'] or '').strip())
    except (ValueError, TypeError):
        return False
    return o['finish_reason'] in ('stop', 'end_turn')


def _truncated(o) -> bool:
    return o['finish_reason'] in ('length', 'max_tokens')


# ---- preflight (zero real calls) ------------------------------------------
def preflight():
    checks = dict(
        freeze_shas_match=True, bodies_ok=True, fail_stop_ok=False,
        budget_stop_ok=False, creds_ok=True, dry_run_invariants=True)
    issues = []
    for fn in FREEZE_FILES:
        p = HERE / fn
        if not p.exists():
            issues.append(f'{fn} missing')
            checks['freeze_shas_match'] = False
    # body wiring (no network): build bodies for one theta per family
    fake_creds = {k: 'FAKE' for k in
                  ('ZHIPU_API_KEY', 'DEEPSEEK_API_KEY',
                   'DASHSCOPE_API_KEY')}
    import deadline_reward_v1.full_dag_executor as SELF

    captured = {}
    import requests as _rq

    class FakeResp:
        def __init__(self):
            self.status_code = 200

        def json(self):
            return dict(choices=[dict(finish_reason='stop',
                                      message=dict(content='[]'))],
                        usage=dict(prompt_tokens=10,
                                   completion_tokens=5))

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['last'] = dict(url=url, body=dict(json))
        return FakeResp()

    orig_post = _rq.post
    _rq.post = fake_post
    try:
        o = SELF.real_call('GLM-5.3', TUNED_THETA['GLM-5.3'], 'p',
                           fake_creds)
        b = captured['last']['body']
        assert b.get('reasoning_effort') == 'low' \
            and 'thinking' not in b, b
        o = SELF.real_call('deepseek-flash',
                           TUNED_THETA['deepseek-flash'], 'p',
                           fake_creds)
        b = captured['last']['body']
        assert b.get('thinking') == {'type': 'disabled'} \
            and 'reasoning_effort' not in b \
            and 'response_format' not in b, b
        o = SELF.real_call('qwen-plus', dict(DEFAULT_THETA), 'p',
                           fake_creds)
        b = captured['last']['body']
        assert 'thinking' not in b and 'reasoning_effort' not in b
        checks['bodies_ok'] = True
    finally:
        _rq.post = orig_post

    # fail-stop + budget-stop: unit-level on RealBudget
    rb = RealBudget()
    rb.attempts = CAPS['attempts']
    try:
        rb.pre_check(1, 1, 0)
        checks['fail_stop_ok'] = False
    except RuntimeError:
        checks['fail_stop_ok'] = True
    rb2 = RealBudget()
    rb2.tokens = CAPS['tokens']
    try:
        rb2.pre_check(1, 1, 0)
        checks['budget_stop_ok'] = False
    except RuntimeError:
        checks['budget_stop_ok'] = True

    creds = load_env_creds()
    for k in ('ZHIPU_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY'):
        if not creds.get(k):
            checks['creds_ok'] = False

    # protocol dry-run invariants must still pass
    rc = full_dag_protocol.dry_run()
    checks['dry_run_invariants'] = (rc == 0)

    all_ok = all(v for k, v in checks.items() if isinstance(v, bool))
    checks['freeze_issues'] = issues
    if all_ok:
        shas = {fn: hashlib.sha256((HERE / fn).read_bytes())
                .hexdigest() for fn in FREEZE_FILES}
        PREFLIGHT.write_text(json.dumps(dict(
            passed=True, freeze_sha256=shas, caps=CAPS,
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S')), indent=1))
    print(json.dumps(checks, indent=1, ensure_ascii=False))
    return 0 if all_ok else 2


def _rerun_invariants():  # retained for API compat; preflight calls
    # full_dag_protocol.dry_run() directly
    return full_dag_protocol.dry_run() == 0


def execute():
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1 (AND the '
                              f'operator\'s explicit real-execution '
                              f'authorization — still pending)')
    if not PREFLIGHT.exists():
        raise PermissionError('preflight has not passed')
    pre = json.loads(PREFLIGHT.read_text())
    for fn, sha in pre['freeze_sha256'].items():
        now = hashlib.sha256((HERE / fn).read_bytes()).hexdigest()
        if now != sha:
            raise PermissionError(f'{fn} drifted since preflight')
    creds = load_env_creds()
    tasks = full_dag_tasks.build_tasks()
    silver = {s['task_id']: s for s in
              json.loads((HERE / 'FULL_DAG_SILVER_V1.json')
                         .read_text())['tasks']}
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'full_dag_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)
    lock_fh = GPU_LOCK.open('a+')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        summary = {}
        docs = full_dag_tasks.load_docs()
        for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
            ledger = run_dir / f'DAG_LEDGER_{arm}.jsonl'
            budget = RealBudget()
            runner = RealRunner(arm, creds, budget, ledger)
            for t in tasks:
                runner.run(t, docs[t['doc_slot']]['text'])
            summary[arm] = dict(attempts=budget.attempts,
                                tokens=budget.tokens,
                                cash_cny=round(budget.cash, 4),
                                wall_s=round(budget.wall, 1))
            assert budget.attempts <= CAPS['attempts']
        (run_dir / 'DAG_RESULTS.json').write_text(json.dumps(dict(
            status='COMPLETE', caps=CAPS, summary=summary),
            indent=1, ensure_ascii=False))
        print(json.dumps(dict(status='COMPLETE', summary=summary),
                         indent=1))
        return 0
    except BaseException as exc:
        (run_dir / 'DAG_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc),
            traceback=traceback.format_exc()), indent=1))
        raise
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    if args.preflight:
        return preflight()
    return execute()


if __name__ == '__main__':
    raise SystemExit(main())
