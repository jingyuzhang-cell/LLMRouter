#!/usr/bin/env python3
"""Stage A-1/A-2: A1 指标定义核实 + 16 对逐项差值分解（零调用）。"""
import json, glob, sys, copy
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1/quality_v4')
from executor import extract_json, apply_format_rules, build_terminal_output
from terminal_quality import evaluate_terminal_quality

BASE = '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/'
CON = {}
for label, f in (('old', 'TASK_CONTRACT_PHASE2B_v2_1.json'), ('v3', 'TASK_CONTRACT_PHASE2B_v3_DRAFT.json')):
    c = json.load(open(BASE + f))
    src = c.pop('source_pages')
    CON[label] = (c, src)
MAP = {'E1': 'D1', 'E2': 'D2', 'E3': 'D3', 'E4': 'D4'}


def score(parsed, contract, relabel=False):
    if parsed is None:
        return {'tp': 0, 'full': 0.0}
    pf = json.loads(json.dumps(parsed))
    if relabel:
        for a in pf.get('answers', []):
            if str(a.get('doc')) in MAP:
                a['doc'] = MAP[str(a['doc'])]
    try:
        term = build_terminal_output(apply_format_rules(pf)[0])
    except Exception:
        return {'tp': 0, 'full': 0.0}
    c, src = CON[contract]
    q = evaluate_terminal_quality(copy.deepcopy(c), term, src)
    tp = sum(1 for x in q['claim_results'] if x['status'].startswith('CORRECT'))
    full = sum(1 for x in q['claim_results'] if x['status'] == 'CORRECT_GOLD')
    n = max(len(q['claim_results']), 1)
    return {'tp': tp, 'full': round(full / n, 4)}


out = {}
for p in glob.glob('/root/research_outputs/static_pi/stage_d/runs_final/*.json'):
    d = json.load(open(p))
    if 'exec_id' not in d:
        continue
    st = [n['text'] for n in (d.get('raw', {}).get('nodes', {}).get('SINK') or []) if n.get('text')]
    parsed = extract_json(st[-1]) if st else None
    r_old = score(parsed, 'old', False)
    r_a1 = score(parsed, 'old', True)
    r_v3 = score(parsed, 'v3', False)
    out[d['exec_id']] = {'exec_old_tp': d['tp'], 'recompute_old_tp': r_old['tp'],
                         'a1_tp': r_a1['tp'], 'a1_full': r_a1['full'],
                         'v3_tp': r_v3['tp']}

json.dump(out, open('/root/research_outputs/static_pi/stage_d/runs_final/PAIRWISE_METRIC_DECOMPOSITION.json', 'w'),
          ensure_ascii=False, indent=1)

same = sum(1 for v in out.values() if v['a1_tp'] == v['recompute_old_tp'])
diff = [(k, v['recompute_old_tp'], v['a1_tp']) for k, v in out.items() if v['a1_tp'] != v['recompute_old_tp']]
print(f'A1_TP == 重算old_TP: {same}/192；不等 {len(diff)} 例')
for x in diff[:10]:
    print('  不等:', x)
d2 = [(k, v['exec_old_tp'], v['recompute_old_tp']) for k, v in out.items()
      if v['exec_old_tp'] != v['recompute_old_tp']]
print(f'执行器old_TP != 重算old_TP: {len(d2)} 例')
for x in d2[:10]:
    print('  差异:', x)
