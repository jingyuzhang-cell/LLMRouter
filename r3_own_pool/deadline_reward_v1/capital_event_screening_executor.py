"""Gated CapitalEvent screening executor + prompt renderer.

Renders the 80 prompts from the frozen plan (zero-call). The executor
is a skeleton: actual API dispatch requires the operator to fill
MODEL_REGISTRY with verified credentials + pricing, then issue a
screening GO.

Run: python3 -m deadline_reward_v1.capital_event_screening_executor
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
HERE = Path(__file__).resolve().parent
FREEZE_PATH = HERE / 'CAPITAL_EVENT_NODE_SCREENING_FREEZE.json'

EXECUTOR_ENV_FLAG = 'CAPITAL_EVENT_SCREENING_GO'  # does not exist yet


def render_prompt(assignment: dict, model_cfg: dict) -> str:
    """Render the actual prompt for one screening call from the frozen
    plan. Same node input → same prompt content for all 4 models
    (pairing requirement)."""
    parts = [
        '你是一个资本市场事件调查助手。',
        '',
        f'## 任务类型：{assignment["node_type"]}',
        '',
        f'## 任务描述',
        assignment['subtask'],
        '',
        '## 证据文档',
        assignment.get('evidence', '(见附件)'),
        '',
        '## 输出要求',
        f'- 输出格式：JSON',
        f'- 输出契约：{assignment.get("output_contract", "free_form")}',
        f'- 最大输出长度：{assignment.get("max_output_tokens", 700)} tokens',
        '',
        '请严格按照输出要求完成任务。',
    ]
    return '\n'.join(parts)


def render_all() -> dict:
    """Render all 80 prompts from the frozen plan. Returns a dict
    keyed by assignment_id → {prompt, prompt_sha256, model, blocked}."""
    freeze = json.loads(FREEZE_PATH.read_text())
    plan = freeze['plan']
    rendered = {}
    for aid, a in plan['assignments'].items():
        prompt = render_prompt(a, plan['models'].get(a['model_key'], {}))
        rendered[aid] = dict(
            prompt=prompt,
            prompt_sha256=hashlib.sha256(
                prompt.encode()).hexdigest(),
            model_key=a['model_key'],
            model_id=a['model_id'],
            node_type=a['node_type'],
            event=a['event'],
            pairing_id=a['pairing_id'],
            gold_status=a['gold_status'],
            blocked=a.get('blocked', False),
            max_output_tokens=a.get('max_output_tokens', 700))
    return rendered


def verify_pairing(rendered: dict) -> dict:
    """Verify: same pairing_id across models → same prompt content."""
    by_pair = {}
    for aid, r in rendered.items():
        by_pair.setdefault(r['pairing_id'],
                           {})[r['model_key']] = r['prompt_sha256']
    issues = []
    for pid, models in by_pair.items():
        shas = set(models.values())
        if len(shas) > 1:
            issues.append(f'{pid}: {len(shas)} different prompts across '
                          f'{len(models)} models — pairing VIOLATED')
    return dict(pairs=len(by_pair), issues=issues,
               ok=not issues)


def estimate_budget(rendered: dict, pricing: dict) -> dict:
    """Estimate from rendered prompts + a pricing table (per-model
    input/output rates in CNY per million tokens)."""
    from deadline_reward_v1.offline_toolkit import BudgetCalculator
    bc = BudgetCalculator(pricing)
    # rough token estimates from prompt length (Chinese ~1 char ≈ 1 tok)
    per_model = {}
    total_cash = 0.0
    for aid, r in rendered.items():
        est_in = max(200, len(r['prompt']))  # lower-bound estimate
        est_out = r['max_output_tokens']
        mk = r['model_key']
        if mk not in per_model:
            per_model[mk] = dict(calls=0, est_cash=0.0)
        c = bc.estimate_call_cost(mk, est_in, est_out)
        per_model[mk]['calls'] += 1
        per_model[mk]['est_cash'] += c['cash_cny']
        total_cash += c['cash_cny']
    return dict(
        total_calls=len(rendered),
        total_cash_cny=round(total_cash, 4),
        per_model={k: dict(v, est_cash=round(v['est_cash'], 4))
                   for k, v in per_model.items()})


def main():
    rendered = render_all()
    pairing = verify_pairing(rendered)

    # save rendered prompts (audit + future execution input)
    out = HERE / 'CAPITAL_EVENT_SCREENING_PROMPTS.json'
    out.write_text(json.dumps(dict(
        version='CAPITAL_EVENT_SCREENING_PROMPTS_v1',
        n_prompts=len(rendered),
        pairing_check=pairing,
        prompts=rendered), indent=1, ensure_ascii=False))

    print(f'rendered: {len(rendered)} prompts')
    print(f'pairing check: {"PASS" if pairing["ok"] else "FAIL"} '
          f'({pairing["pairs"]} pairs)')
    if pairing['issues']:
        for i in pairing['issues']:
            print(f'  ISSUE: {i}')
    blocked = sum(1 for r in rendered.values() if r['blocked'])
    print(f'blocked (M3/M4 unverified): {blocked}')
    print(f'executable now (M1/M2): {len(rendered) - blocked}')
    print(f'saved: {out}')
    print(f'\nexecutor env flag "{EXECUTOR_ENV_FLAG}" does NOT exist; '
          f'real screening requires operator GO.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
