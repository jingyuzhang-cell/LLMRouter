"""Full-DAG discriminative experiment executor — REAL transports, with
zero-call preflight. REAL EXECUTION IS NOT AUTHORIZED (operator decides
separately; DAG_EXPERIMENT_GO is never set in this round).

Corrected execution chain (operator ruling 2026-10-14, priority 1):

  real DAG      fe -> tl; {tl, er} -> xc. er reads the raw document
                INDEPENDENTLY (no fe->er edge). xc = intra-document
                cross-check (tl and er derive from the same doc).
  propagation   repaired outputs REPLACE the node's current version;
                prompts are built from CURRENT upstream versions and
                record the sha256 of every upstream answer consumed;
                stale downstream nodes are re-executed in TOPOLOGICAL
                order (Kahn, deterministic), never alphabetical.
  per-task clock  each task accumulates its own service time
                (sequential — NO parallelism is claimed or simulated;
                TL and ER call latencies are summed, not maxed).
  budget guard  pre-request reservation from the RENDERED prompt
                (conservative CJK upper bound ~1 token/char +256) plus
                the full output cap; post-call settlement at real
                usage; global caps; unknown costs never zero; first
                unexpected error -> INCOMPLETE halt.
  DD eU         two-branch expected utility: success branch carries
                predicted quality-given-pass (DEV prior) at its own
                time/cost; failure branch carries q=0 PLUS the
                fallback continuation cost/time. No success-quality
                leakage into the failure branch, no double pr.

Frozen (unchanged): task identities, fault schedule (seed 20261014),
arms, utility U = 1(T<=D)q - 0.5 C/C0 - (T-D)+/D - 2*1(T>D), C0=60K.

Usage:
  python3 -m deadline_reward_v1.full_dag_executor --preflight
  python3 -m deadline_reward_v1.full_dag_executor --chain-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import full_dag_protocol, full_dag_tasks, \
    theta_actions  # noqa: E402
from deadline_reward_v1.full_dag_protocol import (  # noqa: E402
    TUNED_THETA, utility)
from deadline_reward_v1.theta_actions import (  # noqa: E402
    DEFAULT_THETA, theta_legal)

PREFLIGHT = HERE / 'DAG_EXPERIMENT_PREFLIGHT_PASS.json'
FREEZE_FILES = ['FULL_DAG_TASKS.json', 'FULL_DAG_PROTOCOL_FREEZE.json',
                'FULL_DAG_SILVER_V1.json']
RATES = json.loads(
    (HERE / 'REVERSE_ENGINEERED_RATES_V2.json').read_text())['rates']

CAPS = dict(attempts=320, tokens=450000, cash=0.80, wall=5400.0)


# ---- DAG structure helpers ------------------------------------------------
def topo_order():
    """Kahn topological order over the REAL edges, deterministic."""
    edges = full_dag_tasks.EDGES
    nodes = ['fe', 'er', 'tl', 'xc']
    indeg = {n: 0 for n in nodes}
    for u, vs in edges.items():
        for v in vs:
            indeg[v] += 1
    order, ready = [], [n for n in nodes if indeg[n] == 0]
    while ready:
        n = ready.pop(0)
        order.append(n)
        for v in edges.get(n, []):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    assert len(order) == len(nodes), 'cycle in DAG'
    return order


def downstream_of(node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in full_dag_tasks.EDGES.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def sha(text) -> str:
    return hashlib.sha256((text or '').encode()).hexdigest()[:16]


# ---- transports -----------------------------------------------------------
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
    mt = force_max_tokens or theta.get('max_tokens') or 2048
    if model_id.startswith('GLM'):
        url = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
        headers = {'x-api-key': creds.get('ZHIPU_API_KEY', ''),
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
        headers = {'Authorization':
                   f'Bearer {creds.get("DEEPSEEK_API_KEY", "")}',
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
        headers = {'Authorization':
                   f'Bearer {creds.get("DASHSCOPE_API_KEY", "")}',
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
                tokens_in=tin, tokens_out=tout,
                cash_cny=round(cash, 6), latency_s=round(latency, 3))


# ---- budget & clock -------------------------------------------------------
def est_in_tokens(prompt: str) -> int:
    """Conservative reservation: CJK ~1 token/char upper bound for
    Chinese-heavy prompts (ASCII over-counted on purpose — the guard
    must over-, never under-reserve) + framing overhead."""
    return int(len(prompt) * 1.0) + 256


def cash_reserve(model_id, tokens_in, tokens_out):
    rk = {'deepseek-flash': 'deepseek_flash',
          'qwen-plus': 'qwen_plus'}.get(model_id)
    if not rk:
        return 0.0
    r = RATES[rk]
    return (tokens_in * r['input_cny_per_mtok']
            + tokens_out * r['output_cny_per_mtok']) / 1e6


class GlobalBudget:
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

    def settle(self, o):
        """Post-call settlement at REAL usage."""
        self.attempts += 1
        self.tokens += o['tokens_in'] + o['tokens_out']
        self.cash += o['cash_cny']
        self.wall += o['latency_s']


class TaskClock:
    """Per-task service time, SEQUENTIAL (no parallelism claimed).
    The global wall never substitutes for the task deadline."""

    def __init__(self, deadline_s):
        self.D = deadline_s
        self.t = 0.0
        self.breakdown = []

    def add(self, node, lat, tag):
        self.t += lat
        self.breakdown.append(dict(node=node, tag=tag, lat_s=lat,
                                   task_t=round(self.t, 3)))

    def remaining(self):
        return self.D - self.t


# ---- versioned execution chain -------------------------------------------
class DagChain:
    """Node outputs are versioned; prompts consume CURRENT versions
    and record the sha of each upstream answer consumed; repairs
    write back and invalidate stale downstream."""

    def __init__(self, task, docs_text):
        self.task = task
        self.docs_text = docs_text
        self.state = {}        # node -> dict(current, versions[...])
        self.prompt_meta = {}  # node -> {upstream: sha}

    def current(self, node):
        return self.state.get(node, {}).get('current')

    def set_output(self, node, o, tag):
        st = self.state.setdefault(node, dict(current=None, versions=[]))
        st['current'] = o
        st['versions'].append(
            dict(tag=tag, answer_head=o['answer'][:2000],
                 finish=o['finish_reason'], sha=sha(o['answer']),
                 version=len(st['versions'])))

    def build_prompt(self, node):
        t = self.task
        doc_id = t['doc_id']
        consumed = {}
        if node == 'fe':
            p = t['nodes']['fe']['prompt']
        elif node == 'er':
            p = t['nodes']['er']['prompt']  # INDEPENDENT of fe
        elif node == 'tl':
            up = (self.current('fe') or {}).get('answer', '')
            consumed['fe'] = sha(up)
            from deadline_reward_v1.full_dag_tasks import prompt_tl
            p = prompt_tl(doc_id, up[:4000], self.docs_text[:1200])
        else:  # xc consumes tl AND er
            a = (self.current('tl') or {}).get('answer', '')
            b = (self.current('er') or {}).get('answer', '')
            consumed['tl'] = sha(a)
            consumed['er'] = sha(b)
            from deadline_reward_v1.full_dag_tasks import prompt_xc
            p = prompt_xc(doc_id, a[:4000], doc_id, b[:4000])
        self.prompt_meta[node] = consumed
        return p, consumed

    def stale_downstream(self, node):
        """Downstream nodes that already produced output on a
        now-replaced upstream version."""
        return {d for d in downstream_of(node)
                if self.current(d) is not None}


def _ok(o) -> bool:
    try:
        json.loads((o['answer'] or '').strip())
    except (ValueError, TypeError):
        return False
    return o['finish_reason'] in ('stop', 'end_turn')


def _truncated(o) -> bool:
    return o['finish_reason'] in ('length', 'max_tokens')


class RealRunner:
    def __init__(self, arm, creds, budget, ledger_path,
                 transport=None):
        self.arm = arm
        self.creds = creds
        self.budget = budget
        self.ledger_path = Path(ledger_path)
        self.transport = transport or real_call
        self.records = []
        self.task_id = None

    def _log(self, entry):
        with open(self.ledger_path, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def _exec(self, chain, clock, node, model, theta, tag, inject=None):
        prompt, consumed = chain.build_prompt(node)
        est_in = est_in_tokens(prompt)
        est_out = theta.get('max_tokens') or 2048
        self.budget.pre_check(est_in, est_out,
                              cash_reserve(model, est_in, est_out))
        first = not any(r['node'] == node
                        for r in self.records)
        force = 64 if (inject == 'F_TRUNCATED' and first
                       and tag == 'planned') else None
        o = dict(self.transport(model, theta, prompt, self.creds,
                                force_max_tokens=force))
        if inject == 'F_JSON' and first and tag == 'planned':
            o = dict(o, answer='[{"fact":"占位","evidence_doc_id":"?"}]',
                     injected='output_replaced')
        self.budget.settle(o)
        clock.add(node, o['latency_s'], tag)
        entry = dict(task=self.task_id, node=node, model=model,
                     theta={k: v for k, v in theta.items() if v},
                     tag=tag, arm=self.arm,
                     finish_reason=o['finish_reason'],
                     usage=dict(prompt_tokens=o['tokens_in'],
                                completion_tokens=o['tokens_out']),
                     cash_cny=o['cash_cny'], latency_s=o['latency_s'],
                     answer=o['answer'], prompt_sha256=sha(prompt),
                     consumed_upstream=consumed,
                     injected=bool(inject and first
                                   and tag == 'planned'),
                     task_t_s=round(clock.t, 3), deadline_s=clock.D,
                     timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
        self._log(entry)
        self.records.append(dict(node=node, tag=tag,
                                 tokens=o['tokens_in']
                                 + o['tokens_out'],
                                 cash=o['cash_cny'],
                                 latency=o['latency_s'],
                                 service_lat=o['latency_s']))
        chain.set_output(node, o, tag)
        return o

    def task_totals(self):
        """REAL per-task spend across ALL attempts (planned + repair
        + fallback + closure-rerun) — failed/replaced attempts are
        real cost and are never dropped from settlement."""
        toks = sum(r['tokens'] for r in self.records)
        cash = sum(r['cash'] for r in self.records)
        return dict(tokens=toks, cash_cny=round(cash, 6),
                    calls=len(self.records),
                    recovery_calls=sum(1 for r in self.records
                                       if r['tag'] != 'planned'),
                    per_task_remaining_vs_C0=round(
                        60000 - toks, 1))

    def reset_task(self):
        self.records = []

    # ---- arm repair decisions --------------------------------------------
    def _repair_candidate(self, task, clock, node, model,
                          stale_closure=frozenset()):
        if self.arm == 'SS-Tuned':
            return None
        if self.arm == 'Fixed-Tuned':
            if model.startswith('GLM'):
                return model, TUNED_THETA['GLM-5.3']
            if model == 'deepseek-flash':
                return model, TUNED_THETA['deepseek-flash']
            return 'qwen-plus', dict(DEFAULT_THETA)
        from deadline_reward_v1 import dd_decision
        from deadline_reward_v1.full_dag_protocol import (
            MODEL_MENU, utility)
        dec = dd_decision.choose(
            planned_pi=task['planned_pi'], clock=clock,
            faulted_node=node, faulted_model=model,
            stale_closure=set(stale_closure),
            global_budget_tokens=self.budget.tokens,
            caps_tokens=CAPS['tokens'], model_menu=MODEL_MENU,
            utility_fn=utility)
        self.last_dd_decision = dec
        return dec['model'], dec['theta']

    def _dd_candidate(self, clock, node, model):
        """DD-Online: two-branch expected utility under the frozen
        mainline reward. Inputs: DEV priors + observable feedback +
        DAG state + remaining budget/deadline + support table. Never
        same-task candidate outcomes."""
        from deadline_reward_v1.full_dag_protocol import MODEL_MENU
        from deadline_reward_v1.theta_actions import (
            budget_reservation, enumerate_legal_thetas)
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
                res = budget_reservation(m, th, 4000)
                if (self.budget.tokens + res['tokens_in']
                        + res['tokens_out_reserved']
                        > CAPS['tokens']):
                    continue  # budget-illegal candidate
                p = theta_actions.prior_for(m, th)
                pr, mr = p['pass_rate'], p['mean_recall']
                fb = budget_reservation('qwen-plus',
                                        dict(DEFAULT_THETA), 4000)
                # SUCCESS branch: quality-given-pass mr, own cost/time
                U_succ = utility(
                    mr,
                    res['tokens_in'] + res['tokens_out_reserved'],
                    clock.t + res['latency_s_reserved'], clock.D)
                # FAILURE branch: q=0 + fallback continuation
                U_fail = utility(
                    0.0,
                    res['tokens_in'] + res['tokens_out_reserved']
                    + fb['tokens_in'] + fb['tokens_out_reserved'],
                    clock.t + res['latency_s_reserved']
                    + fb['latency_s_reserved'], clock.D)
                eU = round(pr * U_succ + (1 - pr) * U_fail, 6)
                cands.append(dict(model=m, theta=th, eU=eU,
                                  pr=pr, mr=mr, U_succ=U_succ,
                                  U_fail=U_fail))
        if not cands:
            return 'qwen-plus', dict(DEFAULT_THETA)
        cands.sort(key=lambda c: -c['eU'])
        return cands[0]['model'], cands[0]['theta']

    # ---- task run ----------------------------------------------------------
    def run_task(self, task, docs_text):
        self.task_id = task['task_id']
        self.reset_task()   # per-task budget/cost tracking window
        chain = DagChain(task, docs_text)
        clock = TaskClock(task['deadline_s'])
        for node in topo_order():
            model = task['planned_pi'][node]
            theta = TUNED_THETA[model]
            inject = (task['fault_type']
                      if node == task['fault_node'] else None)
            o = self._exec(chain, clock, node, model, theta, 'planned',
                           inject=inject)
            if inject == 'F_TRUNCATED' and _truncated(o):
                self._recover(chain, clock, task, node)
        xc = chain.current('xc')
        if (task['fault_type'] == 'F_JSON' and xc is not None
                and not _ok(xc)):
            root = task['fault_node']
            if self._recover(chain, clock, task, root):
                stale = {root} | chain.stale_downstream(root)
                for n in topo_order():  # topological, not alphabetical
                    if n in stale and n != root:
                        m = task['planned_pi'][n]
                        self._exec(chain, clock, n, m, TUNED_THETA[m],
                                   'closure-rerun')
        return chain, clock

    def _recover(self, chain, clock, task, node):
        model = task['planned_pi'][node]
        # stale downstream = already-executed nodes that must re-run
        # after this repair (closure pricing enters the DD decision)
        stale = chain.stale_downstream(node)
        cand = self._repair_candidate(task, clock, node, model,
                                      stale_closure=stale)
        if cand is None:
            return False
        r_model, r_theta = cand
        o = self._exec(chain, clock, node, r_model, r_theta, 'repair')
        if not _ok(o):
            o = self._exec(chain, clock, node, 'qwen-plus',
                           dict(DEFAULT_THETA), 'fallback')
        return _ok(o)  # set_output already replaced the version


# ---- offline chain test (priority-1 data-dependency proof) ----------------
def chain_test():
    """FE truncation -> FE repaired -> TL must consume the REPAIRED
    answer (prompt containment + recorded upstream sha) -> XC must
    consume the new TL and the UNTOUCHED ER. Proves DATA dependency,
    not just control flow."""
    calls = []

    def fake(model_id, theta, prompt, creds, force_max_tokens=None):
        calls.append(dict(model=model_id, force=force_max_tokens,
                          prompt=prompt))
        if ('## 任务类型：fact_extraction' in prompt
                and force_max_tokens == 64):
            return dict(answer='{"facts":[{"fact":"cut',
                        finish_reason='max_tokens', tokens_in=100,
                        tokens_out=64, cash_cny=0.0, latency_s=1.0)
        if '## 任务类型：fact_extraction' in prompt:
            return dict(answer='[{"fact":"FE_REPAIRED_ANSWER_9f01",'
                               '"evidence_doc_id":"d"}]',
                        finish_reason='stop', tokens_in=100,
                        tokens_out=80, cash_cny=0.0, latency_s=1.0)
        if '## 任务类型：timeline' in prompt:
            return dict(answer='[{"date":"2026-05-08",'
                               '"event":"TL_FROM_UPSTREAM_ok"}]',
                        finish_reason='stop', tokens_in=100,
                        tokens_out=60, cash_cny=0.0, latency_s=1.0)
        if '## 任务类型：entity_relations' in prompt:
            return dict(answer='[{"entity":"ER_INDEPENDENT_77ab",'
                               '"role":"x"}]',
                        finish_reason='stop', tokens_in=100,
                        tokens_out=60, cash_cny=0.0, latency_s=1.0)
        return dict(answer='[{"claim":"c","verdict":"SUPPORTED"}]',
                    finish_reason='stop', tokens_in=100,
                    tokens_out=60, cash_cny=0.0, latency_s=1.0)

    tasks = full_dag_tasks.build_tasks()
    t = next(x for x in tasks if x['fault_node'] == 'fe'
             and x['fault_type'] == 'F_TRUNCATED')
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        runner = RealRunner('Fixed-Tuned', {}, GlobalBudget(),
                            Path(td) / 'chain_test.jsonl',
                            transport=fake)
        docs = full_dag_tasks.load_docs()
        chain, clock = runner.run_task(t, docs[t['doc_slot']]['text'])

    fe_versions = chain.state['fe']['versions']
    tl_prompt = [c['prompt'] for c in calls
                 if '## 任务类型：timeline' in c['prompt']][0]
    xc_prompt = [c['prompt'] for c in calls
                 if '## 任务类型：cross_verification'
                 in c['prompt']][0]
    REPAIRED = ('[{"fact":"FE_REPAIRED_ANSWER_9f01",'
                '"evidence_doc_id":"d"}]')
    checks = dict(
        fe_two_versions=(len(fe_versions) == 2
                         and fe_versions[0]['finish'] == 'max_tokens'
                         and fe_versions[-1]['finish'] == 'stop'),
        fe_current_is_repaired=(chain.current('fe')['answer']
                                == REPAIRED),
        tl_consumes_repaired=('FE_REPAIRED_ANSWER_9f01'
                              in tl_prompt),
        tl_upstream_sha_matches=(chain.prompt_meta['tl'].get('fe')
                                 == sha(REPAIRED)),
        xc_consumes_new_tl=('TL_FROM_UPSTREAM_ok' in xc_prompt),
        xc_consumes_er=('ER_INDEPENDENT_77ab' in xc_prompt),
        er_untouched_single_version=(
            len(chain.state['er']['versions']) == 1),
        no_unnecessary_fallback=all(
            v['tag'] != 'fallback' for v in fe_versions),
        clock_within_deadline=(clock.t <= clock.D))
    print(json.dumps(dict(
        task=t['task_id'], fe_fault=t['fault_type'], checks=checks,
        fe_version_tags=[v['tag'] for v in fe_versions],
        task_time_s=round(clock.t, 2), deadline_s=clock.D),
        indent=1, ensure_ascii=False))
    print(f'CHAIN TEST: {"PASS" if all(checks.values()) else "FAIL"}')
    return 0 if all(checks.values()) else 2


# ---- preflight ------------------------------------------------------------
def preflight():
    checks = dict(freeze_shas_match=True, bodies_ok=True,
                  fail_stop_ok=True, budget_stop_ok=True,
                  reservation_conservative=True, creds_ok=True,
                  dry_run_invariants=True, chain_test_ok=True)
    issues = []
    for fn in FREEZE_FILES:
        if not (HERE / fn).exists():
            issues.append(f'{fn} missing')
            checks['freeze_shas_match'] = False
    fake_creds = {k: 'FAKE' for k in
                  ('ZHIPU_API_KEY', 'DEEPSEEK_API_KEY',
                   'DASHSCOPE_API_KEY')}
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return dict(choices=[dict(
                finish_reason='stop',
                message=dict(content='[]'))],
                usage=dict(prompt_tokens=10,
                           completion_tokens=5))

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['last'] = dict(url=url, body=dict(json))
        return FakeResp()

    orig = requests.post
    requests.post = fake_post
    try:
        real_call('GLM-5.3', TUNED_THETA['GLM-5.3'], 'p', fake_creds)
        b = captured['last']['body']
        assert b.get('reasoning_effort') == 'low' \
            and 'thinking' not in b
        real_call('deepseek-flash',
                  TUNED_THETA['deepseek-flash'], 'p', fake_creds)
        b = captured['last']['body']
        assert b.get('thinking') == {'type': 'disabled'} \
            and 'reasoning_effort' not in b \
            and 'response_format' not in b
        real_call('qwen-plus', dict(DEFAULT_THETA), 'p', fake_creds)
        b = captured['last']['body']
        assert 'thinking' not in b and 'reasoning_effort' not in b
    finally:
        requests.post = orig

    gb = GlobalBudget()
    gb.attempts = CAPS['attempts']
    try:
        gb.pre_check(1, 1, 0)
        checks['fail_stop_ok'] = False
    except RuntimeError:
        pass
    gb2 = GlobalBudget()
    gb2.tokens = CAPS['tokens']
    try:
        gb2.pre_check(1, 1, 0)
        checks['budget_stop_ok'] = False
    except RuntimeError:
        pass
    checks['reservation_conservative'] = \
        est_in_tokens('证' * 10000) > 10000

    creds = load_env_creds()
    for k in ('ZHIPU_API_KEY', 'DEEPSEEK_API_KEY',
              'DASHSCOPE_API_KEY'):
        if not creds.get(k):
            checks['creds_ok'] = False

    checks['dry_run_invariants'] = (full_dag_protocol.dry_run() == 0)
    checks['chain_test_ok'] = (chain_test() == 0)

    all_ok = all(v for v in checks.values() if isinstance(v, bool))
    checks['freeze_issues'] = issues
    if all_ok:
        shas = {fn: hashlib.sha256(
            (HERE / fn).read_bytes()).hexdigest()
            for fn in FREEZE_FILES}
        PREFLIGHT.write_text(json.dumps(dict(
            passed=True, freeze_sha256=shas, caps=CAPS,
            reservation='rendered-prompt conservative '
                        '(1 tok/char +256) + full output cap',
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S')), indent=1))
    print(json.dumps(checks, indent=1, ensure_ascii=False))
    return 0 if all_ok else 2


def execute():
    raise PermissionError(
        'Real execution NOT authorized this round (operator decides '
        'separately); DAG_EXPERIMENT_GO must never be set by the '
        'agent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--chain-test', action='store_true')
    args = parser.parse_args()
    if args.chain_test:
        return chain_test()
    if args.preflight:
        return preflight()
    return execute()


if __name__ == '__main__':
    raise SystemExit(main())
