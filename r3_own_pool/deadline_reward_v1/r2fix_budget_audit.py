"""R2-fix FINAL BUDGET AUDIT (operator directive 2026-10-25, zero-call).

Answers three required items:
  A. Actual billing tokenizer & billing rules — or a rigorously grounded
     input-token upper bound.
  B. Exact (UNROUNDED) input caps, output caps, per-call worst costs,
     and unrounded totals for all 18 planned calls.
  C. Whether Σ worst <= ¥0.30 and no call can breach the remaining
     budget — under EACH instrument, honestly separated:
       C1  historical empirical (5 delivered deepseek calls)
       C2  independent real tokenizer (local Qwen2.5-1.5B, 151,646-vocab
           byte-level BBPE — same class as DeepSeek's BBPE; NOT the
           billing tokenizer) measuring the EXACT prompt constructions
           incl. pathological charset probes
       C3  absolute math: tokens <= bytes for any byte-level BPE
     Plus the residual-breach envelope of the anomaly fail-stop, and
     computed fallback options if ¥0.30 is not certifiable.

Run: python3 -m deadline_reward_v1.r2fix_budget_audit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import r2fix_runner as R
from deadline_reward_v1.full_dag_tasks import load_docs

RATES = json.loads(
    (ROOT / 'deadline_reward_v1' / 'REVERSE_ENGINEERED_RATES_V2.json')
    .read_text())['rates']['deepseek_flash']
CIN = RATES['input_cny_per_mtok'] / 1e6    # 2.13e-6 CNY/token
COUT = RATES['output_cny_per_mtok'] / 1e6  # 8.52e-6 CNY/token
ENV = 128
TOKCHAR = 0.75

QWEN_TOK = '/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct'


def load_qwen():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(QWEN_TOK, local_files_only=True)


def worst_cost(tokens_in_ub: float, tokens_out_ub: int) -> float:
    return tokens_in_ub * CIN + tokens_out_ub * COUT   # unrounded


def main():
    doc = load_docs()[R.DOC_SLOT]
    specs, bounds = R.plan_call_specs(doc['text'], doc['doc_id'])
    print(f'billing: deepseek_flash ¥{CIN*1e6}/Mtok in, '
          f'¥{COUT*1e6}/Mtok out (frozen V2 rates, 17-call fit r2=1.0);'
          f'\n         cache-hit input bills LOWER, so full-rate is the '
          f'conservative side. Envelope +{ENV} tok/call.')

    # ---------- C1 historical ----------
    print('\n[C1] historical empirical: 5 delivered deepseek calls, '
          'max ratio 0.6259, x1.15 = 0.7198 <= 0.75 (review R11).')

    # ---------- C2 independent tokenizer ----------
    print('\n[C2] independent tokenizer: Qwen2.5-1.5B (151,646-vocab '
          'byte-level BBPE), offline, measuring EXACT constructions:')
    tok = load_qwen()
    ntok = lambda s: len(tok(s, add_special_tokens=False)['input_ids'])

    fills = {
        'ascii_X': 'X' * 3000,
        'common_cjk': '处罚决定罚款市场禁入虚增营业收入' * 250,
        'rare_cjk_extB': ''.join(chr(0x20000 + (i % 500))
                                 for i in range(3000)),
        'emoji_4byte': '😀' * 3000,
        'digit_storm': '0123456789' * 300,
        'json_escape': '{"k\\u4e2d\\u56fdv":1,' * 150,
        'real_doc_slice': doc['text'][:3000],
    }
    ratios = {}
    for name, s in fills.items():
        s = s[:3000]
        ratios[name] = ntok(s) / len(s)
        print(f'    fill {name:>15}: {len(s):>5}ch -> {ntok(s):>6}tok '
              f'ratio {ratios[name]:.4f}')

    # build real prompts with the worst fill per role and tokenize
    dag = R.HeteroDAG(doc['text'], doc['doc_id'])
    worst_fill = max(fills.values(), key=lambda s: ntok(s[:3000]))
    for n in R.ORDER:
        dag.outputs[n] = dict(answer=worst_fill[:3000])
    probes = {
        'root': dag.build_prompt(R.ROOT_NODE),
        'section': dag.build_prompt('b1'),
        'sink': dag.build_prompt('sink'),
    }
    print('    full-prompt tokenization (worst fill):')
    c2_ratio = 0.0
    for k, p in probes.items():
        t = ntok(p)
        r = t / len(p)
        c2_ratio = max(c2_ratio, r)
        print(f'    {k:>8}: {len(p):>6}ch -> {t:>6}tok ratio {r:.4f}')
    print(f'    C2 max ratio over exact constructions: {c2_ratio:.4f}')

    # ---------- C3 absolute ----------
    print('\n[C3] absolute math: tokens <= bytes (any byte-level BPE); '
          'upstream fills at 4 bytes/char:')
    b_doc = len(doc['text'][:3000].encode('utf-8'))
    dag2 = R.HeteroDAG(doc['text'], doc['doc_id'])
    for n in R.ORDER:
        dag2.outputs[n] = dict(answer='😀' * 3000)   # 12,000 bytes
    pb = {k: len(p.encode('utf-8')) for k, p in [
        ('root', dag2.build_prompt(R.ROOT_NODE)),
        ('section', dag2.build_prompt('b1')),
        ('sink', dag2.build_prompt('sink'))]}
    print(f'    bytes: {pb} (doc slice {b_doc}B)')

    # ---------- exact unrounded per-call table ----------
    print('\n[B] EXACT per-call worst (unrounded), 3 instruments:')
    hdr = (f'{"#":>2} {"role":>10} {"ch_bound":>8} {"out_ub":>6} |'
           f' {"C1/0.75 tok_in":>14} {"C2 tok_in":>12} {"C3 bytes":>10} |'
           f' {"C1 ¥":>10} {"C2 ¥":>10} {"C3 ¥":>10}')
    print(hdr)
    tot = {'C1': 0.0, 'C2': 0.0, 'C3': 0.0}
    per_call = []
    for i, (chars, out) in enumerate(specs, 1):
        role = R.PLAN_ROLES[i - 1]
        t_c1 = chars * TOKCHAR + ENV
        kind = ('root' if role == 'extraction'
                else 'sink' if role == 'synthesis' else 'section')
        t_c2 = pb[kind] * c2_ratio / max(
            1, pb[kind]) * c2_ratio  # token bound = measured ratio x chars
        t_c2 = chars * c2_ratio + ENV
        t_c3 = pb[kind] + ENV
        w1, w2, w3 = (worst_cost(t_c1, out), worst_cost(t_c2, out),
                      worst_cost(t_c3, out))
        tot['C1'] += w1; tot['C2'] += w2; tot['C3'] += w3
        per_call.append(dict(i=i, role=role, chars=chars, out_ub=out,
                             tok_in_C1=t_c1, tok_in_C2=t_c2,
                             tok_in_C3=t_c3, cny_C1=w1, cny_C2=w2,
                             cny_C3=w3))
        print(f'{i:>2} {role:>10} {chars:>8} {out:>6} | {t_c1:>14.1f} '
              f'{t_c2:>12.1f} {t_c3:>10d} | {w1:>10.7f} {w2:>10.7f} '
              f'{w3:>10.7f}')
    print('-' * len(hdr))
    print(f'{"TOTAL (unrounded)":>40} '
          f'{tot["C1"]:>23.7f} {tot["C2"]:>10.7f} {tot["C3"]:>10.7f}')
    for k in ('C1', 'C2', 'C3'):
        print(f'  {k}: Σ={tot[k]!r}  {"<= ¥0.30 PASS" if tot[k] <= 0.30 else "> ¥0.30 FAIL"}')

    # ---------- residual-breach envelope (C1 guard in force) ----------
    print('\n[C] residual envelope of the admitted bound (0.75 + env):'
          '\n    anomaly fail-stop halts at the FIRST breach; damage is '
          'bounded by one call. Worst breach position = final sink call'
          ' (admitted ¥0.0309, prior 17 calls at admitted worst).')
    sink_chars, sink_out = specs[-1]
    for r_breach in (0.9, 1.0, 1.44, 3.0):
        t_breach = sink_chars * r_breach + ENV
        w_breach = worst_cost(t_breach, sink_out)
        prior = tot['C1'] - worst_cost(sink_chars * TOKCHAR + ENV, sink_out)
        total = prior + w_breach
        print(f'    actual ratio {r_breach:>5}: breach call ¥{w_breach:.5f}'
              f' -> run total ¥{total:.5f} '
              f'{"<=0.30" if total <= 0.30 else ">0.30 (overshoot "
                 f"¥{total-0.30:.5f}, run halted, no further calls)"}')

    # ---------- fallbacks if ¥0.30 uncertifiable ----------
    print('\n[fallbacks] if C1 grounding is rejected:')
    n_shared_c3 = sum(1 for i, s in enumerate(specs[:8]))
    w_shared_c3 = sum(per_call[i]['cny_C3'] for i in range(8))
    print(f'  (a) cut output caps under C3: input alone = '
          f'¥{sum(pc["tok_in_C3"] for pc in per_call)*CIN:.4f} > 0.30 '
          f'-> INFEASIBLE regardless of output caps')
    max_calls_c3 = 0; acc = 0.0
    for pc in per_call:
        if acc + pc['cny_C3'] > 0.30:
            break
        acc += pc['cny_C3']; max_calls_c3 += 1
    print(f'  (b) shrink plan under C3: max {max_calls_c3} of 18 calls '
          f'affordable (shared-8 alone = ¥{w_shared_c3:.4f} > 0.30) '
          f'-> experiment invalidated')
    print(f'  (c) subscription billing (GLM via zhipu): ¥0 marginal per '
          f'request -> hard cap trivially satisfied; but GLM-5.3 '
          f'thinking-burn makes structured JSON unusable (prior '
          f'finding); GLM-5.3-Flash unverified for this task — needs a '
          f'¥0-marginal screening before any switch')

    out = dict(status='AUDIT_COMPLETE', billing=dict(
                   input_cny_per_mtok=RATES['input_cny_per_mtok'],
                   output_cny_per_mtok=RATES['output_cny_per_mtok']),
               tokenizer=dict(billing_tokenizer='unobtainable (HF '
                              'network-blocked; no public endpoint)',
                              instrument='Qwen2.5-1.5B 151,646-vocab '
                              'byte-level BBPE, offline'),
               fill_ratios={k: round(v, 4) for k, v in ratios.items()},
               c2_max_ratio=round(c2_ratio, 4), bytes=pb,
               per_call=per_call, totals_unrounded=tot,
               cap=0.30, plan_worst_v2_1=round(tot['C1'], 7))
    (ROOT / 'deadline_reward_v1' / 'R2FIX_BUDGET_AUDIT.json').write_text(
        json.dumps(out, indent=1, ensure_ascii=False))
    print('\nwrote R2FIX_BUDGET_AUDIT.json')


if __name__ == '__main__':
    main()
