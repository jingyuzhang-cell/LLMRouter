#!/usr/bin/env python3
"""RQ_DAJF post-hoc scorer (ZERO model calls).

Scoring convention (reproduced from RQ_DYN_3ARM_V2 frozen results):
  Q_merge  (primary) = E04 gold-slot hit rate on the exec's ADOPTED merge-stage facts
  Q_report (secondary/diagnostic) = same rule on report facts (paraphrase-sensitive)
Hit rule: whitespace/comma-stripped containment of gold quote (or >=6-char value) in
the normalized (value+quote) blob of the fact set.

Adopted merge facts reconstructed from record['actions']:
  merge:ok -> base merge; R:ok -> reroll; pi:ok -> reroll2;
  Z2:ok -> union of split_* outputs; else -> empty (unrecovered).
"""
import json, re
from pathlib import Path
from rq2_p2r_runner import parse_facts

HERE = Path(__file__).parent
RUNS = HERE / 'rq_dajf_runs'
GOLD = json.load(open('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/'
                      'e04_candidates_atomic_facts.json'))['candidates']


def norm(s):
    return re.sub(r'[\s,，、；;：:]+', '', str(s))


def hit_rate(facts):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    h = 0
    for c in GOLD:
        gq = norm(c.get('quote') or '')
        gv = norm(c.get('value') or '')
        if (gq and gq in blob) or (len(gv) >= 6 and gv in blob):
            h += 1
    return h, len(GOLD)


def adopted_merge_facts(ex_outs, actions):
    def out(node, role):
        for o in reversed(ex_outs):
            if o['node'] == node and o['role'] == role:
                return o['raw_output']
        return None
    a = ';'.join(actions)
    if 'Z2:ok' in a:
        facts = []
        for o in ex_outs:
            if o['node'].startswith('split_'):
                _, f, _ = parse_facts(o['raw_output'])
                facts += [x for x in f if isinstance(x, dict)]
        return facts
    for tag, node, role in (('R:ok', 'merge', 'reroll'), ('pi:ok', 'merge', 'reroll2'),
                            ('merge:ok', 'merge', 'base')):
        if tag in a:
            _, f, _ = parse_facts(out(node, role) or '')
            return [x for x in f if isinstance(x, dict)]
    return []


def main():
    recs = {}
    for p in RUNS.glob('*.json'):
        if p.name == 'GLOBAL_BUDGET.json':
            continue
        d = json.loads(p.read_text('utf-8'))
        if 'exec_id' in d and 'strategy' in d:
            recs[d['exec_id']] = d

    outputs = [json.loads(l) for l in open(RUNS / 'outputs.jsonl')]
    ledger = [json.loads(l) for l in open(RUNS / 'ledger.jsonl')]

    rows = []
    for eid, d in sorted(recs.items()):
        ex_outs = [o for o in outputs if o['strategy'] == d['strategy']
                   and o['condition'] == d['condition'] and o['rep'] == d['rep']]
        mf = adopted_merge_facts(ex_outs, d.get('actions', []))
        rep = next((o for o in reversed(ex_outs) if o['node'] == 'report'), None)
        _, rf, _ = parse_facts(rep['raw_output']) if rep else (False, [], [])
        hm, n = hit_rate(mf)
        hr, _ = hit_rate(rf)
        led = [l for l in ledger if l['strategy'] == d['strategy']
               and l['condition'] == d['condition'] and l['rep'] == d['rep']]
        rows.append(dict(exec_id=eid, strategy=d['strategy'], condition=d['condition'],
                         rep=d['rep'], Q_merge=round(hm / n, 3), Q_report=round(hr / n, 3),
                         n_adopted=len(mf), n_report=len(rf), calls=len(led),
                         yuan=round(sum(l['yuan'] for l in led), 4), L_s=d['exec_span_s'],
                         deadline_met=d.get('deadline_met'), actions=d.get('actions')))
    json.dump(rows, open(HERE / 'RQ_DAJF_SCORED.json', 'w'), ensure_ascii=False, indent=1)

    print(f"{'exec_id':30} {'Q_m':>5} {'Q_r':>5} {'n_adopt':>7} {'calls':>5} {'¥':>6} {'L_s':>6} {'DL':>5}")
    for r in rows:
        print(f"{r['exec_id']:30} {r['Q_merge']:>5} {r['Q_report']:>5} {r['n_adopted']:>7} "
              f"{r['calls']:>5} {r['yuan']:>6} {r['L_s']:>6} {str(r['deadline_met']):>5}")

    print('\n== strategy × condition (mean over reps) ==')
    for cond in ('natural', 'persistent'):
        for st in ('Static', 'Proposed', 'DA-JS-v1'):
            rs = [r for r in rows if r['strategy'] == st and r['condition'] == cond]
            if not rs:
                continue
            n = len(rs)
            qm = sum(r['Q_merge'] for r in rs) / n
            qr = sum(r['Q_report'] for r in rs) / n
            dl = sum(1 for r in rs if r['deadline_met']) / n
            joint = sum(1 for r in rs if r['deadline_met'] and r['Q_merge'] >= 0.5) / n
            print(f"{st:11}|{cond:10} Q_merge={qm:.3f} Q_report={qr:.3f} "
                  f"C={sum(r['calls'] for r in rs)/n:.1f}c/¥{sum(r['yuan'] for r in rs)/n:.3f} "
                  f"L={sum(r['L_s'] for r in rs)/n:.0f}s DL={dl:.0%} JointSucc={joint:.0%}")


if __name__ == '__main__':
    main()
