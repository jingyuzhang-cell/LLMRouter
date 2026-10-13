"""FE1-FE5 × 4-model fact_extraction screening (authorized conditional GO).

Reads FACT_EXTRACTION_SAMPLES_V2.json evidence_full_text (NOT the old
truncated evidence_summary). max_output_tokens=2048. One global budget
guard. Same prompt content across all 4 models per pairing group.

Gate conditions (all zero-call, checked BEFORE any real API call):
  1. FE_V2_GO=1 + --approved-samples-sha256 matches
  2. clean git tree
  3. 5 pairing groups, 4 models each, prompt SHA identical within group
  4. credentials available (env vars)
  5. budget caps: 24 attempts / 250K tokens / CNY 2.00 / 3600s

Usage:
  FE_V2_GO=1 python3 -m deadline_reward_v1.fe_screening_launch \
    --approved-samples-sha256 <sha> [--rehearse]
"""
from __future__ import annotations
import argparse

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

GO_FLAG = 'FE_V2_GO'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
SAMPLES_V2 = HERE / 'FACT_EXTRACTION_SAMPLES_V2.json'
MODELS = {
    'glm53': dict(model_id='GLM-5.3', env='ZHIPU_API_KEY',
                  billing='subscription'),
    'glm53flash': dict(model_id='GLM-5.3-Flash', env='ZHIPU_API_KEY',
                       billing='subscription'),
    'deepseek': dict(model_id='deepseek-chat', env='DEEPSEEK_API_KEY',
                     billing='per_token_cny'),
    'qwen': dict(model_id='qwen-plus', env='QWEN_API_KEY',
                 billing='per_token_cny'),
}
MAX_OUTPUT_TOKENS = 2048
CAPS = dict(max_attempts=24, max_tokens=250000, max_cash_cny=2.00,
            wall_seconds=3600.0)

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


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_prompts(samples):
    """Build prompts from V2 full evidence. Returns dict keyed by
    (sample_id, model_key) with prompt text and SHA."""
    result = {}
    for s in samples:
        evidence = s['evidence_full_text']  # FULL text, no truncation
        prompt = PROMPT_TEMPLATE.format(
            evidence=evidence, max_out=MAX_OUTPUT_TOKENS)
        psha = hashlib.sha256(prompt.encode()).hexdigest()
        for mk in MODELS:
            result[(s['sample_id'], mk)] = dict(
                prompt=prompt, prompt_sha256=psha,
                sample_id=s['sample_id'], model_key=mk,
                model_id=MODELS[mk]['model_id'],
                event=s['event'],
                evidence_doc_id=s['evidence_doc_id'],
                information_cutoff=s['information_cutoff'],
                evaluatable_facts=s.get('evaluatable_facts', []),
                evaluatable_count=s.get('evaluable_count', 0))
    return result


def check_pairing(prompts):
    """Verify: within each sample_id group, all 4 models have the same
    prompt SHA."""
    by_sample = {}
    for (sid, mk), p in prompts.items():
        by_sample.setdefault(sid, {})[mk] = p['prompt_sha256']
    issues = []
    for sid, shas in sorted(by_sample.items()):
        if len(shas) != len(MODELS):
            issues.append(f'{sid}: only {len(shas)} models (need {len(MODELS)})')
        unique = set(shas.values())
        if len(unique) > 1:
            issues.append(f'{sid}: {len(unique)} different prompt SHAs')
    return len(by_sample), issues


def check_credentials():
    """Check that all model credential env vars are set."""
    issues = []
    env_file = Path('/root/.env')
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env_vars[k.strip()] = v.strip()
    for mk, cfg in MODELS.items():
        key = env_vars.get(cfg['env']) or os.environ.get(cfg['env'])
        if not key:
            issues.append(f'{mk}: {cfg["env"]} not in /root/.env or env')
    return issues


