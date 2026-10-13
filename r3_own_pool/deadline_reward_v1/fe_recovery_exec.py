"""FE DS/Qwen recovery execution — 10 calls (FE1-FE5 x deepseek-flash +
qwen-plus). Recovers the 10 ERROR entries of run fe_20261013_211741.

Fixes vs fe_screening_launch.py (per operator ruling):
  1. rates read via json.load (was: `import rates` on a JSON file ->
     ModuleNotFoundError on every DS/Qwen call)
  2. model_id 'deepseek-flash' (historical ledger-verified; rates are
     bound to it), not 'deepseek-chat'
  3. FAIL-STOP: first unexpected error -> INCOMPLETE marker -> stop.
     No per-call catch-and-continue.
  4. records stop_reason/finish_reason + truncated + json_valid
     (the original launcher dropped these)
  5. status COMPLETE only if 10/10 delivered with no ERROR

Pairing: prompts rebuilt from FACT_EXTRACTION_SAMPLES_V2.json; per-sample
prompt SHA256 asserted EQUAL to the original run's ledger entries, so
the 4-model comparison stays same-prompt paired.

Caps (operator ruling): 10 attempts / 120K tokens / CNY 1.00 / 1800s.
max_output_tokens stays 2048 (same contract as GLM arm; DS/Qwen direct
outputs historically stop well below it).

Usage:
  python3 -m deadline_reward_v1.fe_recovery_exec --rehearse
  FE_RECOVERY_GO=1 python3 -m deadline_reward_v1.fe_recovery_exec \
      --approved-samples-sha256 <sha>
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

GO_FLAG = 'FE_RECOVERY_GO'
GPU_LOCK = ROOT / 'collect/logs/local_gpu.lock'
SAMPLES_V2 = HERE / 'FACT_EXTRACTION_SAMPLES_V2.json'
RATES_V2 = HERE / 'REVERSE_ENGINEERED_RATES_V2.json'
ORIG_LEDGER = (HERE / 'fe_screening_runs' / 'fe_20261013_211741' /
               'FE_LEDGER.jsonl')

MODELS = {
    'deepseek': dict(model_id='deepseek-flash', rate_key='deepseek_flash',
                     env='DEEPSEEK_API_KEY',
                     url='https://api.deepseek.com/chat/completions',
                     billing='per_token_cny'),
    'qwen': dict(model_id='qwen-plus', rate_key='qwen_plus',
                 env='DASHSCOPE_API_KEY',
                 url=('https://dashscope.aliyuncs.com/compatible-mode/v1/'
                      'chat/completions'),
                 billing='per_token_cny'),
}
MAX_OUTPUT_TOKENS = 2048
CAPS = dict(max_attempts=10, max_tokens=120000, max_cash_cny=1.00,
            wall_seconds=1800.0)

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


def load_env_creds():
    """Credentials from /root/.env.modelpool (the file the historical
    screening run used; holds the VALID deepseek/dashscope keys), then
    /root/.env as fallback, then process env. Values never logged."""
    env_vars = {}
    for path in ('/root/.env.modelpool', '/root/.env'):
        p = Path(path)
        if p.exists():
            for line in p.read_text().splitlines():
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars.setdefault(k.strip(), v.strip())
    return env_vars


def build_prompts(samples):
    out = {}
    for s in samples:
        prompt = PROMPT_TEMPLATE.format(
            evidence=s['evidence_full_text'], max_out=MAX_OUTPUT_TOKENS)
        psha = hashlib.sha256(prompt.encode()).hexdigest()
        for mk, cfg in MODELS.items():
            out[(s['sample_id'], mk)] = dict(
                prompt=prompt, prompt_sha256=psha,
                sample_id=s['sample_id'], model_key=mk,
                model_id=cfg['model_id'], event=s['event'],
                evidence_doc_id=s['evidence_doc_id'],
                information_cutoff=s['information_cutoff'])
    return out


def check_pairing_against_original(prompts):
    """Assert per-sample prompt SHA == original run's ledger entries."""
    orig = [json.loads(l) for l in ORIG_LEDGER.read_text().splitlines()
            if l.strip()]
    orig_sha = {}
    for e in orig:
        orig_sha[e['sample_id']] = e['prompt_sha256']  # same for all models
    issues = []
    for (sid, _mk), p in prompts.items():
        if sid not in orig_sha:
            issues.append(f'{sid}: not in original ledger')
        elif p['prompt_sha256'] != orig_sha[sid]:
            issues.append(f'{sid}: prompt SHA drift vs original run')
    return issues


