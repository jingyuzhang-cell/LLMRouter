#!/usr/bin/env python3
"""Per-slot loss ledger: Gold -> Extract -> Merge/Z2 -> Verify -> Report (ZERO calls).

For every E04 gold slot x execution path, mark the FIRST node where the slot is
lost. Paths:
  G2 (TFJS_V1): rep 1-3 x {Proposed (pi-merge), DA-JS-v2 (Z2 union)}, SHARED extracts
  G1 (TFJS_V1): 6 stored Z2 sets x {A_original, B_fidelity} reports
Stage hit rule: normalized quote-or-value containment in the stage's fact blob
(value+quote; verify blob is value-only because verify re-emits fid/value/status).
Verify CANNOT lose slots in this pipeline by design (report input = merge facts
+ statuses, annotate-not-filter); its own re-emission fidelity is measured separately.
"""
import json
from pathlib import Path
from rq2_p2r_runner import parse_facts
from rq_dajf2_score import GOLD, norm

HERE = Path(__file__).parent


def hit_slots(facts):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    out = []
    for i, c in enumerate(GOLD):
        gq = norm(c.get('quote') or '')
        gv = norm(c.get('value') or '')
        if (gq and gq in blob) or (len(gv) >= 6 and gv in blob):
            out.append(i)
    return set(out)


def load(path):
    return [json.loads(l) for l in open(HERE / path)]