def gates(args):
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1')
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    v2 = json.loads(SAMPLES_V2.read_text())
    if args.approved_samples_sha256 != sha_file(SAMPLES_V2):
        raise PermissionError('samples v2 hash mismatch')
    return commit, v2


class Budget:
    def __init__(self):
        self.attempts = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cash_cny = 0.0
        self.start = time.monotonic()

    def can(self):
        if self.attempts >= CAPS['max_attempts']:
            return 'attempts cap'
        if self.tokens_in + self.tokens_out >= CAPS['max_tokens']:
            return 'token cap'
        if self.cash_cny >= CAPS['max_cash_cny']:
            return 'cash cap'
        if time.monotonic() - self.start >= CAPS['wall_seconds']:
            return 'wall cap'
        return None

    def record(self, tokens_in, tokens_out, cash_cny=0.0):
        self.attempts += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cash_cny += cash_cny


def dispatch(model_key, prompt):
    """Real API call via the operator's existing infrastructure.
    Reads credentials from env; returns response dict."""
    cfg = MODELS[model_key]
    # The capital_opinion_pilot has a working API client — reuse it
    sys.path.insert(0, str(ROOT.parent / 'capital_opinion_pilot'))
    # Try to find the client module
    import importlib
    for mod_name in ('screening_full80_client', 'model_client',
                     'api_client'):
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, 'call_model'):
                return mod.call_model(cfg['model_id'], prompt)
        except ImportError:
            continue
    # Fallback: use the direct API approach
    return _direct_api_call(cfg, prompt)


def _direct_api_call(cfg, prompt):
    """Direct API call. Adjusts per provider."""
    import requests
    model_id = cfg['model_id']
    key = os.environ.get(cfg['env'], '')

    # Read credential from /root/.env or environment
    env_file = Path('/root/.env')
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env_vars[k.strip()] = v.strip()
    key = env_vars.get(cfg['env']) or key

    if 'deepseek' in model_id.lower():
        url = 'https://api.deepseek.com/chat/completions'
        headers = {'Authorization': f'Bearer {key}',
                   'Content-Type': 'application/json'}
        body = dict(model='deepseek-chat', messages=[dict(role='user',
                                                          content=prompt)],
                    max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0)
    elif 'qwen' in model_id.lower():
        url = ('https://dashscope.aliyuncs.com/compatible-mode/v1/'
               'chat/completions')
        headers = {'Authorization': f'Bearer {key}',
                   'Content-Type': 'application/json'}
        body = dict(model=model_id, messages=[dict(role='user',
                                                    content=prompt)],
                    max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0)
    else:  # GLM via Anthropic-compatible endpoint
        url = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
        headers = {'x-api-key': key,
                   'anthropic-version': '2023-06-01',
                   'Content-Type': 'application/json'}
        body = dict(model=model_id, max_tokens=MAX_OUTPUT_TOKENS,
                    messages=[dict(role='user', content=prompt)],
                    temperature=0.0)

    t0 = time.monotonic()
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    latency = time.monotonic() - t0
    data = resp.json()

    answer = ''
    if 'choices' in data and data['choices']:
        answer = data['choices'][0].get('message', {}).get('content', '')
    elif 'content' in data and isinstance(data.get('content'), list):
        # Anthropic format
        for block in data['content']:
            if isinstance(block, dict) and block.get('type') == 'text':
                answer = block.get('text', '')
                break
    usage = data.get('usage', {})
    tokens_in = usage.get('prompt_tokens', usage.get('input_tokens', 0))
    tokens_out = usage.get('completion_tokens', usage.get('output_tokens', 0))

    # Cost in CNY
    if cfg['billing'] == 'per_token_cny':
        from deadline_reward_v1.REVERSE_ENGINEERED_RATES_V2 import rates
        r = rates.get(model_id.replace('-', '_'), {})
        cash = (tokens_in * r.get('input_cny_per_mtok', 0) / 1e6 +
                tokens_out * r.get('output_cny_per_mtok', 0) / 1e6)
    else:
        cash = 0.0

    return dict(status='delivered', answer=answer,
                usage=dict(prompt_tokens=tokens_in,
                           completion_tokens=tokens_out,
                           total_tokens=tokens_in + tokens_out),
                latency_s=round(latency, 3), cash_cny=round(cash, 6))