def call_api(cfg, prompt, creds):
    """One real API call. Returns dict; raises on HTTP/API error
    (fail-stop relies on the exception propagating)."""
    key = creds.get(cfg['env']) or os.environ.get(cfg['env'], '')
    if not key:
        raise RuntimeError(f"credential {cfg['env']} missing")
    body = dict(model=cfg['model_id'],
                messages=[dict(role='user', content=prompt)],
                max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0)
    headers = {'Authorization': f'Bearer {key}',
               'Content-Type': 'application/json'}
    t0 = time.monotonic()
    resp = requests.post(cfg['url'], headers=headers, json=body,
                         timeout=120)
    latency = time.monotonic() - t0
    if resp.status_code != 200:
        raise RuntimeError(f'HTTP {resp.status_code}: '
                           f'{resp.text[:200]}')
    data = resp.json()
    if 'choices' not in data or not data['choices']:
        raise RuntimeError(f'no choices in response: '
                           f'{json.dumps(data)[:200]}')
    choice = data['choices'][0]
    answer = choice.get('message', {}).get('content', '') or ''
    finish_reason = choice.get('finish_reason')
    usage = data.get('usage', {})
    tokens_in = usage.get('prompt_tokens', 0)
    tokens_out = usage.get('completion_tokens', 0)

    # CASH (CNY): rates from the JSON file — json.load, NOT import
    rates = json.loads(RATES_V2.read_text())['rates']
    r = rates[cfg['rate_key']]
    cash = (tokens_in * r['input_cny_per_mtok'] / 1e6 +
            tokens_out * r['output_cny_per_mtok'] / 1e6)

    return dict(status='delivered', answer=answer,
                finish_reason=finish_reason,
                truncated=(finish_reason != 'stop'),
                usage=dict(prompt_tokens=tokens_in,
                           completion_tokens=tokens_out,
                           total_tokens=tokens_in + tokens_out),
                latency_s=round(latency, 3), cash_cny=round(cash, 6))


def gates(args):
    if os.environ.get(GO_FLAG) != '1':
        raise PermissionError(f'requires {GO_FLAG}=1')
    if args.approved_samples_sha256 != sha_file(SAMPLES_V2):
        raise PermissionError('samples v2 hash mismatch')
    dirty = subprocess_git_dirty()
    if dirty:
        raise PermissionError(f'uncommitted changes:\n{dirty}')
    return subprocess_git_head()


def subprocess_git_dirty():
    import subprocess
    return subprocess.run(
        ['git', '-C', str(ROOT), 'status', '--porcelain', '--',
         'deadline_reward_v1'], capture_output=True, text=True).stdout.strip()


def subprocess_git_head():
    import subprocess
    return subprocess.run(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
        capture_output=True, text=True).stdout.strip()


