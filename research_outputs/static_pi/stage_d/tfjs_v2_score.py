#!/usr/bin/env python3
"""TFJS-V2 scorer (ZERO calls). Operator-specified conventions:
1. Q_report = SOLE primary endpoint (fact coverage), paired C vs B per set
2. ES = corrected symmetric-normalization scorer (erratum applied)
3. fid echo rate = UNIQUE LEGAL upstream fids echoed in the RAW model output
   (pre-backfill); duplicate and unknown fids reported separately. B's echo is
   computed the same way from stored raw outputs (colliding-fid upstream).
Framing: end-to-end identity-uniqueness intervention effect (not Report-model
capability). Raw model outputs come from the call records; finals from the
*-scored pseudo-records (post-backfill).
"""
import json
from pathlib import Path
from rq2_p2r_runner import parse_facts
from rq_dajf2_score import GOLD, slot_hits, evidence_support, adopted_merge_facts
from tfjs_v2_step1 import SETS
from tfjs_v2_runner import namespaced_upstream

HERE = Path(__file__).parent


def echo_stats(raw_text, upstream_fids):
    """(unique_legal_echo, n_dup_fid_occurrences, n_unknown_fids, n_facts) from raw output."""
    _, facts, _ = parse_facts(raw_text)
    fids = [str(x.get('fid', '')) for x in facts if isinstance(x, dict)]
    seen, dup, unknown = set(), 0, 0
    for f in fids:
        if f not in upstream_fids:
            unknown += 1
        elif f in seen:
            dup += 1
        else:
            seen.add(f)
    return len(seen), dup, unknown, len(fids)


def report_metrics(final_facts):
    hr, n = slot_hits(final_facts)
    es, _ = evidence_support(final_facts)
    return round(hr / n, 3), round(es, 3)


def main():
    v2_outs = [json.loads(l) for l in open(HERE / 'tfjs_v2_runs/outputs.jsonl')]
    g1_outs = [json.loads(l) for l in open(HERE / 'tfjs_runs/outputs.jsonl')]

    rows = []
    for (runs_dir, strat, cond, rep, _) in SETS:
        unit = f"{strat}_{cond}_r{rep}"
        orig = [json.loads(l) for l in open(HERE / runs_dir / 'outputs.jsonl')]
        b_up = adopted_merge_facts(
            [o for o in orig if o['strategy'] == strat and o['condition'] == cond
             and o['rep'] == rep], json.loads(
                (HERE / runs_dir / f"{strat}__{cond}__r{rep}.json").read_text())['actions'])
        b_fids = {str(f.get('fid', '')) for f in b_up if isinstance(f, dict)}
        c_up = namespaced_upstream(runs_dir, strat, cond, rep)
        c_fids = {str(f['fid']) for f in c_up}
        row = dict(unit=unit, n_up_B=len(b_up), n_up_uniqB=len(b_fids), n_up_C=len(c_up))
        for arm, fid_set in (('B', b_fids), ('C', c_fids)):
            if arm == 'B':
                raws = {o['role']: o['raw_output'] for o in g1_outs
                        if o.get('group') == 'G1' and o.get('arm') == 'B_fidelity'
                        and o.get('unit') == unit and o['node'] == 'report'}
                fins = {o['role']: json.loads(o['raw_output']) for o in g1_outs
                        if o.get('group') == 'G1-scored' and o.get('arm') == 'B_fidelity'
                        and o.get('unit') == unit}
            else:
                raws = {o['role']: o['raw_output'] for o in v2_outs
                        if o.get('unit') == unit and o['node'] == 'report'}
                fins = {o['role']: json.loads(o['raw_output']) for o in v2_outs
                        if o.get('unit') == unit and o.get('node') == 'report_final'}
            per = {}
            for r in ('r1', 'r2'):
                if r not in raws:
                    continue
                u, d, k, n = echo_stats(raws[r], fid_set)
                qr, es = report_metrics(fins[r])
                per[r] = dict(echo_uniq_legal=u, echo_rate=round(u / len(fid_set), 3),
                              dup=d, unknown=k, n_out=n, Q_report=qr, ES=es)
            row[arm] = per
        row['dQ_report'] = round(
            sum(per['Q_report'] for per in row['C'].values()) / len(row['C']) -
            sum(per['Q_report'] for per in row['B'].values()) / len(row['B']), 3)
        rows.append(row)

    json.dump(rows, open(HERE / 'TFJS_V2_SCORED.json', 'w'), ensure_ascii=False, indent=1)

    print(f"{'unit':28} | {'B: Qr/echo/dup/unk':>22} | {'C: Qr/echo/dup/unk':>22} | dQr")
    for row in rows:
        def agg(a):
            ps = list(row[a].values())
            return (f"{sum(p['Q_report'] for p in ps)/len(ps):.3f}/"
                    f"{sum(p['echo_rate'] for p in ps)/len(ps):.2f}/"
                    f"{sum(p['dup'] for p in ps)/len(ps):.1f}/"
                    f"{sum(p['unknown'] for p in ps)/len(ps):.1f}")
        print(f"{row['unit']:28} | {agg('B'):>22} | {agg('C'):>22} | {row['dQ_report']:+.3f}")

    for a in ('B', 'C'):
        qs = [p['Q_report'] for row in rows for p in row[a].values()]
        es = [p['ES'] for row in rows for p in row[a].values()]
        er = [p['echo_rate'] for row in rows for p in row[a].values()]
        print(f"{a}: mean Q_report={sum(qs)/len(qs):.3f} ES={sum(es)/len(es):.3f} "
              f"echo_rate={sum(er)/len(er):.3f} (n={len(qs)})")
    dq = sum(r['dQ_report'] for r in rows) / len(rows)
    print(f"\nPRIMARY ENDPOINT dQ_report(C-B) = {dq:+.3f}")


if __name__ == '__main__':
    main()
