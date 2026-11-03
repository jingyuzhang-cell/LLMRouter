"""Step3 four-arm input-fairness audit + new-window cost recomputation (zero-call).

Part A — what each arm ACTUALLY saw (from the step3 ledgers + the pre-registered
gate document STEP3_EXECUTION_GATE.md; prompts themselves were only hashed):
  per-call table (purpose -> arm/node), evidence-seen reconstruction, and the
  two fairness verdicts:
    F1 answer-directed windows (evaluation leakage)?
    F2 did A receive raw text the DAG did not?

Part B — recomputed per-strategy cost at unified windows 6000/10000/19000 with
evidence_packer v2 line packs (50/50 per line). Measured bases (NOT the old
600c totals 1277/5031/6548/7174):
  - input density: chars x 0.677 tokens (measured KDX ratio)
  - extract-node measured anchors from the valid e4-v2 runs (8000c/line):
    t1/t2 in ~= 4950 tok, t3/t4 in ~= 2910 tok, t5 ~= 2370, t6 ~= 1100
    (scaled linearly by window/8000; t3-t6 scale with merged-facts size which
    tracks extraction input)
  - output: capability_table_v3 per-node avg output for the assigned model
  - latency: capability-table avg_lat_s scaled by input ratio (estimate)
  - cost: GLM/Flash subscription ¥0; DeepSeek (in*0.30+out*1.20)/1e6*7.1

Output: step3_fairness_v2.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR

P = PILOT_DIR
WINDOWS = [6000, 10000, 19000]
# measured anchors from valid e4-v2 runs at 8000c/line (kdx:B1 / kdx:B3p)
ANCHOR = {'t1': 4950, 't2': 4950, 't3': 2910, 't4': 2910, 't5': 2370, 't6': 1100}
ANCHOR_CHARS = 8000  # per-line chars the anchors were measured at
TEMPLATE_TOK = 80
CAP = json.loads((P / 'capability_table_v3.json').read_text())
KIND = {'t1': 'fact_extraction', 't2': 'fact_extraction', 't3': 'timeline',
        't4': 'entity_relations', 't5': 'crosssource_check', 't6': 'timeline'}
GLM_ALIAS = {'glm53', 'glm53flash'}


def arm_call_table():
    rows = []
    for fname in ('step3_glm_ledger.jsonl', 'step3_s6_glm_ledger.jsonl'):
        for line in open(P / fname):
            if not line.strip():
                continue
            r = json.loads(line)
            rows.append(r)
    mapping = {'s3:1': ('A', 'oneshot'), 's3:2': ('B', 't1'), 's3:3': ('B', 't2'),
               's3:4': ('B', 't3'), 's3:5': ('B', 't4'), 's3:6': ('B', 't5'),
               's3:7': ('B', 't6'), 's3:8': ('S5CG', 't1'), 's3:9': ('S5CG', 't2'),
               's3:10': ('S5CG', 't3'), 's3:11': ('S5CG', 't4'), 's3:12': ('S5CG', 't5'),
               's3:13': ('S5CG', 't6'), 's3:15': ('S6', 't2'), 's3:16': ('S6', 't3'),
               's6fin:1': ('S6', 't4'), 's6fin:3': ('S6', 't6')}
    out = []
    for r in rows:
        key = r['purpose'].rsplit(':', 1)[0]  # strip ':model' suffix -> 's3:1' / 's6fin:1'
        arm, node = mapping.get(key, ('UNMAPPED', r['purpose']))
        out.append({'purpose': r['purpose'], 'arm': arm, 'node': node,
                    'model': r['model_alias'], 'prompt_chars': r['prompt_chars'],
                    'in_tok': r['usage']['input_tokens'], 'out_tok': r['usage']['output_tokens'],
                    'lat_s': r['latency_s']})
    return out


def evidence_seen_verdicts():
    return {
        'window_design': ('Step3 gate pre-registered ANSWER-DIRECTED windows: t1 = D5 chunk '
                          'containing RF1 (60万元罚款), t2 = D1 chunk containing RF4 (北京银行协议), '
                          '~600c per line'),
        'F1_answer_directed_windows_leakage': True,
        'F1_detail': ('windows were chosen BY the T1 answer positions — inflates absolute T1 for '
                      'ALL arms; forbidden by the v2 rule (task-term ranking only); Step3 T1 '
                      'numbers must be read as input-limited, not model-quality'),
        'F2_A_extra_raw_text': ('A saw the UNION of both 600c windows as raw text in one prompt '
                                '(prompt_chars=1300); the DAG extraction nodes saw the same two '
                                'windows separately, but DAG downstream nodes (t3-t6) saw ONLY '
                                'merged facts, never raw text. So: A received no raw text beyond '
                                "the extract nodes' inputs, but DID see raw evidence end-to-end — "
                                'the structural single-model counterfactual.'),
        'A_prompt_chars_evidence': 'A=1300c vs t1=~752c + t2=~406c templates included',
    }


def strategy_specs():
    """Model assignment per arm under the pre-registered F5 fault (t1/t5 GLM blocked).
    S5+Cap: fixed recovery scope + light Q/C/L table lookup (per e2_s6_ablation:
    t1->flash quality-tie list order, t5->deepseek)."""
    base = {'t1': 'glm53', 't2': 'glm53', 't3': 'glm53', 't4': 'glm53',
            't5': 'glm53', 't6': 'glm53'}
    f5 = dict(base, t1='glm53flash', t5='glm53flash')            # S5+CG fixed rule
    s5cap = dict(base, t1='glm53flash', t5='deepseek')           # S5+Cap table lookup
    s6 = dict(base, t1='deepseek', t5='deepseek')                # S6 joint
    return {'A': None, 'B': base, 'S5CG': f5, 'S5Cap': s5cap, 'S6': s6}


def cap_cell(node, alias):
    return CAP.get(f'{KIND[node]}|{alias}', {'avg_tokens': 900, 'avg_lat_s': 6.0,
                                             'avg_output': 5})


def node_input_tok(node, w):
    scale = w / ANCHOR_CHARS
    return int(ANCHOR[node] * scale) + TEMPLATE_TOK


def lat_est(node, alias, in_tok):
    """Measured-anchor latency estimate (s): fixed base + linear token term.
    Rates from the unpolluted e4-v2/earlier measured calls: GLM extract
    4888tok->17-28s, DS extract 5020tok->9s, GLM mid 2900tok->9-15s.
    Model: GLM/Flash lat = 3 + in/300; DS lat = 1 + in/800."""
    rate = 800 if alias == 'deepseek' else 300
    base = 1 if alias == 'deepseek' else 3
    return base + in_tok / rate


def recompute(w):
    """Per-strategy estimates at unified global window w (per line w/2 chars)."""
    res = {}
    per_line_tok = {n: node_input_tok(n, w) for n in ANCHOR}
    for name, pi in strategy_specs().items():
        if name == 'A':
            in_tok = per_line_tok['t1'] + per_line_tok['t2']  # union pack, one prompt
            out_tok = 1200
            lat = lat_est('t6', 'glm53', in_tok)
            cash = 0.0
            calls = 1
        else:
            in_tok = out_tok = 0
            cash = 0.0
            for n in ANCHOR:
                m = pi[n]
                it = per_line_tok[n]
                ot = min(int(cap_cell(n, m)['avg_output'] * 120), 2500)
                in_tok += it
                out_tok += ot
                if m == 'deepseek':
                    cash += (it * 0.30 + ot * 1.20) / 1e6 * 7.1
            # parallel critical path: max(t1,t2) + max(t3,t4) + t5 + t6
            lat = (max(lat_est('t1', pi['t1'], per_line_tok['t1']),
                       lat_est('t2', pi['t2'], per_line_tok['t2']))
                   + max(lat_est('t3', pi['t3'], per_line_tok['t3']),
                         lat_est('t4', pi['t4'], per_line_tok['t4']))
                   + lat_est('t5', pi['t5'], per_line_tok['t5'])
                   + lat_est('t6', pi['t6'], per_line_tok['t6']))
            calls = 6
        res[name] = {'calls': calls, 'in_tok': in_tok, 'out_tok_est': out_tok,
                     'total_tok_est': in_tok + out_tok,
                     'cash_rmb_est': round(cash, 4),
                     'wall_s_est': round(lat, 1),
                     'deadline_30s_feasible_est': lat <= 30.0,
                     'deadline_60s_feasible_est': lat <= 60.0}
    return res


def main():
    out = {'date': '2026-10-14', 'part_a': {
        'calls': arm_call_table(),
        'evidence_verdicts': evidence_seen_verdicts()},
        'part_b': {str(w): recompute(w) for w in WINDOWS}}
    (P / 'step3_fairness_v2.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('== Part A: step3 calls by arm ==')
    for c in out['part_a']['calls']:
        print(f"  {c['purpose']:12s} {c['arm']:6s} {c['node']:7s} {c['model']:12s} "
              f"in={c['in_tok']:5d} prompt_chars={c['prompt_chars']:5d}")
    print('\n== Part B: recomputed estimates at unified windows (e4-v2 measured anchors) ==')
    for w in WINDOWS:
        print(f'  window {w}:')
        for name, r in out['part_b'][str(w)].items():
            print(f"    {name:6s} calls={r['calls']} in={r['in_tok']:6d} tot={r['total_tok_est']:6d} "
                  f"¥{r['cash_rmb_est']:.4f} wall~{r['wall_s_est']}s "
                  f"30s:{r['deadline_30s_feasible_est']} 60s:{r['deadline_60s_feasible_est']}")
    print('saved step3_fairness_v2.json')


if __name__ == '__main__':
    main()
