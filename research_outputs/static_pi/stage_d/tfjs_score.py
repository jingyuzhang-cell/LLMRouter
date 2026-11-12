#!/usr/bin/env python3
"""TFJS scorer (ZERO model calls).

Metrics (operator table):
  Q_merge  : gold-slot hit rate on adopted merge facts (unchanged V1/V2 rule)
  Q_report : gold-slot hit rate on terminal report facts
  ES       : citation location accuracy (valid doc + verbatim quote in that doc)
  Support  : among report facts that hit a gold slot, fraction whose quote
             verbatim-contains that gold slot's quote span (declared proxy:
             "citation anchors the assertion to the right evidence")
  C / L    : calls+yuan per arm from ledger; arm span (recovery+verify+report)
  JointSuccess : Q_report>=0.5 AND deadline met
"""
import json, re
from pathlib import Path
from rq2_p2r_runner import parse_facts
from rq_dajf2_score import GOLD, norm, slot_hits, evidence_support, adopted_merge_facts

HERE = Path(__file__).parent
RUNS = HERE / 'tfjs_runs'
G1_SETS = [('rq_dajf_runs', 'DA-JS-v1', 'persistent', 1),
           ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 2),
           ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 3),
           ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 1),
           ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 2),
           ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 3)]


def support(report_facts):
    dictfacts = [x for x in report_facts if isinstance(x, dict)]
    hit_facts = []
    for x in dictfacts:
        blob = norm(str(x.get('value', '')) + str(x.get('quote', '')))
        for c in GOLD:
            gq = norm(c.get('quote') or '')
            gv = norm(c.get('value') or '')
            if (gq and gq in blob) or (len(gv) >= 6 and gv in blob):
                hit_facts.append((x, c))
                break
    if not hit_facts:
        return None, 0
    ok = sum(1 for x, c in hit_facts
             if norm(c.get('quote') or '') and norm(c['quote']) in norm(str(x.get('quote', ''))))
    return ok / len(hit_facts), len(hit_facts)


def report_metrics(rf):
    hr, n = slot_hits(rf)
    es, _ = evidence_support(rf)
    sup, nsup = support(rf)
    return dict(Q_report=round(hr / n, 3), ES=round(es, 3),
                Support=(round(sup, 3) if sup is not None else None), n_hit_facts=nsup,
                n_report=len(rf))


def load_final_reports():
    outs = [json.loads(l) for l in open(RUNS / 'outputs.jsonl')]
    finals = {}
    for o in outs:
        if o.get('group') in ('G1-scored', 'G2-scored'):
            _, rf, _ = parse_facts(o['raw_output'])
            finals[(o['group'], o['arm'], o['unit'], o['role'])] = rf if rf else \
                (json.loads(o['raw_output']) if o['raw_output'].strip().startswith('[') else [])
    return finals


