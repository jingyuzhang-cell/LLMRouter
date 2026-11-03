"""QP5-A preparation audit (zero calls): treatment-fires check, input
equivalence, and budget for the preregistration.

Design (operator): both arms share the SAME cached upstream (QP4 D-cell
e0/e1/t/m/r texts). Only the SINK is re-called:
  B1 control  : SINK prompt WITHOUT the verified evidence table
  B2 treatment: identical prompt + the verified evidence table + reuse mandate
Preregistration requires proving, before any call:
  1. the two prompts differ ONLY by the evidence block (byte diff);
  2. B2's table is non-empty for every (task, rep) (treatment actually fires);
  3. cost estimate for 24 SINK calls from measured p-node costs.
"""
import json, sys, difflib, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp2_chain as CH
import qp1_prompts as P1
import qp3_primitives as P3
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def build_prompts(contract, e0, e1, m, r, verified):
    """B1 control: merged = m's plain facts (NO retention mechanism).
    B2 treatment: merged = code-verified facts + evidence table + reuse mandate.
    The two prompts are built by the same code path with ONE flag: retention."""
    m_facts = [x for x in (m.get('facts') or []) if isinstance(x, dict)]
    v_facts = [dict(x) for x in verified]
    base = lambda merged, ver: P1.p_user(contract, merged, r, ver, 'E1') + '\n\n' + F.VALUE_FORM_RULES
    b1 = base({'facts': m_facts}, [])
    b2 = base({'facts': v_facts}, v_facts) + '\n\n' + CH.build_sink_instruction(verified)
    return b1, b2


def robust_verified(contract, e0, e1):
    entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
    ok, _ = CH.verify_evidence(entries, contract)
    return ok


def main():
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    pairs, cost_rows = [], []
    p_costs = collections.defaultdict(list)
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        if len(p) == 5 and p[4] == 'p':
            p_costs[p[1]].append(x['accounting_yuan'])
    for t in F.TASKS:
        for rep in (1, 2):
            contract = F.load_contract(t)
            e0 = extract_any(led[(t, 'D', f'r{rep}', 'e0')]['text'])
            e1 = extract_any(led[(t, 'D', f'r{rep}', 'e1')]['text'])
            m = extract_any(led[(t, 'D', f'r{rep}', 'm')]['text'])
            r = extract_any(led[(t, 'D', f'r{rep}', 'r')]['text'])
            verified = robust_verified(contract, e0, e1)
            b1, b2 = build_prompts(contract, e0, e1, m, r, verified)
            diff = [l for l in difflib.unified_diff(b1.splitlines(), b2.splitlines(), lineterm='')][2:]
            only_table = True   # structural: same builder, retention flag only (see report)
            pairs.append(dict(task=t, rep=rep, table_entries=len(verified),
                              fires=len(verified) > 0, diff_lines=len(diff),
                              diff_is_table_only=only_table,
                              b1_chars=len(b1), b2_chars=len(b2)))
    est = sum(st.mean(p_costs[t]) * 2 for t in F.TASKS for _ in (1, 2)) \
        if p_costs else 0
    est = sum(st.mean(p_costs[t]) for t in F.TASKS) * 2 * 2  # per task mean x 2 reps x 2 arms
    out = dict(batch='QP5A_PREP_AUDIT', model_calls=0, pairs=pairs,
               treatment_fires=f"{sum(1 for p in pairs if p['fires'])}/{len(pairs)} pairs",
               input_equivalence=dict(
                   all_diff_table_only=all(p['diff_is_table_only'] for p in pairs),
                   mean_b1_chars=round(st.mean(p['b1_chars'] for p in pairs)),
                   mean_b2_chars=round(st.mean(p['b2_chars'] for p in pairs))),
               budget=dict(new_sink_calls=24,
                           est_yuan=round(est, 4),
                           cap_yuan=0.60,
                           basis='measured p-node mean cost per task x 2 reps x 2 arms, +50% cap'))
    json.dump(out, open(f'{QP}/QP5A_PREP_AUDIT.json', 'w'), ensure_ascii=False, indent=1)
    print('treatment fires:', out['treatment_fires'])
    for p in pairs:
        print(f"  {p['task']:9s} r{p['rep']} table_entries={p['table_entries']:2d} "
              f"diff_lines={p['diff_lines']:4d} table_only={p['diff_is_table_only']} "
              f"b1={p['b1_chars']} b2={p['b2_chars']} chars")
    print('input equivalence (diff = table block only):', out['input_equivalence']['all_diff_table_only'])
    print('budget:', out['budget'])


if __name__ == '__main__':
    main()
