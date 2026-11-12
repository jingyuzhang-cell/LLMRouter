#!/usr/bin/env python3
"""RQ_DAJF_V2 scorer + V1 retro-scoring (ZERO model calls).

Metrics per execution (operator requirement: terminal Report quality + citation
accuracy, not only Q_merge):
  Q_merge : gold-slot hit rate on ADOPTED merge-stage facts (V1 convention, continuity)
  Q_report: gold-slot hit rate on terminal report facts
  ES      : EvidenceSupport / citation accuracy of report facts =
            fraction with valid doc_id in {doc1,doc2,doc3} AND normalized quote
            (>=6 chars) verbatim-contained in that document
  Q_terminal = 0.7*Q_report + 0.3*ES
            (P0 contract weights 0.5FC+0.3ES+0.2Comp collapse to 0.7/0.3 here because
             this gold has no negative slots, so Completeness == FactCorrectness;
             declared, not silently changed)

Hit rule (unchanged from V1, reproduced from RQ_DYN_3ARM_V2): whitespace/comma-
stripped containment of gold quote (or >=6-char value) in normalized value+quote.
"""
import json, re
from pathlib import Path
from rq2_p2r_runner import parse_facts

HERE = Path(__file__).parent
GOLD = json.load(open('/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/'
                      'e04_candidates_atomic_facts.json'))['candidates']
DOC_IDS = {'doc1', 'doc2', 'doc3'}
# ERRATUM 2026-11-06: doc content must be normalized with the SAME norm() as the
# quote (whitespace+punct class). Previously docs were whitespace-only stripped while
# quotes were punctuation-stripped -> comma/colon-bearing quotes (monetary amounts)
# could never match. Direction: ES systematically UNDERcounted in all prior batches.
DOCS = {d: re.sub(r'[\s,，、；;：:]+', '', open(p, encoding='utf-8').read())
        for d, p in {'doc1': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20260910.txt',
                     'doc2': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261009.txt',
                     'doc3': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261013.txt'}.items()}


def norm(s):
    return re.sub(r'[\s,，、；;：:]+', '', str(s))


def slot_hits(facts):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in facts if isinstance(x, dict)))
    h = 0
    for c in GOLD:
        gq = norm(c.get('quote') or '')
        gv = norm(c.get('value') or '')
        if (gq and gq in blob) or (len(gv) >= 6 and gv in blob):
            h += 1
    return h, len(GOLD)


def evidence_support(facts):
    """Citation accuracy: valid doc + verbatim quote in that doc. No quote -> unsupported."""
    dictfacts = [x for x in facts if isinstance(x, dict)]
    if not dictfacts:
        return 0.0, 0
    ok = 0
    for x in dictfacts:
        doc, q = str(x.get('doc', '')), norm(x.get('quote', ''))
        if doc in DOC_IDS and len(q) >= 6 and q in DOCS[doc]:
            ok += 1
    return ok / len(dictfacts), ok


def adopted_merge_facts(ex_outs, actions):
    def out(role):
        for o in reversed(ex_outs):
            if o['node'] == 'merge' and o['role'] == role:
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
    for tag, role in (('R:ok', 'reroll'), ('pi:ok', 'reroll2'), ('merge:ok', 'base')):
        if tag in a:
            _, f, _ = parse_facts(out(role) or '')
            return [x for x in f if isinstance(x, dict)]
    return []


def score_runs(runs_dir, label):
    runs = Path(runs_dir)
    recs = {}
    for p in runs.glob('*.json'):
        if p.name == 'GLOBAL_BUDGET.json':
            continue
        d = json.loads(p.read_text('utf-8'))
        if 'exec_id' in d and 'strategy' in d:
            recs[d['exec_id']] = d
    outputs = [json.loads(l) for l in open(runs / 'outputs.jsonl')]
    ledger = [json.loads(l) for l in open(runs / 'ledger.jsonl')]
    rows = []
    for eid, d in sorted(recs.items()):
        ex = [o for o in outputs if o['strategy'] == d['strategy']
              and o['condition'] == d['condition'] and o['rep'] == d['rep']]
        mf = adopted_merge_facts(ex, d.get('actions', []))
        rep = next((o for o in reversed(ex) if o['node'] == 'report'), None)
        _, rf, _ = parse_facts(rep['raw_output']) if rep else (False, [], [])
        hm, n = slot_hits(mf)
        hr, _ = slot_hits(rf)
        es_r, es_n = evidence_support(rf)
        es_m, _ = evidence_support(mf)
        led = [l for l in ledger if l['strategy'] == d['strategy']
               and l['condition'] == d['condition'] and l['rep'] == d['rep']]
        rows.append(dict(exec_id=eid, strategy=d['strategy'], condition=d['condition'],
                         rep=d['rep'], Q_merge=round(hm / n, 3), Q_report=round(hr / n, 3),
                         ES_report=round(es_r, 3), ES_merge=round(es_m, 3),
                         Q_terminal=round(0.7 * (hr / n) + 0.3 * es_r, 3),
                         n_report=len(rf), calls=len(led),
                         yuan=round(sum(l['yuan'] for l in led), 4),
                         L_s=d['exec_span_s'], deadline_met=d.get('deadline_met'),
                         actions=d.get('actions')))
    return rows


def print_rows(rows, title):
    print(f'\n== {title} ==')
    print(f"{'exec_id':32} {'Q_m':>5} {'Q_r':>5} {'ES_r':>5} {'Q_term':>6} {'calls':>5} {'L_s':>6}")
    for r in rows:
        print(f"{r['exec_id']:32} {r['Q_merge']:>5} {r['Q_report']:>5} {r['ES_report']:>5} "
              f"{r['Q_terminal']:>6} {r['calls']:>5} {r['L_s']:>6}")


def main():
    v1 = score_runs(HERE / 'rq_dajf_runs', 'RQ_DAJF_V1 retro (terminal metrics)')
    json.dump(v1, open(HERE / 'RQ_DAJF_V1_TERMINAL_RETRO.json', 'w'),
              ensure_ascii=False, indent=1)
    print_rows(v1, 'RQ_DAJF_V1 retro (terminal metrics)')
    if (HERE / 'rq_dajf2_runs' / 'outputs.jsonl').exists():
        v2 = score_runs(HERE / 'rq_dajf2_runs', 'RQ_DAJF_V2')
        json.dump(v2, open(HERE / 'RQ_DAJF_V2_SCORED.json', 'w'),
                  ensure_ascii=False, indent=1)
        print_rows(v2, 'RQ_DAJF_V2')


if __name__ == '__main__':
    main()
