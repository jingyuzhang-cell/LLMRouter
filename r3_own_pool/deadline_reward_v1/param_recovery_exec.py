"""Phase-4 parameter-recovery executor — 8 frozen cells, FE3/FE4 only.

Operator conditional GO (2026-10-13): preflight (zero-call fake
transport) must verify parameter wiring, budget guards and fail-stop;
once preflight passes the authorization auto-activates — real run
requires PARAM_RECOVERY_GO=1 plus the PREFLIGHT_PASS.json artifact.

Frozen cells (PARAM_RECOVERY_FREEZE_v1), execution order chosen to
maximize surviving information under fail-stop (deepseek's thinking
channel is the best-documented; GLM reasoning_effort acceptance is
judged by the live response, no extra probe calls):

  1-2  deepseek-flash  thinking=disabled, max_tokens=2048  x FE3,FE4
  3-4  GLM-5.3         reasoning_effort=low, max_tokens=2048 x FE3,FE4
  5-6  GLM-5.3         reasoning_effort=low, max_tokens=8192 x FE3,FE4
  7-8  GLM-5.3-Flash   reasoning_effort=low, max_tokens=8192 x FE3,FE4

Hard caps: 8 attempts / 120,000 tokens / CNY 0.50 / 900 s. No
retries, no sample expansion, first unexpected error -> INCOMPLETE.

Prompt contract: byte-identical to the original FE run (per-sample
prompt SHA asserted against fe_20261013_211741 ledger). GLM bodies
carry reasoning_effort ONLY (never a thinking field); deepseek body
carries thinking={"type":"disabled"} and NO response_format.

Usage:
  python3 -m deadline_reward_v1.param_recovery_exec --preflight
  PARAM_RECOVERY_GO=1 python3 -m deadline_reward_v1.param_recovery_exec
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

from deadline_reward_v1.theta_actions import theta_legal  # noqa: E402

GO_FLAG = 'PARAM_RECOVERY_GO'
FREEZE = HERE / 'PARAM_RECOVERY_FREEZE.json'
PREFLIGHT = HERE / 'PARAM_RECOVERY_PREFLIGHT_PASS.json'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
SAMPLES_V2 = HERE / 'FACT_EXTRACTION_SAMPLES_V2.json'
RATES_V2 = HERE / 'REVERSE_ENGINEERED_RATES_V2.json'
ORIG_LEDGER = (HERE / 'fe_screening_runs' / 'fe_20261013_211741' /
               'FE_LEDGER.jsonl')

CAPS = dict(attempts=8, tokens=120000, cash_cny=0.50, wall_s=900.0)

# (order, model_key, model_id, sample, theta, url, rate_key)
CELLS = [
    dict(i=1, model_key='deepseek', model_id='deepseek-flash',
         sample='FE3',
         theta=dict(thinking='disabled', max_tokens=2048,
                    reasoning_effort=None, response_format=None),
         url='https://api.deepseek.com/chat/completions',
         rate_key='deepseek_flash', env='DEEPSEEK_API_KEY'),
    dict(i=2, model_key='deepseek', model_id='deepseek-flash',
         sample='FE4',
         theta=dict(thinking='disabled', max_tokens=2048,
                    reasoning_effort=None, response_format=None),
         url='https://api.deepseek.com/chat/completions',
         rate_key='deepseek_flash', env='DEEPSEEK_API_KEY'),
    dict(i=3, model_key='glm53', model_id='GLM-5.3', sample='FE3',
         theta=dict(reasoning_effort='low', max_tokens=2048,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
    dict(i=4, model_key='glm53', model_id='GLM-5.3', sample='FE4',
         theta=dict(reasoning_effort='low', max_tokens=2048,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
    dict(i=5, model_key='glm53', model_id='GLM-5.3', sample='FE3',
         theta=dict(reasoning_effort='low', max_tokens=8192,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
    dict(i=6, model_key='glm53', model_id='GLM-5.3', sample='FE4',
         theta=dict(reasoning_effort='low', max_tokens=8192,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
    dict(i=7, model_key='glm53flash', model_id='GLM-5.3-Flash',
         sample='FE3',
         theta=dict(reasoning_effort='low', max_tokens=8192,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
    dict(i=8, model_key='glm53flash', model_id='GLM-5.3-Flash',
         sample='FE4',
         theta=dict(reasoning_effort='low', max_tokens=8192,
                    thinking=None, response_format=None),
         url='https://open.bigmodel.cn/api/anthropic/v1/messages',
         rate_key=None, env='ZHIPU_API_KEY'),
]

PROMPT_TEMPLATE = (
    '你是一个资本市场事件调查助手。\n'
    '\n'
    '## 任务类型：fact_extraction\n'
    '\n'
    '## 任务描述\n'
    '从证据文档中抽取原子事实：涉及主体、处罚决定（罚款金额、警告、'
    '市场禁入）、违法行为类型，每条含事实陈述、数值/日期、证据doc_id。\n'
    '\n'
    '## 证据文档\n'
    '{evidence}\n'
    '\n'
    '## 输出要求\n'
    '- 输出格式：JSON数组，每个元素包含 fact, date, entities, '
    'evidence_doc_id 字段\n'
    '- 输出契约：entity_facts.v1\n'
    '- 最大输出长度：{max_out} tokens\n'
    '- 只抽取有证据支持的事实，不得虚构\n'
    '\n'
    '请严格按照输出要求完成任务。')


def load_env_creds():
    """modelpool first (valid keys), then /root/.env fallback."""
    env_vars = {}
    for path in ('/root/.env.modelpool', '/root/.env'):
        p = Path(path)
        if p.exists():
            for line in p.read_text().splitlines():
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars.setdefault(k.strip(), v.strip())
    return env_vars


def build_prompts():
    v2 = json.loads(SAMPLES_V2.read_text())
    wanted = {s['sample_id']: s for s in v2['samples']
              if s['sample_id'] in ('FE3', 'FE4')}
    out = {}
    for sid, s in wanted.items():
        prompt = PROMPT_TEMPLATE.format(
            evidence=s['evidence_full_text'], max_out=2048)
        out[sid] = dict(prompt=prompt,
                        sha=hashlib.sha256(prompt.encode()).hexdigest(),
                        prompt_tokens_est=None)
    return out


def orig_prompt_shas():
    orig = {}
    for line in ORIG_LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        orig.setdefault(e['sample_id'], e['prompt_sha256'])
    return orig


def observed_prompt_tokens():
    """Real prompt-token counts from the original FE run (same prompts,
    same tokenizer): FE3=3482, FE4=6322."""
    out = {}
    for line in ORIG_LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e['status'] == 'delivered':
            out.setdefault(e['sample_id'],
                           e['usage']['prompt_tokens'])
    return out


def make_body(cell):
    """Request body per provider. GLM: reasoning_effort ONLY (never a
    thinking field). deepseek: thinking disabled, NO response_format."""
    th = cell['theta']
    if cell['model_key'] == 'deepseek':
        body = dict(model=cell['model_id'],
                    messages=[dict(role='user',
                                   content=cell['prompt'])],
                    max_tokens=th['max_tokens'], temperature=0.0)
        body['thinking'] = {'type': 'disabled'}
        assert 'response_format' not in body
    else:
        body = dict(model=cell['model_id'],
                    messages=[dict(role='user',
                                   content=cell['prompt'])],
                    max_tokens=th['max_tokens'], temperature=0.0)
        body['reasoning_effort'] = 'low'
        assert 'thinking' not in body
    ok, why = theta_legal(cell['model_id'], th)
    assert ok, f'cell {cell["i"]} illegal theta: {why}'
    return body


def make_headers(cell, key):
    if cell['model_key'] == 'deepseek':
        return {'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json'}
    return {'x-api-key': key, 'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json'}


def parse_response(cell, data):
    """Normalize OpenAI-compat and Anthropic-compat shapes."""
    answer, finish, usage = '', None, {}
    if 'choices' in data and data['choices']:
        ch = data['choices'][0]
        answer = ch.get('message', {}).get('content', '') or ''
        finish = ch.get('finish_reason')
        u = data.get('usage', {}) or {}
        usage = dict(
            prompt_tokens=u.get('prompt_tokens', 0),
            completion_tokens=u.get('completion_tokens', 0),
            reasoning_tokens=u.get('reasoning_tokens',
                                   u.get('completion_tokens_details', {})
                                   .get('reasoning_tokens')),
            raw_usage=u)
    elif isinstance(data.get('content'), list):
        for block in data['content']:
            if isinstance(block, dict) and block.get('type') == 'text':
                answer = block.get('text', '')
                break
        finish = data.get('stop_reason')  # 'end_turn' | 'max_tokens'
        u = data.get('usage', {}) or {}
        usage = dict(
            prompt_tokens=u.get('input_tokens', 0),
            completion_tokens=u.get('output_tokens', 0),
            reasoning_tokens=u.get('reasoning_tokens',
                                   u.get('output_tokens_details', {})
                                   .get('reasoning_tokens')),
            raw_usage=u)
    else:
        raise RuntimeError(f'unrecognized response shape: '
                           f'{json.dumps(data)[:200]}')
    return answer, finish, usage


def cash_of(cell, tokens_in, tokens_out):
    if not cell['rate_key']:
        return 0.0  # GLM subscription
    rates = json.loads(RATES_V2.read_text())['rates'][cell['rate_key']]
    return (tokens_in * rates['input_cny_per_mtok'] / 1e6
            + tokens_out * rates['output_cny_per_mtok'] / 1e6)


# ---- transports -----------------------------------------------------------
def real_transport(url, headers, body, timeout=120):
    t0 = time.monotonic()
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    latency = time.monotonic() - t0
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f'non-JSON response HTTP {resp.status_code}: '
                           f'{resp.text[:200]}')
    if resp.status_code != 200:
        raise RuntimeError(f'HTTP {resp.status_code}: '
                           f'{json.dumps(data)[:300]}')
    return data, latency


class FakeTransport:
    """Scriptable transport for the zero-call preflight. Records every
    request body; never touches the network."""

    def __init__(self, script=None, fail_at=None, huge_tokens_at=None):
        self.script = script or {}
        self.fail_at = fail_at          # cell index -> (status, body)
        self.huge_tokens_at = huge_tokens_at or set()
        self.requests = []
        self.latency = 0.01

    def __call__(self, url, headers, body, timeout=120):
        self.requests.append(dict(url=url, body=dict(body),
                                   headers_keys=sorted(headers)))
        idx = len(self.requests)
        if self.fail_at and idx == self.fail_at[0]:
            raise RuntimeError(f'FAKE HTTP {self.fail_at[1]}: '
                               f'injected preflight failure')
        data = dict(self.script)
        if idx in self.huge_tokens_at:
            data = json.loads(json.dumps(data))
            data['usage'] = dict(prompt_tokens=60000,
                                 completion_tokens=70000)
        return data, self.latency


# ---- core runner ----------------------------------------------------------
def run_cells(transport, creds, prompts, ptok, run_dir, preflight=False):
    ledger_path = run_dir / 'PR_LEDGER.jsonl'
    rates_tot = dict(attempts=0, tokens_in=0, tokens_out=0, cash=0.0)
    t0 = time.monotonic()
    entries = []
    for cell in CELLS:
        cell = dict(cell)
        cell['prompt'] = prompts[cell['sample']]['prompt']

        # ---- pre-request budget gate (global, conservative) ----
        est_in = ptok[cell['sample']]
        est_out = cell['theta']['max_tokens']
        est_cash = cash_of(cell, est_in, est_out)
        if rates_tot['attempts'] + 1 > CAPS['attempts']:
            raise RuntimeError('budget stop: attempts cap')
        if (rates_tot['tokens_in'] + rates_tot['tokens_out']
                + est_in + est_out > CAPS['tokens']):
            raise RuntimeError('budget stop: token cap (pre-request)')
        if rates_tot['cash'] + est_cash > CAPS['cash_cny']:
            raise RuntimeError('budget stop: cash cap (pre-request)')
        if time.monotonic() - t0 > CAPS['wall_s']:
            raise RuntimeError('budget stop: wall cap')

        body = make_body(cell)
        key = ('FAKE-PREFLIGHT-KEY' if preflight
               else creds.get(cell['env'], ''))
        if not preflight and not key:
            raise RuntimeError(f"credential {cell['env']} missing")

        # FAIL-STOP: no per-call catch
        data, latency = transport(cell['url'],
                                  make_headers(cell, key), body)
        answer, finish, usage = parse_response(cell, data)
        cash = cash_of(cell, usage['prompt_tokens'],
                       usage['completion_tokens'])
        rates_tot['attempts'] += 1
        rates_tot['tokens_in'] += usage['prompt_tokens']
        rates_tot['tokens_out'] += usage['completion_tokens']
        rates_tot['cash'] += cash
        entry = dict(
            cell=cell['i'], sample=cell['sample'],
            model_key=cell['model_key'], model_id=cell['model_id'],
            theta={k: v for k, v in cell['theta'].items() if v},
            prompt_sha256=prompts[cell['sample']]['sha'],
            status='delivered', answer=answer, finish_reason=finish,
            usage=dict(prompt_tokens=usage['prompt_tokens'],
                       completion_tokens=usage['completion_tokens'],
                       reasoning_tokens=usage['reasoning_tokens']),
            max_output_tokens=cell['theta']['max_tokens'],
            latency_s=round(latency, 3), cash_cny=round(cash, 6),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
        entries.append(entry)
        with open(ledger_path, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
        print(f"  cell{cell['i']} {cell['model_id']:14s} "
              f"{cell['sample']} finish={finish} "
              f"tok={usage['prompt_tokens']}+"
              f"{usage['completion_tokens']} "
              f"cash=CNY{cash:.4f}", flush=True)
    return entries, rates_tot, time.monotonic() - t0


# ---- preflight ------------------------------------------------------------
def preflight(args):
    prompts = build_prompts()
    orig = orig_prompt_shas()
    issues = []
    for sid, p in prompts.items():
        if p['sha'] != orig.get(sid):
            issues.append(f'{sid}: prompt SHA drift vs original run')

    checks = dict(prompt_shas_match=not issues, bodies_ok=True,
                  fail_stop_ok=False, budget_stop_ok=False,
                  no_thinking_for_glm=True, ds_has_thinking_disabled=True,
                  ds_no_response_format=True, caps_exact=True)

    # 1) body wiring on a fake happy transport
    fake_ok = FakeTransport(script=dict(
        choices=[dict(finish_reason='stop',
                      message=dict(content='[]'))],
        usage=dict(prompt_tokens=100, completion_tokens=10)))
    tmp = Path('/tmp/pr_preflight_bodies')
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    run_cells(fake_ok, {}, prompts, dict(FE3=3482, FE4=6322), tmp,
              preflight=True)
    for r in fake_ok.requests:
        b = r['body']
        is_glm = 'anthropic' in r['url']
        if is_glm:
            if b.get('reasoning_effort') != 'low':
                checks['bodies_ok'] = False
            if 'thinking' in b:
                checks['no_thinking_for_glm'] = False
        else:
            if b.get('thinking') != {'type': 'disabled'}:
                checks['ds_has_thinking_disabled'] = False
            if 'response_format' in b:
                checks['ds_no_response_format'] = False
            if 'reasoning_effort' in b:
                checks['bodies_ok'] = False
        if b.get('max_tokens') not in (2048, 8192):
            checks['caps_exact'] = False
    checks['n_requests'] = len(fake_ok.requests)

    # 2) fail-stop: injected HTTP error must abort immediately and
    #    leave exactly fail_at-1 delivered entries
    tmp2 = Path('/tmp/pr_preflight_failstop')
    shutil.rmtree(tmp2, ignore_errors=True)
    tmp2.mkdir(parents=True)
    fake_fail = FakeTransport(
        script=dict(choices=[dict(finish_reason='stop',
                                  message=dict(content='[]'))],
                    usage=dict(prompt_tokens=100,
                               completion_tokens=10)),
        fail_at=(3, 500))
    aborted = False
    try:
        run_cells(fake_fail, {}, prompts, dict(FE3=3482, FE4=6322),
                  tmp2, preflight=True)
    except RuntimeError as exc:
        aborted = 'FAKE HTTP 500' in str(exc)
    n_after_fail = len([l for l in
                        (tmp2 / 'PR_LEDGER.jsonl').read_text()
                        .splitlines() if l.strip()])
    checks['fail_stop_ok'] = (aborted and n_after_fail == 2
                              and len(fake_fail.requests) == 3)

    # 3) budget stop: huge usage must trip the token cap pre-request
    tmp3 = Path('/tmp/pr_preflight_budget')
    shutil.rmtree(tmp3, ignore_errors=True)
    tmp3.mkdir(parents=True)
    fake_huge = FakeTransport(
        script=dict(choices=[dict(finish_reason='stop',
                                  message=dict(content='[]'))],
                    usage=dict(prompt_tokens=60000,
                               completion_tokens=60000)))
    budget_stopped = False
    try:
        run_cells(fake_huge, {}, prompts, dict(FE3=3482, FE4=6322),
                  tmp3, preflight=True)
    except RuntimeError as exc:
        budget_stopped = 'budget stop' in str(exc)
    checks['budget_stop_ok'] = budget_stopped

    checks['prompt_issues'] = issues
    all_ok = (checks['prompt_shas_match'] and checks['bodies_ok']
              and checks['fail_stop_ok'] and checks['budget_stop_ok']
              and checks['no_thinking_for_glm']
              and checks['ds_has_thinking_disabled']
              and checks['ds_no_response_format']
              and checks['caps_exact'])
    checks['preflight_pass'] = all_ok
    if all_ok:
        freeze_sha = hashlib.sha256(FREEZE.read_bytes()).hexdigest()
        PREFLIGHT.write_text(json.dumps(dict(
            passed=True, freeze_sha256=freeze_sha,
            caps=CAPS, n_cells=len(CELLS),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S')), indent=1))
    print(json.dumps(checks, indent=1, ensure_ascii=False))
    return 0 if all_ok else 2


def execute(args):
    if not PREFLIGHT.exists():
        raise PermissionError('preflight has not passed')
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1')
    pre = json.loads(PREFLIGHT.read_text())
    freeze_sha = hashlib.sha256(FREEZE.read_bytes()).hexdigest()
    if pre.get('freeze_sha256') != freeze_sha:
        raise PermissionError('freeze drifted since preflight')

    prompts = build_prompts()
    orig = orig_prompt_shas()
    for sid, p in prompts.items():
        if p['sha'] != orig.get(sid):
            raise PermissionError(f'{sid}: prompt SHA drift')

    creds = load_env_creds()
    ptok = observed_prompt_tokens()
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'param_recovery_%Y%m%d_%H%M%S')
    if run_dir.exists():
        raise PermissionError('run dir exists')
    run_dir.mkdir(parents=True)

    lock_fh = GPU_LOCK.open('a+')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        entries, tot, wall = run_cells(real_transport, creds, prompts,
                                       ptok, run_dir)
        delivered = sum(1 for e in entries if e['status'] == 'delivered')
        status = 'COMPLETE' if delivered == len(CELLS) else 'INCOMPLETE'
        (run_dir / 'PR_RESULTS.json').write_text(json.dumps(dict(
            status=status, n_cells=len(entries), delivered=delivered,
            totals=dict(**tot, cash_cny=round(tot['cash'], 6)),
            wall_s=round(wall, 1), caps=CAPS,
            freeze_sha256=freeze_sha,
            entries=[{k: v for k, v in e.items() if k != 'answer'}
                     for e in entries]), indent=1, ensure_ascii=False))
        print(json.dumps(dict(status=status, n=len(entries),
                              cash=round(tot['cash'], 4),
                              tokens=tot['tokens_in'] + tot['tokens_out'],
                              wall=round(wall, 1)), indent=1))
        return 0 if status == 'COMPLETE' else 2
    except BaseException as exc:
        (run_dir / 'PR_INCOMPLETE.json').write_text(json.dumps(dict(
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
        return preflight(args)
    return execute(args)


if __name__ == '__main__':
    raise SystemExit(main())
