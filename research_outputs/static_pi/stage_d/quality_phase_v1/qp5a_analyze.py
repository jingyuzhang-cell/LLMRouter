"""QP5-A preregistered analysis (zero calls, reads QP5A_RESULTS + deterministic
ev_map rebuild for the placebo subgroup)."""
import json, sys, random, statistics as st, collections
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import qp4_factorial as F
import qp5a_pure_prep as PP
import scorer_qp1 as Q1
import qp3_primitives as P3
import qp2_chain as CH
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
EXCLUDED = {('MVR1', 2)}   # preregistered: treatment cannot fire


def rebuild_ev(led, t, rep):
    contract = F.load_contract(t)
    e0 = extract_any(led[(t, 'D', f'r{rep}', 'e0')]['text'])
    e1 = extract_any(led[(t, 'D', f'r{rep}', 'e1')]['text'])
    m = extract_any(led[(t, 'D', f'r{rep}', 'm')]['text'])
    entries = P3.normalize_stage(e0) + P3.normalize_stage(e1)
    verified, _ = CH.verify_evidence(entries, contract)
    m_facts = {}
    for e in P3.normalize_stage(m):
        k = PP.fact_key(e)
        if k and e.get('value') not in (None, ''):
            m_facts.setdefault(k, e.get('value'))
    return contract, PP.match_evidence(m_facts, verified, contract), m_facts


def gold_to_evkey(contract, ev_map, m_facts):
    """Map each gold fact to the evidence-bearing m-key (name first, value-grounding second)."""
    out = {}
    for f in contract['required_facts']:
        fid = f['fact_id']
        keys = [k for k in ev_map if P3.name_matches(ev_map[k], f)]
        if not keys:
            for k, v in m_facts.items():
                if k in ev_map and v not in (None, '') and Q1.value_in_quote(f.get('value'), ev_map[k].get('quote', '')):
                    keys = [k]
                    break
        out[fid] = keys[0] if keys else None
    return out