def execute(args):
    creds = load_env_creds()
    v2 = json.loads(SAMPLES_V2.read_text())
    prompts = build_prompts(v2['samples'])
    pairing_issues = check_pairing_against_original(prompts)
    missing = [f'{mk}:{cfg["env"]}' for mk, cfg in MODELS.items()
               if not (creds.get(cfg['env'])
                       or os.environ.get(cfg['env']))]

    print(json.dumps(dict(
        status='REHEARSAL' if args.rehearse else 'GATES_PASS',
        n_calls=len(prompts), models=list(MODELS),
        pairing_vs_original_ok=not pairing_issues,
        pairing_issues=pairing_issues,
        credentials_ok=not missing,
        max_output_tokens=MAX_OUTPUT_TOKENS, caps=CAPS), indent=1))
    if pairing_issues:
        raise PermissionError(f'pairing failed: {pairing_issues}')
    if missing and not args.rehearse:
        raise PermissionError(f'credentials missing: {missing}')
    if args.rehearse:
        return 0

    commit = gates(args)
    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'fe_recovery_%Y%m%d_%H%M%S')
    if run_dir.exists():
        raise PermissionError('run dir exists')
    run_dir.mkdir(parents=True)
    ledger_path = run_dir / 'FE_LEDGER.jsonl'

    lock_fh = GPU_LOCK.open('a+')
    attempts = 0
    tokens_in_tot = 0
    tokens_out_tot = 0
    cash_tot = 0.0
    t0 = time.monotonic()
    entries = []
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for (sid, mk), p in sorted(prompts.items()):
            # budget pre-check
            if attempts >= CAPS['max_attempts']:
                raise RuntimeError('budget stop: attempts cap')
            if tokens_in_tot + tokens_out_tot >= CAPS['max_tokens']:
                raise RuntimeError('budget stop: token cap')
            if cash_tot >= CAPS['max_cash_cny']:
                raise RuntimeError('budget stop: cash cap')
            if time.monotonic() - t0 >= CAPS['wall_seconds']:
                raise RuntimeError('budget stop: wall cap')

            # FAIL-STOP: no per-call catch. Any unexpected error
            # aborts the run; the finally block writes INCOMPLETE.
            resp = call_api(MODELS[mk], p['prompt'], creds)
            attempts += 1
            tokens_in_tot += resp['usage']['prompt_tokens']
            tokens_out_tot += resp['usage']['completion_tokens']
            cash_tot += resp['cash_cny']
            entry = dict(
                sample_id=sid, model_key=mk, model_id=p['model_id'],
                event=p['event'], evidence_doc_id=p['evidence_doc_id'],
                prompt_sha256=p['prompt_sha256'],
                status=resp['status'], answer=resp['answer'],
                finish_reason=resp['finish_reason'],
                truncated=resp['truncated'],
                usage=resp['usage'], latency_s=resp['latency_s'],
                cash_cny=resp['cash_cny'],
                max_output_tokens=MAX_OUTPUT_TOKENS,
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))
            entries.append(entry)
            with open(ledger_path, 'a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
            print(f'  {sid}|{mk}: {entry["status"]} '
                  f'finish={entry["finish_reason"]} '
                  f'tokens={entry["usage"]["total_tokens"]} '
                  f'cash=CNY {entry["cash_cny"]:.4f}', flush=True)

        delivered = sum(1 for e in entries if e['status'] == 'delivered')
        status = 'COMPLETE' if delivered == len(prompts) else 'INCOMPLETE'
        summary = dict(
            status=status, n_calls=len(entries),
            delivered=delivered,
            budget=dict(attempts=attempts, tokens_in=tokens_in_tot,
                        tokens_out=tokens_out_tot,
                        cash_cny=round(cash_tot, 6),
                        wall_s=round(time.monotonic() - t0, 1)),
            caps=CAPS, git_commit=commit,
            recovery_of='fe_20261013_211741 (DS/Qwen ERROR entries)',
            entries=[{k: v for k, v in e.items() if k != 'answer'}
                     for e in entries])
        (run_dir / 'FE_RESULTS.json').write_text(
            json.dumps(summary, indent=1, ensure_ascii=False))
        print(json.dumps(dict(status=status, n=len(entries),
                              cash_cny=round(cash_tot, 4),
                              tokens=tokens_in_tot + tokens_out_tot),
                         indent=1))
        return 0 if status == 'COMPLETE' else 2
    except BaseException as exc:
        (run_dir / 'FE_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc), n_done=len(entries),
            budget=dict(attempts=attempts, tokens_in=tokens_in_tot,
                        tokens_out=tokens_out_tot, cash_cny=cash_tot),
            traceback=traceback.format_exc()), indent=1))
        raise
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-samples-sha256')
    parser.add_argument('--rehearse', action='store_true')
    args = parser.parse_args()
    return execute(args)


if __name__ == '__main__':
    raise SystemExit(main())
