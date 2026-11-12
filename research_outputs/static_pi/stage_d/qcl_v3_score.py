#!/usr/bin/env python3
"""QCL_TABLE_V3 scorer (ZERO calls): terminal-Q action gains on UB-1.

Per unit x cell: Q_terminal (slot hits on report_final; E04=11 slots, E03=18),
paired dQ vs the unit's NONE baseline, incremental calls/tokens/yuan and span
from the ledger/records. Artifact-triggered E cell labeled as such.
"""
import json
from pathlib import Path
from rq_dajf2_score import GOLD as G04, norm

HERE = Path(__file__).parent
RUNS = HERE / 'qcl_v3_runs'
G03 = json.load(open(HERE / 'E03_GOLD_CANDIDATES.json'))


def hits(facts, gold, span_key):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    n = 0
    for c in gold:
        gq = norm(c.get('quote') or c.get(span_key) or '')
        gv = norm(c.get('value') or '')
        if (gq and gq in blob) or (len(gv) >= 6 and gv in blob):
            n += 1
    return n, len(gold)


def q_terminal(rf, unit):
    gold, sk = (G03, 'span') if unit.startswith('E03') else (G04, 'quote')
    h, n = hits(rf, gold, sk)
    return h / n


def main():
    outs = [json.loads(l) for l in open(RUNS / 'outputs.jsonl')]
    ledger = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]
    finals = {}
    for o in outs:
        if o.get('node') == 'report_final':
            finals[(o['unit'], o['cell'])] = json.loads(o['raw_output'])
    recs = {}
    for p in RUNS.glob('*__*.json'):
        d = json.loads(p.read_text())
        recs[d['exec_id']] = d

    rows = []
    for eid, d in sorted(recs.items()):
        if eid.startswith('BASE'):
            unit = d['unit']
            rf = finals.get((unit, 'NONE'), [])
            rows.append(dict(cell='NONE', unit=unit, Q=round(q_terminal(rf, unit), 3),
                             n_report=len(rf), d_calls=0,
                             note=f"store={d['n_store']}"))
        elif eid.startswith('FAULT'):
            unit, fault, arm = eid.split('|')[1], eid.split('|')[2], eid.split('|')[3]
            cell = f'FAULT-{fault}'
            rf = finals.get((unit, cell), []) if arm in ('R',) else \
                finals.get((unit, cell), [])
            # both arms wrote report_final under same cell name; distinguish by model
            cand = [o for o in outs if o.get('unit') == unit and o.get('cell') == cell
                    and o.get('node') == 'report_final']
            rf_arm = []
            for o in cand:
                if arm == 'R' and o.get('model') == 'qwen':
                    rf_arm = json.loads(o['raw_output'])
                if arm == 'pi' and o.get('model') == 'deepseek':
                    rf_arm = json.loads(o['raw_output'])
            base = q_terminal(finals.get((unit, 'NONE'), []), unit)
            led = [l for l in ledger if l['unit'] == unit and l['cell'] == cell
                   and ((arm == 'R' and l['model'] == 'qwen' and l['node'] == 'report')
                        or (arm == 'pi' and l['model'] == 'deepseek'))]
            rows.append(dict(cell=f'{fault}-{arm}', unit=unit,
                             Q=round(q_terminal(rf_arm, unit), 3),
                             dQ=round(q_terminal(rf_arm, unit) - base, 3),
                             d_calls=len(led), d_tok=sum(l['tin'] + l['tout'] for l in led),
                             note=';'.join(d.get('actions', []))))
        elif eid.startswith('E|'):
            unit = d['unit']
            rf = finals.get((unit, 'E'), [])
            base = q_terminal(finals.get((unit, 'NONE'), []), unit)
            led = [l for l in ledger if l['unit'] == unit and l['cell'] == 'E']
            rows.append(dict(cell='E(artifact-triggered)', unit=unit,
                             Q=round(q_terminal(rf, unit), 3),
                             dQ=round(q_terminal(rf, unit) - base, 3),
                             d_calls=len(led), d_tok=sum(l['tin'] + l['tout'] for l in led),
                             note=';'.join(d.get('actions', []))[:90]))
        elif eid.startswith('ZX'):
            unit = d['unit']
            rf = finals.get((unit, 'ZX'), [])
            base = q_terminal(finals.get((unit, 'NONE'), []), unit)
            led = [l for l in ledger if l['unit'] == unit and l['cell'] == 'ZX']
            rows.append(dict(cell='Zx', unit=unit, Q=round(q_terminal(rf, unit), 3),
                             dQ=round(q_terminal(rf, unit) - base, 3),
                             d_calls=len(led), d_tok=sum(l['tin'] + l['tout'] for l in led),
                             note=f"store={d['n_store']} span={d['span_s']}s"))

    json.dump(rows, open(HERE / 'QCL_TABLE_V3.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{'cell':22} {'unit':10} {'Q':>6} {'dQ':>7} {'d_calls':>7} {'d_tok':>7}  note")
    for r in rows:
        print(f"{r['cell']:22} {r['unit']:10} {r['Q']:>6} {str(r.get('dQ','')):>7} "
              f"{str(r.get('d_calls','')):>7} {str(r.get('d_tok','')):>7}  {r['note'][:60]}")

    print('\n== action-level summary (exploratory; mean [range], n) ==')
    import collections
    agg = collections.defaultdict(list)
    for r in rows:
        if 'dQ' in r:
            agg[r['cell']].append(r)
    for cell, rs in sorted(agg.items()):
        dqs = [r['dQ'] for r in rs]
        print(f"{cell:24} dQ mean={sum(dqs)/len(dqs):+.3f} range=[{min(dqs):+.3f},{max(dqs):+.3f}] "
              f"dC={sum(r['d_calls'] for r in rs)/len(rs):.1f}c/{sum(r['d_tok'] for r in rs)/len(rs):.0f}tok n={len(rs)}")
    nones = [r['Q'] for r in rows if r['cell'] == 'NONE']
    print(f"NONE baseline Q: E04={[r['Q'] for r in rows if r['cell']=='NONE' and not r['unit'].startswith('E03')]} "
          f"E03={[r['Q'] for r in rows if r['cell']=='NONE' and r['unit'].startswith('E03')]}")


if __name__ == '__main__':
    main()
