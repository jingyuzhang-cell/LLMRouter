"""QP5-C V2.1 preregistered analysis (zero calls)."""
import json, sys, random, statistics as st, collections
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
import qp4_factorial as F
import qp3_primitives as P3
import qp5a_pure_prep as PP
import qp2_chain as CH
import scorer_qp1 as Q1
from qp4b_attribution import is_composite
from real_provider_v22 import extract_any


def main():
    d = json.load(open(f'{QP}/QP5C_RESULTS.json'))
    by = {}
    for r in d['results']:
        if not r.get('error'):
            by[(r['task'], r['rep'], r['arm'])] = r
    # ---- primary: task-level paired ΔQ (C2 − C1')
    task_rows = []
    for t in F.TASKS:
        deltas = []
        for rep in (1, 2):
            c1, c2 = by.get((t, rep, 'C1')), by.get((t, rep, 'C2'))
            if c1 and c2:
                deltas.append(c2['q'] - c1['q'])
        task_rows.append(dict(task=t, delta=round(st.mean(deltas), 4) if deltas else None,
                              deltas=[round(x, 4) for x in deltas]))
    deltas = [r['delta'] for r in task_rows if r['delta'] is not None]
    macro = st.mean(deltas)
    pos = sum(1 for x in deltas if x >= 0)
    rng = random.Random(20261103)
    obs = abs(sum(deltas)); hit = 0
    for _ in range(20000):
        s = sum(x if rng.random() < 0.5 else -x for x in deltas)
        if abs(s) >= obs - 1e-12: hit += 1
    p = (hit + 1) / 20001

    # ---- C0 noise ruler (paired cells with identical inputs)
    c0_pairs = []
    for (t, rep), in [(k, ) for k in [(t, rep) for (t, rep, a) in by if a == 'C0' for rep in [rep]]]:
        pass
    c0_cells = [(t, rep) for (t, rep, a) in by if a == 'C0']
    for t, rep in c0_cells:
        c0, c1 = by.get((t, rep, 'C0')), by.get((t, rep, 'C1'))
        if c0 and c1:
            c0_pairs.append(dict(task=t, rep=rep, dq=round(c0['q'] - c1['q'], 4),
                                 abs_dq=round(abs(c0['q'] - c1['q']), 4)))
    noise = [x['abs_dq'] for x in c0_pairs]

    # ---- safety + mechanism (C2 vs C1' pooled)
    def pooled(arm):
        rs = [r for (t, rep, a), r in by.items() if a == arm]
        return dict(
            Q=round(st.mean(r['q'] for r in rs), 4),
            wrong_assert=sum(r['wrong_assert'] for r in rs),
            wrong_cit=sum(r['wrong_cit'] for r in rs),
            abst=sum(r['abst'] for r in rs),
            crit_tp=sum(r['crit_tp'] for r in rs),
            verified_mean=round(st.mean(r['n_verified'] for r in rs), 1),
            gate_pass=sum(1 for r in rs if r['gate'] == 'PASS'))

    # ---- decomposition: E-value correctness, coverage, precision, junk (offline, gold)
    led5c = {}
    for path in (f'{QP}/QP5C_LEDGER.jsonl', f'{QP}/QP4_LEDGER.jsonl'):
        for line in open(path):
            x = json.loads(line)
            led5c.setdefault(x['purpose'], x)
    mech = {}
    for arm in ('C1', 'C2'):
        cov_n = prec_n = prec_d = junk = val_ok = tot = 0
        for t in F.TASKS:
            for rep in (1, 2):
                contract = F.load_contract(t)
                if arm == 'C1':
                    e_texts = [led5c[f'qp4|{t}|D|r{rep}|e0']['text'], led5c[f'qp4|{t}|D|r{rep}|e1']['text']]
                else:
                    e0 = led5c.get(f'qp5c|{t}|C2|r{rep}|e0')
                    e1 = led5c.get(f'qp5c|{t}|C2|r{rep}|e1')
                    r0 = led5c.get(f'qp5c|{t}|C2|R|r{rep}|e0')
                    r1 = led5c.get(f'qp5c|{t}|C2|R|r{rep}|e1')
                    if not e0 or not e1:
                        continue
                    e_texts = [e0['text'], e1['text']]
                    if r0: e_texts[0] = r0['text']
                    if r1: e_texts[1] = r1['text']
                entries = []
                for tx in e_texts:
                    entries += P3.normalize_stage(extract_any(tx))
                verified, _ = CH.verify_evidence(entries, contract)
                bound = 0; ok_val = 0
                for f in contract['required_facts']:
                    tot += 1
                    v = f.get('value')
                    hit_v = False
                    for e in verified:
                        ev = e.get('raw') or e.get('value')
                        if P3.name_matches(e, f) or Q1.value_in_quote(v, e.get('quote', '')):
                            bound += 1
                            if Q1.TQ._value_equal({'value': ev, 'value_kind': f.get('value_kind')}, dict(f)):
                                ok_val += 1
                            hit_v = True
                            break
                    if hit_v:
                        cov_n += 1
                        val_ok += 1 if Q1.TQ._value_equal(
                            {'value': next((e.get('raw') or e.get('value') for e in verified
                                            if P3.name_matches(e, f) or Q1.value_in_quote(v, e.get('quote', ''))), ''),
                             'value_kind': f.get('value_kind')}, dict(f)) else 0
                prec_n += ok_val; prec_d += bound
                junk += len(verified) - bound
        mech[arm] = dict(coverage=round(cov_n / tot, 4), precision=round(prec_n / max(1, prec_d), 4),
                         junk_entries=junk, n_verified_entries=prec_d,
                         e_value_correct=round(val_ok / tot, 4))

    out = dict(batch='QP5C_ANALYSIS', model_calls=0,
               per_task=task_rows, macro_delta=round(macro, 4),
               positive=f'{pos}/{len(deltas)}', signflip_p=round(p, 4),
               c0_noise=dict(pairs=c0_pairs, mean_abs_dQ=round(st.mean(noise), 4) if noise else None),
               pooled=dict(C1=pooled('C1'), C2=pooled('C2'), C0=pooled('C0')),
               decomposition=mech,
               criteria=dict(delta_min=macro >= 0.10, four_of_six=pos >= 4))
    json.dump(out, open(f'{QP}/QP5C_ANALYSIS.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'per_task'}, ensure_ascii=False, indent=1))
    print('per-task:', [(r['task'], r['delta']) for r in task_rows])


if __name__ == '__main__':
    main()