def main():
    finals = load_final_reports()
    ledger = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]

    # ---- Group 1: paired report-variant contrast on identical upstream ----
    g1_rows = []
    for (runs_dir, strat, cond, rep) in G1_SETS:
        unit = f"{strat}_{cond}_r{rep}"
        outputs = [json.loads(l) for l in open(HERE / runs_dir / 'outputs.jsonl')]
        ex = [o for o in outputs if o['strategy'] == strat and o['condition'] == cond
              and o['rep'] == rep]
        rec = json.loads((HERE / runs_dir / f"{strat}__{cond}__r{rep}.json").read_text())
        mf = adopted_merge_facts(ex, rec.get('actions', []))
        hm, n = slot_hits(mf)
        row = dict(unit=unit, Q_merge=round(hm / n, 3))
        for variant in ('A_original', 'B_fidelity'):
            for r in (1, 2):
                rf = finals.get(('G1-scored', variant, unit, f'r{r}'), [])
                m = report_metrics(rf)
                row[f'{variant}_r{r}'] = m
        g1_rows.append(row)
    json.dump(g1_rows, open(HERE / 'TFJS_G1_SCORED.json', 'w'), ensure_ascii=False, indent=1)

    print('== G1: report fidelity (paired, identical upstream) ==')
    print('  (Sup = span-anchor PROXY on gold-hitting facts; UAR = 1-ES over ALL assertions)')
    print(f"{'unit':30} {'Q_m':>5} | {'A: Qr/ES/UAR/Sup':>20} {'B: Qr/ES/UAR/Sup':>20} | dB_Qr")
    for row in g1_rows:
        def agg(v):
            qs = [row[f'{v}_r{r}']['Q_report'] for r in (1, 2)]
            es = [row[f'{v}_r{r}']['ES'] for r in (1, 2)]
            sp = [row[f'{v}_r{r}']['Support'] for r in (1, 2) if row[f'{v}_r{r}']['Support'] is not None]
            uar = 1 - sum(es) / 2
            return (f"{sum(qs)/2:.3f}/{sum(es)/2:.3f}/{uar:.3f}/" +
                    (f"{sum(sp)/len(sp):.3f}" if sp else 'n/a'))
        a, b = agg('A_original'), agg('B_fidelity')
        dQ = (sum(row[f'B_fidelity_r{r}']['Q_report'] for r in (1, 2)) / 2 -
              sum(row[f'A_original_r{r}']['Q_report'] for r in (1, 2)) / 2)
        print(f"{row['unit']:30} {row['Q_merge']:>5} | {a:>16} {b:>16} | {dQ:+.3f}")

    # ---- Group 2: paired scheduling contrast on identical extracts ----
    g2_rows = []
    for rep in (1, 2, 3):
        p = RUNS / f"G2__r{rep}.json"
        if not p.exists():
            continue
        rec = json.loads(p.read_text())
        outs = [json.loads(l) for l in open(RUNS / 'outputs.jsonl')]
        for arm in ('Proposed', 'DA-JS-v2'):
            mo = []
            if arm == 'Proposed':
                for o in reversed(outs):
                    if o.get('group') == 'G2' and o['arm'] == arm and o['unit'] == f'r{rep}' \
                            and o['node'] == 'merge' and o['role'] == 'reroll2':
                        _, mo, _ = parse_facts(o['raw_output'])
                        break
            else:
                for o in outs:
                    if o.get('group') == 'G2' and o['arm'] == arm and o['unit'] == f'r{rep}' \
                            and o['node'].startswith('split_'):
                        _, f2, _ = parse_facts(o['raw_output'])
                        mo += [x for x in f2 if isinstance(x, dict)]
            hm, n = slot_hits(mo)
            rf = finals.get(('G2-scored', arm, f'r{rep}', 'base'), [])
            m = report_metrics(rf)
            led = [l for l in ledger if l['group'] == 'G2' and l['arm'] == arm
                   and l['unit'] == f'r{rep}']
            led_shared = [l for l in ledger if l['group'] == 'G2' and l['arm'] == 'shared'
                          and l['unit'] == f'r{rep}']
            own_c, own_y = len(led), round(sum(l['yuan'] for l in led), 4)
            sh_c, sh_y = len(led_shared), round(sum(l['yuan'] for l in led_shared), 4)
            m['UAR'] = round(1 - m['ES'], 3)  # unsupported/error assertion rate (1-ES)
            g2_rows.append(dict(rep=rep, arm=arm, Q_merge=round(hm / n, 3),
                                C_own=own_c, yuan_own=own_y,
                                C_incl_shared=own_c + sh_c,
                                yuan_incl_shared=round(own_y + sh_y, 4),
                                shared_c=sh_c, shared_yuan=sh_y,
                                L_recovery_s=rec['arms'][arm]['L_recovery_s'],
                                L_e2e_s=rec['arms'][arm]['L_e2e_s'],
                                deadline_met=bool(rec['arms'][arm]['L_e2e_s'] <= 240),
                                **m, actions=rec['arms'][arm]['actions']))
    json.dump(g2_rows, open(HERE / 'TFJS_G2_SCORED.json', 'w'), ensure_ascii=False, indent=1)

    print('\n== G2: scheduling (paired extracts, fidelity report both arms) ==')
    print(f"{'rep':>3} {'arm':11} {'Q_m':>5} {'Q_r':>5} {'ES':>5} {'UAR':>5} {'Sup':>5} "
          f"{'C_own':>5} {'C_e2e':>5} {'L_rec':>6} {'L_e2e':>6} {'DL':>5}")
    for r in g2_rows:
        print(f"{r['rep']:>3} {r['arm']:11} {r['Q_merge']:>5} {r['Q_report']:>5} {r['ES']:>5} "
              f"{r['UAR']:>5} {str(r['Support']):>5} {r['C_own']:>5} {r['C_incl_shared']:>5} "
              f"{r['L_recovery_s']:>6} {r['L_e2e_s']:>6} {str(r['deadline_met']):>5}")
    for arm in ('Proposed', 'DA-JS-v2'):
        rs = [r for r in g2_rows if r['arm'] == arm]
        if rs:
            print(f"{arm:11} means: Q_m={sum(r['Q_merge'] for r in rs)/len(rs):.3f} "
                  f"Q_r={sum(r['Q_report'] for r in rs)/len(rs):.3f} "
                  f"ES={sum(r['ES'] for r in rs)/len(rs):.3f} "
                  f"C_own={sum(r['C_own'] for r in rs)/len(rs):.1f} "
                  f"C_e2e={sum(r['C_incl_shared'] for r in rs)/len(rs):.1f} "
                  f"L_rec={sum(r['L_recovery_s'] for r in rs)/len(rs):.0f}s "
                  f"L_e2e={sum(r['L_e2e_s'] for r in rs)/len(rs):.0f}s")


if __name__ == '__main__':
    main()
