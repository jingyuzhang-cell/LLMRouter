"""Six-arm unified execution contract (V2.3): the evidence directive is one
constant, appended identically to every arm's SINK prompt. No arm parameter.

This module does not run anything; it only builds prompt text. Prompt assembly
for the real pipeline will import `evidence_directive()` so that Z / Joint can
never receive a different evidence contract than Static arms.
"""
import hashlib

VERSION = 'v23-1'

EVIDENCE_DIRECTIVE = (
    '证据与输出要求（本要求对全部执行策略完全相同，不得省略）：\n'
    '1) 每个答案必须给出 doc、page、quote 三个字段；doc 只能是 D1/D2/D3/D4。\n'
    '2) quote 必须是被引文书中连续出现的一段原文，逐字复制；禁止使用省略号、'
    '禁止把不连续的片段拼接起来。\n'
    '3) quote 必须真正支持该 fact_id 所问的事实，不能只是出现在同一份文书里。\n'
    '4) 一个事实给一条引文；若必须跨段才能支持，请只引用最关键的那一段连续原文。\n'
    '5) 无法从材料判定的条目放入 abstentions，写清拒答理由；不得为了满足引用要求编造证据。\n'
    '6) 只输出 JSON，不输出解释性文字。'
)


def evidence_directive():
    """Arm-independent by construction."""
    return EVIDENCE_DIRECTIVE


def apply_to_system(system_prompt):
    return (system_prompt or '') + '\n\n' + evidence_directive()


def contract_sha256():
    payload = (VERSION + '\n' + EVIDENCE_DIRECTIVE).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def prompt_fingerprint(arm, system_prompt, user_prompt):
    """Fingerprint of (arm, assembled prompt). The evidence block itself must be
    identical across arms; only the arm label may differ in bookkeeping."""
    h = hashlib.sha256()
    h.update(arm.encode())
    h.update(b'\x00')
    h.update(apply_to_system(system_prompt).encode())
    h.update(b'\x00')
    h.update((user_prompt or '').encode())
    return h.hexdigest()


def evidence_violations(answer):
    """Pre-scoring contract gate. Reports, never repairs, evidence violations.
    Returns a list of violation codes (empty = complies)."""
    out = []
    if not isinstance(answer, dict):
        return ['not_object']
    doc = str(answer.get('doc') or '')
    if doc not in ('D1', 'D2', 'D3', 'D4'):
        out.append('nonstandard_doc')
    page = answer.get('page')
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        out.append('bad_page')
    quote = answer.get('quote')
    if not isinstance(quote, str) or len(quote.strip()) < 4:
        out.append('missing_quote')
    else:
        if '…' in quote or '...' in quote:
            out.append('elided_quote')
    return out
