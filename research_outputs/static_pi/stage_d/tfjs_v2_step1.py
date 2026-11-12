#!/usr/bin/env python3
"""TFJS-V2 Step 1: zero-call identity & evidence fidelity audit + replay scoring.

(a) fid collision audit on stored Z2 split unions (branch-aware rebuild)
(b) branch-namespaced fid rewrite: fid_global = branch || '::' || fid_local
(c) quote recoverability: anchor each split fact to its branch's EXTRACT fact
    (value match) and recover verbatim-in-doc quote/doc from the extract record
(d) counterfactual replay: C-arm ceiling (identity+evidence-complete input)
    vs frozen A/B actuals from TFJS_V1 G1

Zero model calls. Sources: rq_dajf_runs/, rq_dajf2_runs/, tfjs_runs/ outputs.
"""
import json, re
from pathlib import Path
from rq2_p2r_runner import parse_facts
from rq_dajf2_score import GOLD, norm, slot_hits, evidence_support

HERE = Path(__file__).parent
SETS = [  # (runs_dir, strategy, condition, rep, has_branch_splits)
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 1, True),
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 2, True),
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 3, True),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 1, True),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 2, True),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 3, True),
]


def branch_facts(outputs, strat, cond, rep):
    """Per-branch fact lists from split_* nodes (Z2) or merge node (pi)."""
    branches = {}
    for o in outputs:
        if o['strategy'] == strat and o['condition'] == cond and o['rep'] == rep:
            if o['node'].startswith('split_'):
                _, f, _ = parse_facts(o['raw_output'])
                branches[o['node']] = [x for x in f if isinstance(x, dict)]
    return branches


def extract_facts(outputs, strat, cond, rep):
    ex = {}
    for o in outputs:
        if o['strategy'] == strat and o['condition'] == cond and o['rep'] == rep \
                and o['node'].startswith('ext_'):
            _, f, _ = parse_facts(o['raw_output'])
            ex[o['node']] = [x for x in f if isinstance(x, dict)]
    return ex


def quote_valid(f):
    d, q = str(f.get('doc', '')), norm(f.get('quote', ''))
    DOC = {'doc1': 'e04d1', 'doc2': 'e04d2', 'doc3': 'e04d3'}
    docs = getattr(quote_valid, '_docs', None)
    if docs is None:
        docs = quote_valid._docs = {
            'doc1': norm(open('/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20260910.txt').read()),
            'doc2': norm(open('/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261009.txt').read()),
            'doc3': norm(open('/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261013.txt').read())}
    return d in docs and len(q) >= 6 and q in docs[d]


def anchor(f, ex_branch):
    """Anchor split fact to an extract fact of the same branch by value text."""
    v = norm(f.get('value', ''))
    if not v:
        return None
    best = None
    for e in ex_branch:
        ev = norm(e.get('value', ''))
        if not ev:
            continue
        if v == ev or (len(ev) >= 6 and (ev in v or v in ev)):
            if best is None or len(ev) > len(norm(best.get('value', ''))):
                best = e
    return best


def main():
    report = []
    print(f"{'set':28} {'facts':>5} {'uniqFid':>7} {'coll%':>5} | {'ownQ%':>5} {'anchor%':>7} "
          f"{'recQ%':>5} {'finalQ%':>6} | {'C_ceilQr':>8} {'C_ceilES':>8}")
    for (runs_dir, strat, cond, rep, _) in SETS:
        outputs = [json.loads(l) for l in open(HERE / runs_dir / 'outputs.jsonl')]
        brs = branch_facts(outputs, strat, cond, rep)
        exs = extract_facts(outputs, strat, cond, rep)
        all_f = [f for b in brs.values() for f in b]
        uniq = {str(f.get('fid', '')) for f in all_f}
        coll = 1 - len(uniq) / max(len(all_f), 1)

        own_valid = sum(1 for f in all_f if quote_valid(f))
        rebuilt = []
        anchored = recovered = 0
        for node, facts in brs.items():
            ex_branch = exs.get(node.replace('split_', 'ext_'), [])
            for f in facts:
                q_ok = quote_valid(f)
                nf = {'fid': f"{node}::{f.get('fid','')}", 'value': f.get('value', ''),
                      'doc': f.get('doc', ''), 'quote': f.get('quote', ''), 'branch': node}
                if not q_ok:
                    e = anchor(f, ex_branch)
                    if e:
                        anchored += 1
                        nf['doc'] = e.get('doc', nf['doc'])
                        nf['quote'] = e.get('quote', nf['quote'])
                        nf['anchored'] = True
                        if quote_valid(nf):
                            recovered += 1
                rebuilt.append(nf)
        final_valid = sum(1 for f in rebuilt if quote_valid(f))
        hm, n = slot_hits(rebuilt)
        es, _ = evidence_support(rebuilt)
        row = dict(set=f"{strat}_{cond}_r{rep}", n_facts=len(all_f), uniq_fids=len(uniq),
                   collision_rate=round(coll, 3), own_quote_valid=round(own_valid / len(all_f), 3),
                   anchor_rate=round(anchored / max(len(all_f) - own_valid, 1), 3),
                   recovered_valid=round(recovered / max(len(all_f) - own_valid, 1), 3),
                   final_quote_valid=round(final_valid / len(rebuilt), 3),
                   C_ceiling_Q_report=round(hm / n, 3), C_ceiling_ES=round(es, 3))
        report.append(row)
        print(f"{row['set']:28} {row['n_facts']:>5} {row['uniq_fids']:>7} {row['collision_rate']:>5} | "
              f"{row['own_quote_valid']:>5} {row['anchor_rate']:>7} {row['recovered_valid']:>5} "
              f"{row['final_quote_valid']:>6} | {row['C_ceiling_Q_report']:>8} {row['C_ceiling_ES']:>8}")

    json.dump(report, open(HERE / 'TFJS_V2_STEP1_AUDIT.json', 'w'), ensure_ascii=False, indent=1)

    # frozen A/B actuals for comparison (TFJS_V1 G1)
    g1 = json.load(open(HERE / 'TFJS_G1_SCORED.json'))
    qa = sum(sum(r[f'A_original_r{i}']['Q_report'] for i in (1, 2)) / 2 for r in g1) / 6
    qb = sum(sum(r[f'B_fidelity_r{i}']['Q_report'] for i in (1, 2)) / 2 for r in g1) / 6
    ea = sum(sum(r[f'A_original_r{i}']['ES'] for i in (1, 2)) / 2 for r in g1) / 6
    eb = sum(sum(r[f'B_fidelity_r{i}']['ES'] for i in (1, 2)) / 2 for r in g1) / 6
    cq = sum(r['C_ceiling_Q_report'] for r in report) / 6
    ce = sum(r['C_ceiling_ES'] for r in report) / 6
    print(f"\nfrozen actuals: A Qr={qa:.3f} ES={ea:.3f} | B Qr={qb:.3f} ES={eb:.3f}")
    print(f"C-arm CEILING (identity+evidence-complete input, perfect echo): Qr={cq:.3f} ES={ce:.3f}")
    print(f"recoverable headroom vs B: dQr={cq-qb:+.3f} dES={ce-eb:+.3f}")


if __name__ == '__main__':
    main()