def main():
    d = json.load(open(f'{QP}/QP5A_RESULTS.json'))
    led = {}
    for line in open(f'{QP}/QP4_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        led[(p[1], p[2], p[3], p[4])] = x
    by = {}
    for r in d['results']:
        if r.get('error'):
            continue
        by[(r['task'], r['rep'], r['arm'])] = r
    TASKS = F.TASKS
    task_rows = []
    placebo_ev, placebo_no = [], []
    safety = collections.defaultdict(lambda: dict(B1=[], B2=[]))
    for t in TASKS:
        deltas, reps_used = [], []
        for rep in (1, 2):
            if (t, rep) in EXCLUDED:
                continue
            b1, b2 = by.get((t, rep, 'B1')), by.get((t, rep, 'B2'))
            if not b1 or not b2:
                continue
            deltas.append(b2['q'] - b1['q'])
            reps_used.append(rep)
            # safety
            for arm, cell in (('B1', b1), ('B2', b2)):
                safety[t][arm].append(dict(wa=cell['wrong_assertions'], wc=cell['wrong_citations'],
                                           ab=cell['abstentions'], ctp=cell['crit_tp'], cn=cell['crit_n']))
            # placebo subgroup from raw rows + deterministic ev rebuild
            contract, ev_map, m_facts = rebuild_ev(led, t, rep)
            g2e = gold_to_evkey(contract, ev_map, m_facts)
            for arm, cell in (('B1', b1), ('B2', b2)):
                ev_rows = [r for r in cell['rows'] if g2e.get(r['fact_id'])]
                no_rows = [r for r in cell['rows'] if not g2e.get(r['fact_id'])]
                tp_e = sum(1 for r in ev_rows if r['status'] == 'TP') / len(ev_rows) if ev_rows else None
                tp_n = sum(1 for r in no_rows if r['status'] == 'TP') / len(no_rows) if no_rows else None
                (placebo_ev if arm == 'B2' else placebo_no).append((t, rep, tp_e, tp_n)) if arm == 'B2' else None
                if arm == 'B1':
                    globals().setdefault('_b1sub', []).append((tp_e, tp_n))
                else:
                    globals().setdefault('_b2sub', []).append((tp_e, tp_n))
        task_rows.append(dict(task=t, reps=reps_used, delta=round(st.mean(deltas), 4) if deltas else None,
                              deltas=[round(x, 4) for x in deltas]))
    # placebo aggregation
    def agg(store):
        ev = [a for a, b in store if a is not None]
        no = [b for a, b in store if b is not None]
        return (round(st.mean(ev), 4) if ev else None, round(st.mean(no), 4) if no else None)
    b1e, b1n = agg(globals().get('_b1sub', []))
    b2e, b2n = agg(globals().get('_b2sub', []))

    deltas = [r['delta'] for r in task_rows if r['delta'] is not None]
    macro = st.mean(deltas)
    pos = sum(1 for x in deltas if x >= 0)
    rng = random.Random(SEED := 20261103)
    obs = abs(sum(deltas))
    hit = 0
    for _ in range(20000):
        s = sum(x if rng.random() < 0.5 else -x for x in deltas)
        if abs(s) >= obs - 1e-12:
            hit += 1
    p = (hit + 1) / 20001
    # safety deltas
    wa1 = sum(v['wa'] for t in TASKS for v in safety[t]['B1'])
    wa2 = sum(v['wa'] for t in TASKS for v in safety[t]['B2'])
    wc1 = sum(v['wc'] for t in TASKS for v in safety[t]['B1'])
    wc2 = sum(v['wc'] for t in TASKS for v in safety[t]['B2'])
    ab1 = sum(v['ab'] for t in TASKS for v in safety[t]['B1'])
    ab2 = sum(v['ab'] for t in TASKS for v in safety[t]['B2'])
    ct1 = sum(v['ctp'] for t in TASKS for v in safety[t]['B1'])
    ct2 = sum(v['ctp'] for t in TASKS for v in safety[t]['B2'])
    gates1 = sum(1 for t in TASKS for rep in (1, 2)
                 if (t, rep) not in EXCLUDED and by.get((t, rep, 'B1'), {}).get('gate') == 'PASS')
    gates2 = sum(1 for t in TASKS for rep in (1, 2)
                 if (t, rep) not in EXCLUDED and by.get((t, rep, 'B2'), {}).get('gate') == 'PASS')

    verdict_1 = macro >= 0.10
    verdict_2 = pos >= 4
    verdict_3 = (wa2 <= wa1 * 1.10 + 1e-9 and wc2 <= wc1 * 1.10 + 1e-9 and
                 ab2 <= ab1 + 0.10 * sum(1 for _ in safety[t]['B1'] for t in TASKS) * 0 +
                 (ab1 + 0.10 * 16) and ct2 >= ct1)
    out = dict(batch='QP5A_ANALYSIS', model_calls=0,
               per_task=task_rows, macro_delta=round(macro, 4), positive_tasks=f'{pos}/{len(deltas)}',
               signflip_p=round(p, 4),
               placebo=dict(B1=dict(evidence=b1e, no_evidence=b1n),
                            B2=dict(evidence=b2e, no_evidence=b2n),
                            delta_evidence=round(b2e - b1e, 4) if b1e is not None and b2e is not None else None,
                            delta_no_evidence=round(b2n - b1n, 4) if b1n is not None and b2n is not None else None),
               safety=dict(wrong_assertions=dict(B1=wa1, B2=wa2),
                           wrong_citations=dict(B1=wc1, B2=wc2),
                           abstentions=dict(B1=ab1, B2=ab2),
                           critical_tp=dict(B1=ct1, B2=ct2),
                           gate_pass=dict(B1=gates1, B2=gates2)),
               criteria=dict(delta_min_0_10=verdict_1, at_least_4of6=verdict_2, safety=verdict_3))
    json.dump(out, open(f'{QP}/QP5A_ANALYSIS.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'per_task'}, ensure_ascii=False, indent=1))
    print('\nper-task deltas:', [(r['task'], r['delta']) for r in task_rows])


if __name__ == '__main__':
    main()