def g2_paths():
    outs = load('tfjs_runs/outputs.jsonl')
    paths = []
    for rep in (1, 2, 3):
        ex = [o for o in outs if o.get('group') == 'G2' and o['unit'] == f'r{rep}']
        shared = [o for o in ex if o['arm'] == 'shared']
        ext = [x for o in shared if o['node'].startswith('ext_')
               for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
        for arm in ('Proposed', 'DA-JS-v2'):
            ao = [o for o in ex if o['arm'] == arm]
            rp = []
            for o in outs:
                if o.get('group') == 'G2-scored' and o.get('arm') == arm \
                        and o.get('unit') == f'r{rep}':
                    rp = json.loads(o['raw_output'])
            if arm == 'Proposed':
                mg = [x for o in ao if o['node'] == 'merge' and o['role'] == 'reroll2'
                      for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
            else:
                mg = [x for o in ao if o['node'].startswith('split_')
                      for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
            vf = [x for o in ao if o['node'] == 'verify'
                  for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
            paths.append(dict(pid=f'G2|{arm}|r{rep}', arm=arm, rep=rep,
                              extract=hit_slots(ext), merge=hit_slots(mg),
                              verify=hit_slots(vf), report=hit_slots(rp),
                              n_extract=len(ext), n_merge=len(mg),
                              n_verify_out=len(vf), n_report=len(rp)))
    return paths


def g1_paths():
    from tfjs_v2_step1 import SETS, branch_facts
    paths = []
    tfjs_outs = load('tfjs_runs/outputs.jsonl')
    for (runs_dir, strat, cond, rep, _) in SETS:
        unit = f"{strat}_{cond}_r{rep}"
        orig = load(f'{runs_dir}/outputs.jsonl')
        ext = [x for o in orig if o['strategy'] == strat and o['condition'] == cond
               and o['rep'] == rep and o['node'].startswith('ext_')
               for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
        brs = branch_facts(orig, strat, cond, rep)
        mg = [f for facts in brs.values() for f in facts]
        vf = [x for o in tfjs_outs if o.get('group') == 'G1' and o.get('arm') == 'shared'
              and o.get('unit') == unit and o['node'] == 'verify'
              for x in parse_facts(o['raw_output'])[1] if isinstance(x, dict)]
        for variant in ('A_original', 'B_fidelity'):
            rp = []
            for o in tfjs_outs:
                if o.get('group') == 'G1-scored' and o['arm'] == variant \
                        and o.get('unit') == unit and o['role'] in ('r1', 'r2'):
                    rp += json.loads(o['raw_output'])
            paths.append(dict(pid=f'G1|{variant}|{unit}', arm=variant, rep=rep,
                              extract=hit_slots(ext), merge=hit_slots(mg),
                              verify=hit_slots(vf), report=hit_slots(rp),
                              n_extract=len(ext), n_merge=len(mg),
                              n_verify_out=len(vf), n_report=len(rp)))
    return paths


def first_loss(p):
    out = {}
    for i in range(len(GOLD)):
        if i in p['report']:
            out[i] = 'SURVIVED'
        elif i in p['merge']:      # verify is annotate-only by design
            out[i] = 'REPORT'
        elif i in p['extract']:
            out[i] = 'MERGE'
        else:
            out[i] = 'EXTRACT'
    return out


def main():
    g2, g1 = g2_paths(), g1_paths()
    ledger = {'g2': [], 'g1': []}
    print(f"{'path':34} {'ext':>3} {'mrg':>3} {'vfy':>3} {'rpt':>3} | first-loss: E/M/R/S")
    for p in g2 + g1:
        fl = first_loss(p)
        c = {k: sum(1 for v in fl.values() if v == k)
             for k in ('EXTRACT', 'MERGE', 'REPORT', 'SURVIVED')}
        row = dict(pid=p['pid'], ext=len(p['extract']), mrg=len(p['merge']),
                   vfy=len(p['verify']), rpt=len(p['report']),
                   n_extract=p['n_extract'], n_merge=p['n_merge'],
                   n_verify_out=p['n_verify_out'], n_report=p['n_report'],
                   first_loss={str(i): fl[i] for i in fl})
        (ledger['g2'] if p['pid'].startswith('G2') else ledger['g1']).append(row)
        print(f"{p['pid']:34} {len(p['extract']):>3} {len(p['merge']):>3} {len(p['verify']):>3} "
              f"{len(p['report']):>3} | {c['EXTRACT']}/{c['MERGE']}/{c['REPORT']}/{c['SURVIVED']}")

    print('\n== aggregate (slot-opportunities out of 11 per path) ==')
    for name, rows in (('G2 Proposed', [r for r in ledger['g2'] if 'Proposed' in r['pid']]),
                       ('G2 DA-JS-v2(Z2)', [r for r in ledger['g2'] if 'DA-JS-v2' in r['pid']]),
                       ('G1 A_original', [r for r in ledger['g1'] if 'A_orig' in r['pid']]),
                       ('G1 B_fidelity', [r for r in ledger['g1'] if 'B_fid' in r['pid']])):
        n = len(rows)
        agg = {k: sum(r[k] for r in rows) for k in ('ext', 'mrg', 'vfy', 'rpt')}
        fl = {K: sum(1 for r in rows for v in r['first_loss'].values() if v == K)
              for K in ('EXTRACT', 'MERGE', 'REPORT', 'SURVIVED')}
        tot = 11 * n
        print(f"{name:18} n={n} paths, {tot} slots | extract {agg['ext']} ({agg['ext']/tot:.0%}) "
              f"-> merge {agg['mrg']} ({agg['mrg']/tot:.0%}) -> verify {agg['vfy']} "
              f"-> report {agg['rpt']} ({agg['rpt']/tot:.0%}) | first-loss E/M/R/S = "
              f"{fl['EXTRACT']}/{fl['MERGE']}/{fl['REPORT']}/{fl['SURVIVED']}")

    # per-slot chronic loss across all 18 paths
    print('\n== per-slot fate (18 paths: 6 G2 + 12 G1) ==')
    slot_tab = []
    for i, c in enumerate(GOLD):
        fates = [first_loss(p)[i] for p in g2 + g1]
        cnt = {k: fates.count(k) for k in ('EXTRACT', 'MERGE', 'REPORT', 'SURVIVED')}
        slot_tab.append(dict(slot=c.get('cand_id', f'slot{i}'), quote=c['quote'][:30], **cnt))
        print(f"{c.get('cand_id', f'slot{i}'):8} {c['quote'][:26]:28} "
              f"E={cnt['EXTRACT']:>2} M={cnt['MERGE']:>2} R={cnt['REPORT']:>2} S={cnt['SURVIVED']:>2}")

    # Z2 vs pi-merge preservation on SHARED extracts (G2 only, paired)
    print('\n== G2 paired preservation (same extracts): P(merge|extract) ==')
    for rep in (1, 2, 3):
        pr = next(p for p in g2 if p['arm'] == 'Proposed' and p['rep'] == rep)
        dj = next(p for p in g2 if p['arm'] == 'DA-JS-v2' and p['rep'] == rep)
        e = pr['extract']
        print(f"r{rep}: extract {len(e)} | pi-merge keeps {len(e & pr['merge'])}/{len(e)} "
              f"(abs {len(pr['merge'])}) | Z2 keeps {len(e & dj['merge'])}/{len(e)} "
              f"(abs {len(dj['merge'])})")

    json.dump(dict(ledger=ledger, slot_table=slot_tab),
              open(HERE / 'TFJS_LOSS_LEDGER.json', 'w'), ensure_ascii=False, indent=1)
    print('\nwritten TFJS_LOSS_LEDGER.json')


if __name__ == '__main__':
    main()
