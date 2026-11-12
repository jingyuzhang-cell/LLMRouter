#!/usr/bin/env python3
"""MERGE_VIS scorer (ZERO calls). Per-unit paired (n=6), not per-slot samples.

Metrics (operator table):
  Merge Retention : gold slots hit at merge / gold slots hit by FULL extract input
  Q_merge, Q_report (primary result metric), Amount Recall (4 monetary slots),
  ES (corrected symmetric scorer), C/L, fid echo (B: unique legal input fids)
Secondary DIAGNOSTIC only (primary verbatim rule untouched): paraphrase-tolerant
hits for title/conditional slots E04-02/E04-09 via key substrings.
Reference column: frozen-pipeline visibility ceiling (complete facts within [:3000]).
"""
import json
from pathlib import Path
from rq2_p2r_runner import parse_facts
from rq_dajf2_score import GOLD, norm, evidence_support
from merge_vis_runner import stored_extract_sets

HERE = Path(__file__).parent
RUNS = HERE / 'merge_vis_runs'
AMOUNT = [i for i, c in enumerate(GOLD)
          if '万' in c['quote'] and any(d in c['quote'] for d in '0123456789')]
PARA = {'E04-02': ['立案调查进展', '退市风险提示'], 'E04-09': ['低于1元', '终止上市']}


def hits(facts):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    return {i for i, c in enumerate(GOLD) if norm(c['quote']) and norm(c['quote']) in blob}


def para_hits(facts):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    return sum(1 for k, parts in PARA.items() if any(norm(p) in blob for p in parts))


def visible(facts, cap=3000):
    J = json.dumps(facts, ensure_ascii=False)[:cap]
    depth, st, objs = 0, None, []
    for i, ch in enumerate(J):
        if ch == '{':
            if depth == 0:
                st = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    objs.append(json.loads(J[st:i + 1]))
                except Exception:
                    pass
    return objs


def main():
    outs = [json.loads(l) for l in open(RUNS / 'outputs.jsonl')]
    ledger = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]
    rows = []
    for name, facts in stored_extract_sets():
        ex_h = hits(facts)
        in_fids = {f['fid'] for f in facts}
        row = dict(unit=name, extract_slots=len(ex_h), extract_amounts=len(ex_h & set(AMOUNT)),
                   frozen_cap_ceiling=len(hits(visible(facts))))
        for arm in ('A_full', 'B_full'):
            rec_p = RUNS / f"MV__{name}__{arm}.json"
            if not rec_p.exists():
                row[arm] = None
                continue
            fin = {o['node']: json.loads(o['raw_output']) for o in outs
                   if o['unit'] == name and o['arm'] == arm and o['node'].endswith('_final')}
            raw_m = next((o['raw_output'] for o in outs if o['unit'] == name
                          and o['arm'] == arm and o['node'] == 'merge'), '')
            mo, rf = fin.get('merge_final', []), fin.get('report_final', [])
            mh, rh = hits(mo), hits(rf)
            echo = {str(x.get('fid', '')) for x in parse_facts(raw_m)[1] if isinstance(x, dict)}
            led = [l for l in ledger if l['unit'] == name and l['arm'] == arm]
            rec = json.loads((RUNS / f"MV__{name}__{arm}.json").read_text())
            row[arm] = dict(
                Q_merge=round(len(mh) / 11, 3), Q_report=round(len(rh) / 11, 3),
                merge_retention=round(len(mh & ex_h) / max(len(ex_h), 1), 3),
                amount_recall=round(len(mh & set(AMOUNT)) / max(len(ex_h & set(AMOUNT)), 1), 3),
                amount_recall_report=round(len(rh & set(AMOUNT)) / max(len(ex_h & set(AMOUNT)), 1), 3),
                ES=round(evidence_support(rf)[0], 3),
                fid_echo_rate=round(len(echo & in_fids) / len(in_fids), 3),
                para_slots_merge=para_hits(mo), para_slots_report=para_hits(rf),
                n_merge=len(mo), n_report=len(rf), parse_ok=rec.get('merge_parse_ok'),
                calls=len(led), tokens=sum(l['tin'] + l['tout'] for l in led),
                yuan=round(sum(l['yuan'] for l in led), 4), L_s=rec.get('span_s'))
        rows.append(row)
    json.dump(rows, open(HERE / 'MERGE_VIS_SCORED.json', 'w'), ensure_ascii=False, indent=1)

    print(f"{'unit':10} ext cap | {'A: Qm/Qr/ret/amt/ES':>26} | {'B: Qm/Qr/ret/amt/ES/echo':>32}")
    for r in rows:
        a = r['A_full'] or dict(Q_merge=0, Q_report=0, merge_retention=0, amount_recall=0, ES=0)
        b = r['B_full'] or dict(Q_merge=0, Q_report=0, merge_retention=0, amount_recall=0, ES=0,
                                fid_echo_rate=0)
        print(f"{r['unit']:10} {r['extract_slots']:>2}  {r['frozen_cap_ceiling']:>2} | "
              f"{a['Q_merge']:.3f}/{a['Q_report']:.3f}/{a['merge_retention']:.2f}/"
              f"{a['amount_recall']:.2f}/{a['ES']:.2f} | "
              f"{b['Q_merge']:.3f}/{b['Q_report']:.3f}/{b['merge_retention']:.2f}/"
              f"{b['amount_recall']:.2f}/{b['ES']:.2f}/{b['fid_echo_rate']:.2f}")
    for k in ('Q_merge', 'Q_report', 'merge_retention', 'amount_recall', 'ES', 'L_s', 'tokens'):
        A = [r['A_full'] for r in rows if r['A_full']]
        B = [r['B_full'] for r in rows if r['B_full']]
        ma = sum(x[k] for x in A) / len(A) if A else 0
        mb = sum(x[k] for x in B) / len(B) if B else 0
        d = [r['B_full'][k] - r['A_full'][k] for r in rows
             if r['A_full'] and r['B_full']]
        if d:
            print(f"{k:16} A={ma:.3f} B={mb:.3f} paired d(B-A)={sum(d)/len(d):+.3f} "
                  f"(+{sum(1 for x in d if x > 0)}/0:{sum(1 for x in d if x == 0)}/-{sum(1 for x in d if x < 0)})")
        else:
            print(f"{k:16} A={ma:.3f} (B arm not run - operator option ii)")
    cap = sum(r['frozen_cap_ceiling'] for r in rows) / len(rows) / 11
    print(f"reference: frozen [:3000] merge-input ceiling mean Q={cap:.3f}")


if __name__ == '__main__':
    main()