def execute(args):
    commit, v2 = gates(args)
    samples = v2['samples']

    prompts = build_prompts(samples)
    n_groups, pairing_issues = check_pairing(prompts)
    cred_issues = check_credentials()

    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'fe_%Y%m%d_%H%M%S')
    if run_dir.exists():
        raise PermissionError('run dir exists')
    run_dir.mkdir(parents=True)
    ledger_path = run_dir / 'FE_LEDGER.jsonl'
    budget = Budget()

    if pairing_issues:
        raise PermissionError(f'pairing check failed: {pairing_issues}')
    if cred_issues and not args.rehearse:
        raise PermissionError(f'credentials missing: {cred_issues}')

    print(json.dumps(dict(
        status='PREHEARSAL_PASS' if args.rehearse else 'READY_TO_EXECUTE',
        n_samples=len(samples), n_groups=n_groups,
        n_prompts=len(prompts),
        pairing_ok=not pairing_issues,
        credentials_ok=not cred_issues,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        caps=CAPS,
        git_commit=commit), indent=1))

    if args.rehearse:
        return 0

    lock_fh = GPU_LOCK.open('a+')
    results = {}
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for (sid, mk), p in sorted(prompts.items()):
            stop = budget.can()
            if stop:
                raise RuntimeError(f'budget stop: {stop}')
            try:
                resp = dispatch(mk, p['prompt'])
                budget.record(resp['usage']['prompt_tokens'],
                              resp['usage']['completion_tokens'],
                              resp.get('cash_cny', 0))
                entry = dict(
                    sample_id=sid, model_key=mk,
                    model_id=p['model_id'], event=p['event'],
                    evidence_doc_id=p['evidence_doc_id'],
                    prompt_sha256=p['prompt_sha256'],
                    status=resp['status'], answer=resp['answer'],
                    usage=resp['usage'],
                    latency_s=resp['latency_s'],
                    cash_cny=resp.get('cash_cny', 0),
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
            except Exception as exc:
                budget.attempts += 1
                entry = dict(
                    sample_id=sid, model_key=mk,
                    model_id=p['model_id'],
                    prompt_sha256=p['prompt_sha256'],
                    status='ERROR', error=repr(exc),
                    timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
            results[(sid, mk)] = entry
            with open(ledger_path, 'a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            print(f'  {sid}|{mk}: {entry["status"]} '
                  f'tokens={entry.get("usage",{}).get("total_tokens",0)} '
                  f'cash=CNY {entry.get("cash_cny",0):.4f}')

        # save results
        summary = dict(
            status='COMPLETE',
            n_calls=len(results),
            budget=dict(attempts=budget.attempts,
                        tokens_in=budget.tokens_in,
                        tokens_out=budget.tokens_out,
                        cash_cny=round(budget.cash_cny, 6),
                        wall_s=round(time.monotonic() - budget.start, 1)),
            results={f'{s}|{m}': r for (s, m), r in results.items()})
        (run_dir / 'FE_RESULTS.json').write_text(
            json.dumps(summary, indent=1, ensure_ascii=False))
        print(json.dumps(dict(status='COMPLETE',
                              n=len(results),
                              cash_cny=round(budget.cash_cny, 4),
                              tokens=budget.tokens_in + budget.tokens_out),
                         indent=1))
        return 0
    except BaseException as exc:
        (run_dir / 'FE_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc),
            traceback=traceback.format_exc()), indent=1))
        raise
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-samples-sha256', required=True)
    parser.add_argument('--rehearse', action='store_true')
    args = parser.parse_args()
    return execute(args)


if __name__ == '__main__':
    raise SystemExit(main())